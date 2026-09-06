"""
TrackFlow — Telemetry Pipeline Test Suite
===========================================

Tests for the 5 CEO KPI transformation tasks defined in
``data/pipelines/pipeline.py``.

Principles (as required):
  1. **Total Isolation** — No databases, APIs, or environment variables.
     All tests run inside ``prefect_test_harness()`` with static in-memory
     dictionaries as input.
  2. **Mathematical Accuracy (Happy Path)** — For every task, a test with
     known input asserts the exact computed value.
  3. **Defensive Behaviour (Edge Cases)** — For every task, at least one
     test injects malformed data (``None`` payload, missing key, wrong type)
     and asserts graceful handling (default value or typed exception).

Usage:
    cd data/pipelines
    uv run pytest ../../tests/pipelines/test_pipeline.py -v
"""

from __future__ import annotations

from typing import Any

import pytest
from prefect.testing.utilities import prefect_test_harness

# All internal tasks and test data are imported from the production module.
from pipeline import (
    _SAMPLE_EVENTS,
    _compute_customer_satisfaction_task,
    _compute_delivery_rate_task,
    _compute_operational_cost_task,
    _compute_returns_task,
    _compute_shipping_volume_task,
    assemble_executive_kpis,
)

# ====================================================================
# Helpers
# ====================================================================


def _run_in_harness(task_callable, *args, **kwargs):
    """Wrap a Prefect task call inside a test harness context.

    Calls the task *directly* (not ``.fn``) so that Prefect 3 properly
    creates a task run context — required by ``get_run_logger()`` and
    other orchestration features inside the task body.
    """
    with prefect_test_harness():
        return task_callable(*args, **kwargs)


# ====================================================================
# Fixtures  —  Canonical test data
# ====================================================================


@pytest.fixture
def canonical_events() -> list[dict[str, Any]]:
    """Six events from the production ``_SAMPLE_EVENTS`` constant.

    2 shipments created (LA + Zaragoza)
    2 delivered (1 on_time, 1 late)
    2 returns (initiated + completed)
    """
    return _SAMPLE_EVENTS.copy()


@pytest.fixture
def empty_events() -> list[dict[str, Any]]:
    """No events at all — empty pipeline run."""
    return []


# ====================================================================
# 1.  SHIPPING VOLUME  —  _compute_shipping_volume_task
# ====================================================================


class TestShippingVolume:
    """Tests for ``_compute_shipping_volume_task``.

    Contract: returns ``{"total": int, "por_almacen": dict[str, int]}``
    Logic:    counts events where ``event_type == "shipment.created"``
              and groups by ``warehouse``.
    """

    # ── Happy path ──────────────────────────────────────────────────

    def test_exact_count_with_canonical_events(self, canonical_events):
        """Canonical data has 2 created events: total=2.

        Expected:
            total       = 2
            por_almacen = {"los-angeles": 1, "zaragoza": 1}
        """
        result = _run_in_harness(_compute_shipping_volume_task, canonical_events)

        assert result["total"] == 2
        assert result["por_almacen"] == {"los-angeles": 1, "zaragoza": 1}

    def test_all_events_created_single_warehouse(self):
        """3 created events in the same warehouse."""
        events = [
            {"event_id": "e1", "warehouse": "madrid", "event_type": "shipment.created"},
            {"event_id": "e2", "warehouse": "madrid", "event_type": "shipment.created"},
            {"event_id": "e3", "warehouse": "madrid", "event_type": "shipment.created"},
        ]
        result = _run_in_harness(_compute_shipping_volume_task, events)
        assert result["total"] == 3
        assert result["por_almacen"] == {"madrid": 3}

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_events_list(self, empty_events):
        """No events → zero volume, empty warehouse map."""
        result = _run_in_harness(_compute_shipping_volume_task, empty_events)
        assert result["total"] == 0
        assert result["por_almacen"] == {}

    def test_non_shipment_events_filtered_out(self):
        """Events without 'shipment.created' type are ignored."""
        events = [
            {"event_id": "e1", "warehouse": "barcelona", "event_type": "shipment.delivered"},
            {"event_id": "e2", "warehouse": "barcelona", "event_type": "return.initiated"},
        ]
        result = _run_in_harness(_compute_shipping_volume_task, events)
        assert result["total"] == 0
        assert result["por_almacen"] == {}

    def test_missing_event_type_key_raises_keyerror(self):
        """Event without ``event_type`` key causes KeyError.

        This is expected defensive behaviour: the pipeline does not
        silently swallow schema violations.
        """
        events = [
            {"event_id": "e1", "warehouse": "madrid"},
        ]
        with pytest.raises(KeyError):
            _run_in_harness(_compute_shipping_volume_task, events)

    def test_non_string_event_type_is_filtered(self):
        """Integer event_type (e.g. 123) does not match string comparison."""
        events = [
            {"event_id": "e1", "warehouse": "madrid", "event_type": 123},
            {"event_id": "e2", "warehouse": "sevilla", "event_type": "shipment.created"},
        ]
        result = _run_in_harness(_compute_shipping_volume_task, events)
        # Only e2 counts
        assert result["total"] == 1
        assert result["por_almacen"] == {"sevilla": 1}


