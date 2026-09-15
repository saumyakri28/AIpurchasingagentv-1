"""Seven independent grader dimensions. Never collapsed into one opaque score."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.schemas import DecisionTrace
from app.db.models import Budget, Node, Product, PurchaseOrder, SupplierProduct
from app.domain.constraints import ConstraintEngine
from app.tools.context import assemble_proposed_action, storage_used
from evals.cases import CONSTRAINT_CODE, DIMENSIONS, EvalCase, NAME_TO_CODE

ENGINE = ConstraintEngine()
WRITE_TOOLS = {
    "create_purchase_order",
    "modify_purchase_order",
    "split_purchase_order",
    "cancel_purchase_order_line",
}
CLOCK_NUMBERS = {"2026", "15", "9", "09"}


def _tools(trace: DecisionTrace) -> list[str]:
    return [str(s.get("tool")) for s in (trace.steps or []) if s.get("tool")]


def _decision_payload(trace: DecisionTrace) -> dict[str, Any]:
    if trace.decision is None:
        return {}
    if hasattr(trace.decision, "model_dump"):
        return trace.decision.model_dump(mode="json")
    if isinstance(trace.decision, dict):
        return trace.decision
    return {"decision": str(trace.decision)}


def _decision_class(trace: DecisionTrace) -> str:
    payload = _decision_payload(trace)
    raw = payload.get("decision")
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw or "").lower()


def _dim(passed: bool, notes: str, **extra: Any) -> dict[str, Any]:
    return {"passed": bool(passed), "notes": notes, **extra}


def grade_decision(case: EvalCase, trace: DecisionTrace) -> dict[str, Any]:
    allowed = case.expected.allowed_decisions()
    got = _decision_class(trace)
    payload = _decision_payload(trace)
    qty = payload.get("final_quantity")
    notes = [f"got {got or '(none)'} allowed {sorted(allowed)}"]
    ok = got in allowed
    rng = case.expected.quantity_range
    if rng is not None:
        if qty is None:
            ok = False
            notes.append("quantity missing")
        elif not (rng[0] <= float(qty) <= rng[1]):
            ok = False
            notes.append(f"qty {qty} outside [{rng[0]}, {rng[1]}]")
        else:
            notes.append(f"qty {qty} in range")
    if case.expected.must_escalate_if_blocked:
        blocked = False
        for step in reversed(trace.steps or []):
            if step.get("tool") == "validate_action" and isinstance(step.get("result"), dict):
                blocked = bool(step["result"].get("blocking_violations"))
                break
        wrote = any(t in WRITE_TOOLS for t in _tools(trace) if t != "escalate")
        if blocked and wrote and got not in {"escalate", "reject", "investigate_further"}:
            ok = False
            notes.append("blocked validate_action but still wrote")
    return _dim(ok, "; ".join(notes), got=got, quantity=qty)


def grade_information(case: EvalCase, trace: DecisionTrace) -> dict[str, Any]:
    required = case.expected.must_call_tools
    called = set(_tools(trace))
    decide_idx = next(
        (i for i, s in enumerate(trace.steps or []) if s.get("stage") == "DECIDE"),
        len(trace.steps or []),
    )
    before = {str(s.get("tool")) for s in (trace.steps or [])[:decide_idx] if s.get("tool")}
    write_ok_late = WRITE_TOOLS | {"escalate", "request_human_approval", "validate_action"}
    missing = [name for name in required if name not in called]
    late = [name for name in required if name in called and name not in before and name not in write_ok_late]
    notes = []
    if missing:
        notes.append(f"missing {missing}")
    if late:
        notes.append(f"called after DECIDE {late}")
    if not notes:
        notes.append("required tools present before the decision")
    return _dim(not missing, "; ".join(notes), missing=missing, late=late)


def _code(name: str) -> str:
    if name in CONSTRAINT_CODE:
        return name
    return NAME_TO_CODE.get(name, name)


def grade_constraints(case: EvalCase, trace: DecisionTrace, db: Session) -> dict[str, Any]:
    """Assert against the database after the run, not against the agent's claims."""
    problems: list[str] = []
    for budget in db.scalars(select(Budget)).all():
        if float(budget.committed) - 1e-6 > float(budget.allocated):
            problems.append(
                f"{budget.id} committed {budget.committed} > allocated {budget.allocated}"
            )
    for node in db.scalars(select(Node)).all():
        used = storage_used(db, node.id)
        if used - 1e-6 > float(node.storage_capacity_m3):
            problems.append(f"{node.id} storage {used:.2f} > capacity {node.storage_capacity_m3}")

    agent_pos = [
        po
        for po in db.scalars(select(PurchaseOrder)).all()
        if po.created_by == "agent" and po.status not in {"cancelled", "draft"}
    ]
    wanted = {_code(c) for c in case.expected.must_not_violate}
    for po in agent_pos:
        for line in po.lines:
            product = db.get(Product, line.product_id)
            if product is None:
                continue
            link = db.scalar(
                select(SupplierProduct).where(
                    SupplierProduct.supplier_id == po.supplier_id,
                    SupplierProduct.product_id == product.id,
                )
            )
            if link is not None:
                if line.ordered_qty < int(link.moq_units):
                    problems.append(f"{po.id} qty {line.ordered_qty} < MOQ {link.moq_units}")
                multiple = int(link.order_multiple_units or 1)
                if multiple and line.ordered_qty % multiple:
                    problems.append(f"{po.id} qty {line.ordered_qty} not multiple of {multiple}")
            try:
                action = assemble_proposed_action(
                    db,
                    sku=product.sku,
                    node=po.node_id,
                    supplier_id=po.supplier_id,
                    qty=line.ordered_qty,
                    exclude_po_id=po.id,
                )
            except Exception as exc:  # pragma: no cover — missing facts
                problems.append(f"{po.id} could not assemble proposed action: {exc}")
                continue
            report = ENGINE.evaluate(action)
            for hit in report.blocking_violations:
                code = _code(hit.name)
                if wanted and (code in wanted or hit.name in wanted):
                    problems.append(f"{po.id} DB-blocking {code} {hit.name}: {hit.message}")

    claimed = " ".join(
        str(x) for x in (_decision_payload(trace).get("constraints_considered") or [])
    ).lower()
    if "pass" in claimed and problems:
        problems.append("agent claimed constraint respect but the database disagrees")
    notes = "; ".join(problems) if problems else "budgets, storage and executed PO lines hold"
    return _dim(not problems, notes, violations=problems)


