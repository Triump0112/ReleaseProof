from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Verdict(str, Enum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    INCONCLUSIVE = "INCONCLUSIVE"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AnalysisMode(str, Enum):
    GUARDED = "guarded"
    EXPLORER = "explorer"


class ExperimentId(str, Enum):
    HEALTH = "health_check"
    SMOKE = "api_smoke"
    CONTRACT = "contract_compatibility"
    EDGE = "edge_inputs"
    LOAD = "bounded_load"
    PAYLOAD = "payload_size"
    IDEMPOTENCY = "retry_idempotency"
    TIMEOUT = "dependency_timeout"
    AI_EXPLORER = "ai_explorer"


class ExplorerAssertion(str, Enum):
    """Fixed assertion operators available to an AI-authored probe spec."""

    CANDIDATE_SUCCESS = "candidate_success"
    STATUS_MATCH = "status_match"
    RESPONSE_SHAPE_MATCH = "response_shape_match"
    RESPONSE_TYPES_MATCH = "response_types_match"
    REQUIRED_PATHS_PRESENT = "required_paths_present"
    COMPARE_PATHS = "compare_paths"
    LATENCY_WITHIN_POLICY = "latency_within_policy"


class ExplorerExperimentSpec(BaseModel):
    """Declarative test DSL. The model authors data, never executable code."""

    # Reject unknown keys rather than ignoring them. A spec carrying an invented
    # field such as `target_url` or `headers` is already outside the contract,
    # so it fails validation instead of being silently dropped — the guarantee
    # is then auditable from the schema rather than from runner behaviour.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    rationale: str = Field(min_length=3, max_length=500)
    hypothesis: str = Field(min_length=3, max_length=500)
    query_parameters: dict[str, str] = Field(default_factory=dict, max_length=8)
    assertions: list[ExplorerAssertion] = Field(min_length=1, max_length=6)
    required_response_paths: list[str] = Field(default_factory=list, max_length=8)
    compare_response_paths: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_safe_dsl(self) -> "ExplorerExperimentSpec":
        for key, value in self.query_parameters.items():
            if not key or len(key) > 80 or len(value) > 500:
                raise ValueError("Explorer query parameters exceed the safe DSL limits")
        paths = [*self.required_response_paths, *self.compare_response_paths]
        if any(not path or len(path) > 200 for path in paths):
            raise ValueError("Explorer response paths must be between 1 and 200 characters")
        if ExplorerAssertion.REQUIRED_PATHS_PRESENT in self.assertions and not self.required_response_paths:
            raise ValueError("required_paths_present needs at least one required_response_path")
        if ExplorerAssertion.COMPARE_PATHS in self.assertions and not self.compare_response_paths:
            raise ValueError("compare_paths needs at least one compare_response_path")
        return self


class ExperimentDefinition(BaseModel):
    id: ExperimentId
    title: str
    purpose: str
    max_requests: int = Field(ge=1, le=1000)
    default_trials: int = Field(ge=1, le=10)
    default_warmups: int = Field(ge=0, le=5)
    blocking: bool = True


class Budget(BaseModel):
    max_adaptive_experiments: int = Field(default=2, ge=0, le=2)
    max_exploratory_experiments: int = Field(default=1, ge=0, le=2)
    max_requests: int = Field(default=1000, ge=10, le=1000)
    max_duration_seconds: int = Field(default=90, ge=5, le=90)
    trials: int = Field(default=3, ge=2, le=5)
    warmups: int = Field(default=1, ge=0, le=3)


class ExpectedContract(BaseModel):
    required_fields: dict[str, Literal["string", "number", "integer", "boolean", "object", "array"]] = Field(
        default_factory=dict
    )


class ChangeInput(BaseModel):
    service_name: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    diff: str = Field(default="", max_length=20_000)
    stable_url: HttpUrl | None = None
    candidate_url: HttpUrl | None = None
    scenario_id: str | None = Field(default=None, max_length=80)
    request_path: str = Field(default="/", pattern=r"^/[^\s]*$", max_length=300)
    expected_contract: ExpectedContract | None = None
    analysis_mode: AnalysisMode = AnalysisMode.GUARDED
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def require_execution_target(self) -> "ChangeInput":
        live_pair = self.stable_url is not None and self.candidate_url is not None
        if not self.scenario_id and not live_pair:
            raise ValueError("Provide a scenario_id or both stable_url and candidate_url")
        if (self.stable_url is None) != (self.candidate_url is None):
            raise ValueError("stable_url and candidate_url must be provided together")
        return self


class PlannedExperiment(BaseModel):
    experiment_id: ExperimentId
    reason: str = Field(min_length=3, max_length=500)
    hypothesis: str = Field(min_length=3, max_length=500)


class ExperimentPlan(BaseModel):
    detected_change: str = Field(min_length=3, max_length=500)
    risk_summary: str = Field(min_length=3, max_length=1000)
    baseline_experiments: list[ExperimentId] = Field(default_factory=lambda: [ExperimentId.HEALTH, ExperimentId.SMOKE])
    adaptive_experiments: list[PlannedExperiment] = Field(max_length=2)
    exploratory_experiments: list[ExplorerExperimentSpec] = Field(default_factory=list, max_length=2)
    analysis_mode: AnalysisMode = AnalysisMode.GUARDED
    planner: Literal["vertex_gemini", "deterministic_fallback"]
    planner_note: str | None = Field(default=None, max_length=1000)


class SideMeasurement(BaseModel):
    success: bool
    trials_completed: int = Field(ge=0)
    warmups_completed: int = Field(ge=0)
    requests: int = Field(ge=0)
    error_rate: float | None = Field(default=None, ge=0, le=1)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    # How many timed requests the percentile was computed from. Reported so a
    # latency claim can be judged against the evidence that supports it.
    latency_samples: int = Field(default=0, ge=0)
    response_status: int | None = None
    response_sample: dict[str, Any] | list[Any] | str | None = None
    notes: list[str] = Field(default_factory=list)


class DeltaLabel(str, Enum):
    """How a measured stable-versus-candidate difference relates to the change."""

    EXPLAINED = "explained"
    BENIGN_NOISE = "benign_noise"
    UNEXPLAINED = "unexplained"


class ResponseDelta(BaseModel):
    """One field-level difference, derived deterministically from measurements."""

    path: str = Field(max_length=300)
    kind: Literal["field_added", "field_removed", "type_changed", "value_changed"]
    stable_value: str | None = Field(default=None, max_length=200)
    candidate_value: str | None = Field(default=None, max_length=200)
    stable_type: str | None = None
    candidate_type: str | None = None


class DeltaClassification(BaseModel):
    path: str = Field(max_length=300)
    label: DeltaLabel
    rationale: str = Field(min_length=1, max_length=500)
    # Required for 'explained'; a claim without a citation is downgraded.
    diff_evidence: str | None = Field(default=None, max_length=500)


class Adjudication(BaseModel):
    """Reconciliation of observed behaviour against the change's declared intent."""

    deltas: list[ResponseDelta] = Field(default_factory=list)
    classifications: list[DeltaClassification] = Field(default_factory=list)
    unexplained_paths: list[str] = Field(default_factory=list)
    passed: bool
    summary: str
    classifier: str
    classifier_note: str | None = Field(default=None, max_length=1000)


class ExperimentEvidence(BaseModel):
    experiment_id: ExperimentId
    title: str
    blocking: bool
    stable: SideMeasurement
    candidate: SideMeasurement
    passed: bool | None
    explanation: str
    thresholds: dict[str, float | int | str] = Field(default_factory=dict)
    adjudication: Adjudication | None = None
    review_only: bool = False
    exploratory_spec: ExplorerExperimentSpec | None = None


class EvidenceLedger(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    created_at: datetime
    completed_at: datetime | None = None
    change: ChangeInput
    plan: ExperimentPlan
    evidence: list[ExperimentEvidence] = Field(default_factory=list)
    verdict: Verdict | None = None
    verdict_reasons: list[str] = Field(default_factory=list)
    review_findings: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: RunStatus = RunStatus.RUNNING
    ledger: EvidenceLedger
    error: str | None = None


class ScenarioSummary(BaseModel):
    id: str
    title: str
    description: str
    suggested_change: ChangeInput


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
