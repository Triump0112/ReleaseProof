"""Tests for intent reconciliation.

The behaviour that matters most is the failure direction: an unexplained
difference must block, and the offline classifier must never turn a real
regression into a pass.
"""

from __future__ import annotations

import pytest

from app.adjudicator import adjudicate, response_deltas
from app.models import ChangeInput, DeltaLabel


def _change(summary: str, diff: str) -> ChangeInput:
    return ChangeInput(
        service_name="pricing-api",
        summary=summary,
        diff=diff,
        scenario_id="undeclared-side-effect",
        request_path="/api/v1/quote",
    )


GST_CHANGE = _change(
    "Apply 18% GST to the quote total",
    "-    total = subtotal\n+    tax_rate = 0.18\n+    total = subtotal * (1 + tax_rate)",
)


def test_identical_responses_produce_no_deltas():
    body = {"total": 499.0, "currency": "INR"}
    assert response_deltas(body, dict(body)) == []


def test_deltas_classify_each_kind_of_difference():
    stable = {"keep": 1, "drop": "x", "retype": 5, "move": "a"}
    candidate = {"keep": 1, "retype": "5", "move": "b", "add": True}
    kinds = {delta.path: delta.kind for delta in response_deltas(stable, candidate)}
    assert kinds == {
        "drop": "field_removed",
        "add": "field_added",
        "retype": "type_changed",
        "move": "value_changed",
    }
    assert "keep" not in kinds


def test_nested_and_list_paths_are_addressable():
    stable = {"items": [{"price": 10}], "meta": {"region": "in"}}
    candidate = {"items": [{"price": 12}], "meta": {"region": "sg"}}
    paths = {delta.path for delta in response_deltas(stable, candidate)}
    assert paths == {"items[0].price", "meta.region"}


def test_undeclared_side_effect_blocks():
    """The headline case: identical shape and types, one undeclared value."""
    stable = {
        "total": 499.0, "currency": "INR", "tax_rate": 0.0, "discount_applied": 0.0,
        "quote_id": "aaa", "issued_at": "2026-10-08T09:00:00+00:00",
    }
    candidate = {
        "total": 500.5, "currency": "INR", "tax_rate": 0.18, "discount_applied": 0.15,
        "quote_id": "bbb", "issued_at": "2026-10-08T09:00:03+00:00",
    }
    result = adjudicate(GST_CHANGE, stable, candidate)

    assert result.passed is False
    assert result.unexplained_paths == ["discount_applied"]

    labels = {item.path: item.label for item in result.classifications}
    # The declared change accounts for these two.
    assert labels["total"] == DeltaLabel.EXPLAINED
    assert labels["tax_rate"] == DeltaLabel.EXPLAINED
    # These differ on every call to either revision and must not block.
    assert labels["quote_id"] == DeltaLabel.BENIGN_NOISE
    assert labels["issued_at"] == DeltaLabel.BENIGN_NOISE


def test_non_deterministic_fields_alone_do_not_block():
    """Noise must never produce a false positive, or the gate gets disabled."""
    stable = {"total": 499.0, "request_id": "r1", "elapsed_ms": 11.4}
    candidate = {"total": 499.0, "request_id": "r2", "elapsed_ms": 12.9}
    result = adjudicate(GST_CHANGE, stable, candidate)
    assert result.passed is True
    assert result.unexplained_paths == []


@pytest.mark.parametrize("field", ["processing_ms", "elapsed_ms", "duration_seconds", "latency_ms"])
def test_measured_durations_do_not_block(field):
    """Timing belongs to the latency policy, not to intent reconciliation.

    A concurrency change makes the candidate genuinely slower, and the latency
    experiment already judges that. Reporting it here as well would fail the
    smoke baseline on every performance-related change.
    """
    concurrency_change = _change(
        "Increase Cloud Run concurrency from 4 to 32",
        "- containerConcurrency: 4\n+ containerConcurrency: 32",
    )
    result = adjudicate(
        concurrency_change,
        {"total": 499.0, field: 31.2},
        {"total": 499.0, field: 128.7},
    )
    assert result.passed is True
    assert result.unexplained_paths == []
    labels = {item.path: item.label for item in result.classifications}
    assert labels[field] == DeltaLabel.BENIGN_NOISE


def test_identical_bodies_pass_with_no_classifications():
    body = {"total": 499.0, "currency": "INR"}
    result = adjudicate(GST_CHANGE, body, dict(body))
    assert result.passed is True
    assert result.deltas == []
    assert result.classifier == "none_required"


@pytest.mark.parametrize("field", ["shipping_fee", "loyalty_tier", "settlement_account"])
def test_any_unmentioned_field_change_blocks(field):
    stable = {"total": 499.0, field: "before"}
    candidate = {"total": 499.0, field: "after"}
    result = adjudicate(GST_CHANGE, stable, candidate)
    assert result.passed is False
    assert result.unexplained_paths == [field]


def test_offline_classifier_is_conservative_by_default():
    """With Vertex disabled, an unrecognised change must block rather than pass."""
    empty_intent = _change("Refactor internals", "- old_helper()\n+ new_helper()")
    result = adjudicate(empty_intent, {"balance": 10}, {"balance": 0})
    assert result.classifier == "deterministic_fallback"
    assert result.passed is False
