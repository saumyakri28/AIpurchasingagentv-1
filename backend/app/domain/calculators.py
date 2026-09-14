"""Pure replenishment calculators.

The LLM never performs arithmetic. Every quantitative claim the agent
makes must come from one of these functions (exposed as tools).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

# z_{0.95} for the common default; other service levels use the inverse CDF.
Z_95 = 1.6448536269514722

OPEN_PO_STATUSES = frozenset(
    {"submitted", "confirmed", "partially_confirmed", "pending_approval"}
)


class DemandStats(BaseModel):
    mean_daily: float
    std_daily: float
    trend_slope: float
    last_14d_vs_prior_28d_delta: float
    spike_detected: bool
    anomaly_flag: bool


class IncomingSupply(BaseModel):
    qty: float
    expected_date: date | None = None


class CoverageResult(BaseModel):
    coverage_days: float
    projected_daily_stock: list[float] = Field(default_factory=list)
    projected_stockout_date: date | None = None


class RoundingResult(BaseModel):
    qty: int
    explanation: str
    changes: list[str] = Field(default_factory=list)


def _as_float_series(sales: Sequence[Any]) -> list[float]:
    values: list[float] = []
    for item in sales:
        if isinstance(item, (tuple, list)) and item:
            values.append(float(item[-1]))
        elif isinstance(item, Mapping):
            values.append(float(item.get("units_sold", item.get("qty", 0))))
        else:
            values.append(float(item))
    return values


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values)


def _ols_slope(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = 0.0
    den = 0.0
    for i, y in enumerate(values):
        dx = i - x_mean
        num += dx * (y - y_mean)
        den += dx * dx
    return 0.0 if den == 0 else num / den


def _anomaly_in(window: Sequence[float], *, dominate_share: float = 0.35) -> bool:
    """Single-day outlier > 3σ of the other days, dominating window volume."""
    if len(window) < 2:
        return False
    peak = max(window)
    peak_i = window.index(peak)
    others = [v for i, v in enumerate(window) if i != peak_i]
    if not others:
        return False
    total = sum(window)
    if total <= 0:
        return False
    other_mean = statistics.fmean(others)
    other_std = statistics.pstdev(others)
    if other_std <= 0:
        z = math.inf if peak > other_mean else 0.0
    else:
        z = (peak - other_mean) / other_std
    return z > 3.0 and (peak / total) >= dominate_share


def demand_stats(
    sales: Sequence[Any],
    window: int | None = None,
    product: str | None = None,  # noqa: ARG001 — accepted so the tool wrapper can pass identity
    node: str | None = None,  # noqa: ARG001
) -> DemandStats:
    """Mean daily, std, OLS trend slope, 14d vs prior-28d delta, spike and anomaly.

    `sales` is a daily series, oldest first. `window` is the lookback used for
    mean/std/trend/anomaly; last-14 vs prior-28 is always taken from the tail
    of the full series when enough history exists.
    """
    del product, node
    series = _as_float_series(sales)
    if window is not None:
        if window <= 0:
            raise ValueError("window must be positive")
        analysed = series[-window:] if series else []
    else:
        analysed = series

    if not analysed:
        return DemandStats(
            mean_daily=0.0,
            std_daily=0.0,
            trend_slope=0.0,
            last_14d_vs_prior_28d_delta=0.0,
            spike_detected=False,
            anomaly_flag=False,
        )

    mean_daily = statistics.fmean(analysed)
    std_daily = _sample_std(analysed)
    trend_slope = _ols_slope(analysed)

    last14 = series[-14:] if len(series) >= 1 else []
    prior28 = series[-42:-14] if len(series) >= 15 else []
    last14_mean = statistics.fmean(last14) if last14 else 0.0
    prior28_mean = statistics.fmean(prior28) if prior28 else 0.0
    delta = last14_mean - prior28_mean

    # Anomaly is evaluated on the recent 14d window (promo/bulk-order case).
    anomaly_window = last14 if len(last14) >= 2 else analysed
    anomaly_flag = _anomaly_in(anomaly_window)

    if not prior28:
        spike_detected = False
    elif prior28_mean <= 0:
        spike_detected = last14_mean > 0 and not anomaly_flag
    else:
        spike_detected = last14_mean > prior28_mean * 1.5 and not anomaly_flag

    return DemandStats(
        mean_daily=mean_daily,
        std_daily=std_daily,
        trend_slope=trend_slope,
        last_14d_vs_prior_28d_delta=delta,
        spike_detected=spike_detected,
        anomaly_flag=anomaly_flag,
    )


def effective_available(on_hand: float, reserved: float, damaged: float) -> float:
    """on_hand - reserved - damaged. May be negative (over-reserved / write-off)."""
    return float(on_hand) - float(reserved) - float(damaged)


def _incoming_qty_for_line(status: str, ordered_qty: float, confirmed_qty: float) -> float | None:
    if status not in OPEN_PO_STATUSES:
        return None
    if status == "partially_confirmed":
        return float(confirmed_qty)
    if confirmed_qty > 0:
        return float(confirmed_qty)
    return float(ordered_qty)


def incoming_supply(open_pos: Sequence[Any]) -> list[IncomingSupply]:
    """Incoming qty/date pairs. Honour confirmed_qty on partially_confirmed POs.

    Each item may be a flat mapping::

        {status, ordered_qty, confirmed_qty, expected_date}

    or a PO with ``lines``. Statuses outside the open set are skipped.
    """
    receipts: list[IncomingSupply] = []
    for po in open_pos:
        if not isinstance(po, Mapping):
            po = {
                "status": getattr(po, "status", None),
                "expected_date": getattr(po, "expected_date", None),
                "ordered_qty": getattr(po, "ordered_qty", None),
                "confirmed_qty": getattr(po, "confirmed_qty", 0),
                "lines": getattr(po, "lines", None),
            }
        status = str(po.get("status") or "")
        expected = po.get("expected_date")
        if isinstance(expected, str):
            expected = date.fromisoformat(expected[:10])
        lines = po.get("lines")
        if lines:
            for line in lines:
                if isinstance(line, Mapping):
                    ordered = float(line.get("ordered_qty", 0) or 0)
                    confirmed = float(line.get("confirmed_qty", 0) or 0)
                else:
                    ordered = float(getattr(line, "ordered_qty", 0) or 0)
                    confirmed = float(getattr(line, "confirmed_qty", 0) or 0)
                qty = _incoming_qty_for_line(status, ordered, confirmed)
                if qty is None:
                    continue
                receipts.append(IncomingSupply(qty=qty, expected_date=expected))
        else:
            ordered = float(po.get("ordered_qty", 0) or 0)
            confirmed = float(po.get("confirmed_qty", 0) or 0)
            qty = _incoming_qty_for_line(status, ordered, confirmed)
            if qty is None:
                continue
            receipts.append(IncomingSupply(qty=qty, expected_date=expected))
    return receipts


def coverage_days(
    available: float,
    incoming: Sequence[IncomingSupply | Mapping[str, Any]],
    forecast: Sequence[float],
    *,
    as_of: date | None = None,
) -> CoverageResult:
    """Days of cover, end-of-day stock curve, and first projected stockout date.

    Incoming receipts are added at the start of their expected day (late receipts
    with a date before ``as_of`` are treated as arriving today). Demand is then
    subtracted. Coverage is the number of days until stock would go negative;
    a fractional last day is ``remaining / that day's forecast``.

    If demand is zero across the horizon, coverage is ``inf`` when starting
    stock is non-negative.
    """
    receipts: list[IncomingSupply] = []
    for item in incoming:
        if isinstance(item, IncomingSupply):
            receipts.append(item)
        elif isinstance(item, Mapping):
            expected = item.get("expected_date")
            if isinstance(expected, str):
                expected = date.fromisoformat(expected[:10])
            receipts.append(IncomingSupply(qty=float(item.get("qty", 0)), expected_date=expected))
        else:
            receipts.append(item)

    arrivals: dict[int, float] = {}
    for rec in receipts:
        if rec.expected_date is None or as_of is None:
            offset = 0
        else:
            offset = (rec.expected_date - as_of).days
            if offset < 0:
                offset = 0
        arrivals[offset] = arrivals.get(offset, 0.0) + rec.qty

    horizon = list(float(x) for x in forecast)
    if not horizon:
        leftover = float(available) + arrivals.get(0, 0.0)
        if leftover < 0:
            return CoverageResult(
                coverage_days=0.0,
                projected_daily_stock=[],
                projected_stockout_date=as_of,
            )
        return CoverageResult(
            coverage_days=math.inf if leftover >= 0 else 0.0,
            projected_daily_stock=[],
            projected_stockout_date=None,
        )

    stock = float(available)
    curve: list[float] = []
    stockout_date: date | None = None
    coverage = 0.0
    stocked_out = False

    for i, demand in enumerate(horizon):
        stock += arrivals.get(i, 0.0)
        if stocked_out:
            stock -= demand
            curve.append(stock)
            continue
        if demand <= 0:
            curve.append(stock)
            coverage = float(i + 1)
            continue
        if stock <= 0:
            coverage = float(i)
            stock -= demand
            curve.append(stock)
            stockout_date = as_of + timedelta(days=i) if as_of is not None else None
            stocked_out = True
            continue
        if stock < demand:
            coverage = float(i) + (stock / demand)
            stock -= demand
            curve.append(stock)
            stockout_date = as_of + timedelta(days=i) if as_of is not None else None
            stocked_out = True
            continue
        stock -= demand
        curve.append(stock)
        coverage = float(i + 1)

    if not stocked_out:
        positive_demand = [d for d in horizon if d > 0]
        if not positive_demand:
            coverage = math.inf
        elif stock > 0:
            avg = statistics.fmean(positive_demand)
            coverage = len(horizon) + (stock / avg if avg > 0 else 0.0)

    return CoverageResult(
        coverage_days=coverage,
        projected_daily_stock=curve,
        projected_stockout_date=stockout_date,
    )


def inverse_normal_cdf(p: float) -> float:
    """Acklam's approximation of Φ^{-1}(p) (standard normal quantile)."""
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")
    # Coefficients from Acklam (2002).
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577509590705e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def safety_stock(
    mean_daily: float,
    demand_std: float,
    lead_time_days: float,
    lead_time_std: float,
    service_level: float = 0.95,
) -> float:
    """Safety stock from the lead-time demand standard deviation.

    Lead-time demand is modelled as the sum of daily demand over a (possibly
    random) lead time. With daily demand ~ (μ_d, σ_d) independent of lead time
    L ~ (L̄, σ_L)::

        σ_LT = sqrt( L̄ · σ_d²  +  μ_d² · σ_L² )

    Safety stock is ``z_{service_level} · σ_LT``. For the default 95% cycle
    service level, ``z = Φ^{-1}(0.95) ≈ 1.64485``.

    When lead time is deterministic (σ_L = 0) this reduces to the common
    ``z · σ_d · sqrt(L)`` formula. Returns 0 when σ_LT is 0.
    """
    if service_level <= 0:
        return 0.0
    lead = max(0.0, float(lead_time_days))
    sigma_d = max(0.0, float(demand_std))
    mu_d = max(0.0, float(mean_daily))
    sigma_l = max(0.0, float(lead_time_std))
    variance = lead * sigma_d**2 + (mu_d**2) * (sigma_l**2)
    if variance <= 0:
        return 0.0
    z = Z_95 if abs(service_level - 0.95) < 1e-12 else inverse_normal_cdf(service_level)
    if not math.isfinite(z) or z <= 0:
        return 0.0
    return z * math.sqrt(variance)


