"""Autonomy envelope. Anything outside it goes to human approval.

Thresholds are configuration, not prompt text. Implemented in Prompt 3.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PolicyDecision(BaseModel):
    autonomous: bool
    requires_approval: bool
    reasons: list[str]


class AutonomyPolicy:
    """Value, confidence, constraint-breach, and supplier-reliability gates."""

    def evaluate(self, action: dict[str, Any], *, confidence: float | None = None) -> PolicyDecision:
        raise NotImplementedError
