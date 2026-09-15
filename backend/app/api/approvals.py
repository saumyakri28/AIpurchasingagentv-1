"""Human approval queue — decide, execute, re-verify against the trace contract."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.schemas import ExpectedOutcome
from app.agent.validator import collect_source_of_truth, post_verify
from app.db.clock import FROZEN_NOW
from app.db.models import (
    ApprovalRequest,
    ApprovalStatus,
    DecisionTrace as TraceRow,
    POStatus,
    Product,
    PurchaseOrder,
)
from app.db.session import get_db
from app.tools.context import serialize_po
from app.tools.errors import ConstraintRefused, EntityNotFound
from app.tools.write_tools import _log, submit_pending_purchase_order

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ModifyApproveBody(BaseModel):
    qty: int
    decided_by: str = "buyer"


class DecideBody(BaseModel):
    decided_by: str = "buyer"


def _serialize(row: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "trace_id": row.trace_id,
        "status": row.status,
        "reason": row.reason,
        "urgency": row.urgency,
        "options_considered": row.options_considered,
        "action_payload": row.action_payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def _require(db: Session, approval_id: str) -> ApprovalRequest:
    row = db.get(ApprovalRequest, approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"approval {approval_id} not found")
    return row


def _po_from_payload(db: Session, payload: dict[str, Any]) -> PurchaseOrder | None:
    po_id = payload.get("po_id")
    if not po_id:
        return None
    return db.get(PurchaseOrder, po_id)


def _reverify(db: Session, approval: ApprovalRequest, po: PurchaseOrder | None) -> dict[str, Any] | None:
    if approval.trace_id is None or po is None:
        return None
    trace = db.get(TraceRow, approval.trace_id)
    if trace is None or not trace.decision:
        return None
    expected_raw = (trace.decision or {}).get("expected_outcome") or {}
    expected = ExpectedOutcome.model_validate(expected_raw)
    sku = (trace.intake or {}).get("sku")
    if sku is None and po.lines:
        product = db.get(Product, po.lines[0].product_id)
        sku = product.sku if product else None
    truth = collect_source_of_truth(
        db,
        po_id=po.id,
        sku=sku,
        node=po.node_id,
        supplier_id=po.supplier_id,
    )
    report = post_verify(expected, source_of_truth=truth)
    steps = list(trace.steps or [])
    steps.append(
        {
            "stage": "POST-VERIFY",
            "note": "re-verify after human approval",
            "result": {"source_of_truth": truth, "verification": report.model_dump(mode="json")},
        }
    )
    trace.steps = steps
    trace.verification = report.model_dump(mode="json")
    return report.model_dump(mode="json")


def _close(row: ApprovalRequest, *, status: str, decided_by: str) -> None:
    row.status = status
    row.decided_by = decided_by
    row.decided_at = FROZEN_NOW


@router.get("")
def list_approvals(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()
    return [_serialize(row) for row in rows]


@router.get("/{approval_id}")
def get_approval(approval_id: str, db: Session = Depends(get_db)) -> dict:
    return _serialize(_require(db, approval_id))


@router.post("/{approval_id}/approve")
def approve(approval_id: str, body: DecideBody | None = None, db: Session = Depends(get_db)) -> dict:
    payload = body or DecideBody()
    row = _require(db, approval_id)
    if row.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"approval is {row.status}")
    action = row.action_payload or {}
    po = _po_from_payload(db, action)
    executed: dict[str, Any] | None = None
    try:
        if action.get("tool") == "create_purchase_order" and po is not None:
            if po.status == POStatus.PENDING_APPROVAL.value:
                executed = submit_pending_purchase_order(po, db=db)
        _close(row, status=ApprovalStatus.APPROVED.value, decided_by=payload.decided_by)
        verification = _reverify(db, row, po)
        _log(db, "approval_approved", "approval_request", row.id, {"po_id": po.id if po else None})
        db.commit()
    except ConstraintRefused as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_dict()) from exc
    except (ValueError, EntityNotFound) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "approval": _serialize(row),
        "executed": executed,
        "verification": verification,
        "po": serialize_po(po) if po is not None else None,
    }


@router.post("/{approval_id}/reject")
def reject(approval_id: str, body: DecideBody | None = None, db: Session = Depends(get_db)) -> dict:
    payload = body or DecideBody()
    row = _require(db, approval_id)
    if row.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"approval is {row.status}")
    po = _po_from_payload(db, row.action_payload or {})
    if po is not None and po.status == POStatus.PENDING_APPROVAL.value:
        po.status = POStatus.CANCELLED.value
        _log(db, "po_cancelled", "purchase_order", po.id, {"reason": "approval_rejected"})
    _close(row, status=ApprovalStatus.REJECTED.value, decided_by=payload.decided_by)
    _log(db, "approval_rejected", "approval_request", row.id, {})
    db.commit()
    return {"ok": True, "approval": _serialize(row), "po": serialize_po(po) if po is not None else None}


@router.post("/{approval_id}/modify")
def modify_and_approve(approval_id: str, body: ModifyApproveBody, db: Session = Depends(get_db)) -> dict:
    row = _require(db, approval_id)
    if row.status != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"approval is {row.status}")
    po = _po_from_payload(db, row.action_payload or {})
    if po is None or not po.lines:
        raise HTTPException(status_code=400, detail="approval has no pending PO to modify")
    if po.status != POStatus.PENDING_APPROVAL.value:
        raise HTTPException(status_code=409, detail=f"PO is {po.status}")
    if body.qty <= 0:
        raise HTTPException(status_code=400, detail="qty must be positive")
    try:
        po.lines[0].ordered_qty = body.qty
        po.total_cost = sum(line.ordered_qty * line.unit_price for line in po.lines)
        executed = submit_pending_purchase_order(po, db=db)
        _close(row, status=ApprovalStatus.MODIFIED.value, decided_by=body.decided_by)
        payload = dict(row.action_payload or {})
        payload["modified_qty"] = body.qty
        row.action_payload = payload
        verification = _reverify(db, row, po)
        _log(db, "approval_modified", "approval_request", row.id, {"qty": body.qty})
        db.commit()
    except ConstraintRefused as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=exc.as_dict()) from exc
    except (ValueError, EntityNotFound) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "approval": _serialize(row),
        "executed": executed,
        "verification": verification,
        "po": serialize_po(po),
    }