def reorder_point(mean_daily: float, lead_time_days: float, safety_stock_qty: float) -> float:
    """ROP = μ_d · L + SS (expected demand over lead time plus safety stock)."""
    return max(0.0, float(mean_daily)) * max(0.0, float(lead_time_days)) + float(safety_stock_qty)


def net_requirement(
    projected_demand: float,
    available: float,
    incoming_qty: float,
    safety_stock_qty: float,
) -> float:
    """Raw required qty before supplier rounding. Floor at 0."""
    raw = float(projected_demand) + float(safety_stock_qty) - float(available) - float(incoming_qty)
    return max(0.0, raw)


def apply_supplier_rounding(
    qty: float,
    moq: int,
    order_multiple: int,
    max_units_per_order: int | None,
) -> RoundingResult:
    """Round a raw requirement to supplier terms.

    Order of operations (each step recorded in ``changes``):

    1. If raw qty ≤ 0, return 0 (do not bump a zero need up to MOQ).
    2. Ceil to an integer.
    3. Round *up* to the next ``order_multiple``.
    4. If still below MOQ, raise to MOQ and re-align to the multiple.
    5. If above ``max_units_per_order``, cap at the largest multiple that
       does not exceed the max (may then fall below MOQ — caller must treat
       that as infeasible).
    """
    changes: list[str] = []
    raw = float(qty)
    if raw <= 0:
        return RoundingResult(qty=0, explanation="Raw requirement is 0; no order.", changes=["zero_requirement"])

    moq = max(0, int(moq))
    multiple = max(1, int(order_multiple or 1))

    rounded = int(math.ceil(raw - 1e-12))
    if rounded != raw:
        changes.append(f"ceiled {raw:g} -> {rounded}")

    if rounded % multiple != 0:
        bumped = ((rounded + multiple - 1) // multiple) * multiple
        changes.append(f"rounded up to multiple {multiple}: {rounded} -> {bumped}")
        rounded = bumped

    if moq and rounded < moq:
        lifted = moq
        if lifted % multiple != 0:
            lifted = ((lifted + multiple - 1) // multiple) * multiple
        changes.append(f"raised to MOQ {moq}: {rounded} -> {lifted}")
        rounded = lifted

    if max_units_per_order is not None:
        cap = int(max_units_per_order)
        if rounded > cap:
            capped = (cap // multiple) * multiple
            changes.append(f"capped at max_units_per_order {cap}: {rounded} -> {capped}")
            rounded = capped

    if not changes:
        explanation = f"Qty {rounded} already satisfies MOQ {moq} and multiple {multiple}."
    else:
        explanation = "; ".join(changes)
    return RoundingResult(qty=int(rounded), explanation=explanation, changes=changes)


def landed_cost(qty: float, unit_price: float) -> float:
    return float(qty) * float(unit_price)


def storage_footprint(qty: float, volume_per_unit_m3: float) -> float:
    return float(qty) * float(volume_per_unit_m3)
