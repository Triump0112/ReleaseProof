from .models import ExperimentDefinition, ExperimentId


CATALOG: dict[ExperimentId, ExperimentDefinition] = {
    ExperimentId.HEALTH: ExperimentDefinition(
        id=ExperimentId.HEALTH,
        title="Health check",
        purpose="Confirms that each revision responds successfully.",
        max_requests=10,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.SMOKE: ExperimentDefinition(
        id=ExperimentId.SMOKE,
        title="API smoke",
        purpose="Compares the normal request path on stable and candidate revisions.",
        max_requests=20,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.CONTRACT: ExperimentDefinition(
        id=ExperimentId.CONTRACT,
        title="Contract compatibility",
        purpose="Detects removed fields and incompatible response types.",
        max_requests=20,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.EDGE: ExperimentDefinition(
        id=ExperimentId.EDGE,
        title="Edge inputs",
        purpose="Checks empty, Unicode, boundary and missing-optional-field inputs.",
        max_requests=60,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.LOAD: ExperimentDefinition(
        id=ExperimentId.LOAD,
        title="Bounded load",
        purpose="Compares tail latency and errors under a safe concurrency cap.",
        max_requests=600,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.PAYLOAD: ExperimentDefinition(
        id=ExperimentId.PAYLOAD,
        title="Payload-size boundary",
        purpose="Tests small, medium and near-limit request payloads.",
        max_requests=60,
        default_trials=3,
        default_warmups=1,
    ),
    ExperimentId.IDEMPOTENCY: ExperimentDefinition(
        id=ExperimentId.IDEMPOTENCY,
        title="Retry and idempotency",
        purpose="Checks whether safe retries produce duplicate side effects.",
        max_requests=40,
        default_trials=3,
        default_warmups=0,
    ),
    ExperimentId.TIMEOUT: ExperimentDefinition(
        id=ExperimentId.TIMEOUT,
        title="Dependency timeout",
        purpose="Checks bounded behaviour when a dependency responds slowly.",
        max_requests=30,
        default_trials=3,
        default_warmups=0,
    ),
    ExperimentId.AI_EXPLORER: ExperimentDefinition(
        id=ExperimentId.AI_EXPLORER,
        title="AI Explorer probe",
        purpose="Runs an AI-authored declarative probe inside fixed request and assertion boundaries.",
        max_requests=20,
        default_trials=3,
        default_warmups=0,
        blocking=False,
    ),
}


BASELINE_IDS = (ExperimentId.HEALTH, ExperimentId.SMOKE)
ADAPTIVE_IDS = tuple(
    experiment_id
    for experiment_id in CATALOG
    if experiment_id not in (*BASELINE_IDS, ExperimentId.AI_EXPLORER)
)


# A transparent risk map, separate from the executable catalog.  Listing a
# risk here does not pretend that the prototype already has evidence for it.
RISK_TAXONOMY = [
    {"id": "contract", "title": "Contract compatibility", "coverage": "implemented", "experiments": ["contract_compatibility"]},
    {"id": "semantic", "title": "Business and semantic behaviour", "coverage": "partial", "experiments": ["api_smoke", "intent_reconciliation"]},
    {"id": "input_boundaries", "title": "Boundary and malformed input", "coverage": "partial", "experiments": ["edge_inputs", "payload_size"]},
    {"id": "authentication", "title": "Authentication and authorization", "coverage": "planned", "experiments": []},
    {"id": "security", "title": "Security and information leakage", "coverage": "planned", "experiments": []},
    {"id": "performance", "title": "Latency, load and resource pressure", "coverage": "implemented", "experiments": ["bounded_load"]},
    {"id": "concurrency", "title": "Concurrency, retries and idempotency", "coverage": "partial", "experiments": ["bounded_load", "retry_idempotency"]},
    {"id": "data_integrity", "title": "Database and data integrity", "coverage": "planned", "experiments": []},
    {"id": "external_effects", "title": "Events, queues and external calls", "coverage": "planned", "experiments": []},
    {"id": "dependency_resilience", "title": "Dependency failures and timeouts", "coverage": "partial", "experiments": ["dependency_timeout"]},
    {"id": "rollback", "title": "Rollback and version interoperability", "coverage": "planned", "experiments": []},
    {"id": "observability", "title": "Logs, metrics and error reporting", "coverage": "planned", "experiments": []},
]
