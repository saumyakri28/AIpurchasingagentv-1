"""Human approval queue."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApprovalRequest
from app.db.session import get_db

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _serialize(row: ApprovalRequest) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "reason": row.reason,
        "urgency": row.urgency,
        "options_considered": row.options_considered,
        "action_payload": row.action_payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


@router.get("")
def list_approvals(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())).all()
    return [_serialize(row) for row in rows]


@router.post("/{approval_id}/approve")
def approve(approval_id: str, db: Session = Depends(get_db)) -> dict:
    raise HTTPException(status_code=501, detail="Approval decide-and-reverify lands in Prompt 6")


@router.post("/{approval_id}/reject")
def reject(approval_id: str, db: Session = Depends(get_db)) -> dict:
    raise HTTPException(status_code=501, detail="Approval decide-and-reverify lands in Prompt 6")
