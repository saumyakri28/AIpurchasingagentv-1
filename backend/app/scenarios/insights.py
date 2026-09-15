"""Cheap extras: PO hygiene, supplier scorecard, alternates, safety stock."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.clock import FROZEN_TODAY
from app.db.models import Inventory, OPEN_PO_STATUSES, Product, PurchaseOrder, Supplier, SupplierProduct
from app.domain.calculators import demand_stats, safety_stock
from app.tools.context import forecast_units, incoming_for, product_by_sku, sales_units
from app.tools.read_tools import find_alternate_suppliers, get_supplier_performance
from app.tools.schemas import SkuArg, SupplierIdArg


def po_hygiene(db: Session, *, as_of: date = FROZEN_TODAY) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for po in db.scalars(select(PurchaseOrder)).all():
        if po.status not in OPEN_PO_STATUSES:
            continue
        expected = po.expected_delivery_date
        overdue_days = (as_of - expected).days if expected is not None else None
        ordered = sum(line.ordered_qty for line in po.lines)
        confirmed = sum(line.confirmed_qty for line in po.lines)
        received = sum(line.received_qty for line in po.lines)
        ghost = bool(
            expected is not None
            and expected < as_of
            and confirmed == 0
            and received == 0
        )
        overdue = bool(expected is not None and expected < as_of and received < ordered)
        if not overdue and not ghost:
            continue
        rows.append(
            {
                "po_id": po.id,
                "supplier_id": po.supplier_id,
                "node_id": po.node_id,
                "status": po.status,
                "expected_delivery_date": expected.isoformat() if expected else None,
                "overdue_days": overdue_days,
                "ordered_qty": ordered,
                "confirmed_qty": confirmed,
                "received_qty": received,
                "flags": [flag for flag, on in (("overdue", overdue), ("ghost", ghost)) if on],
            }
        )
    rows.sort(key=lambda r: int(r["overdue_days"] or 0), reverse=True)
    return {"as_of": as_of.isoformat(), "count": len(rows), "purchase_orders": rows}


def supplier_scorecard(db: Session) -> dict[str, Any]:
    suppliers = db.scalars(select(Supplier).order_by(Supplier.id)).all()
    cards = [get_supplier_performance(SupplierIdArg(supplier_id=s.id), db=db) for s in suppliers]
    ranked = sorted(cards, key=lambda c: float(c["reliability_score"]))
    return {
        "suppliers": cards,
        "weakest": ranked[0] if ranked else None,
        "floor": 0.70,
        "below_floor": [c for c in cards if float(c["reliability_score"]) < 0.70],
    }


def alternate_supplier_comparison(db: Session, sku: str | None = None) -> dict[str, Any]:
    if sku:
        skus = [sku]
    else:
        products = db.scalars(select(Product).order_by(Product.sku)).all()
        skus = [p.sku for p in products]
    comparisons: list[dict[str, Any]] = []
    for code in skus:
        payload = find_alternate_suppliers(SkuArg(sku=code), db=db)
        if len(payload["suppliers"]) < 2:
            continue
        comparisons.append(payload)
    return {"count": len(comparisons), "skus": comparisons}


def safety_stock_recommendation(
    db: Session,
    *,
    sku: str | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    stmt = select(Inventory)
    if sku:
        product = product_by_sku(db, sku)
        stmt = stmt.where(Inventory.product_id == product.id)
    if node:
        stmt = stmt.where(Inventory.node_id == node)
    rows = db.scalars(stmt).all()
    recs: list[dict[str, Any]] = []
    for inv in rows:
        product = db.get(Product, inv.product_id)
        assert product is not None
        link = db.scalar(
            select(SupplierProduct).where(
                SupplierProduct.product_id == product.id,
                SupplierProduct.is_primary.is_(True),
            )
        )
        if link is None:
            continue
        supplier = db.get(Supplier, link.supplier_id)
        assert supplier is not None
        series = sales_units(db, product.id, inv.node_id, 120)
        stats = demand_stats(series, window=42)
        ss = safety_stock(
            stats.mean_daily,
            stats.std_daily,
            float(link.lead_time_days),
            float(supplier.lead_time_std_days),
        )
        incoming = incoming_for(db, product.id, inv.node_id)
        incoming_qty = sum(r.qty for r in incoming)
        forecast = forecast_units(db, product.id, inv.node_id, 28)
        recs.append(
            {
                "sku": product.sku,
                "node": inv.node_id,
                "supplier_id": supplier.id,
                "on_hand": inv.on_hand,
                "incoming_qty": incoming_qty,
                "mean_daily": stats.mean_daily,
                "std_daily": stats.std_daily,
                "lead_time_days": link.lead_time_days,
                "lead_time_std_days": supplier.lead_time_std_days,
                "safety_stock": round(ss, 2),
                "on_hand_vs_ss": round(inv.on_hand - ss, 2),
                "forecast_28d": round(sum(forecast), 2),
                "service_level": 0.95,
            }
        )
    recs.sort(key=lambda r: r["on_hand_vs_ss"])
    return {"count": len(recs), "recommendations": recs}