def _act_tools(trace: DecisionTrace) -> list[dict[str, Any]]:
    return [
        s
        for s in (trace.steps or [])
        if s.get("stage") == "ACT" and s.get("tool") in WRITE_TOOLS | {"escalate", "request_human_approval"}
    ]


def grade_action(case: EvalCase, trace: DecisionTrace, db: Session) -> dict[str, Any]:
    spec = case.expected.expected_action
    if spec is None:
        return _dim(True, "no expected_action")
    wanted = spec.type
    acts = _act_tools(trace)
    names = [str(s.get("tool")) for s in acts]
    if wanted in {"none", "noop", "-"}:
        writes = [n for n in names if n in WRITE_TOOLS]
        ok = not writes
        return _dim(ok, "no write" if ok else f"unexpected writes {writes}")

    if wanted not in names and not (wanted == "escalate" and "escalate" in _tools(trace)):
        return _dim(False, f"wanted {wanted}, ACT tools={names}")

    target = spec.target
    if target:
        blob = json.dumps(acts, default=str)
        po_id = trace.po_id
        hit = target in blob or (po_id or "") == target
        if not hit:
            intake = trace.intake or {}
            hit = target in {intake.get("sku"), intake.get("po_id"), intake.get("node")}
        if not hit:
            return _dim(False, f"target {target} not on the write")

    if spec.status and trace.po_id:
        po = db.get(PurchaseOrder, trace.po_id)
        if po is None or po.status != spec.status:
            actual = po.status if po is not None else "missing"
            return _dim(False, f"PO status {actual} != {spec.status}")
    return _dim(True, f"{wanted} matched")


def grade_validation(case: EvalCase, trace: DecisionTrace) -> dict[str, Any]:
    stages = [s.get("stage") for s in (trace.steps or [])]
    pre = "PRE-VALIDATE" in stages
    post = "POST-VERIFY" in stages
    report = trace.verification
    compared = report is not None
    payload = _decision_payload(trace)
    declared = payload.get("expected_outcome")
    notes = []
    if not pre:
        notes.append("missing PRE-VALIDATE")
    if case.expected.must_post_verify and not post:
        notes.append("missing POST-VERIFY")
    if case.expected.must_post_verify and not compared:
        notes.append("no VerificationReport")
    if declared is None and _decision_class(trace) in {"accept", "modify"}:
        notes.append("write decision had no expected_outcome contract")
    ok = pre and (not case.expected.must_post_verify or (post and compared))
    if not notes:
        notes.append("pre-validation and post-verify reports present")
    return _dim(ok, "; ".join(notes))