# ====================================================================
# 2.  ON-TIME DELIVERY RATE  —  _compute_delivery_rate_task
# ====================================================================


class TestOnTimeDeliveryRate:
    """Tests for ``_compute_delivery_rate_task``.

    Contract: ``{"porcentaje": float, "entregas_on_time": int,
                 "entregas_totales": int}``
    Logic:    of ``shipment.delivered`` events, what fraction has
              ``payload["on_time"] == True``?
    """

    # ── Happy path ──────────────────────────────────────────────────

    def test_exact_rate_with_canonical_events(self, canonical_events):
        """1 on-time + 1 late = 2 total → 50.0%."""
        result = _run_in_harness(_compute_delivery_rate_task, canonical_events)

        assert result["porcentaje"] == 50.0
        assert result["entregas_on_time"] == 1
        assert result["entregas_totales"] == 2

    def test_all_deliveries_on_time(self):
        """3/3 on-time → 100.0%."""
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": True}},
            {"event_id": "e2", "event_type": "shipment.delivered", "payload": {"on_time": True}},
            {"event_id": "e3", "event_type": "shipment.delivered", "payload": {"on_time": True}},
        ]
        result = _run_in_harness(_compute_delivery_rate_task, events)
        assert result["porcentaje"] == 100.0
        assert result["entregas_on_time"] == 3

    def test_no_deliveries_on_time(self):
        """0/3 on-time → 0.0%."""
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e2", "event_type": "shipment.delivered", "payload": {"on_time": False}},
        ]
        result = _run_in_harness(_compute_delivery_rate_task, events)
        assert result["porcentaje"] == 0.0
        assert result["entregas_on_time"] == 0

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_events_list(self, empty_events):
        """No deliveries → 0.0%, 0/0."""
        result = _run_in_harness(_compute_delivery_rate_task, empty_events)
        assert result["porcentaje"] == 0.0
        assert result["entregas_on_time"] == 0
        assert result["entregas_totales"] == 0

    def test_payload_is_none_raises_attributeerror(self):
        """A delivered event with ``payload=None`` crashes with AttributeError.

        The task calls ``e["payload"].get("on_time")`` — when payload is
        ``None`` the ``.get()`` call fails. The test asserts this is a
        typed exception (not a silent swallow), documenting the current
        defensive boundary.
        """
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": None},
        ]
        with pytest.raises(AttributeError):
            _run_in_harness(_compute_delivery_rate_task, events)

    def test_missing_on_time_key_defaults_to_false(self):
        """When ``payload`` lacks an ``on_time`` key, ``.get()`` returns
        ``None`` → counted as late."""
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {}},
        ]
        result = _run_in_harness(_compute_delivery_rate_task, events)
        assert result["porcentaje"] == 0.0
        assert result["entregas_on_time"] == 0
        assert result["entregas_totales"] == 1

    def test_non_delivery_events_filtered(self):
        """Only ``shipment.delivered`` events are considered."""
        events = [
            {"event_id": "e1", "event_type": "shipment.created", "payload": {}},
            {"event_id": "e2", "event_type": "return.initiated", "payload": {}},
        ]
        result = _run_in_harness(_compute_delivery_rate_task, events)
        assert result["porcentaje"] == 0.0
        assert result["entregas_on_time"] == 0
        assert result["entregas_totales"] == 0


# ====================================================================
# 3.  OPERATIONAL COST  —  _compute_operational_cost_task
# ====================================================================


