"""Agent run entry points. Scenario wrappers land in Prompt 5."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.llm import FakeLLM, build_llm
from app.agent.loop import AgentLoop
from app.db.session import get_db

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunBody(BaseModel):
    intake: dict[str, Any]
    script: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional FakeLLM fixture. When set, the run is deterministic (no API key).",
    )


@router.post("/run")
def run_agent(body: AgentRunBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    llm = FakeLLM(body.script) if body.script is not None else build_llm()
    try:
        trace = AgentLoop(llm, db).run(body.intake)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return trace.model_dump(mode="json")


@router.post("/run/recommendation-review")
def run_recommendation_review() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 1 lands in Prompt 5")


@router.post("/run/supplier-shortfall")
def run_supplier_shortfall() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 2 lands in Prompt 5")


@router.post("/run/demand-change")
def run_demand_change() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 3 lands in Prompt 5")


@router.post("/run/constrained-buy")
def run_constrained_buy() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 4 lands in Prompt 5")
