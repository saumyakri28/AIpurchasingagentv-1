"""Decision traces persisted by the agent loop."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentAction, DecisionTrace as TraceRow
from app.db.session import get_db

router = APIRouter(prefix="/traces", tags=["traces"])


def _po_id_from_steps(steps: list) -> str | None:
    for step in reversed(steps or []):
        if not isinstance(step, dict):
            continue
        result = step.get("result")
        if isinstance(result, dict):
            po = result.get("po")
            if isinstance(po, dict) and po.get("id"):
                return str(po["id"])
            if result.get("po_id"):
                return str(result["po_id"])
            truth = result.get("source_of_truth")
            if isinstance(truth, dict) and truth.get("po_id"):
                return str(truth["po_id"])
    return None


def _summary(row: TraceRow) -> dict[str, Any]:
    decision = row.decision or {}
    verification = row.verification or {}
    return {
        "id": row.id,
        "scenario_type": row.scenario_type,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "decision": decision.get("decision") if isinstance(decision, dict) else None,
        "plan": row.plan,
        "matched": verification.get("matched") if isinstance(verification, dict) else None,
        "po_id": _po_id_from_steps(row.steps or []),
    }


def _detail(row: TraceRow) -> dict[str, Any]:
    actions = [
        {
            "id": a.id,
            "step_index": a.step_index,
            "action_type": a.action_type,
            "tool_name": a.tool_name,
            "arguments": a.arguments,
            "result": a.result,
            "latency_ms": a.latency_ms,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in sorted(row.actions, key=lambda x: x.step_index)
    ]
    return {
        **_summary(row),
        "intake": row.intake,
        "steps": row.steps,
        "decision": row.decision,
        "verification": row.verification,
        "actions": actions,
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
    return _detail(row)
