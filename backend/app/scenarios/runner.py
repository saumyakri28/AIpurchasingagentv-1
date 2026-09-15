"""Seed a fixture world and run the shared AgentLoop with scenario-specific intake."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm import FakeLLM, LLMClient, build_llm
from app.agent.loop import AgentLoop
from app.agent.schemas import DecisionTrace
from app.config import get_settings
from app.db.seed import seed_world
from app.scenarios.catalogue import canned_script, get_scenario


def resolve_variant(scenario_id: str, variant_id: str | None, extra: dict[str, Any]) -> str:
    spec = get_scenario(scenario_id)
    if variant_id:
        return spec.variant(variant_id).id
    rec = extra.get("recommendation_id")
    if rec:
        for row in spec.variants:
            if row.intake.get("recommendation_id") == rec:
                return row.id
    sku = extra.get("sku")
    node = extra.get("node")
    if sku:
        for row in spec.variants:
            if row.intake.get("sku") == sku and (not node or row.intake.get("node") == node):
                return row.id
    po_id = extra.get("po_id")
    if po_id:
        for row in spec.variants:
            if row.intake.get("po_id") == po_id:
                return row.id
    return spec.default_variant


def build_intake(scenario_id: str, variant_id: str, extra: dict[str, Any]) -> dict[str, Any]:
    spec = get_scenario(scenario_id)
    variant = spec.variant(variant_id)
    intake = {
        "type": spec.intake_type,
        "scenario_id": spec.id,
        "variant_id": variant.id,
        "world": spec.world,
        "brief": spec.brief,
        **variant.intake,
    }
    for key, value in extra.items():
        if value is not None:
            intake[key] = value
    return intake


def choose_llm(
    *,
    scenario_id: str,
    variant_id: str,
    script: list[dict[str, Any]] | None,
) -> LLMClient:
    if script is not None:
        return FakeLLM(script)
    settings = get_settings()
    if settings.llm_provider == "fake":
        return FakeLLM(canned_script(scenario_id, variant_id))
    return build_llm()


def execute_scenario(
    scenario_id: str,
    *,
    db: Session,
    variant_id: str | None = None,
    extra_intake: dict[str, Any] | None = None,
    script: list[dict[str, Any]] | None = None,
    seed: bool = True,
) -> DecisionTrace:
    extra = dict(extra_intake or {})
    resolved = resolve_variant(scenario_id, variant_id, extra)
    spec = get_scenario(scenario_id)
    intake = build_intake(scenario_id, resolved, extra)
    llm = choose_llm(scenario_id=scenario_id, variant_id=resolved, script=script)

    if not seed:
        return AgentLoop(llm, db).run(intake)

    bind = db.get_bind()
    db.rollback()
    seed_world(spec.world, engine=bind)
    working = sessionmaker(bind=bind, autoflush=False, autocommit=False)()
    try:
        return AgentLoop(llm, working).run(intake)
    finally:
        working.close()
