"""Autonomy envelope. Anything outside it goes to human approval.

Thresholds are configuration, not prompt text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.config import get_settings


class PolicyDecision(BaseModel):
    autonomous: bool
    requires_approval: bool
    reasons: list[str] = Field(default_factory=list)


class AutonomyPolicy:
    """Value, confidence, and supplier-reliability gates.

    Constraint breaches are refused by ConstraintEngine, not sent to approval.
    """

    def __init__(
        self,
        *,
        max_order_value: float | None = None,
        reliability_floor: float = 0.70,
        min_confidence: float = 0.60,
    ) -> None:
        settings = get_settings()
        self.max_order_value = (
            float(max_order_value) if max_order_value is not None else float(settings.autonomy_max_order_value)
        )
        self.reliability_floor = reliability_floor
        self.min_confidence = min_confidence

    def evaluate(
        self,
        action: dict[str, Any],
        *,
        confidence: float | None = None,
    ) -> PolicyDecision:
        reasons: list[str] = []
        cost = float(action.get("total_cost") or 0.0)
        if cost <= 0:
            qty = float(action.get("qty") or 0)
            price = float(action.get("unit_price") or 0)
            cost = qty * price
        if cost > self.max_order_value:
            reasons.append(
                f"order value {cost:.2f} exceeds autonomy max {self.max_order_value:.2f}"
            )
        reliability = action.get("reliability_score")
        if reliability is not None and float(reliability) < self.reliability_floor:
            reasons.append(
                f"supplier reliability {float(reliability):.2f} is below floor {self.reliability_floor:.2f}"
            )
        if confidence is not None and confidence < self.min_confidence:
            reasons.append(
                f"confidence {confidence:.2f} is below envelope {self.min_confidence:.2f}"
            )
        requires = bool(reasons)
        return PolicyDecision(autonomous=not requires, requires_approval=requires, reasons=reasons)


def default_policy() -> AutonomyPolicy:
    return AutonomyPolicy()
