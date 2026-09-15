"""Terminal demo: seed Scenario 1 and run it end-to-end with a readable trace.

No UI, no live API, no Anthropic key. Uses FakeLLM canned scripts.

    python -m app.demo
    python -m app.demo --variant healthy
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.db.clock import FROZEN_TODAY
from app.db.engine import get_engine
from app.scenarios.catalogue import get_scenario
from app.scenarios.runner import execute_scenario
from app.tools import registry as _registry  # noqa: F401 — register tools

SCENARIO_ID = "recommendation-review"
DEFAULT_VARIANT = "overbuy"
DEMO_DB = Path(tempfile.gettempdir()) / "purchasing-agent-demo.db"

_LOOK_FOR = {
    "overbuy": (
        "REC-OVERBUY for SKU-COVERED is rejected. PO-COVERED already confirms 800 "
        "inbound (cover 38.4 days, net requirement 0). C8/C12 bind. No new PO."
    ),
    "healthy": (
        "REC-HEALTHY 140 is accepted. compute_replenishment_plan + validate_action "
        "pass; a PO is submitted to Acme and post-verified against expected_outcome."
    ),
    "moq": (
        "REC-MOQ needs ~320 vs Acme MOQ 1000. The agent tries the rounded qty, "
        "C7/C12 block it, and the run escalates instead of over-buying."
    ),
}


def _decision_payload(trace: Any) -> dict[str, Any]:
    raw = getattr(trace, "decision", None)
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return raw
    return {"decision": str(raw)}


def _clip(text: str, n: int = 220) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _summarize_result(tool: str | None, result: Any) -> str:
    if not isinstance(result, dict):
        return _clip(json.dumps(result, default=str))
    if tool == "get_recommendation":
        return (
            f"id={result.get('id')} sku={result.get('sku')} "
            f"qty={result.get('recommended_qty')} supplier={result.get('supplier_id')}"
        )
    if tool == "compute_replenishment_plan":
        return (
            f"rounded_qty={result.get('rounded_qty')} incoming={result.get('incoming_qty')} "
            f"cover_days={result.get('coverage_days')} "
            f"stockout={result.get('projected_stockout_date')} "
            f"cost={result.get('landed_cost')}"
        )
    if tool == "validate_action":
        binding = result.get("binding_constraint") or {}
        name = binding.get("name") if isinstance(binding, dict) else None
        return (
            f"passed={result.get('passed')} binding={name or 'none'} "
            f"suggested_max={result.get('suggested_max_feasible_qty')}"
        )
    if tool == "get_open_purchase_orders":
        pos = result.get("purchase_orders") or []
        bits = [
            f"{p.get('id')}:{p.get('status')}:{sum(ln.get('ordered_qty') or 0 for ln in (p.get('lines') or []))}"
            for p in pos[:4]
            if isinstance(p, dict)
        ]
        return f"open={len(pos)} " + (" ".join(bits) if bits else "")
    if tool in {"create_purchase_order", "modify_purchase_order", "split_purchase_order"}:
        po = result.get("po") or {}
        return (
            f"po={po.get('id')} status={result.get('status') or po.get('status')} "
            f"supplier_ok={(result.get('supplier') or {}).get('accepted')}"
        )
    if tool == "escalate":
        return _clip(str(result.get("reason") or result.get("status") or result))
    keys = ("ok", "passed", "status", "decision", "matched", "sku", "node", "id")
    bits = [f"{k}={result[k]}" for k in keys if k in result]
    return _clip(" ".join(bits) if bits else json.dumps(result, default=str)[:180])


def render_trace(trace: Any) -> str:
    decision = _decision_payload(trace)
    lines: list[str] = []
    lines.append(f"trace     {getattr(trace, 'id', '')}")
    lines.append(f"status    {getattr(trace, 'status', '')}")
    lines.append("")
    for step in getattr(trace, "steps", None) or []:
        stage = str(step.get("stage") or "")
        if stage in {"INTAKE", "LLM"}:
            continue
        tool = step.get("tool")
        note = step.get("note")
        result = step.get("result")
        head = f"{stage:<14}"
        if tool:
            head += f" {tool}"
        if note:
            head += f"  ({note})"
        lines.append(head)
        if stage == "DECIDE" and isinstance(result, dict):
            lines.append(
                f"              decision={result.get('decision')} "
                f"qty={result.get('final_quantity')} "
                f"supplier={result.get('supplier_id')}"
            )
            summary = result.get("reasoning_summary")
            if summary:
                lines.append(f"              {_clip(str(summary), 280)}")
        elif stage == "POST-VERIFY" and isinstance(result, dict):
            report = result.get("verification") or {}
            diffs = report.get("diffs") or result.get("diffs") or []
            lines.append(
                f"              matched={report.get('matched')} diffs={json.dumps(diffs, default=str)}"
            )
        elif stage == "RECONCILE" and isinstance(result, dict):
            lines.append(
                f"              action={result.get('action')} "
                f"diffs={json.dumps(result.get('diffs'), default=str)}"
            )
            if result.get("reason"):
                lines.append(f"              {_clip(str(result['reason']), 240)}")
        elif tool:
            lines.append(f"              {_summarize_result(str(tool), result)}")
        elif note and result is None:
            pass
        elif result is not None and stage not in {"INTAKE", "PLAN", "REPORT"}:
            lines.append(f"              {_clip(json.dumps(result, default=str), 200)}")
    lines.append("")
    lines.append(f"verdict   {str(decision.get('decision') or '—').upper()}")
    if decision.get("final_quantity") is not None:
        lines.append(f"quantity  {decision.get('final_quantity')}")
    if decision.get("reasoning_summary"):
        lines.append(f"why       {_clip(str(decision['reasoning_summary']), 360)}")
    constraints = decision.get("constraints_considered") or []
    if constraints:
        lines.append(f"constraints  {', '.join(str(c) for c in constraints)}")
    verification = getattr(trace, "verification", None)
    if isinstance(verification, dict):
        lines.append(
            f"post-verify  matched={verification.get('matched')} "
            f"diffs={json.dumps(verification.get('diffs') or [], default=str)}"
        )
    return "\n".join(lines)


def run_demo(*, variant: str, db_path: Path) -> int:
    spec = get_scenario(SCENARIO_ID)
    expected = spec.variant(variant).expected_decision
    engine = get_engine(f"sqlite:///{db_path}")
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        banner = [
            "=" * 72,
            "  AI Purchasing Agent — terminal demo (no UI, no API key)",
            f"  Scenario 1  {spec.title}",
            f"  variant     {variant}   expected {expected}",
            f"  clock       {FROZEN_TODAY.isoformat()} (frozen)",
            f"  llm         FakeLLM canned script",
            f"  db          {db_path}",
            "=" * 72,
            "",
        ]
        print("\n".join(banner), flush=True)
        print(f"Seeding world {spec.world!r} and running the agent…\n", flush=True)
        trace = execute_scenario(SCENARIO_ID, db=db, variant_id=variant, seed=True)
        print(render_trace(trace))
        got = str(_decision_payload(trace).get("decision") or "").lower()
        print()
        print(f"Look for: {_LOOK_FOR.get(variant, spec.variant(variant).note)}")
        if got == expected:
            print(f"OK  agent decided {got!r} (matches catalogue).")
            return 0
        print(f"UNEXPECTED  agent decided {got!r}, catalogue expected {expected!r}.")
        return 1
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed S1 and print a readable agent trace.")
    parser.add_argument(
        "--variant",
        default=DEFAULT_VARIANT,
        choices=["overbuy", "healthy", "moq"],
        help="Scenario 1 variant (default: overbuy — the 60-second reject demo).",
    )
    parser.add_argument(
        "--db",
        default=str(DEMO_DB),
        help="SQLite path for the demo world (default: a temp file).",
    )
    args = parser.parse_args(argv)
    return run_demo(variant=args.variant, db_path=Path(args.db))


if __name__ == "__main__":
    sys.exit(main())
