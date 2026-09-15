"""Scenario catalogue, world load, and current-world summary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EventLog, Product, SystemRecommendation
from app.db.seed import list_worlds, seed_world
from app.db.session import get_db
from app.scenarios.catalogue import INSIGHT_CATALOGUE, get_scenario, list_scenarios
from app.tools.context import serialize_recommendation

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


class SeedBody(BaseModel):
    world: str | None = None


def _current_world(db: Session) -> dict[str, Any] | None:
    row = db.scalar(
        select(EventLog)
        .where(EventLog.event_type == "world_seeded")
        .order_by(EventLog.ts.desc())
    )
    if row is None:
        return None
    return {
        "world": row.entity_id,
        "seeded_at": row.ts.isoformat() if row.ts else None,
        "payload": row.payload,
    }


@router.get("")
def catalogue() -> list[dict[str, Any]]:
    return list_scenarios()


@router.get("/insights")
def insight_catalogue() -> list[dict[str, Any]]:
    return INSIGHT_CATALOGUE


@router.get("/current")
def current_world(db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _current_world(db)
    if current is None:
        return {"world": None, "worlds": list_worlds()}
    return {**current, "worlds": list_worlds()}


@router.get("/{scenario_id}")
def get_one(scenario_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        spec = get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    recs = []
    for rec in db.scalars(select(SystemRecommendation)).all():
        product = db.get(Product, rec.product_id)
        if product is not None:
            recs.append(serialize_recommendation(rec, product))
    return {**spec.as_dict(), "current_world": _current_world(db), "recommendations": recs}


@router.post("/{scenario_id}/seed")
def seed_scenario(scenario_id: str, body: SeedBody | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        spec = get_scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    world = (body.world if body and body.world else spec.world)
    bind = db.get_bind()
    db.rollback()
    report = seed_world(world, engine=bind)
    return {"ok": True, "world": world, "summary": report.summary(), "scenario_id": scenario_id}
