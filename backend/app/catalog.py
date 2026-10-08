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
}


BASELINE_IDS = (ExperimentId.HEALTH, ExperimentId.SMOKE)
ADAPTIVE_IDS = tuple(experiment_id for experiment_id in CATALOG if experiment_id not in BASELINE_IDS)