class TestOperationalCost:
    """Tests for ``_compute_operational_cost_task``.

    Contract: ``{"total": float, "breakdown": {...}, "currency": "USD",
                 "unit_costs": {...}}``
    Cost model:
        - shipment.created:   $10.00 per event (handling)
        - shipment.delivered:  $5.00 per event (delivery)
        - return.*:           $15.00 per event (reverse logistics)
    """

    # ── Happy path ──────────────────────────────────────────────────

    def test_exact_cost_with_canonical_events(self, canonical_events):
        """2 created ($20) + 2 delivered ($10) + 2 returns ($30) = $60.00.

        Breakdown:
            handling                  = 20.00
            delivery                  = 10.00
            returns_reverse_logistics = 30.00
        """
        result = _run_in_harness(_compute_operational_cost_task, canonical_events)

        assert result["total"] == 60.00
        assert result["breakdown"]["handling"] == 20.00
        assert result["breakdown"]["delivery"] == 10.00
        assert result["breakdown"]["returns_reverse_logistics"] == 30.00
        assert result["currency"] == "USD"
        assert result["unit_costs"]["handling_cost_per_shipment"] == 10.0
        assert result["unit_costs"]["delivery_cost_per_shipment"] == 5.0
        assert result["unit_costs"]["return_cost_per_return"] == 15.0

    def test_only_created_events(self):
        """3 created → $30.00, no delivery or return costs."""
        events = [
            {"event_id": "e1", "event_type": "shipment.created"},
            {"event_id": "e2", "event_type": "shipment.created"},
            {"event_id": "e3", "event_type": "shipment.created"},
        ]
        result = _run_in_harness(_compute_operational_cost_task, events)
        assert result["total"] == 30.00
        assert result["breakdown"]["handling"] == 30.00
        assert result["breakdown"]["delivery"] == 0.00
        assert result["breakdown"]["returns_reverse_logistics"] == 0.00

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_events_list(self, empty_events):
        """No events → total $0.00."""
        result = _run_in_harness(_compute_operational_cost_task, empty_events)
        assert result["total"] == 0.00
        assert result["breakdown"]["handling"] == 0.00
        assert result["breakdown"]["delivery"] == 0.00
        assert result["breakdown"]["returns_reverse_logistics"] == 0.00

    def test_non_shipment_event_types_ignored(self):
        """Unknown event types contribute zero cost."""
        events = [
            {"event_id": "e1", "event_type": "inventory.check"},
            {"event_id": "e2", "event_type": "warehouse.maintenance"},
        ]
        result = _run_in_harness(_compute_operational_cost_task, events)
        assert result["total"] == 0.00

    def test_missing_event_type_key_raises_keyerror(self):
        """Event without ``event_type`` key causes KeyError — schema enforcement."""
        events = [
            {"event_id": "e1"},
        ]
        with pytest.raises(KeyError):
            _run_in_harness(_compute_operational_cost_task, events)

    def test_float_event_type_does_not_match(self):
        """A float event_type does not match string equality or ``.startswith()``."""
        events = [
            {"event_id": "e1", "event_type": 3.14},
            {"event_id": "e2", "event_type": "shipment.created"},
        ]
        result = _run_in_harness(_compute_operational_cost_task, events)
        # Only e2 matches
        assert result["total"] == 10.00


# ====================================================================
# 4.  RETURNS  —  _compute_returns_task
# ====================================================================


class TestReturns:
    """Tests for ``_compute_returns_task``.

    Contract: ``{"volumen": int, "tasa_porcentaje": float}``
    Logic:    events where ``event_type.startswith("return.")`` vs.
              ``event_type == "shipment.created"``.
    """

    # ── Happy path ──────────────────────────────────────────────────

    def test_exact_return_rate_with_canonical_events(self, canonical_events):
        """2 returns / 2 created shipments = 100.0%."""
        result = _run_in_harness(_compute_returns_task, canonical_events)

        assert result["volumen"] == 2
        assert result["tasa_porcentaje"] == 100.0

    def test_no_returns_with_shipments(self):
        """0 returns, 3 created → 0.0%."""
        events = [
            {"event_id": "e1", "event_type": "shipment.created"},
            {"event_id": "e2", "event_type": "shipment.created"},
            {"event_id": "e3", "event_type": "shipment.delivered"},
        ]
        result = _run_in_harness(_compute_returns_task, events)
        assert result["volumen"] == 0
        assert result["tasa_porcentaje"] == 0.0

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_events_list(self, empty_events):
        """No events → zero returns, 0.0%."""
        result = _run_in_harness(_compute_returns_task, empty_events)
        assert result["volumen"] == 0
        assert result["tasa_porcentaje"] == 0.0

    def test_returns_without_any_created_shipments(self):
        """Returns exist but no created shipments → division-by-zero
        prevention yields 0.0%."""
        events = [
            {"event_id": "e1", "event_type": "return.initiated"},
            {"event_id": "e2", "event_type": "return.completed"},
        ]
        result = _run_in_harness(_compute_returns_task, events)
        assert result["volumen"] == 2
        assert result["tasa_porcentaje"] == 0.0  # protected division

    def test_missing_event_type_key_raises_keyerror(self):
        """Event without ``event_type`` → KeyError (schema enforcement)."""
        events = [
            {"event_id": "e1"},
        ]
        with pytest.raises(KeyError):
            _run_in_harness(_compute_returns_task, events)

    def test_non_return_events_filtered(self):
        """Only ``return.*`` events count as returns."""
        events = [
            {"event_id": "e1", "event_type": "shipment.created"},
            {"event_id": "e2", "event_type": "inventory.received"},
        ]
        result = _run_in_harness(_compute_returns_task, events)
        assert result["volumen"] == 0
        # 1 created shipment → 0% rate
        assert result["tasa_porcentaje"] == 0.0


# ====================================================================
# 5.  CUSTOMER SATISFACTION  —  _compute_customer_satisfaction_task
# ====================================================================


class TestCustomerSatisfaction:
    """Tests for ``_compute_customer_satisfaction_task``.

    Contract: ``{"score": float, "level": str, "penalties": {...},
                 "scale": "0-100"}``
    Logic:
        - Base 100.
        - 20-point penalty per late delivery.
        - 10-point penalty per return.
        - Clamped to [0, 100].
        - Level: high ≥ 80, medium ≥ 50, low < 50.
    """

    # ── Happy path ──────────────────────────────────────────────────

    def test_exact_score_with_canonical_events(self, canonical_events):
        """1 late delivery = -20, 2 returns = -20 → 100 - 40 = 60.0.

        Expected level = "medium" (50 ≤ 60 < 80).
        """
        result = _run_in_harness(
            _compute_customer_satisfaction_task, canonical_events
        )

        assert result["score"] == 60.0
        assert result["level"] == "medium"
        assert result["penalties"]["late_deliveries"] == 1
        assert result["penalties"]["returns"] == 2
        assert result["scale"] == "0-100"

    def test_no_penalties_perfect_score(self):
        """All deliveries on time, no returns → 100.0, level=high."""
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": True}},
        ]
        result = _run_in_harness(_compute_customer_satisfaction_task, events)
        assert result["score"] == 100.0
        assert result["level"] == "high"
        assert result["penalties"]["late_deliveries"] == 0
        assert result["penalties"]["returns"] == 0

    def test_all_penalties_clamped_to_zero(self):
        """3 late (-60) + 4 returns (-40) = 100-100 → 0.0, level=low."""
        events = [
            # 3 late deliveries
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e2", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e3", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            # 4 returns
            {"event_id": "e4", "event_type": "return.initiated"},
            {"event_id": "e5", "event_type": "return.initiated"},
            {"event_id": "e6", "event_type": "return.completed"},
            {"event_id": "e7", "event_type": "return.completed"},
        ]
        result = _run_in_harness(_compute_customer_satisfaction_task, events)
        assert result["score"] == 0.0
        assert result["level"] == "low"
        assert result["penalties"]["late_deliveries"] == 3
        assert result["penalties"]["returns"] == 4

    # ── Edge cases ──────────────────────────────────────────────────

    def test_empty_events_list(self, empty_events):
        """No events → perfect 100.0, high."""
        result = _run_in_harness(
            _compute_customer_satisfaction_task, empty_events
        )
        assert result["score"] == 100.0
        assert result["level"] == "high"
        assert result["penalties"]["late_deliveries"] == 0
        assert result["penalties"]["returns"] == 0

    def test_payload_is_none_raises_attributeerror(self):
        """A delivered event with ``payload=None`` crashes with AttributeError.

        This documents the current defensive boundary: the task calls
        ``e["payload"].get("on_time")``, which fails on ``None``.
        """
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": None},
        ]
        with pytest.raises(AttributeError):
            _run_in_harness(_compute_customer_satisfaction_task, events)

    def test_missing_warehouse_key_does_not_affect_score(self):
        """The satisfaction task does not access ``warehouse`` — a missing
        warehouse key should not affect the score."""
        events = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": True}},
            {"event_id": "e2", "event_type": "return.initiated"},
        ]
        result = _run_in_harness(_compute_customer_satisfaction_task, events)
        # 1 return → -10 → 90.0
        assert result["score"] == 90.0
        assert result["level"] == "high"

    def test_score_boundary_levels(self):
        """Verify level thresholds at boundaries.

        80.0 should be "high", 79.99 should be "medium".
        50.0 should be "medium", 49.99 should be "low".
        """
        # 1 late delivery → -20 → 80.0 → high
        events_high = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": False}},
        ]
        result_high = _run_in_harness(_compute_customer_satisfaction_task, events_high)
        assert result_high["score"] == 80.0
        assert result_high["level"] == "high"

        # 1 late + 1 return → 100 - 20 - 10 = 70.0 → medium
        events_medium = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e2", "event_type": "return.initiated"},
        ]
        result_medium = _run_in_harness(
            _compute_customer_satisfaction_task, events_medium
        )
        assert result_medium["score"] == 70.0
        assert result_medium["level"] == "medium"

        # 3 late + 1 return → 100 - 60 - 10 = 30.0 → low
        events_low = [
            {"event_id": "e1", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e2", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e3", "event_type": "shipment.delivered", "payload": {"on_time": False}},
            {"event_id": "e4", "event_type": "return.initiated"},
        ]
        result_low = _run_in_harness(
            _compute_customer_satisfaction_task, events_low
        )
        assert result_low["score"] == 30.0
        assert result_low["level"] == "low"


