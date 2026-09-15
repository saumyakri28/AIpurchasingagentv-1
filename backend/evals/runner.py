"""Run one eval case against a freshly seeded SQLite world."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm import FakeLLM, build_llm
from app.agent.loop import AgentLoop
from app.db.engine import get_engine
from app.db.seed import seed_world
from app.scenarios.runner import build_intake, resolve_variant
from app.scenarios.scripts import script_for
from app.services.supplier_api import supplier_api
from evals.cases import DIMENSIONS, EvalCase, load_cases
from evals.grader import grade_case


def _script(case: EvalCase) -> list[dict[str, Any]]:
    key = case.resolved_script_key()
    try:
        if ":" in key and not key.startswith("eval:"):
            scenario, variant = key.split(":", 1)
            return script_for(scenario, variant)
        if key.startswith("eval:"):
            from app.scenarios.scripts import SCRIPTS

            return SCRIPTS[key]
    except KeyError:
        pass
    from app.scenarios.scripts import SCRIPTS

    if key in SCRIPTS:
        return SCRIPTS[key]
    scenario = case.intake.scenario
    variant = case.intake.variant or resolve_variant(scenario, None, case.intake.payload)
    return script_for(scenario, variant)


def run_once(case: EvalCase, *, db: Session, llm: str) -> dict[str, Any]:
    original = dict(supplier_api.behaviours)
    try:
        if case.supplier_override:
            supplier_api.behaviours.update(case.supplier_override)
        extra = dict(case.intake.payload)
        resolved = resolve_variant(case.intake.scenario, case.intake.variant, extra)
        intake = build_intake(case.intake.scenario, resolved, extra)
        if llm == "real":
            client = build_llm()
        else:
            client = FakeLLM(_script(case))
        trace = AgentLoop(client, db).run(intake)
        graded = grade_case(case, trace, db)
        graded["error"] = None
        return graded
    except Exception as exc:
        return {
            "id": case.id,
            "description": case.description,
            "trace_id": None,
            "decision": None,
            "status": "failed",
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "dimensions": {
                name: {"passed": False, "notes": f"run aborted: {exc}"}
                for name in DIMENSIONS
            },
            "assertions": [{"category": name, "passed": False, "notes": str(exc)} for name in DIMENSIONS],
        }
    finally:
        supplier_api.behaviours = original


def _stability(repeats: list[dict[str, Any]]) -> float:
    if not repeats:
        return 0.0
    keys: list[tuple] = []
    for row in repeats:
        dims = row.get("dimensions") or {}
        vector = tuple(bool((dims.get(name) or {}).get("passed")) for name in DIMENSIONS)
        keys.append((row.get("decision"), vector))
    counts: dict[tuple, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values()) / len(repeats)


def aggregate_case(case: EvalCase, repeats: list[dict[str, Any]]) -> dict[str, Any]:
    stability = _stability(repeats)
    dim_roll: dict[str, Any] = {}
    for name in DIMENSIONS:
        flags = [bool((row.get("dimensions") or {}).get(name, {}).get("passed")) for row in repeats]
        dim_roll[name] = {
            "passed": all(flags) if flags else False,
            "pass_rate": (sum(flags) / len(flags)) if flags else 0.0,
        }
    passed = all(row.get("passed") for row in repeats) if repeats else False
    return {
        "id": case.id,
        "description": case.description,
        "world": case.world,
        "passed": passed,
        "stability": round(stability, 3),
        "dimensions": dim_roll,
        "assertions": [
            {
                "category": name,
                "passed": dim_roll[name]["passed"],
                "notes": f"pass_rate={dim_roll[name]['pass_rate']:.2f}",
            }
            for name in DIMENSIONS
        ],
        "repeats": repeats,
        "decision": repeats[0].get("decision") if repeats else None,
    }


def run_suite(
    *,
    suite: str = "all",
    repeat: int = 1,
    llm: str = "fake",
    db_dir: Path | None = None,
) -> dict[str, Any]:
    cases = load_cases(suite)
    if not cases:
        raise ValueError(f"No eval cases matched suite={suite!r}")
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"EV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    results = []
    workdir = Path(db_dir) if db_dir else Path("/tmp") / "purchasing-evals"
    workdir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        repeats = []
        for i in range(max(1, repeat)):
            db_path = workdir / f"{run_id}-{case.id}-{i}.db"
            engine = get_engine(f"sqlite:///{db_path}")
            seed_world(case.world, engine=engine)
            session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
            try:
                repeats.append(run_once(case, db=session, llm=llm))
            finally:
                session.close()
                engine.dispose()
        results.append(aggregate_case(case, repeats))
    passed_n = sum(1 for row in results if row["passed"])
    return {
        "id": run_id,
        "kind": "harness",
        "suite": suite,
        "llm": llm,
        "repeat": max(1, repeat),
        "created_at": created,
        "passed": passed_n == len(results),
        "cases_passed": passed_n,
        "cases_total": len(results),
        "stability_mean": round(sum(r["stability"] for r in results) / len(results), 3),
        "assertions": [
            {
                "category": name,
                "passed": all(r["dimensions"][name]["passed"] for r in results),
            }
            for name in DIMENSIONS
        ],
        "cases": results,
        "status": "passed" if passed_n == len(results) else "failed",
        "decision": None,
        "scenario_type": "eval_suite",
        "matched": None,
    }
