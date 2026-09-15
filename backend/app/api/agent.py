"""Agent run entry points — generic loop plus four scenario wrappers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.llm import FakeLLM, build_llm
from app.agent.loop import AgentLoop
from app.db.session import get_db
from app.scenarios.runner import execute_scenario

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunBody(BaseModel):
    intake: dict[str, Any]
    script: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional FakeLLM fixture. When set, the run is deterministic (no API key).",
    )


class ScenarioRunBody(BaseModel):
    variant: str | None = None
    script: list[dict[str, Any]] | None = None
    seed: bool = True


class RecommendationReviewBody(ScenarioRunBody):
    recommendation_id: str | None = None


class SupplierShortfallBody(ScenarioRunBody):
    po_id: str = "PO-SHORTFALL"
    confirmed_qty: int = 250


class DemandChangeBody(ScenarioRunBody):
    sku: str | None = None
    node: str | None = None


class ConstrainedBuyBody(ScenarioRunBody):
    sku: str | None = None
    node: str | None = None


def _dump(trace) -> dict[str, Any]:
    return trace.model_dump(mode="json")


@router.post("/run")
def run_agent(body: AgentRunBody, db: Session = Depends(get_db)) -> dict[str, Any]:
    llm = FakeLLM(body.script) if body.script is not None else build_llm()
    try:
        trace = AgentLoop(llm, db).run(body.intake)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _dump(trace)


def _run_named(scenario_id: str, body: ScenarioRunBody, extra: dict[str, Any], db: Session) -> dict[str, Any]:
    try:
        trace = execute_scenario(
            scenario_id,
            db=db,
            variant_id=body.variant,
            extra_intake=extra,
            script=body.script,
            seed=body.seed,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _dump(trace)


@router.post("/run/recommendation-review")
def run_recommendation_review(
    body: RecommendationReviewBody | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = body or RecommendationReviewBody()
    extra = {"recommendation_id": payload.recommendation_id} if payload.recommendation_id else {}
    return _run_named("recommendation-review", payload, extra, db)


@router.post("/run/supplier-shortfall")
def run_supplier_shortfall(
    body: SupplierShortfallBody | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = body or SupplierShortfallBody()
    extra = {"po_id": payload.po_id, "confirmed_qty": payload.confirmed_qty}
    return _run_named("supplier-shortfall", payload, extra, db)


@router.post("/run/demand-change")
def run_demand_change(
    body: DemandChangeBody | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = body or DemandChangeBody()
    extra = {"sku": payload.sku, "node": payload.node}
    return _run_named("demand-change", payload, extra, db)


@router.post("/run/constrained-buy")
def run_constrained_buy(
    body: ConstrainedBuyBody | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    payload = body or ConstrainedBuyBody()
    extra = {"sku": payload.sku, "node": payload.node}
    return _run_named("constrained-buy", payload, extra, db)
