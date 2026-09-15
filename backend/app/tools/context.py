"""Load world facts and assemble a ProposedAction for the constraint engine."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.clock import FROZEN_TODAY
from app.db.models import (
    Budget,
    Forecast,
    Inventory,
    Node,
    Product,
    PurchaseOrder,
    SalesHistory,
    Supplier,
    SupplierProduct,
    SystemRecommendation,
)
from app.domain.calculators import (
    IncomingSupply,
    coverage_days,
    demand_stats,
    effective_available,
    incoming_supply,
)
from app.domain.constraints import ProposedAction
from app.tools.errors import EntityNotFound


def product_by_sku(db: Session, sku: str) -> Product:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise EntityNotFound("product", sku)
    return product


def require_node(db: Session, node_id: str) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise EntityNotFound("node", node_id)
    return node


def require_supplier(db: Session, supplier_id: str) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise EntityNotFound("supplier", supplier_id)
    return supplier


def inventory_row(db: Session, product_id: str, node_id: str) -> Inventory:
    row = db.get(Inventory, (product_id, node_id))
    if row is None:
        raise EntityNotFound("inventory", f"{product_id}@{node_id}")
    return row


def supplier_link(db: Session, supplier_id: str, product_id: str) -> SupplierProduct | None:
    return db.get(SupplierProduct, (supplier_id, product_id))


def sales_units(db: Session, product_id: str, node_id: str, days: int, *, as_of: date = FROZEN_TODAY) -> list[int]:
    start = as_of - timedelta(days=days)
    rows = db.scalars(
        select(SalesHistory)
        .where(
            SalesHistory.product_id == product_id,
            SalesHistory.node_id == node_id,
            SalesHistory.date >= start,
            SalesHistory.date < as_of,
        )
        .order_by(SalesHistory.date)
    ).all()
    return [r.units_sold for r in rows]


def forecast_units(db: Session, product_id: str, node_id: str, horizon: int, *, as_of: date = FROZEN_TODAY) -> list[float]:
    end = as_of + timedelta(days=horizon - 1)
    rows = db.scalars(
        select(Forecast)
        .where(
            Forecast.product_id == product_id,
            Forecast.node_id == node_id,
            Forecast.date >= as_of,
            Forecast.date <= end,
        )
        .order_by(Forecast.date)
    ).all()
    return [float(r.forecast_units) for r in rows]


def open_po_dicts(
    db: Session,
    *,
    sku: str | None = None,
    node: str | None = None,
    supplier: str | None = None,
    product_id: str | None = None,
    exclude_po_id: str | None = None,
) -> list[dict]:
    stmt = select(PurchaseOrder)
    if node:
        stmt = stmt.where(PurchaseOrder.node_id == node)
    if supplier:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier)
    pos = db.scalars(stmt).all()
    wanted_product = product_id
    if sku and wanted_product is None:
        wanted_product = product_by_sku(db, sku).id
    payload: list[dict] = []
    for po in pos:
        if exclude_po_id and po.id == exclude_po_id:
            continue
        lines = []
        for line in po.lines:
            if wanted_product and line.product_id != wanted_product:
                continue
            lines.append(
                {
                    "id": line.id,
                    "product_id": line.product_id,
                    "ordered_qty": line.ordered_qty,
                    "confirmed_qty": line.confirmed_qty,
                    "received_qty": line.received_qty,
                    "unit_price": line.unit_price,
                }
            )
        if wanted_product and not lines:
            continue
        payload.append(
            {
                "id": po.id,
                "supplier_id": po.supplier_id,
                "node_id": po.node_id,
                "status": po.status,
                "created_at": po.created_at.isoformat() if po.created_at else None,
                "expected_delivery_date": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
                "total_cost": po.total_cost,
                "created_by": po.created_by,
                "lines": lines,
                "ordered_qty": sum(l["ordered_qty"] for l in lines),
                "confirmed_qty": sum(l["confirmed_qty"] for l in lines),
            }
        )
    return payload


def incoming_for(db: Session, product_id: str, node_id: str, *, exclude_po_id: str | None = None) -> list[IncomingSupply]:
    pos = open_po_dicts(db, product_id=product_id, node=node_id, exclude_po_id=exclude_po_id)
    shaped = [
        {
            "status": po["status"],
            "expected_date": po.get("expected_delivery_date"),
            "lines": [
                {"ordered_qty": line["ordered_qty"], "confirmed_qty": line["confirmed_qty"]}
                for line in po["lines"]
            ],
        }
        for po in pos
    ]
    return incoming_supply(shaped)


def storage_used(db: Session, node_id: str) -> float:
    rows = db.scalars(select(Inventory).where(Inventory.node_id == node_id)).all()
    used = 0.0
    for row in rows:
        product = db.get(Product, row.product_id)
        if product is None:
            continue
        used += row.on_hand * product.volume_per_unit_m3
    return used


def current_budget(db: Session, node_id: str, category: str, *, as_of: date = FROZEN_TODAY) -> Budget | None:
    return db.scalar(
        select(Budget).where(
            Budget.node_id == node_id,
            Budget.category == category,
            Budget.period_start <= as_of,
            Budget.period_end >= as_of,
        )
    )


def serialize_recommendation(rec: SystemRecommendation, product: Product) -> dict:
    return {
        "id": rec.id,
        "product_id": rec.product_id,
        "sku": product.sku,
        "node_id": rec.node_id,
        "recommended_qty": rec.recommended_qty,
        "supplier_id": rec.supplier_id,
        "reason": rec.reason,
        "generated_at": rec.generated_at.isoformat() if rec.generated_at else None,
    }


def serialize_product(product: Product) -> dict:
    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "unit_cost": product.unit_cost,
        "units_per_case": product.units_per_case,
        "volume_per_unit_m3": product.volume_per_unit_m3,
        "shelf_life_days": product.shelf_life_days,
        "abc_class": product.abc_class,
    }


def assemble_proposed_action(
    db: Session,
    *,
    sku: str,
    node: str,
    supplier_id: str,
    qty: int,
    exclude_po_id: str | None = None,
    as_of: date = FROZEN_TODAY,
) -> ProposedAction:
    product = product_by_sku(db, sku)
    node_row = require_node(db, node)
    supplier = require_supplier(db, supplier_id)
    link = supplier_link(db, supplier_id, product.id)
    inv = inventory_row(db, product.id, node)
    budget = current_budget(db, node, product.category, as_of=as_of)
    sales = sales_units(db, product.id, node, 120, as_of=as_of)
    stats = demand_stats(sales, window=42)
    forecast = forecast_units(db, product.id, node, 56, as_of=as_of)
    incoming = incoming_for(db, product.id, node, exclude_po_id=exclude_po_id)
    incoming_qty = sum(r.qty for r in incoming)
    available = effective_available(inv.on_hand, inv.reserved, inv.damaged)
    cover = coverage_days(available, incoming, forecast, as_of=as_of)
    lead = int(link.lead_time_days) if link else int(supplier.avg_lead_time_days)
    return ProposedAction(
        qty=int(qty),
        unit_price=float(link.unit_price) if link else 0.0,
        moq_units=int(link.moq_units) if link else 1,
        order_multiple_units=int(link.order_multiple_units) if link else 1,
        max_units_per_order=link.max_units_per_order if link else None,
        budget_remaining=budget.remaining if budget else 0.0,
        storage_capacity_m3=node_row.storage_capacity_m3,
        storage_used_m3=storage_used(db, node),
        volume_per_unit_m3=product.volume_per_unit_m3,
        supplier_active=bool(supplier.active),
        supplier_sells_product=link is not None,
        reliability_score=float(supplier.reliability_score),
        lead_time_days=lead,
        as_of=as_of,
        projected_stockout_date=cover.projected_stockout_date,
        available=available,
        incoming_qty=incoming_qty,
        incoming=incoming,
        forecast=forecast,
        mean_daily=stats.mean_daily,
        shelf_life_days=product.shelf_life_days,
        receiving_capacity_units_per_day=node_row.receiving_capacity_units_per_day,
    )


def serialize_po(po: PurchaseOrder) -> dict:
    return {
        "id": po.id,
        "supplier_id": po.supplier_id,
        "node_id": po.node_id,
        "status": po.status,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "expected_delivery_date": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
        "total_cost": po.total_cost,
        "created_by": po.created_by,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "ordered_qty": line.ordered_qty,
                "confirmed_qty": line.confirmed_qty,
                "received_qty": line.received_qty,
                "unit_price": line.unit_price,
            }
            for line in po.lines
        ],
    }
