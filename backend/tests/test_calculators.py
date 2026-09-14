"""Pure-function tests for replenishment calculators. No LLM, no DB."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from app.domain.calculators import (
    Z_95,
    IncomingSupply,
    apply_supplier_rounding,
    coverage_days,
    demand_stats,
    effective_available,
    incoming_supply,
    inverse_normal_cdf,
    landed_cost,
    net_requirement,
    reorder_point,
    safety_stock,
    storage_footprint,
)

AS_OF = date(2026, 9, 15)


class TestDemandStats:
    def test_zero_demand(self) -> None:
        stats = demand_stats([0] * 42, window=42)
        assert stats.mean_daily == 0.0
        assert stats.std_daily == 0.0
        assert stats.trend_slope == 0.0
        assert stats.last_14d_vs_prior_28d_delta == 0.0
        assert stats.spike_detected is False
        assert stats.anomaly_flag is False

    def test_empty_series(self) -> None:
        stats = demand_stats([])
        assert stats.mean_daily == 0.0
        assert stats.spike_detected is False

    def test_constant_series_mean_and_zero_std(self) -> None:
        stats = demand_stats([10] * 30, window=30)
        assert stats.mean_daily == 10.0
        assert stats.std_daily == 0.0
        assert stats.trend_slope == pytest.approx(0.0)

    def test_sample_std_known_values(self) -> None:
        # population of 2,4,4,4,5,5,7,9 — sample stdev = 2.138...
        stats = demand_stats([2, 4, 4, 4, 5, 5, 7, 9], window=8)
        assert stats.mean_daily == pytest.approx(5.0)
        assert stats.std_daily == pytest.approx(2.138089935, rel=1e-6)

    def test_trend_slope_exact_line(self) -> None:
        # y = 2x : 0,2,4,6,8 → slope 2
        stats = demand_stats([0, 2, 4, 6, 8], window=5)
        assert stats.trend_slope == pytest.approx(2.0)

    def test_genuine_spike_not_anomaly(self) -> None:
        prior = [18] * 28
        recent = [48] * 14
        stats = demand_stats(prior + recent, window=42)
        assert stats.last_14d_vs_prior_28d_delta == pytest.approx(30.0)
        assert stats.spike_detected is True
        assert stats.anomaly_flag is False

    def test_promo_anomaly_not_spike(self) -> None:
        # 13 days at 24 plus one 560-unit bulk invoice in the last 14.
        prior = [24] * 28
        recent = [24] * 6 + [560] + [24] * 7
        stats = demand_stats(prior + recent, window=42)
        assert stats.anomaly_flag is True
        assert stats.spike_detected is False
        assert stats.last_14d_vs_prior_28d_delta == pytest.approx((24 * 13 + 560) / 14 - 24)

    def test_window_uses_the_tail(self) -> None:
        series = [1] * 20 + [9] * 10
        full = demand_stats(series, window=30)
        tail = demand_stats(series, window=10)
        assert full.mean_daily == pytest.approx((20 + 90) / 30)
        assert tail.mean_daily == pytest.approx(9.0)

    def test_rejects_non_positive_window(self) -> None:
        with pytest.raises(ValueError):
            demand_stats([1, 2, 3], window=0)


class TestEffectiveAvailable:
    def test_simple(self) -> None:
        assert effective_available(100, 10, 5) == 85.0

    def test_zero(self) -> None:
        assert effective_available(0, 0, 0) == 0.0

    def test_negative_available(self) -> None:
        assert effective_available(10, 8, 5) == -3.0

    def test_all_reserved(self) -> None:
        assert effective_available(50, 50, 0) == 0.0


class TestIncomingSupply:
    def test_submitted_uses_ordered_qty(self) -> None:
        receipts = incoming_supply(
            [
                {
                    "status": "submitted",
                    "ordered_qty": 500,
                    "confirmed_qty": 0,
                    "expected_date": AS_OF,
                }
            ]
        )
        assert len(receipts) == 1
        assert receipts[0].qty == 500

    def test_confirmed_uses_confirmed_qty(self) -> None:
        receipts = incoming_supply(
            [
                {
                    "status": "confirmed",
                    "ordered_qty": 800,
                    "confirmed_qty": 800,
                    "expected_date": AS_OF + timedelta(days=5),
                }
            ]
        )
        assert receipts[0].qty == 800

    def test_partially_confirmed_honours_confirmed_qty(self) -> None:
        receipts = incoming_supply(
            [
                {
                    "status": "partially_confirmed",
                    "ordered_qty": 500,
                    "confirmed_qty": 250,
                    "expected_date": AS_OF + timedelta(days=7),
                }
            ]
        )
        assert receipts[0].qty == 250
        assert receipts[0].expected_date == AS_OF + timedelta(days=7)

    def test_partial_zero_confirmed_stays_zero(self) -> None:
        receipts = incoming_supply(
            [{"status": "partially_confirmed", "ordered_qty": 500, "confirmed_qty": 0, "expected_date": AS_OF}]
        )
        assert receipts[0].qty == 0

    def test_cancelled_and_received_skipped(self) -> None:
        receipts = incoming_supply(
            [
                {"status": "cancelled", "ordered_qty": 100, "confirmed_qty": 100, "expected_date": AS_OF},
                {"status": "received", "ordered_qty": 40, "confirmed_qty": 40, "expected_date": AS_OF},
            ]
        )
        assert receipts == []

    def test_lines_on_a_po(self) -> None:
        receipts = incoming_supply(
            [
                {
                    "status": "confirmed",
                    "expected_date": AS_OF,
                    "lines": [
                        {"ordered_qty": 10, "confirmed_qty": 10},
                        {"ordered_qty": 5, "confirmed_qty": 5},
                    ],
                }
            ]
        )
        assert [r.qty for r in receipts] == [10, 5]


class TestCoverageDays:
    def test_exact_integer_cover(self) -> None:
        result = coverage_days(30, [], [10, 10, 10], as_of=AS_OF)
        assert result.coverage_days == pytest.approx(3.0)
        assert result.projected_daily_stock == [20, 10, 0]
        assert result.projected_stockout_date is None

    def test_stockout_mid_horizon(self) -> None:
        result = coverage_days(25, [], [10, 10, 10, 10], as_of=AS_OF)
        assert result.coverage_days == pytest.approx(2.5)
        assert result.projected_stockout_date == AS_OF + timedelta(days=2)
        assert result.projected_daily_stock[0] == pytest.approx(15)
        assert result.projected_daily_stock[1] == pytest.approx(5)
        assert result.projected_daily_stock[2] == pytest.approx(-5)

    def test_incoming_arrives_before_demand(self) -> None:
        incoming = [IncomingSupply(qty=20, expected_date=AS_OF + timedelta(days=1))]
        result = coverage_days(10, incoming, [10, 10, 10], as_of=AS_OF)
        # day 0: 10-10=0; day 1: 0+20-10=10; day 2: 10-10=0
        assert result.projected_daily_stock == pytest.approx([0, 10, 0])
        assert result.projected_stockout_date is None
        assert result.coverage_days == pytest.approx(3.0)

    def test_late_receipt_counted_today(self) -> None:
        incoming = [IncomingSupply(qty=5, expected_date=AS_OF - timedelta(days=2))]
        result = coverage_days(0, incoming, [5], as_of=AS_OF)
        assert result.projected_daily_stock == [0]
        assert result.projected_stockout_date is None

    def test_zero_demand_infinite_cover(self) -> None:
        result = coverage_days(12, [], [0, 0, 0], as_of=AS_OF)
        assert math.isinf(result.coverage_days)
        assert result.projected_stockout_date is None
        assert result.projected_daily_stock == [12, 12, 12]

    def test_negative_available_stockout_today(self) -> None:
        result = coverage_days(-4, [], [10, 10], as_of=AS_OF)
        assert result.coverage_days == pytest.approx(0.0)
        assert result.projected_stockout_date == AS_OF

    def test_empty_forecast_no_stockout_when_non_negative(self) -> None:
        result = coverage_days(5, [], [], as_of=AS_OF)
        assert math.isinf(result.coverage_days)
        assert result.projected_stockout_date is None

    def test_survives_horizon_with_extra_days(self) -> None:
        result = coverage_days(50, [], [10, 10], as_of=AS_OF)
        # 2 days of forecast + leftover 30 / avg 10 = 5 days total
        assert result.coverage_days == pytest.approx(5.0)


class TestSafetyStockAndRop:
    def test_z95_matches_acklam(self) -> None:
        assert inverse_normal_cdf(0.95) == pytest.approx(Z_95, rel=1e-5)

    def test_deterministic_lead_time_reduces_to_z_sigma_sqrt_l(self) -> None:
        ss = safety_stock(mean_daily=10, demand_std=2, lead_time_days=9, lead_time_std=0, service_level=0.95)
        assert ss == pytest.approx(Z_95 * 2 * math.sqrt(9))

    def test_sigma_lt_includes_lead_time_variance(self) -> None:
        ss = safety_stock(mean_daily=10, demand_std=2, lead_time_days=9, lead_time_std=1, service_level=0.95)
        sigma_lt = math.sqrt(9 * 4 + 100 * 1)
        assert ss == pytest.approx(Z_95 * sigma_lt)

    def test_zero_demand_zero_ss(self) -> None:
        assert safety_stock(0, 0, 7, 0) == 0.0

    def test_zero_lead_time_zero_ss_without_lt_std(self) -> None:
        assert safety_stock(10, 2, 0, 0) == 0.0

    def test_reorder_point(self) -> None:
        assert reorder_point(10, 7, 12) == pytest.approx(82.0)

    def test_reorder_point_zero_demand(self) -> None:
        assert reorder_point(0, 7, 0) == 0.0


class TestNetRequirement:
    def test_positive_gap(self) -> None:
        # demand 100 + SS 10 - available 30 - incoming 20 = 60
        assert net_requirement(100, 30, 20, 10) == pytest.approx(60.0)

    def test_already_covered_returns_zero(self) -> None:
        assert net_requirement(50, 80, 20, 5) == 0.0

    def test_negative_available_increases_need(self) -> None:
        assert net_requirement(40, -10, 0, 0) == pytest.approx(50.0)

    def test_zero_demand(self) -> None:
        assert net_requirement(0, 10, 0, 5) == 0.0


class TestSupplierRounding:
    def test_exactly_at_moq(self) -> None:
        result = apply_supplier_rounding(1000, moq=1000, order_multiple=50, max_units_per_order=5000)
        assert result.qty == 1000
        assert result.changes == []

    def test_round_up_to_multiple_then_moq(self) -> None:
        result = apply_supplier_rounding(320, moq=1000, order_multiple=50, max_units_per_order=5000)
        assert result.qty == 1000
        assert any("MOQ" in c for c in result.changes)

    def test_round_up_to_multiple_only(self) -> None:
        result = apply_supplier_rounding(21, moq=10, order_multiple=10, max_units_per_order=None)
        assert result.qty == 30

    def test_zero_requirement_does_not_lift_to_moq(self) -> None:
        result = apply_supplier_rounding(0, moq=100, order_multiple=10, max_units_per_order=None)
        assert result.qty == 0
        assert "zero_requirement" in result.changes

    def test_negative_requirement_is_zero(self) -> None:
        result = apply_supplier_rounding(-12, moq=10, order_multiple=1, max_units_per_order=None)
        assert result.qty == 0

    def test_cap_at_max_units(self) -> None:
        result = apply_supplier_rounding(80, moq=10, order_multiple=10, max_units_per_order=50)
        assert result.qty == 50

    def test_cap_below_moq_is_callers_problem(self) -> None:
        result = apply_supplier_rounding(40, moq=100, order_multiple=10, max_units_per_order=80)
        assert result.qty == 80  # 100 lifted then capped to 80
        assert any("capped" in c for c in result.changes)


class TestCostAndFootprint:
    def test_landed_cost(self) -> None:
        assert landed_cost(400, 16.0) == pytest.approx(6400.0)

    def test_landed_cost_zero(self) -> None:
        assert landed_cost(0, 16.0) == 0.0

    def test_storage_footprint(self) -> None:
        assert storage_footprint(800, 0.05) == pytest.approx(40.0)

    def test_storage_footprint_zero_volume(self) -> None:
        assert storage_footprint(100, 0.0) == 0.0
