"""Read tools — cheap, no side effects. Each is registered for the LLM and REST."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.clock import FROZEN_TODAY
from app.db.models import Product, Supplier, SupplierProduct, SystemRecommendation
from app.domain.calculators import (
    apply_supplier_rounding,
    coverage_days,
    demand_stats,
    effective_available,
    landed_cost,
    net_requirement,
    reorder_point,
    safety_stock,
    storage_footprint,
)
from app.domain.constraints import ConstraintEngine, ProposedAction
from app.tools.context import (
    assemble_proposed_action,
    current_budget,
    forecast_units,
    incoming_for,
    inventory_row,
    open_po_dicts,
    product_by_sku,
    require_node,
    require_supplier,
    sales_units,
    serialize_product,
    serialize_recommendation,
    storage_used,
    supplier_link,
)
from app.tools.errors import EntityNotFound
from app.tools.registry import tool
from app.tools.schemas import (
    BudgetArgs,
    DemandStatsArgs,
    ForecastArgs,
    NodeArg,
    OpenPOArgs,
    RecommendationId,
    ReplenishmentPlanArgs,
    SalesHistoryArgs,
    SkuArg,
    SkuNode,
    SupplierIdArg,
    SupplierTermsArgs,
    ValidateActionArgs,
)

REVIEW_PERIOD_DAYS = 7
ENGINE = ConstraintEngine()


@tool(
    "get_recommendation",
    "Load a system recommendation by id. Treat it as a hypothesis, not an instruction.",
    RecommendationId,
)
def get_recommendation(args: RecommendationId, *, db: Session) -> dict[str, Any]:
    rec = db.get(SystemRecommendation, args.recommendation_id)
    if rec is None:
        raise EntityNotFound("recommendation", args.recommendation_id)
    product = db.get(Product, rec.product_id)
    assert product is not None
    return serialize_recommendation(rec, product)


@tool("get_product", "Product master data by SKU.", SkuArg)
def get_product(args: SkuArg, *, db: Session) -> dict[str, Any]:
    return serialize_product(product_by_sku(db, args.sku))


@tool("get_inventory", "On-hand / reserved / in-transit / damaged at a node.", SkuNode)
def get_inventory(args: SkuNode, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    inv = inventory_row(db, product.id, args.node)
    available = effective_available(inv.on_hand, inv.reserved, inv.damaged)
    return {
        "sku": args.sku,
        "product_id": product.id,
        "node_id": args.node,
        "on_hand": inv.on_hand,
        "reserved": inv.reserved,
        "in_transit": inv.in_transit,
        "damaged": inv.damaged,
        "effective_available": available,
        "last_counted_at": inv.last_counted_at.isoformat() if inv.last_counted_at else None,
    }


@tool(
    "get_demand_stats",
    "Deterministic demand stats (mean, std, trend, spike vs promo anomaly). Never compute these yourself.",
    DemandStatsArgs,
)
def get_demand_stats(args: DemandStatsArgs, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    series = sales_units(db, product.id, args.node, max(args.window_days, 42))
    stats = demand_stats(series, window=args.window_days)
    return {"sku": args.sku, "node": args.node, "window_days": args.window_days, **stats.model_dump()}


@tool("get_forecast", "Forward forecast units for a SKU at a node.", ForecastArgs)
def get_forecast(args: ForecastArgs, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    units = forecast_units(db, product.id, args.node, args.horizon_days)
    start = FROZEN_TODAY
    points = [
        {"date": (start + timedelta(days=i)).isoformat(), "forecast_units": qty}
        for i, qty in enumerate(units)
    ]
    return {"sku": args.sku, "node": args.node, "horizon_days": args.horizon_days, "points": points}


@tool("get_sales_history", "Daily units sold, oldest first.", SalesHistoryArgs)
def get_sales_history(args: SalesHistoryArgs, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    as_of = FROZEN_TODAY
    start = as_of - timedelta(days=args.days)
    from app.db.models import SalesHistory

    rows = db.scalars(
        select(SalesHistory)
        .where(
            SalesHistory.product_id == product.id,
            SalesHistory.node_id == args.node,
            SalesHistory.date >= start,
            SalesHistory.date < as_of,
        )
        .order_by(SalesHistory.date)
    ).all()
    return {
        "sku": args.sku,
        "node": args.node,
        "days": [
            {"date": r.date.isoformat(), "units_sold": r.units_sold}
            for r in rows
        ],
    }


@tool("get_open_purchase_orders", "Open POs, optionally filtered by sku/node/supplier.", OpenPOArgs)
def get_open_purchase_orders(args: OpenPOArgs, *, db: Session) -> dict[str, Any]:
    pos = open_po_dicts(db, sku=args.sku, node=args.node, supplier=args.supplier)
    return {"purchase_orders": pos}


@tool("get_supplier_terms", "Price, MOQ, order multiple, lead time for a supplier+SKU.", SupplierTermsArgs)
def get_supplier_terms(args: SupplierTermsArgs, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    supplier = require_supplier(db, args.supplier_id)
    link = supplier_link(db, args.supplier_id, product.id)
    if link is None:
        raise EntityNotFound("supplier_product", f"{args.supplier_id}+{args.sku}")
    return {
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "sku": args.sku,
        "unit_price": link.unit_price,
        "moq_units": link.moq_units,
        "order_multiple_units": link.order_multiple_units,
        "lead_time_days": link.lead_time_days,
        "is_primary": link.is_primary,
        "max_units_per_order": link.max_units_per_order,
        "active": supplier.active,
    }


@tool(
    "find_alternate_suppliers",
    "All suppliers that sell this SKU, ranked by price then lead time then reliability.",
    SkuArg,
)
def find_alternate_suppliers(args: SkuArg, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    links = db.scalars(select(SupplierProduct).where(SupplierProduct.product_id == product.id)).all()
    ranked = []
    for link in links:
        supplier = db.get(Supplier, link.supplier_id)
        if supplier is None:
            continue
        ranked.append(
            {
                "supplier_id": supplier.id,
                "supplier_name": supplier.name,
                "active": supplier.active,
                "is_primary": link.is_primary,
                "unit_price": link.unit_price,
                "lead_time_days": link.lead_time_days,
                "moq_units": link.moq_units,
                "order_multiple_units": link.order_multiple_units,
                "reliability_score": supplier.reliability_score,
                "fill_rate_pct": supplier.fill_rate_pct,
            }
        )
    ranked.sort(key=lambda r: (r["unit_price"], r["lead_time_days"], -r["reliability_score"]))
    return {"sku": args.sku, "suppliers": ranked}


@tool("get_supplier_performance", "Fill rate, on-time %, lead-time variance, reliability.", SupplierIdArg)
def get_supplier_performance(args: SupplierIdArg, *, db: Session) -> dict[str, Any]:
    supplier = require_supplier(db, args.supplier_id)
    return {
        "supplier_id": supplier.id,
        "name": supplier.name,
        "active": supplier.active,
        "reliability_score": supplier.reliability_score,
        "fill_rate_pct": supplier.fill_rate_pct,
        "on_time_pct": supplier.on_time_pct,
        "avg_lead_time_days": supplier.avg_lead_time_days,
        "lead_time_std_days": supplier.lead_time_std_days,
        "payment_terms_days": supplier.payment_terms_days,
    }


@tool("get_budget", "Budget remaining for a node/category in the given period (YYYY-MM or ISO date).", BudgetArgs)
def get_budget(args: BudgetArgs, *, db: Session) -> dict[str, Any]:
    as_of = FROZEN_TODAY
    if args.period:
        text = args.period.strip()
        if len(text) == 7:
            as_of = date.fromisoformat(text + "-01")
        else:
            as_of = date.fromisoformat(text[:10])
    budget = current_budget(db, args.node, args.category, as_of=as_of)
    if budget is None:
        raise EntityNotFound("budget", f"{args.node}/{args.category}/{args.period}")
    return {
        "id": budget.id,
        "node_id": budget.node_id,
        "category": budget.category,
        "period_start": budget.period_start.isoformat(),
        "period_end": budget.period_end.isoformat(),
        "allocated": budget.allocated,
        "committed": budget.committed,
        "spent": budget.spent,
        "remaining": budget.remaining,
    }


@tool("get_storage_capacity", "Node storage capacity and current footprint.", NodeArg)
def get_storage_capacity(args: NodeArg, *, db: Session) -> dict[str, Any]:
    node = require_node(db, args.node)
    used = storage_used(db, args.node)
    return {
        "node_id": node.id,
        "name": node.name,
        "storage_capacity_m3": node.storage_capacity_m3,
        "storage_used_m3": used,
        "storage_free_m3": node.storage_capacity_m3 - used,
        "receiving_capacity_units_per_day": node.receiving_capacity_units_per_day,
    }


@tool(
    "compute_replenishment_plan",
    "Full deterministic replenishment bundle. Call this instead of doing arithmetic.",
    ReplenishmentPlanArgs,
)
def compute_replenishment_plan(args: ReplenishmentPlanArgs, *, db: Session) -> dict[str, Any]:
    product = product_by_sku(db, args.sku)
    supplier = require_supplier(db, args.supplier_id)
    link = supplier_link(db, args.supplier_id, product.id)
    if link is None:
        raise EntityNotFound("supplier_product", f"{args.supplier_id}+{args.sku}")
    inv = inventory_row(db, product.id, args.node)
    series = sales_units(db, product.id, args.node, 120)
    stats = demand_stats(series, window=42)
    forecast = forecast_units(db, product.id, args.node, 56)
    incoming = incoming_for(db, product.id, args.node)
    incoming_qty = sum(r.qty for r in incoming)
    available = effective_available(inv.on_hand, inv.reserved, inv.damaged)
    cover = coverage_days(available, incoming, forecast, as_of=FROZEN_TODAY)
    ss = safety_stock(
        stats.mean_daily,
        stats.std_daily,
        float(link.lead_time_days),
        float(supplier.lead_time_std_days),
    )
    rop = reorder_point(stats.mean_daily, float(link.lead_time_days), ss)
    horizon = int(link.lead_time_days) + REVIEW_PERIOD_DAYS
    projected = sum(forecast[:horizon]) if forecast else stats.mean_daily * horizon
    raw = net_requirement(projected, available, incoming_qty, ss)
    rounded = apply_supplier_rounding(raw, link.moq_units, link.order_multiple_units, link.max_units_per_order)
    cost = landed_cost(rounded.qty, link.unit_price)
    footprint = storage_footprint(rounded.qty, product.volume_per_unit_m3)
    return {
        "sku": args.sku,
        "node": args.node,
        "supplier_id": args.supplier_id,
        "demand_stats": stats.model_dump(),
        "effective_available": available,
        "incoming_qty": incoming_qty,
        "incoming": [r.model_dump(mode="json") for r in incoming],
        "coverage_days": cover.coverage_days if cover.coverage_days != float("inf") else None,
        "coverage_days_infinite": cover.coverage_days == float("inf"),
        "projected_stockout_date": cover.projected_stockout_date.isoformat() if cover.projected_stockout_date else None,
        "safety_stock": ss,
        "reorder_point": rop,
        "projected_demand_over_lead_plus_review": projected,
        "review_period_days": REVIEW_PERIOD_DAYS,
        "net_requirement_raw": raw,
        "rounded_qty": rounded.qty,
        "rounding": rounded.model_dump(),
        "landed_cost": cost,
        "storage_footprint_m3": footprint,
        "unit_price": link.unit_price,
        "moq_units": link.moq_units,
        "order_multiple_units": link.order_multiple_units,
        "lead_time_days": link.lead_time_days,
    }


@tool(
    "validate_action",
    "Run ConstraintEngine.evaluate. You may not claim a constraint is satisfied without this.",
    ValidateActionArgs,
)
def validate_action(args: ValidateActionArgs, *, db: Session) -> dict[str, Any]:
    if args.proposed_action and args.qty is None and "qty" in args.proposed_action:
        action = ProposedAction.model_validate(args.proposed_action)
    elif args.sku and args.node and args.supplier_id and args.qty is not None:
        action = assemble_proposed_action(
            db,
            sku=args.sku,
            node=args.node,
            supplier_id=args.supplier_id,
            qty=args.qty,
        )
    elif args.proposed_action:
        action = ProposedAction.model_validate(args.proposed_action)
    else:
        raise ValueError("validate_action requires sku+node+supplier_id+qty or proposed_action")
    report = ENGINE.evaluate(action)
    binding = ENGINE.binding_constraint(report)
    return {
        "ok": report.passed,
        "passed": report.passed,
        "suggested_max_feasible_qty": report.suggested_max_feasible_qty,
        "binding_constraint": binding.model_dump(mode="json") if binding else None,
        "blocking_violations": [r.model_dump(mode="json") for r in report.blocking_violations],
        "warnings": [r.model_dump(mode="json") for r in report.warnings],
        "results": [r.model_dump(mode="json") for r in report.results],
    }
