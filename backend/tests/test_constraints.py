"""Explicit numeric fixtures for every C1–C12 check, including boundaries."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.domain.calculators import IncomingSupply
from app.domain.constraints import (
    CONSTRAINT_ORDER,
    ConstraintEngine,
    ConstraintStatus,
    ProposedAction,
    suggested_max_feasible_qty,
)

AS_OF = date(2026, 9, 15)
ENGINE = ConstraintEngine()


def healthy(**overrides) -> ProposedAction:
    """A buy that passes every hard constraint; tests override one axis."""
    payload = dict(
        qty=100,
        unit_price=2.0,
        moq_units=20,
        order_multiple_units=10,
        max_units_per_order=500,
        budget_remaining=1000.0,
        storage_capacity_m3=100.0,
        storage_used_m3=10.0,
        volume_per_unit_m3=0.01,
        supplier_active=True,
        supplier_sells_product=True,
        reliability_score=0.95,
        reliability_floor=0.70,
        lead_time_days=7,
        as_of=AS_OF,
        available=200.0,
        incoming_qty=0.0,
        incoming=[],
        forecast=[10.0] * 40,
        mean_daily=10.0,
        shelf_life_days=180,
        receiving_capacity_units_per_day=1000,
        max_weeks_of_supply=8.0,
        redundant_cover_days=28.0,
    )
    payload.update(overrides)
    return ProposedAction.model_validate(payload)


def result_by_name(report, name: str):
    return next(r for r in report.results if r.name == name)


class TestHealthyBaseline:
    def test_all_twelve_checks_present_and_pass(self) -> None:
        report = ENGINE.evaluate(healthy())
        assert report.passed is True
        assert [r.name for r in report.results] == list(CONSTRAINT_ORDER)
        assert report.blocking_violations == []
        assert all(r.status is ConstraintStatus.PASS for r in report.results)

    def test_dict_input_is_accepted(self) -> None:
        report = ENGINE.evaluate(healthy().model_dump())
        assert report.passed is True


class TestC1Budget:
    def test_fail_when_cost_exceeds_remaining(self) -> None:
        action = healthy(qty=400, unit_price=16.0, budget_remaining=600.0, moq_units=50, order_multiple_units=10)
        report = ENGINE.evaluate(action)
        c1 = result_by_name(report, "budget_sufficient")
        assert c1.status is ConstraintStatus.FAIL
        assert c1.actual == pytest.approx(6400.0)
        assert c1.limit == pytest.approx(600.0)
        assert c1.slack == pytest.approx(-5800.0)
        assert report.passed is False
        assert c1 in report.blocking_violations

    def test_pass_exactly_at_budget(self) -> None:
        action = healthy(qty=100, unit_price=2.0, budget_remaining=200.0)
        c1 = result_by_name(ENGINE.evaluate(action), "budget_sufficient")
        assert c1.status is ConstraintStatus.PASS
        assert c1.slack == pytest.approx(0.0)

    def test_suggested_max_is_budget_then_multiple(self) -> None:
        action = healthy(qty=400, unit_price=10.0, budget_remaining=250.0, moq_units=10, order_multiple_units=10)
        assert suggested_max_feasible_qty(action) == 20
        assert ENGINE.evaluate(action).suggested_max_feasible_qty == 20


class TestC2Storage:
    def test_fail_when_footprint_exceeds_capacity(self) -> None:
        action = healthy(
            qty=800,
            volume_per_unit_m3=0.05,
            storage_used_m3=10.0,
            storage_capacity_m3=15.0,
            unit_price=1.0,
            budget_remaining=10_000,
            moq_units=8,
            order_multiple_units=8,
            max_units_per_order=2000,
        )
        c2 = result_by_name(ENGINE.evaluate(action), "storage_capacity_available")
        assert c2.status is ConstraintStatus.FAIL
        assert c2.actual == pytest.approx(50.0)
        assert c2.limit == pytest.approx(15.0)

    def test_pass_exactly_at_capacity(self) -> None:
        action = healthy(qty=100, volume_per_unit_m3=0.1, storage_used_m3=10.0, storage_capacity_m3=20.0)
        c2 = result_by_name(ENGINE.evaluate(action), "storage_capacity_available")
        assert c2.status is ConstraintStatus.PASS
        assert c2.slack == pytest.approx(0.0)

    def test_suggested_max_from_free_volume(self) -> None:
        action = healthy(
            qty=800,
            volume_per_unit_m3=0.05,
            storage_used_m3=10.0,
            storage_capacity_m3=15.0,
            unit_price=1.0,
            budget_remaining=10_000,
            moq_units=8,
            order_multiple_units=8,
            max_units_per_order=2000,
            mean_daily=100.0,
            forecast=[100.0] * 40,
            available=800,
        )
        assert ENGINE.evaluate(action).suggested_max_feasible_qty == 96


class TestC3Moq:
    def test_fail_below_moq(self) -> None:
        action = healthy(qty=320, moq_units=1000, order_multiple_units=50)
        c3 = result_by_name(ENGINE.evaluate(action), "moq_satisfied")
        assert c3.status is ConstraintStatus.FAIL
        assert c3.actual == 320
        assert c3.limit == 1000

    def test_pass_exactly_at_moq(self) -> None:
        action = healthy(
            qty=1000,
            moq_units=1000,
            order_multiple_units=50,
            budget_remaining=10_000,
            max_units_per_order=5000,
        )
        c3 = result_by_name(ENGINE.evaluate(action), "moq_satisfied")
        assert c3.status is ConstraintStatus.PASS
        assert c3.slack == pytest.approx(0.0)

    def test_zero_qty_skips_moq(self) -> None:
        c3 = result_by_name(ENGINE.evaluate(healthy(qty=0)), "moq_satisfied")
        assert c3.status is ConstraintStatus.PASS

    def test_moq_above_other_caps_yields_zero_feasible(self) -> None:
        action = healthy(
            qty=320,
            unit_price=10.0,
            budget_remaining=4000.0,
            moq_units=1000,
            order_multiple_units=50,
        )
        assert ENGINE.evaluate(action).suggested_max_feasible_qty == 0


class TestC4Multiple:
    def test_fail_when_not_multiple(self) -> None:
        c4 = result_by_name(ENGINE.evaluate(healthy(qty=25, order_multiple_units=10)), "order_multiple_satisfied")
        assert c4.status is ConstraintStatus.FAIL
        assert c4.actual == 25
        assert c4.limit == 10

    def test_pass_when_exact_multiple(self) -> None:
        c4 = result_by_name(ENGINE.evaluate(healthy(qty=30, order_multiple_units=10)), "order_multiple_satisfied")
        assert c4.status is ConstraintStatus.PASS


class TestC5MaxOrderQty:
    def test_fail_over_cap(self) -> None:
        c5 = result_by_name(ENGINE.evaluate(healthy(qty=100, max_units_per_order=80)), "max_order_qty_respected")
        assert c5.status is ConstraintStatus.FAIL
        assert c5.slack == pytest.approx(-20.0)

    def test_pass_exactly_at_cap(self) -> None:
        c5 = result_by_name(ENGINE.evaluate(healthy(qty=100, max_units_per_order=100)), "max_order_qty_respected")
        assert c5.status is ConstraintStatus.PASS
        assert c5.slack == pytest.approx(0.0)

    def test_pass_when_no_cap(self) -> None:
        c5 = result_by_name(ENGINE.evaluate(healthy(qty=100, max_units_per_order=None)), "max_order_qty_respected")
        assert c5.status is ConstraintStatus.PASS


class TestC6Supplier:
    def test_fail_inactive(self) -> None:
        report = ENGINE.evaluate(healthy(supplier_active=False))
        c6 = result_by_name(report, "supplier_active_and_sells_product")
        assert c6.status is ConstraintStatus.FAIL
        assert report.suggested_max_feasible_qty == 0

    def test_fail_does_not_sell(self) -> None:
        c6 = result_by_name(
            ENGINE.evaluate(healthy(supplier_sells_product=False)),
            "supplier_active_and_sells_product",
        )
        assert c6.status is ConstraintStatus.FAIL

    def test_pass_active_and_listed(self) -> None:
        c6 = result_by_name(ENGINE.evaluate(healthy()), "supplier_active_and_sells_product")
        assert c6.status is ConstraintStatus.PASS


class TestC7LeadTime:
    def test_fail_when_arrival_after_stockout(self) -> None:
        stockout = AS_OF + timedelta(days=3)
        action = healthy(lead_time_days=14, projected_stockout_date=stockout, available=20)
        c7 = result_by_name(ENGINE.evaluate(action), "lead_time_beats_stockout")
        assert c7.status is ConstraintStatus.FAIL
        assert ENGINE.evaluate(action).suggested_max_feasible_qty == 0

    def test_pass_when_arrival_on_stockout_day(self) -> None:
        stockout = AS_OF + timedelta(days=7)
        action = healthy(lead_time_days=7, projected_stockout_date=stockout)
        c7 = result_by_name(ENGINE.evaluate(action), "lead_time_beats_stockout")
        assert c7.status is ConstraintStatus.PASS
        assert c7.slack == pytest.approx(0.0)

    def test_pass_when_no_stockout(self) -> None:
        action = healthy(
            projected_stockout_date=None,
            available=25,
            forecast=[10.0, 10.0],
            mean_daily=10.0,
        )
        c7 = result_by_name(ENGINE.evaluate(action), "lead_time_beats_stockout")
        assert c7.status is ConstraintStatus.PASS


class TestC8RedundantCoverage:
    def test_fail_when_open_po_already_covers_horizon(self) -> None:
        action = healthy(
            qty=800,
            available=160,
            incoming_qty=800,
            incoming=[IncomingSupply(qty=800, expected_date=AS_OF)],
            forecast=[25.0] * 40,
            mean_daily=25.0,
            unit_price=0.28,
            budget_remaining=10_000,
            moq_units=24,
            order_multiple_units=24,
            max_units_per_order=5000,
            volume_per_unit_m3=0.0006,
            redundant_cover_days=28,
        )
        report = ENGINE.evaluate(action)
        c8 = result_by_name(report, "no_redundant_coverage_with_open_pos")
        assert c8.status is ConstraintStatus.FAIL
        assert report.suggested_max_feasible_qty == 0

    def test_pass_when_cover_is_short(self) -> None:
        c8 = result_by_name(ENGINE.evaluate(healthy()), "no_redundant_coverage_with_open_pos")
        assert c8.status is ConstraintStatus.PASS


class TestC9ShelfLife:
    def test_warn_when_cover_exceeds_shelf_life(self) -> None:
        action = healthy(
            qty=100,
            available=20,
            mean_daily=2.0,
            forecast=[2.0] * 40,
            shelf_life_days=30,
            lead_time_days=3,
            max_weeks_of_supply=16,
        )
        report = ENGINE.evaluate(action)
        c9 = result_by_name(report, "shelf_life_vs_cover_days")
        assert c9.status is ConstraintStatus.WARN
        assert report.passed is True
        assert c9 in report.warnings

    def test_pass_when_cover_within_shelf_life(self) -> None:
        c9 = result_by_name(ENGINE.evaluate(healthy(shelf_life_days=180)), "shelf_life_vs_cover_days")
        assert c9.status is ConstraintStatus.PASS


class TestC10Receiving:
    def test_warn_when_qty_exceeds_daily_receiving(self) -> None:
        action = healthy(
            qty=800,
            receiving_capacity_units_per_day=400,
            budget_remaining=10_000,
            max_units_per_order=2000,
            mean_daily=20.0,
            forecast=[20.0] * 40,
        )
        report = ENGINE.evaluate(action)
        c10 = result_by_name(report, "receiving_capacity_per_day")
        assert c10.status is ConstraintStatus.WARN
        assert report.passed is True

    def test_pass_when_qty_fits_one_day(self) -> None:
        c10 = result_by_name(
            ENGINE.evaluate(healthy(qty=100, receiving_capacity_units_per_day=100)),
            "receiving_capacity_per_day",
        )
        assert c10.status is ConstraintStatus.PASS
        assert c10.slack == pytest.approx(0.0)


class TestC11Reliability:
    def test_warn_below_floor(self) -> None:
        action = healthy(reliability_score=0.41, reliability_floor=0.70)
        report = ENGINE.evaluate(action)
        c11 = result_by_name(report, "supplier_reliability_floor")
        assert c11.status is ConstraintStatus.WARN
        assert c11.slack == pytest.approx(-0.29)
        assert report.passed is True

    def test_pass_exactly_at_floor(self) -> None:
        c11 = result_by_name(
            ENGINE.evaluate(healthy(reliability_score=0.70, reliability_floor=0.70)),
            "supplier_reliability_floor",
        )
        assert c11.status is ConstraintStatus.PASS
        assert c11.slack == pytest.approx(0.0)


class TestC12WeeksOfSupply:
    def test_fail_when_cover_exceeds_max_weeks(self) -> None:
        action = healthy(qty=600, available=200, mean_daily=10.0, forecast=[10.0] * 40, max_weeks_of_supply=8)
        c12 = result_by_name(ENGINE.evaluate(action), "total_cover_within_max_weeks_of_supply")
        assert c12.status is ConstraintStatus.FAIL
        assert c12.actual == pytest.approx(80.0)
        assert c12.limit == pytest.approx(56.0)

    def test_pass_exactly_at_max_weeks(self) -> None:
        action = healthy(qty=360, available=200, mean_daily=10.0, forecast=[10.0] * 10, max_weeks_of_supply=8)
        c12 = result_by_name(ENGINE.evaluate(action), "total_cover_within_max_weeks_of_supply")
        assert c12.status is ConstraintStatus.PASS
        assert c12.slack == pytest.approx(0.0)

    def test_zero_demand_does_not_fail(self) -> None:
        action = healthy(qty=100, mean_daily=0.0, forecast=[0.0] * 10, available=0)
        c12 = result_by_name(ENGINE.evaluate(action), "total_cover_within_max_weeks_of_supply")
        assert c12.status is ConstraintStatus.PASS


class TestBindingAndSuggested:
    def test_binding_on_failure_is_the_tightest_blocker(self) -> None:
        action = healthy(qty=400, unit_price=16.0, budget_remaining=600.0, moq_units=50)
        report = ENGINE.evaluate(action)
        binding = ENGINE.binding_constraint(report)
        assert binding is not None
        assert binding.name == "budget_sufficient"

    def test_binding_on_pass_is_least_slack_hard_check(self) -> None:
        action = healthy(qty=100, unit_price=2.0, budget_remaining=200.0)
        report = ENGINE.evaluate(action)
        assert report.passed is True
        binding = ENGINE.binding_constraint(report)
        assert binding is not None
        assert binding.name == "budget_sufficient"
        assert binding.slack == pytest.approx(0.0)

    def test_storage_binds_over_budget_when_tighter(self) -> None:
        action = healthy(
            qty=800,
            unit_price=1.0,
            budget_remaining=10_000,
            volume_per_unit_m3=0.05,
            storage_used_m3=10.0,
            storage_capacity_m3=15.0,
            moq_units=8,
            order_multiple_units=8,
            max_units_per_order=2000,
            mean_daily=50.0,
            forecast=[50.0] * 40,
            available=400,
        )
        report = ENGINE.evaluate(action)
        binding = ENGINE.binding_constraint(report)
        assert binding is not None
        assert binding.name == "storage_capacity_available"

    def test_negative_available_does_not_crash(self) -> None:
        action = healthy(available=-15.0, qty=20, forecast=[5.0] * 20, mean_daily=5.0)
        report = ENGINE.evaluate(action)
        assert isinstance(report.passed, bool)
        assert len(report.results) == 12
