"""Write tools — pre-validated, policy-gated, idempotent."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.clock import FROZEN_NOW, FROZEN_TODAY
from app.db.models import (
    ApprovalRequest,
    CreatedBy,
    DecisionTrace,
    EventLog,
    IdempotencyRecord,
    POLine,
    POStatus,
    Product,
    PurchaseOrder,
)
from app.domain.constraints import ConstraintEngine
from app.domain.policy import AutonomyPolicy, default_policy
from app.services.supplier_api import supplier_api
from app.tools.context import (
    assemble_proposed_action,
    current_budget,
    product_by_sku,
    serialize_po,
    supplier_link,
)
from app.tools.errors import ConstraintRefused, EntityNotFound
from app.tools.registry import tool
from app.tools.schemas import (
    CancelLineArgs,
    CreatePOArgs,
    EscalateArgs,
    LogDecisionArgs,
    ModifyPOArgs,
    RequestApprovalArgs,
    SplitPOArgs,
)

ENGINE = ConstraintEngine()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _replay(db: Session, key: str) -> dict[str, Any] | None:
    rec = db.get(IdempotencyRecord, key)
    return rec.response if rec is not None else None


def _remember(db: Session, key: str, tool_name: str, response: dict[str, Any]) -> dict[str, Any]:
    db.add(
        IdempotencyRecord(
            key=key,
            tool_name=tool_name,
            response=response,
            created_at=FROZEN_NOW,
        )
    )
    return response


def _log(db: Session, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any]) -> None:
    db.add(
        EventLog(
            id=_new_id("evt"),
            ts=FROZEN_NOW,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
    )


def _parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def _evaluate_or_refuse(action) -> None:
    report = ENGINE.evaluate(action)
    if report.blocking_violations:
        raise ConstraintRefused(report)


def _budget_add(db: Session, node_id: str, category: str, delta: float) -> None:
    if delta == 0:
        return
    budget = current_budget(db, node_id, category)
    if budget is None:
        return
    budget.committed = float(budget.committed) + float(delta)


def _line_category(db: Session, product_id: str) -> str:
    product = db.get(Product, product_id)
    return product.category if product else ""


def _apply_supplier_result(po: PurchaseOrder, result, requested_lead: int) -> None:
    if result.timed_out:
        po.status = POStatus.SUBMITTED.value
        return
    if not result.accepted:
        po.status = POStatus.CANCELLED.value
        for line in po.lines:
            line.confirmed_qty = 0
        return
    confirmed = int(result.confirmed_qty or 0)
    ordered = sum(line.ordered_qty for line in po.lines)
    remaining = confirmed
    for line in po.lines:
        take = min(line.ordered_qty, remaining)
        line.confirmed_qty = take
        remaining -= take
    if confirmed < ordered:
        po.status = POStatus.PARTIALLY_CONFIRMED.value
    else:
        po.status = POStatus.CONFIRMED.value
    lead = result.confirmed_lead_time_days
    if lead is None:
        lead = requested_lead
    po.expected_delivery_date = FROZEN_TODAY + timedelta(days=int(lead))


@tool(
    "create_purchase_order",
    "Create a PO. Pre-validated; blocked constraints refuse. Over-envelope POs go pending_approval.",
    CreatePOArgs,
    is_write=True,
)
def create_purchase_order(args: CreatePOArgs, *, db: Session, policy: AutonomyPolicy | None = None) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    policy = policy or default_policy()
    if not args.lines:
        raise ValueError("create_purchase_order requires at least one line")

    actions = []
    total_cost = 0.0
    reliability = 1.0
    resolved_lines: list[tuple[str, int, float, str]] = []
    for line in args.lines:
        product = product_by_sku(db, line.sku)
        link = supplier_link(db, args.supplier_id, product.id)
        price = float(line.unit_price if line.unit_price is not None else (link.unit_price if link else 0))
        action = assemble_proposed_action(
            db,
            sku=line.sku,
            node=args.node,
            supplier_id=args.supplier_id,
            qty=line.qty,
        )
        if line.unit_price is not None:
            action.unit_price = price
        _evaluate_or_refuse(action)
        actions.append(action)
        total_cost += line.qty * price
        reliability = action.reliability_score
        resolved_lines.append((product.id, line.qty, price, product.category))

    decision = policy.evaluate(
        {"total_cost": total_cost, "reliability_score": reliability},
        confidence=args.confidence,
    )
    status = POStatus.PENDING_APPROVAL.value if decision.requires_approval else POStatus.SUBMITTED.value

    po = PurchaseOrder(
        id=_new_id("PO"),
        supplier_id=args.supplier_id,
        node_id=args.node,
        status=status,
        created_at=FROZEN_NOW,
        expected_delivery_date=_parse_date(args.expected_delivery_date),
        total_cost=total_cost,
        created_by=CreatedBy.AGENT.value,
    )
    for product_id, qty, price, _cat in resolved_lines:
        po.lines.append(
            POLine(
                id=_new_id("POL"),
                product_id=product_id,
                ordered_qty=qty,
                confirmed_qty=0,
                received_qty=0,
                unit_price=price,
            )
        )
    db.add(po)
    db.flush()

    supplier_result = None
    if status == POStatus.SUBMITTED.value:
        for product_id, qty, price, category in resolved_lines:
            _budget_add(db, args.node, category, qty * price)
        lead = actions[0].lead_time_days if actions else 0
        supplier_result = supplier_api.submit_order(
            args.supplier_id,
            {
                "lines": [{"ordered_qty": qty} for _, qty, _, _ in resolved_lines],
                "ordered_qty": sum(q for _, q, _, _ in resolved_lines),
                "lead_time_days": lead,
                "moq_units": actions[0].moq_units if actions else 0,
            },
            db=db,
        )
        _apply_supplier_result(po, supplier_result, lead)
        if po.status == POStatus.CANCELLED.value:
            for product_id, qty, price, category in resolved_lines:
                _budget_add(db, args.node, category, -(qty * price))

    if decision.requires_approval:
        db.add(
            ApprovalRequest(
                id=_new_id("APR"),
                action_payload={"tool": "create_purchase_order", "po_id": po.id, **args.model_dump(mode="json")},
                reason="; ".join(decision.reasons) + f" | {args.justification}",
                urgency="normal",
                options_considered=[],
                created_at=FROZEN_NOW,
            )
        )

    _log(
        db,
        "po_created",
        "purchase_order",
        po.id,
        {
            "status": po.status,
            "justification": args.justification,
            "policy": decision.model_dump(),
            "supplier": supplier_result.model_dump(mode="json") if supplier_result else None,
        },
    )
    response = {
        "ok": True,
        "po": serialize_po(po),
        "status": po.status,
        "requires_human_approval": decision.requires_approval,
        "policy_reasons": decision.reasons,
        "supplier": supplier_result.model_dump(mode="json") if supplier_result else None,
    }
    return _remember(db, args.idempotency_key, "create_purchase_order", response)


@tool(
    "modify_purchase_order",
    "Change ordered qty on PO lines. Increases are constraint-checked. Budget is adjusted if submitted.",
    ModifyPOArgs,
    is_write=True,
)
def modify_purchase_order(args: ModifyPOArgs, *, db: Session, policy: AutonomyPolicy | None = None) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    po = db.get(PurchaseOrder, args.po_id)
    if po is None:
        raise EntityNotFound("purchase_order", args.po_id)
    if po.status in {POStatus.RECEIVED.value, POStatus.CANCELLED.value}:
        raise ValueError(f"Cannot modify PO in status {po.status}")

    deltas: list[tuple[str, float]] = []
    for change in args.line_changes:
        line = next((ln for ln in po.lines if ln.id == change.line_id), None)
        if line is None:
            raise EntityNotFound("po_line", change.line_id)
        product = db.get(Product, line.product_id)
        assert product is not None
        if change.ordered_qty > line.ordered_qty:
            action = assemble_proposed_action(
                db,
                sku=product.sku,
                node=po.node_id,
                supplier_id=po.supplier_id,
                qty=change.ordered_qty,
                exclude_po_id=po.id,
            )
            _evaluate_or_refuse(action)
        delta_cost = (change.ordered_qty - line.ordered_qty) * line.unit_price
        deltas.append((_line_category(db, line.product_id), delta_cost))
        line.ordered_qty = change.ordered_qty

    po.total_cost = sum(ln.ordered_qty * ln.unit_price for ln in po.lines)
    if po.status in {POStatus.SUBMITTED.value, POStatus.CONFIRMED.value, POStatus.PARTIALLY_CONFIRMED.value}:
        for category, delta in deltas:
            _budget_add(db, po.node_id, category, delta)

    _log(db, "po_modified", "purchase_order", po.id, {"justification": args.justification})
    response = {"ok": True, "po": serialize_po(po), "status": po.status}
    return _remember(db, args.idempotency_key, "modify_purchase_order", response)


@tool(
    "split_purchase_order",
    "Move qty off a PO onto a remainder supplier. The new slice is constraint-checked.",
    SplitPOArgs,
    is_write=True,
)
def split_purchase_order(args: SplitPOArgs, *, db: Session, policy: AutonomyPolicy | None = None) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    po = db.get(PurchaseOrder, args.po_id)
    if po is None:
        raise EntityNotFound("purchase_order", args.po_id)
    if not po.lines:
        raise ValueError("PO has no lines to split")
    line = po.lines[0]
    if args.qty <= 0 or args.qty > line.ordered_qty:
        raise ValueError("split qty must be between 1 and the source line qty")
    product = db.get(Product, line.product_id)
    assert product is not None

    action = assemble_proposed_action(
        db,
        sku=product.sku,
        node=po.node_id,
        supplier_id=args.remainder_supplier_id,
        qty=args.qty,
        exclude_po_id=po.id,
    )
    _evaluate_or_refuse(action)

    link = supplier_link(db, args.remainder_supplier_id, product.id)
    price = float(link.unit_price) if link else line.unit_price
    remainder = PurchaseOrder(
        id=_new_id("PO"),
        supplier_id=args.remainder_supplier_id,
        node_id=po.node_id,
        status=POStatus.DRAFT.value,
        created_at=FROZEN_NOW,
        expected_delivery_date=FROZEN_TODAY + timedelta(days=action.lead_time_days),
        total_cost=args.qty * price,
        created_by=CreatedBy.AGENT.value,
    )
    remainder.lines.append(
        POLine(
            id=_new_id("POL"),
            product_id=product.id,
            ordered_qty=args.qty,
            confirmed_qty=0,
            received_qty=0,
            unit_price=price,
        )
    )
    line.ordered_qty -= args.qty
    po.total_cost = sum(ln.ordered_qty * ln.unit_price for ln in po.lines)
    db.add(remainder)
    db.flush()

    policy = policy or default_policy()
    decision = policy.evaluate(
        {"total_cost": remainder.total_cost, "reliability_score": action.reliability_score}
    )
    if decision.requires_approval:
        remainder.status = POStatus.PENDING_APPROVAL.value
        db.add(
            ApprovalRequest(
                id=_new_id("APR"),
                action_payload={"tool": "split_purchase_order", "po_id": remainder.id},
                reason="; ".join(decision.reasons),
                urgency="normal",
                options_considered=[],
                created_at=FROZEN_NOW,
            )
        )
    else:
        remainder.status = POStatus.SUBMITTED.value
        _budget_add(db, remainder.node_id, product.category, remainder.total_cost)
        if po.status in {POStatus.SUBMITTED.value, POStatus.CONFIRMED.value, POStatus.PARTIALLY_CONFIRMED.value}:
            _budget_add(db, po.node_id, product.category, -(args.qty * line.unit_price))
        result = supplier_api.submit_order(
            args.remainder_supplier_id,
            {"lines": [{"ordered_qty": args.qty}], "ordered_qty": args.qty, "lead_time_days": action.lead_time_days},
            db=db,
        )
        _apply_supplier_result(remainder, result, action.lead_time_days)

    _log(db, "po_split", "purchase_order", po.id, {"remainder_po": remainder.id, "qty": args.qty, "justification": args.justification})
    response = {
        "ok": True,
        "source_po": serialize_po(po),
        "remainder_po": serialize_po(remainder),
        "requires_human_approval": decision.requires_approval,
        "policy_reasons": decision.reasons,
    }
    return _remember(db, args.idempotency_key, "split_purchase_order", response)


@tool(
    "cancel_purchase_order_line",
    "Cancel one PO line. Releases committed budget if the PO had been submitted.",
    CancelLineArgs,
    is_write=True,
)
def cancel_purchase_order_line(args: CancelLineArgs, *, db: Session) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    po = db.get(PurchaseOrder, args.po_id)
    if po is None:
        raise EntityNotFound("purchase_order", args.po_id)
    line = next((ln for ln in po.lines if ln.id == args.line_id), None)
    if line is None:
        raise EntityNotFound("po_line", args.line_id)
    if line.received_qty:
        raise ValueError("Cannot cancel a line that has already been received")

    released = line.ordered_qty * line.unit_price
    category = _line_category(db, line.product_id)
    was_live = po.status in {
        POStatus.SUBMITTED.value,
        POStatus.CONFIRMED.value,
        POStatus.PARTIALLY_CONFIRMED.value,
    }
    last_line = len(po.lines) == 1
    db.delete(line)
    db.flush()
    if last_line:
        po.status = POStatus.CANCELLED.value
        po.total_cost = 0.0
    else:
        po.total_cost = sum(ln.ordered_qty * ln.unit_price for ln in po.lines)
    if was_live:
        _budget_add(db, po.node_id, category, -released)

    _log(db, "po_line_cancelled", "purchase_order", po.id, {"line_id": args.line_id, "justification": args.justification})
    response = {"ok": True, "po": serialize_po(po), "status": po.status, "released_budget": released if was_live else 0.0}
    return _remember(db, args.idempotency_key, "cancel_purchase_order_line", response)


@tool(
    "request_human_approval",
    "Park an action on the approval queue with rationale and options considered.",
    RequestApprovalArgs,
    is_write=True,
)
def request_human_approval(args: RequestApprovalArgs, *, db: Session) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    approval = ApprovalRequest(
        id=_new_id("APR"),
        action_payload=args.action_payload,
        reason=args.reason,
        urgency=args.urgency,
        options_considered=args.options_considered,
        created_at=FROZEN_NOW,
    )
    db.add(approval)
    db.flush()
    _log(db, "approval_requested", "approval_request", approval.id, {"urgency": args.urgency})
    response = {
        "ok": True,
        "approval_id": approval.id,
        "status": approval.status,
        "reason": approval.reason,
        "urgency": approval.urgency,
    }
    return _remember(db, args.idempotency_key, "request_human_approval", response)


@tool(
    "escalate",
    "Escalate to a human with context and suggested options. Does not place an order.",
    EscalateArgs,
    is_write=True,
)
def escalate(args: EscalateArgs, *, db: Session) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    approval = ApprovalRequest(
        id=_new_id("APR"),
        action_payload={"tool": "escalate", "context": args.context, "suggested_options": args.suggested_options},
        reason=args.reason,
        urgency="high",
        options_considered=args.suggested_options,
        created_at=FROZEN_NOW,
    )
    db.add(approval)
    db.flush()
    _log(db, "escalated", "approval_request", approval.id, {"reason": args.reason})
    response = {
        "ok": True,
        "escalated": True,
        "approval_id": approval.id,
        "reason": args.reason,
        "suggested_options": args.suggested_options,
    }
    return _remember(db, args.idempotency_key, "escalate", response)


@tool("log_decision", "Persist a DecisionTrace payload for the audit trail.", LogDecisionArgs, is_write=True)
def log_decision(args: LogDecisionArgs, *, db: Session) -> dict[str, Any]:
    cached = _replay(db, args.idempotency_key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}

    payload = args.decision_payload
    trace = DecisionTrace(
        id=str(payload.get("id") or _new_id("TR")),
        scenario_type=payload.get("scenario_type"),
        intake=payload.get("intake") or {},
        plan=payload.get("plan"),
        steps=payload.get("steps") or [],
        decision=payload.get("decision"),
        verification=payload.get("verification"),
        status=str(payload.get("status") or "logged"),
        created_at=FROZEN_NOW,
        completed_at=FROZEN_NOW,
    )
    db.add(trace)
    db.flush()
    response = {"ok": True, "trace_id": trace.id, "status": trace.status}
    return _remember(db, args.idempotency_key, "log_decision", response)