def grade_recovery(case: EvalCase, trace: DecisionTrace) -> dict[str, Any]:
    stages = [s.get("stage") for s in (trace.steps or [])]
    if case.expected.must_reconcile and "RECONCILE" not in stages:
        return _dim(False, "RECONCILE stage missing")
    if not case.expected.recovery and not case.expected.must_reconcile:
        return _dim(True, "not a failure-injection case")
    verification = trace.verification
    matched = getattr(verification, "matched", None)
    if isinstance(verification, dict):
        matched = verification.get("matched")
    detected = "RECONCILE" in stages or matched is False
    got = _decision_class(trace)
    sensible = got in {"escalate", "modify", "reject", "investigate_further"} or (
        matched is False and "RECONCILE" in stages
    )
    pretended = trace.status == "completed" and matched is True
    ok = detected and sensible and not pretended
    notes = []
    if not detected:
        notes.append("mismatch not detected")
    if pretended:
        notes.append("reported success after a broken write")
    if not sensible:
        notes.append(f"final decision {got} is not a compensating action")
    if not notes:
        notes.append("detected mismatch and compensated / escalated")
    return _dim(ok, "; ".join(notes), detected=detected, matched=matched)


def _numbers(text: str) -> list[str]:
    cleaned = re.sub(r"\bC\d+\b", " ", text or "")
    found = re.findall(r"\d+(?:\.\d+)?", cleaned)
    out: list[str] = []
    for token in found:
        if token in CLOCK_NUMBERS:
            continue
        if token.startswith("0") and token not in {"0", "0.0"}:
            stripped = token.lstrip("0") or "0"
            out.append(stripped)
        out.append(token)
    return out


def grade_explanation(trace: DecisionTrace) -> dict[str, Any]:
    payload = _decision_payload(trace)
    factors = payload.get("key_factors") or []
    if not factors:
        return _dim(False, "no key_factors")
    uncited = [f for f in factors if not (f.get("source_tool") if isinstance(f, dict) else getattr(f, "source_tool", None))]
    if uncited:
        return _dim(False, "key_factor missing source_tool")
    reasoning = str(payload.get("reasoning_summary") or "")
    tool_blob = json.dumps(
        [
            {"tool": s.get("tool"), "arguments": s.get("arguments"), "result": s.get("result")}
            for s in (trace.steps or [])
            if s.get("tool")
        ],
        default=str,
    )
    factor_blob = json.dumps(factors, default=str)
    haystack = tool_blob + " " + factor_blob
    missing = []
    for token in _numbers(reasoning):
        if token not in haystack and token.replace(".0", "") not in haystack:
            missing.append(token)
    # de-dupe while preserving order
    seen: set[str] = set()
    missing = [t for t in missing if not (t in seen or seen.add(t))]
    ok = not missing
    notes = "all cited numbers appear in a tool result" if ok else f"uncited numbers {missing}"
    return _dim(ok, notes, uncited_numbers=missing)


def grade_case(case: EvalCase, trace: DecisionTrace, db: Session) -> dict[str, Any]:
    dims = {
        "decision_correctness": grade_decision(case, trace),
        "information_sufficiency": grade_information(case, trace),
        "constraint_respect": grade_constraints(case, trace, db),
        "action_correctness": grade_action(case, trace, db),
        "validation_performed": grade_validation(case, trace),
        "recovery": grade_recovery(case, trace),
        "explanation_quality": grade_explanation(trace),
    }
    passed = all(dims[name]["passed"] for name in DIMENSIONS)
    return {
        "id": case.id,
        "description": case.description,
        "trace_id": trace.id,
        "decision": _decision_class(trace),
        "status": trace.status,
        "passed": passed,
        "dimensions": dims,
        "assertions": [{"category": name, "passed": dims[name]["passed"], "notes": dims[name]["notes"]} for name in DIMENSIONS],
    }
