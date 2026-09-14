"""Write tools — side effects, always pre-validated.

Every write:
  1. ConstraintEngine.evaluate() — refuse on blocking violations
  2. AutonomyPolicy.evaluate() — pending_approval if outside envelope
  3. Idempotency via client-supplied idempotency_key
  4. PRE-VALIDATE → EXECUTE → POST-VERIFY (wired in Prompt 4)

Implemented in Prompt 3.
"""

from __future__ import annotations

from typing import Any


def create_purchase_order(
    supplier_id: str,
    node: str,
    lines: list[dict[str, Any]],
    expected_delivery_date: str,
    justification: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def modify_purchase_order(
    po_id: str,
    line_changes: list[dict[str, Any]],
    justification: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def split_purchase_order(
    po_id: str,
    remainder_supplier_id: str,
    qty: int,
    justification: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def cancel_purchase_order_line(
    po_id: str,
    line_id: str,
    justification: str,
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def request_human_approval(
    action_payload: dict[str, Any],
    reason: str,
    urgency: str,
    options_considered: list[dict[str, Any]],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def escalate(
    reason: str,
    context: dict[str, Any],
    suggested_options: list[dict[str, Any]],
    *,
    idempotency_key: str,
) -> dict[str, Any]:
    raise NotImplementedError


def log_decision(decision_payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    raise NotImplementedError
