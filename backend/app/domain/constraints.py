"""Constraint / invariant engine.

The LLM never decides whether a constraint is satisfied. Every write
action is evaluated here against C1–C12; each check is named and
reportable on its own.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.calculators import (
    IncomingSupply,
    coverage_days,
    landed_cost,
    storage_footprint,
)

HARD_CONSTRAINTS = frozenset(
    {
        "budget_sufficient",
        "storage_capacity_available",
        "moq_satisfied",
        "order_multiple_satisfied",
        "max_order_qty_respected",
        "supplier_active_and_sells_product",
        "lead_time_beats_stockout",
        "no_redundant_coverage_with_open_pos",
        "total_cover_within_max_weeks_of_supply",
    }
)

WARN_CONSTRAINTS = frozenset(
    {
        "shelf_life_vs_cover_days",
        "receiving_capacity_per_day",
        "supplier_reliability_floor",
    }
)

CONSTRAINT_ORDER = (
    "budget_sufficient",
    "storage_capacity_available",
    "moq_satisfied",
    "order_multiple_satisfied",
    "max_order_qty_respected",
    "supplier_active_and_sells_product",
    "lead_time_beats_stockout",
    "no_redundant_coverage_with_open_pos",
    "shelf_life_vs_cover_days",
    "receiving_capacity_per_day",
    "supplier_reliability_floor",
    "total_cover_within_max_weeks_of_supply",
)


class ConstraintStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class ConstraintResult(BaseModel):
    name: str
    status: ConstraintStatus
    actual: float | str | None = None
    limit: float | str | None = None
    slack: float | None = None
    message: str = ""


class ValidationReport(BaseModel):
    passed: bool
    results: list[ConstraintResult] = Field(default_factory=list)
    blocking_violations: list[ConstraintResult] = Field(default_factory=list)
    warnings: list[ConstraintResult] = Field(default_factory=list)
    suggested_max_feasible_qty: int | None = None


class ProposedAction(BaseModel):
    """Facts required to evaluate a buy. Assembled by tools, never by the LLM."""

    qty: int
    unit_price: float = 0.0
    moq_units: int = 1
    order_multiple_units: int = 1
    max_units_per_order: int | None = None
    budget_remaining: float = 0.0
    storage_capacity_m3: float = 0.0
    storage_used_m3: float = 0.0
    volume_per_unit_m3: float = 0.0
    supplier_active: bool = True
    supplier_sells_product: bool = True
    reliability_score: float = 1.0
    reliability_floor: float = 0.70
    lead_time_days: int = 0
    as_of: date | None = None
    projected_stockout_date: date | None = None
    available: float = 0.0
    incoming_qty: float = 0.0
    incoming: list[IncomingSupply] = Field(default_factory=list)
    forecast: list[float] = Field(default_factory=list)
    mean_daily: float | None = None
    shelf_life_days: int | None = None
    receiving_capacity_units_per_day: int | None = None
    max_weeks_of_supply: float = 8.0
    review_period_days: int = 7
    redundant_cover_days: float = 28.0


def _ok(name: str, actual: float | str | None, limit: float | str | None, slack: float | None, message: str) -> ConstraintResult:
    return ConstraintResult(
        name=name,
        status=ConstraintStatus.PASS,
        actual=actual,
        limit=limit,
        slack=slack,
        message=message,
    )


def _fail(name: str, actual: float | str | None, limit: float | str | None, slack: float | None, message: str) -> ConstraintResult:
    return ConstraintResult(
        name=name,
        status=ConstraintStatus.FAIL,
        actual=actual,
        limit=limit,
        slack=slack,
        message=message,
    )


def _warn(name: str, actual: float | str | None, limit: float | str | None, slack: float | None, message: str) -> ConstraintResult:
    return ConstraintResult(
        name=name,
        status=ConstraintStatus.WARN,
        actual=actual,
        limit=limit,
        slack=slack,
        message=message,
    )


def _mean_daily(action: ProposedAction) -> float:
    if action.mean_daily is not None:
        return float(action.mean_daily)
    positive = [d for d in action.forecast if d > 0]
    if positive:
        return sum(positive) / len(positive)
    return 0.0


def _cover_without_new_po(action: ProposedAction) -> float:
    result = coverage_days(
        action.available,
        action.incoming,
        action.forecast,
        as_of=action.as_of,
    )
    return result.coverage_days


def _weeks_of_supply(action: ProposedAction, qty: int) -> float:
    mean = _mean_daily(action)
    if mean <= 0:
        return 0.0
    position = action.available + action.incoming_qty + qty
    return position / mean


def c1_budget_sufficient(action: ProposedAction) -> ConstraintResult:
    cost = landed_cost(action.qty, action.unit_price)
    remaining = float(action.budget_remaining)
    slack = remaining - cost
    if cost <= remaining + 1e-9:
        return _ok("budget_sufficient", cost, remaining, slack, "Landed cost is within remaining budget.")
    return _fail("budget_sufficient", cost, remaining, slack, f"Landed cost {cost:.2f} exceeds remaining budget {remaining:.2f}.")


def c2_storage_capacity_available(action: ProposedAction) -> ConstraintResult:
    added = storage_footprint(action.qty, action.volume_per_unit_m3)
    actual = action.storage_used_m3 + added
    limit = action.storage_capacity_m3
    slack = limit - actual
    if actual <= limit + 1e-9:
        return _ok("storage_capacity_available", actual, limit, slack, "Storage footprint fits remaining capacity.")
    return _fail(
        "storage_capacity_available",
        actual,
        limit,
        slack,
        f"Storage {actual:.4f} m3 exceeds capacity {limit:.4f} m3.",
    )


def c3_moq_satisfied(action: ProposedAction) -> ConstraintResult:
    qty = action.qty
    moq = max(0, int(action.moq_units))
    if qty == 0:
        return _ok("moq_satisfied", qty, moq, float(moq), "Zero qty is not an order; MOQ does not apply.")
    slack = float(qty - moq)
    if qty >= moq:
        return _ok("moq_satisfied", qty, moq, slack, "Qty meets supplier MOQ.")
    return _fail("moq_satisfied", qty, moq, slack, f"Qty {qty} is below MOQ {moq}.")


def c4_order_multiple_satisfied(action: ProposedAction) -> ConstraintResult:
    qty = action.qty
    multiple = max(1, int(action.order_multiple_units or 1))
    if qty == 0:
        return _ok("order_multiple_satisfied", qty, multiple, 0.0, "Zero qty is not an order.")
    remainder = qty % multiple
    slack = 0.0 if remainder == 0 else float(remainder - multiple)
    if remainder == 0:
        return _ok("order_multiple_satisfied", qty, multiple, 0.0, "Qty is an order multiple.")
    return _fail(
        "order_multiple_satisfied",
        qty,
        multiple,
        slack,
        f"Qty {qty} is not a multiple of {multiple} (remainder {remainder}).",
    )


def c5_max_order_qty_respected(action: ProposedAction) -> ConstraintResult:
    qty = action.qty
    cap = action.max_units_per_order
    if cap is None:
        return _ok("max_order_qty_respected", qty, None, None, "Supplier has no max-per-order cap.")
    slack = float(cap - qty)
    if qty <= cap:
        return _ok("max_order_qty_respected", qty, cap, slack, "Qty is within max per order.")
    return _fail("max_order_qty_respected", qty, cap, slack, f"Qty {qty} exceeds max per order {cap}.")


def c6_supplier_active_and_sells_product(action: ProposedAction) -> ConstraintResult:
    active = action.supplier_active
    sells = action.supplier_sells_product
    if active and sells:
        return _ok(
            "supplier_active_and_sells_product",
            "active+listed",
            "active+listed",
            1.0,
            "Supplier is active and lists the product.",
        )
    reasons = []
    if not active:
        reasons.append("inactive")
    if not sells:
        reasons.append("does not sell product")
    return _fail(
        "supplier_active_and_sells_product",
        ",".join(reasons),
        "active+listed",
        -1.0,
        "Supplier is " + " and ".join(reasons) + ".",
    )


def c7_lead_time_beats_stockout(action: ProposedAction) -> ConstraintResult:
    stockout = action.projected_stockout_date
    if stockout is None and action.forecast:
        stockout = coverage_days(
            action.available,
            action.incoming,
            action.forecast,
            as_of=action.as_of,
        ).projected_stockout_date
    if stockout is None:
        return _ok(
            "lead_time_beats_stockout",
            None,
            action.lead_time_days,
            None,
            "No stockout projected inside the forecast horizon.",
        )
    if action.as_of is None:
        return _ok(
            "lead_time_beats_stockout",
            None,
            action.lead_time_days,
            None,
            "No as_of date; lead-time vs stockout not evaluated.",
        )
    as_of = action.as_of
    arrival = as_of + timedelta(days=int(action.lead_time_days))
    slack_days = float((stockout - arrival).days)
    if arrival <= stockout:
        return _ok(
            "lead_time_beats_stockout",
            arrival.isoformat(),
            stockout.isoformat(),
            slack_days,
            f"Arrival {arrival.isoformat()} is on or before stockout {stockout.isoformat()}.",
        )
    return _fail(
        "lead_time_beats_stockout",
        arrival.isoformat(),
        stockout.isoformat(),
        slack_days,
        f"Lead time arrives {arrival.isoformat()}, after stockout {stockout.isoformat()}.",
    )


def c8_no_redundant_coverage_with_open_pos(action: ProposedAction) -> ConstraintResult:
    if not action.forecast or all(d <= 0 for d in action.forecast):
        return _ok(
            "no_redundant_coverage_with_open_pos",
            None,
            action.redundant_cover_days,
            None,
            "No positive forecast; redundancy not evaluated.",
        )
    cover = _cover_without_new_po(action)
    horizon = float(action.redundant_cover_days)
    slack = horizon - cover
    if action.qty <= 0:
        return _ok("no_redundant_coverage_with_open_pos", cover, horizon, slack, "No additional qty proposed.")
    if cover >= horizon:
        return _fail(
            "no_redundant_coverage_with_open_pos",
            cover,
            horizon,
            slack,
            f"Existing available + open POs already cover {cover:.1f} days (horizon {horizon:.0f}).",
        )
    return _ok(
        "no_redundant_coverage_with_open_pos",
        cover,
        horizon,
        slack,
        f"Existing cover {cover:.1f} days is below the {horizon:.0f}-day redundancy horizon.",
    )


def c9_shelf_life_vs_cover_days(action: ProposedAction) -> ConstraintResult:
    shelf = action.shelf_life_days
    if shelf is None:
        return _ok("shelf_life_vs_cover_days", None, None, None, "No shelf-life limit provided.")
    cover = _weeks_of_supply(action, action.qty)
    slack = float(shelf) - cover
    if cover <= float(shelf) + 1e-9:
        return _ok("shelf_life_vs_cover_days", cover, float(shelf), slack, "Projected cover is within shelf life.")
    return _warn(
        "shelf_life_vs_cover_days",
        cover,
        float(shelf),
        slack,
        f"Projected cover {cover:.1f} days exceeds shelf life {shelf} days.",
    )


def c10_receiving_capacity_per_day(action: ProposedAction) -> ConstraintResult:
    cap = action.receiving_capacity_units_per_day
    if cap is None:
        return _ok("receiving_capacity_per_day", action.qty, None, None, "No receiving-capacity limit provided.")
    slack = float(cap - action.qty)
    if action.qty <= cap:
        return _ok("receiving_capacity_per_day", action.qty, cap, slack, "Qty can be received in one day.")
    return _warn(
        "receiving_capacity_per_day",
        action.qty,
        cap,
        slack,
        f"Qty {action.qty} exceeds daily receiving capacity {cap}; split the receipt.",
    )


def c11_supplier_reliability_floor(action: ProposedAction) -> ConstraintResult:
    score = float(action.reliability_score)
    floor = float(action.reliability_floor)
    slack = score - floor
    if score + 1e-12 >= floor:
        return _ok("supplier_reliability_floor", score, floor, slack, "Supplier reliability is at or above the floor.")
    return _warn(
        "supplier_reliability_floor",
        score,
        floor,
        slack,
        f"Reliability {score:.2f} is below floor {floor:.2f}; buffer or re-source.",
    )


def c12_total_cover_within_max_weeks_of_supply(action: ProposedAction) -> ConstraintResult:
    max_days = float(action.max_weeks_of_supply) * 7.0
    cover = _weeks_of_supply(action, action.qty)
    slack = max_days - cover
    if _mean_daily(action) <= 0:
        return _ok(
            "total_cover_within_max_weeks_of_supply",
            cover,
            max_days,
            None,
            "Zero demand; weeks-of-supply cap is not binding.",
        )
    if cover <= max_days + 1e-9:
        return _ok(
            "total_cover_within_max_weeks_of_supply",
            cover,
            max_days,
            slack,
            f"Cover {cover:.1f} days is within {action.max_weeks_of_supply:g} weeks.",
        )
    return _fail(
        "total_cover_within_max_weeks_of_supply",
        cover,
        max_days,
        slack,
        f"Cover {cover:.1f} days exceeds max {action.max_weeks_of_supply:g} weeks ({max_days:.0f} days).",
    )


_CHECKERS = (
    c1_budget_sufficient,
    c2_storage_capacity_available,
    c3_moq_satisfied,
    c4_order_multiple_satisfied,
    c5_max_order_qty_respected,
    c6_supplier_active_and_sells_product,
    c7_lead_time_beats_stockout,
    c8_no_redundant_coverage_with_open_pos,
    c9_shelf_life_vs_cover_days,
    c10_receiving_capacity_per_day,
    c11_supplier_reliability_floor,
    c12_total_cover_within_max_weeks_of_supply,
)


def _align_multiple(qty: int, multiple: int) -> int:
    multiple = max(1, int(multiple or 1))
    return (qty // multiple) * multiple


def suggested_max_feasible_qty(action: ProposedAction) -> int:
    """Largest integer qty that would pass every hard constraint."""
    if not action.supplier_active or not action.supplier_sells_product:
        return 0

    # C7: a slow supplier cannot be rescued by buying more of the same lead time.
    c7 = c7_lead_time_beats_stockout(action)
    if c7.status is ConstraintStatus.FAIL:
        return 0

    # C8: already covered — any extra qty is redundant.
    c8 = c8_no_redundant_coverage_with_open_pos(action.model_copy(update={"qty": 1}))
    if c8.status is ConstraintStatus.FAIL:
        return 0

    multiple = max(1, int(action.order_multiple_units or 1))
    moq = max(0, int(action.moq_units))
    caps: list[int] = []

    if action.unit_price > 0:
        caps.append(int(action.budget_remaining // action.unit_price))
    if action.volume_per_unit_m3 > 0:
        free = action.storage_capacity_m3 - action.storage_used_m3
        caps.append(int(free // action.volume_per_unit_m3) if free > 0 else 0)
    if action.max_units_per_order is not None:
        caps.append(int(action.max_units_per_order))

    mean = _mean_daily(action)
    if mean > 0:
        max_days = float(action.max_weeks_of_supply) * 7.0
        max_position = max_days * mean
        caps.append(int(max_position - action.available - action.incoming_qty))

    if not caps:
        raw_max = 10**9
    else:
        raw_max = min(caps)

    if raw_max < 0:
        raw_max = 0
    aligned = _align_multiple(raw_max, multiple)
    if moq and 0 < aligned < moq:
        return 0
    if moq and aligned >= moq and aligned % multiple != 0:
        aligned = _align_multiple(aligned, multiple)
        if aligned < moq:
            return 0
    return max(0, aligned)


class ConstraintEngine:
    """Individually named, individually reportable invariant checks (C1–C12)."""

    def evaluate(self, proposed_action: ProposedAction | dict[str, Any]) -> ValidationReport:
        action = proposed_action if isinstance(proposed_action, ProposedAction) else ProposedAction.model_validate(proposed_action)
        results = [check(action) for check in _CHECKERS]
        blocking = [r for r in results if r.status is ConstraintStatus.FAIL and r.name in HARD_CONSTRAINTS]
        warnings = [r for r in results if r.status is ConstraintStatus.WARN]
        # Defensive: a FAIL on a warn-class check still shows as a warning, not a block.
        for r in results:
            if r.status is ConstraintStatus.FAIL and r.name in WARN_CONSTRAINTS:
                warnings.append(r)
        return ValidationReport(
            passed=not blocking,
            results=results,
            blocking_violations=blocking,
            warnings=warnings,
            suggested_max_feasible_qty=suggested_max_feasible_qty(action),
        )

    def binding_constraint(self, report: ValidationReport) -> ConstraintResult | None:
        """The single constraint that is the limiting factor.

        On a failing report, the blocking check with the smallest slack (most
        negative room). On a passing report, the hard check with the least
        remaining slack — the one that would break first if qty rose.
        """
        if report.blocking_violations:
            return min(
                report.blocking_violations,
                key=lambda r: (
                    r.slack if r.slack is not None else float("-inf"),
                    CONSTRAINT_ORDER.index(r.name) if r.name in CONSTRAINT_ORDER else 99,
                ),
            )
        tightest: list[ConstraintResult] = [
            r
            for r in report.results
            if r.name in HARD_CONSTRAINTS and r.slack is not None
        ]
        if not tightest:
            return None
        return min(tightest, key=lambda r: (r.slack, CONSTRAINT_ORDER.index(r.name)))
