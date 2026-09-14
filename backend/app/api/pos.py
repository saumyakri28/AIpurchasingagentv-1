"""Purchase order list + detail. Implemented in Prompt 3 / 6."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/pos", tags=["purchase-orders"])


@router.get("")
def list_purchase_orders() -> list[dict[str, str]]:
    return []


@router.get("/{po_id}")
def get_purchase_order(po_id: str) -> dict[str, str]:
    raise HTTPException(status_code=501, detail="PO detail lands in Prompt 3")
