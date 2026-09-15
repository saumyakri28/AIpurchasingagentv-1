"""Purchase order list + detail."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PurchaseOrder
from app.db.session import get_db
from app.tools.context import serialize_po

router = APIRouter(prefix="/pos", tags=["purchase-orders"])


@router.get("")
def list_purchase_orders(db: Session = Depends(get_db)) -> list[dict]:
    pos = db.scalars(select(PurchaseOrder)).all()
    return [serialize_po(po) for po in pos]


@router.get("/{po_id}")
def get_purchase_order(po_id: str, db: Session = Depends(get_db)) -> dict:
    po = db.get(PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(status_code=404, detail=f"PO {po_id} not found")
    return serialize_po(po)
