"""Decision traces persisted by the agent loop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DecisionTrace as TraceRow
from app.db.session import get_db

router = APIRouter(prefix="/traces", tags=["traces"])


def _summary(row: TraceRow) -> dict:
    decision = row.decision or {}
    return {
        "id": row.id,
        "scenario_type": row.scenario_type,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "decision": decision.get("decision") if isinstance(decision, dict) else None,
        "plan": row.plan,
    }


@router.get("")
def list_traces(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(TraceRow).order_by(TraceRow.created_at.desc())).all()
    return [_summary(row) for row in rows]


@router.get("/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.get(TraceRow, trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    return {
        **_summary(row),
        "intake": row.intake,
        "steps": row.steps,
        "decision": row.decision,
        "verification": row.verification,
    }
