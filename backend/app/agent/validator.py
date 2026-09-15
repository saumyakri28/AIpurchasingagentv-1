"""Pre-validate → execute → post-verify + reconcile.

Write actions never skip this loop. The LLM cannot override ConstraintEngine.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agent.schemas import ExpectedOutcome, VerificationDiff, VerificationReport
from app.db.models import Product, PurchaseOrder
from app.domain.calculators import coverage_days, effective_available
from app.domain.constraints import ConstraintEngine, ProposedAction, ValidationReport
from app.tools.context import (
    assemble_proposed_action,
    current_budget,
    forecast_units,
    incoming_for,
    inventory_row,
    product_by_sku,
    serialize_po,
    storage_used,
)
from app.tools.errors import EntityNotFound

MAX_PREVALIDATE_REVISIONS = 2
MAX_RECONCILE_ROUNDS = 2
ENGINE = ConstraintEngine()
WRITE_CONTRACT_FIELDS = ("po_status", "ordered_qty", "committed_cost")
BUY_WRITE_TOOLS = frozenset(
    {"create_purchase_order", "modify_purchase_order", "split_purchase_order"}
)


def pre_validate(proposed_action: dict[str, Any], *, db: Session | None = None) -> ValidationReport:
    """Would this action violate any invariant?

    Prefer assembling facts from the database (same path as `validate_action`)
    so the LLM cannot smuggle a hand-built ProposedAction past the engine.
    """
    action = _action_from_payload(proposed_action, db=db)
    return ENGINE.evaluate(action)


def _action_from_payload(payload: dict[str, Any], *, db: Session | None) -> ProposedAction:
    sku = payload.get("sku")
    node = payload.get("node")
    supplier_id = payload.get("supplier_id")
    qty = payload.get("qty")
    if db is not None and sku and node and supplier_id and qty is not None:
        return assemble_proposed_action(
            db,
            sku=str(sku),
            node=str(node),
            supplier_id=str(supplier_id),
            qty=int(qty),
            exclude_po_id=payload.get("exclude_po_id"),
        )
    nested = payload.get("proposed_action")
    if isinstance(nested, dict):
        return ProposedAction.model_validate(nested)
    return ProposedAction.model_validate(payload)


def _close(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool):
            return a == b
        return abs(float(a) - float(b)) <= max(0.05, 0.01 * abs(float(a)))
    if a is None or b is None:
        return False
    return str(a).strip().lower() == str(b).strip().lower()


def post_verify(
    expected: ExpectedOutcome,
    *,
    source_of_truth: dict[str, Any],
    require_complete: bool = False,
) -> VerificationReport:
    """Re-read persisted state and diff against the declared expected_outcome."""
    diffs: list[VerificationDiff] = []
    declared = expected.model_dump()
    if require_complete:
        missing = [field for field in WRITE_CONTRACT_FIELDS if declared.get(field) is None]
        if missing:
            for field in missing:
                diffs.append(
                    VerificationDiff(
                        field=field,
                        expected=None,
                        actual=source_of_truth.get(field),
                    )
                )
            return VerificationReport(
                matched=False,
                diffs=diffs,
                reason="incomplete_expected_outcome",
            )
    for field, wanted in declared.items():
        if wanted is None:
            continue
        actual = source_of_truth.get(field)
        if not _close(wanted, actual):
            diffs.append(VerificationDiff(field=field, expected=wanted, actual=actual))
    return VerificationReport(matched=not diffs, diffs=diffs)


def reconcile(report: VerificationReport, context: dict[str, Any]) -> dict[str, Any]:
    """On mismatch: compensating action or escalate. Capped at 2 rounds."""
    rounds = int(context.get("reconciliation_rounds") or 0)
    remaining = max(0, MAX_RECONCILE_ROUNDS - rounds)
    payload = {
        "matched": report.matched,
        "diffs": [d.model_dump(mode="json") for d in report.diffs],
        "reconciliation_rounds": rounds,
        "remaining_rounds": remaining,
    }
    if report.matched:
        payload["action"] = "done"
        return payload
    if remaining <= 0:
        payload["action"] = "force_escalate"
        payload["reason"] = (
            "Post-verify still unmatched after two reconciliation rounds. Escalating."
        )
        return payload
    payload["action"] = "revise"
    payload["reason"] = (
        "Persisted state does not match expected_outcome. Choose a compensating "
        "action: top-up from an alternate supplier, split the PO, reduce and re-plan, "
        "or escalate with options."
    )
    return payload


def _stockout_risk(cover_days: float | None) -> str:
    if cover_days is None or cover_days == float("inf") or cover_days > 21:
        return "low"
    if cover_days > 7:
        return "medium"
    return "high"


def collect_source_of_truth(
    db: Session,
    *,
    po_id: str | None,
    sku: str | None,
    node: str | None,
    supplier_id: str | None = None,
) -> dict[str, Any]:
    """Re-read PO + related state FROM THE DATABASE. Never from a tool return value."""
    db.expire_all()
    po = db.get(PurchaseOrder, po_id) if po_id else None
    ordered_qty = 0
    committed_cost = 0.0
    po_status = None
    po_payload = None
    if po is not None:
        po_payload = serialize_po(po)
        ordered_qty = sum(line.ordered_qty for line in po.lines)
        committed_cost = float(po.total_cost)
        po_status = po.status
        node = node or po.node_id
        supplier_id = supplier_id or po.supplier_id
        if sku is None and po.lines:
            product = db.get(Product, po.lines[0].product_id)
            sku = product.sku if product else None

    budget_remaining = None
    storage_after = None
    cover_days: float | None = None
    constraint_report = None
    if sku and node:
        try:
            product = product_by_sku(db, sku)
            inv = inventory_row(db, product.id, node)
        except EntityNotFound:
            product = None
            inv = None
        if inv is not None and product is not None:
            available = effective_available(inv.on_hand, inv.reserved, inv.damaged)
            incoming = incoming_for(db, product.id, node)
            forecast = forecast_units(db, product.id, node, 56)
            cover = coverage_days(available, incoming, forecast)
            cover_days = None if cover.coverage_days == float("inf") else cover.coverage_days
            storage_after = storage_used(db, node)
            budget = current_budget(db, node, product.category)
            if budget is not None:
                budget_remaining = budget.remaining
            qty = ordered_qty if ordered_qty else 0
            if supplier_id and qty:
                action = assemble_proposed_action(
                    db,
                    sku=sku,
                    node=node,
                    supplier_id=supplier_id,
                    qty=qty,
                )
                constraint_report = ENGINE.evaluate(action).model_dump(mode="json")

    return {
        "po_id": po.id if po is not None else None,
        "po": po_payload,
        "po_status": po_status,
        "ordered_qty": ordered_qty,
        "committed_cost": committed_cost,
        "budget_remaining_after": budget_remaining,
        "storage_used_after": storage_after,
        "projected_cover_days": cover_days,
        "stockout_risk": _stockout_risk(cover_days),
        "expected_delivery_date": (
            po.expected_delivery_date.isoformat() if po is not None and po.expected_delivery_date else None
        ),
        "sku": sku,
        "node": node,
        "supplier_id": supplier_id,
        "constraint_report": constraint_report,
    }
