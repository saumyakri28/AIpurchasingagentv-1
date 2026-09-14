"""Pure replenishment calculators.

The LLM never performs arithmetic. Every quantitative claim the agent
makes must come from one of these functions (exposed as tools).

Implemented in Prompt 2.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class DemandStats(BaseModel):
    mean_daily: float
    std_daily: float
    trend_slope: float
    last_14d_vs_prior_28d_delta: float
    spike_detected: bool
    anomaly_flag: bool


class IncomingSupply(BaseModel):
    qty: float
    expected_date: date


class CoverageResult(BaseModel):
    coverage_days: float
    projected_daily_stock: list[float] = Field(default_factory=list)
    projected_stockout_date: date | None = None


class RoundingResult(BaseModel):
    qty: int
    explanation: str
    changes: list[str] = Field(default_factory=list)


def demand_stats(
    product_id: str,
    node_id: str,
    window_days: int,
    *,
    sales: list[Any] | None = None,
) -> DemandStats:
    """Mean daily, std, trend slope, 14d vs 28d delta, spike and anomaly flags."""
    raise NotImplementedError


def effective_available(
    on_hand: float,
    reserved: float,
    damaged: float,
) -> float:
    """on_hand - reserved - damaged."""
    raise NotImplementedError


def incoming_supply(open_pos: list[Any]) -> list[IncomingSupply]:
    """Incoming qty/date pairs, honouring confirmed_qty on partial POs."""
    raise NotImplementedError


def coverage_days(
    available: float,
    incoming: list[IncomingSupply],
    forecast: list[float],
) -> CoverageResult:
    """Days of cover, projected stock curve, projected stockout date."""
    raise NotImplementedError


def safety_stock(
    mean_daily: float,
    demand_std: float,
    lead_time_days: float,
    lead_time_std: float,
    service_level: float = 0.95,
) -> float:
    """Standard sigma_LT safety stock. Formula documented in Prompt 2."""
    raise NotImplementedError


def reorder_point(mean_daily: float, lead_time_days: float, safety_stock_qty: float) -> float:
    raise NotImplementedError


def net_requirement(
    projected_demand: float,
    available: float,
    incoming_qty: float,
    safety_stock_qty: float,
) -> float:
    raise NotImplementedError


def apply_supplier_rounding(
    qty: float,
    moq: int,
    order_multiple: int,
    max_units_per_order: int | None,
) -> RoundingResult:
    raise NotImplementedError


def landed_cost(qty: float, unit_price: float) -> float:
    raise NotImplementedError


def storage_footprint(qty: float, volume_per_unit_m3: float) -> float:
    raise NotImplementedError
