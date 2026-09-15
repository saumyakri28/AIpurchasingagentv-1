"""Purchase order list + detail with audit trail."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EventLog, PurchaseOrder
from app.db.session import get_db
from app.tools.context import serialize_po

router = APIRouter(prefix="/pos", tags=["purchase-orders"])


@router.get("")
def list_purchase_orders(db: Session = Depends(get_db)) -> list[dict]:
    pos = db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())).all()
    return [serialize_po(po) for po in pos]


@router.get("/{po_id}")
def get_purchase_order(po_id: str, db: Session = Depends(get_db)) -> dict:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(status_code=404, detail=f"PO {po_id} not found")
    events = db.scalars(
        select(EventLog)
        .where(EventLog.entity_type == "purchase_order", EventLog.entity_id == po_id)
        .order_by(EventLog.ts)
    ).all()
    payload = serialize_po(po)
    payload["events"] = [
        {
            "id": e.id,
            "ts": e.ts.isoformat() if e.ts else None,
            "event_type": e.event_type,
            "payload": e.payload,
            "trace_id": e.trace_id,
        }
        for e in events
    ]
    return payload
