"""Read tools — cheap, no side effects.

Implemented in Prompt 3. Each function is also exposed as a REST endpoint.
"""

from __future__ import annotations

from typing import Any


def get_recommendation(recommendation_id: str) -> dict[str, Any]:
    raise NotImplementedError


def get_product(sku: str) -> dict[str, Any]:
    raise NotImplementedError


def get_inventory(sku: str, node: str) -> dict[str, Any]:
    raise NotImplementedError


def get_demand_stats(sku: str, node: str, window_days: int) -> dict[str, Any]:
    raise NotImplementedError


def get_forecast(sku: str, node: str, horizon_days: int) -> dict[str, Any]:
    raise NotImplementedError


def get_sales_history(sku: str, node: str, days: int) -> dict[str, Any]:
    raise NotImplementedError


def get_open_purchase_orders(
    sku: str | None = None,
    node: str | None = None,
    supplier: str | None = None,
) -> list[dict[str, Any]]:
    raise NotImplementedError


def get_supplier_terms(supplier_id: str, sku: str) -> dict[str, Any]:
    raise NotImplementedError


def find_alternate_suppliers(sku: str) -> list[dict[str, Any]]:
    raise NotImplementedError


def get_supplier_performance(supplier_id: str) -> dict[str, Any]:
    raise NotImplementedError


def get_budget(node: str, category: str, period: str) -> dict[str, Any]:
    raise NotImplementedError


def get_storage_capacity(node: str) -> dict[str, Any]:
    raise NotImplementedError


def compute_replenishment_plan(sku: str, node: str, supplier_id: str) -> dict[str, Any]:
    """Full deterministic bundle: demand, coverage, ROP, net req, rounding, cost."""
    raise NotImplementedError


def validate_action(proposed_action: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError
