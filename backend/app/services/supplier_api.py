"""MOCK external supplier system — deliberately imperfect.

Behaviours are fixture-driven (supplier.api_behaviour), never random.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Supplier, SupplierProduct


class SupplierBehaviour(str, Enum):
    FULL_ACCEPT = "full_accept"
    PARTIAL_ACCEPT = "partial_accept"
    REJECT_MOQ_VIOLATION = "reject_moq_violation"
    ACCEPT_WITH_LONGER_LEAD_TIME = "accept_with_longer_lead_time"
    TIMEOUT = "timeout"
    CONFIRM_THEN_REVISE = "confirm_then_revise"


class SupplierSubmitResult(BaseModel):
    accepted: bool
    timed_out: bool = False
    confirmed_qty: int | None = None
    confirmed_lead_time_days: int | None = None
    revised_after_confirm: bool = False
    behaviour: SupplierBehaviour
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


def _behaviour_for(supplier: Supplier) -> tuple[SupplierBehaviour, dict[str, Any]]:
    raw = (supplier.api_behaviour or "full_accept").strip()
    try:
        behaviour = SupplierBehaviour(raw)
    except ValueError:
        behaviour = SupplierBehaviour.FULL_ACCEPT
    return behaviour, dict(supplier.api_behaviour_params or {})


class MockSupplierAPI:
    """Fixture-driven supplier gateway. Never random in eval mode."""

    def __init__(self, behaviours: dict[str, dict[str, Any]] | None = None) -> None:
        self.behaviours = behaviours or {}

    def submit_order(
        self,
        supplier_id: str,
        payload: dict[str, Any],
        *,
        db: Session | None = None,
    ) -> SupplierSubmitResult:
        behaviour, params = self._resolve(supplier_id, db)
        lines = payload.get("lines") or []
        ordered = int(sum(int(line.get("ordered_qty") or 0) for line in lines) or payload.get("ordered_qty") or 0)
        requested_lt = int(payload.get("lead_time_days") or params.get("lead_time_days") or 0)

        if behaviour is SupplierBehaviour.TIMEOUT:
            return SupplierSubmitResult(
                accepted=False,
                timed_out=True,
                behaviour=behaviour,
                message="Supplier API timed out; no confirmation received.",
            )

        if behaviour is SupplierBehaviour.REJECT_MOQ_VIOLATION:
            min_qty = int(params.get("min_qty") or payload.get("moq_units") or 0)
            if min_qty and ordered < min_qty:
                return SupplierSubmitResult(
                    accepted=False,
                    confirmed_qty=0,
                    behaviour=behaviour,
                    message=f"Supplier rejected: ordered {ordered} below their MOQ {min_qty}.",
                )
            if params.get("force_reject"):
                return SupplierSubmitResult(
                    accepted=False,
                    confirmed_qty=0,
                    behaviour=behaviour,
                    message="Supplier rejected the order (forced MOQ / policy reject).",
                )

        if behaviour is SupplierBehaviour.PARTIAL_ACCEPT:
            ratio = float(params.get("ratio", 0.5))
            confirmed = int(ordered * ratio)
            return SupplierSubmitResult(
                accepted=True,
                confirmed_qty=confirmed,
                confirmed_lead_time_days=requested_lt,
                behaviour=behaviour,
                message=f"Partial accept: confirmed {confirmed} of {ordered} (ratio {ratio}).",
            )

        extra = int(params.get("extra_lead_time_days", 7))
        if behaviour is SupplierBehaviour.ACCEPT_WITH_LONGER_LEAD_TIME:
            return SupplierSubmitResult(
                accepted=True,
                confirmed_qty=ordered,
                confirmed_lead_time_days=requested_lt + extra,
                behaviour=behaviour,
                message=f"Accepted with lead time +{extra} days.",
            )

        if behaviour is SupplierBehaviour.CONFIRM_THEN_REVISE:
            return SupplierSubmitResult(
                accepted=True,
                confirmed_qty=ordered,
                confirmed_lead_time_days=requested_lt + extra,
                revised_after_confirm=True,
                behaviour=behaviour,
                message="Confirmed, then silently revised lead time.",
                details={"originally_confirmed_lead_time_days": requested_lt},
            )

        # full_accept, or reject_moq when qty is fine
        return SupplierSubmitResult(
            accepted=True,
            confirmed_qty=ordered,
            confirmed_lead_time_days=requested_lt,
            behaviour=behaviour,
            message="Fully accepted.",
        )

    def _resolve(self, supplier_id: str, db: Session | None) -> tuple[SupplierBehaviour, dict[str, Any]]:
        override = self.behaviours.get(supplier_id)
        if override:
            raw = str(override.get("behaviour") or override.get("api_behaviour") or "full_accept")
            try:
                return SupplierBehaviour(raw), dict(override.get("params") or override.get("api_behaviour_params") or {})
            except ValueError:
                return SupplierBehaviour.FULL_ACCEPT, {}
        if db is not None:
            supplier = db.get(Supplier, supplier_id)
            if supplier is not None:
                return _behaviour_for(supplier)
        return SupplierBehaviour.FULL_ACCEPT, {}


supplier_api = MockSupplierAPI()
