"""Latency claims must be supported by the evidence that produced them.

The gate reports a 95th percentile and blocks on a threshold over it. Both of
those are only meaningful with enough timed samples, so these tests pin the
percentile itself and pin that the policy stands down when the sample is too
small to support the claim.
"""

from __future__ import annotations

import pytest

from app.executor import (
    MIN_LATENCY_SAMPLES,
    _evaluate,
    _p95,
    _probe_concurrency,
    _requests_per_trial,
)
from app.models import Budget, ChangeInput, ExperimentId, SideMeasurement


def _side(p95: float, samples: int, success: bool = True) -> SideMeasurement:
    return SideMeasurement(
        success=success,
        trials_completed=3,
        warmups_completed=1,
        requests=samples,
        error_rate=0.0,
        p95_latency_ms=p95,
        latency_samples=samples,
        response_status=200,
        response_sample={"total": 499.0},
    )


def _change() -> ChangeInput:
    return ChangeInput(
        service_name="checkout-api",
        summary="Increase Cloud Run concurrency from 4 to 32",
        diff="- containerConcurrency: 4\n+ containerConcurrency: 32",
        scenario_id="concurrency-regression",
        request_path="/api/v1/quote",
        budget=Budget(trials=3),
    )


def test_percentile_is_not_merely_the_maximum():
    """The regression this file exists for.

    Nearest-rank over a small sample returns the slowest request, so any
    one-off spike was reported as the p95 and could block a release on its own.
    """
    values = [10.0] * 19 + [1000.0]
    assert _p95(values) < 1000.0


def test_percentile_interpolates_between_neighbours():
    # 95% of 99 intervals is 94.05, so the answer sits just past the 95th value.
    assert _p95([float(n) for n in range(1, 101)]) == pytest.approx(95.05, abs=0.01)


def test_percentile_handles_degenerate_inputs():
    assert _p95([]) is None
    assert _p95([42.0]) == 42.0
    assert _p95([7.0, 7.0, 7.0]) == 7.0


def test_latency_policy_stands_down_below_the_sample_floor():
    """A large delta over three requests is not evidence enough to block."""
    passed, explanation, _ = _evaluate(
        ExperimentId.SMOKE,
        _side(p95=50.0, samples=3),
        _side(p95=500.0, samples=3),
        _change(),
    )
    assert passed is True
    assert "regressed" not in explanation


def test_latency_policy_blocks_once_the_sample_supports_it():
    samples = MIN_LATENCY_SAMPLES
    passed, explanation, thresholds = _evaluate(
        ExperimentId.SMOKE,
        _side(p95=50.0, samples=samples),
        _side(p95=500.0, samples=samples),
        _change(),
    )
    assert passed is False
    assert "regressed" in explanation
    # The claim carries the evidence behind it.
    assert str(samples) in explanation
    assert thresholds["latency_samples_per_side"] == samples


def test_a_small_regression_still_passes_with_a_full_sample():
    passed, _, _ = _evaluate(
        ExperimentId.SMOKE,
        _side(p95=100.0, samples=40),
        _side(p95=110.0, samples=40),
        _change(),
    )
    assert passed is True


@pytest.mark.parametrize(
    "experiment_id",
    [ExperimentId.SMOKE, ExperimentId.CONTRACT, ExperimentId.EDGE, ExperimentId.LOAD],
)
def test_every_timed_experiment_collects_enough_samples(experiment_id):
    """Sampling must actually reach the floor the policy requires."""
    minimum_trials = Budget.model_fields["trials"].default
    assert _requests_per_trial(experiment_id) * minimum_trials >= MIN_LATENCY_SAMPLES


@pytest.mark.parametrize(
    "experiment_id",
    [ExperimentId.HEALTH, ExperimentId.SMOKE, ExperimentId.CONTRACT, ExperimentId.EDGE],
)
def test_only_the_load_experiment_overlaps_requests(experiment_id):
    """Collecting more samples must not turn a sequential probe into a load test.

    Raising the sample count once made the smoke baseline issue seven requests
    at a time, which was enough to trigger the candidate's contention and fail
    smoke on latency — destroying the very blind spot the scenario relies on.
    """
    assert _probe_concurrency(experiment_id) == 1
    assert _probe_concurrency(ExperimentId.LOAD) > 1