# ====================================================================
# 6.  INTEGRATION  —  Assemble Executive KPIs
# ====================================================================


class TestAssembleExecutiveKPIs:
    """Tests for ``assemble_executive_kpis``.

    Verifies that the assembly task correctly combines the 5 individual
    KPI results into the final record structure expected by the reporting
    layer.
    """

    def test_full_assembly_with_canonical_data(self, canonical_events):
        """All 5 KPIs are present in the assembled record with correct types."""
        shipping = _run_in_harness(_compute_shipping_volume_task, canonical_events)
        delivery = _run_in_harness(_compute_delivery_rate_task, canonical_events)
        cost = _run_in_harness(_compute_operational_cost_task, canonical_events)
        returns = _run_in_harness(_compute_returns_task, canonical_events)
        satisfaction = _run_in_harness(
            _compute_customer_satisfaction_task, canonical_events
        )

        assembled = assemble_executive_kpis(
            events=canonical_events,
            shipping_volume=shipping,
            on_time_delivery=delivery,
            operational_cost=cost,
            returns=returns,
            customer_satisfaction=satisfaction,
        )

        # Structural fields
        assert assembled["fecha_reporte"] == "2026-09-03"
        assert isinstance(assembled["id_corrida"], str)
        assert len(assembled["id_corrida"]) == 12
        assert assembled["periodo"] == "2026-09-03"
        assert "timestamp" in assembled

        # KPI contract fields (Spanish, consumed by reporting layer)
        assert assembled["volumen_envios"]["total"] == 2
        assert assembled["tasa_entrega_tiempo"]["porcentaje"] == 50.0
        assert assembled["devoluciones"]["volumen"] == 2

        # New CEO KPI fields (English)
        assert assembled["operational_cost"]["total"] == 60.00
        assert assembled["customer_satisfaction"]["score"] == 60.0

    def test_assembly_structure_with_minimal_data(self):
        """Empty events still produce a structurally valid record."""
        events: list[dict[str, Any]] = []

        shipping = _run_in_harness(_compute_shipping_volume_task, events)
        delivery = _run_in_harness(_compute_delivery_rate_task, events)
        cost = _run_in_harness(_compute_operational_cost_task, events)
        returns = _run_in_harness(_compute_returns_task, events)
        satisfaction = _run_in_harness(
            _compute_customer_satisfaction_task, events
        )

        assembled = assemble_executive_kpis(
            events=events,
            shipping_volume=shipping,
            on_time_delivery=delivery,
            operational_cost=cost,
            returns=returns,
            customer_satisfaction=satisfaction,
        )

        # All KPI keys present even with zero data
        assert assembled["volumen_envios"]["total"] == 0
        assert assembled["tasa_entrega_tiempo"]["porcentaje"] == 0.0
        assert assembled["operational_cost"]["total"] == 0.0
        assert assembled["devoluciones"]["volumen"] == 0
        assert assembled["customer_satisfaction"]["score"] == 100.0
        assert assembled["customer_satisfaction"]["level"] == "high"