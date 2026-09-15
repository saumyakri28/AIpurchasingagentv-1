"""Eval dashboard — harness reports first, trace synthesis as fallback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DecisionTrace as TraceRow
from app.db.session import get_db
from app.api.traces import _detail
from evals.report import list_reports, load_latest, load_report, write_report
from evals.runner import run_suite

router = APIRouter(prefix="/evals", tags=["evals"])


def _assertions(row: TraceRow) -> list[dict[str, Any]]:
    steps = row.steps or []
    decision = row.decision if isinstance(row.decision, dict) else {}
    verification = row.verification if isinstance(row.verification, dict) else {}
    tools = {s.get("tool") for s in steps if isinstance(s, dict)}
    has_validate = "validate_action" in tools
    last_validate = None
    for step in reversed(steps):
        if isinstance(step, dict) and step.get("tool") == "validate_action":
            last_validate = step.get("result") or {}
            break
    validate_ok = True
    if isinstance(last_validate, dict) and last_validate:
        validate_ok = bool(last_validate.get("passed") or last_validate.get("ok")) or decision.get("decision") in {
            "reject",
            "escalate",
            "investigate_further",
        }
    recon = any(isinstance(s, dict) and s.get("stage") == "RECONCILE" for s in steps)
    matched = verification.get("matched")
    return [
        {"category": "plan", "passed": any(isinstance(s, dict) and s.get("stage") == "PLAN" for s in steps)},
        {"category": "replenishment", "passed": "compute_replenishment_plan" in tools},
        {"category": "decision", "passed": bool(decision.get("decision"))},
        {"category": "constraints", "passed": (not has_validate) or validate_ok},
        {"category": "verification", "passed": True if matched is None else bool(matched) or recon},
    ]


def _run_from_trace(row: TraceRow) -> dict[str, Any]:
    assertions = _assertions(row)
    return {
        "id": row.id,
        "kind": "trace",
        "scenario_type": row.scenario_type,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "passed": all(a["passed"] for a in assertions),
        "assertions": assertions,
        "decision": (row.decision or {}).get("decision") if isinstance(row.decision, dict) else None,
        "matched": (row.verification or {}).get("matched") if isinstance(row.verification, dict) else None,
    }


class EvalRunBody(BaseModel):
    suite: str = "all"
    repeat: int = Field(default=1, ge=1, le=5)
    llm: str = "fake"


@router.get("")
def list_eval_runs(db: Session = Depends(get_db)) -> list[dict]:
    harness = list_reports()
    traces = [_run_from_trace(row) for row in db.scalars(select(TraceRow).order_by(TraceRow.created_at.desc())).all()]
    return harness + traces


@router.get("/report")
def latest_markdown() -> dict:
    latest = load_latest()
    if latest is None:
        return {"markdown": None, "report": None}
    return {"markdown": latest.get("markdown"), "report": {k: latest.get(k) for k in latest if k != "markdown"}}


@router.post("/run")
def trigger_eval_run(body: EvalRunBody | None = None) -> dict:
    payload = body or EvalRunBody()
    if payload.llm not in {"fake", "real"}:
        raise HTTPException(status_code=400, detail="llm must be fake or real")
    try:
        report = run_suite(suite=payload.suite, repeat=payload.repeat, llm=payload.llm)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_report(report)
    return report


@router.get("/{run_id}")
def get_eval_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    harness = load_report(run_id)
    if harness is not None:
        return harness
    row = db.get(TraceRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"eval run {run_id} not found")
    return {**_run_from_trace(row), "trace": _detail(row)}
