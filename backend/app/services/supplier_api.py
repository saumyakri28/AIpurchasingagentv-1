"""MOCK external supplier system — deliberately imperfect.

Configurable per-supplier behaviours (driven by scenario fixtures, not
randomness, so evals are reproducible):

  full_accept, partial_accept(ratio), reject_moq_violation,
  accept_with_longer_lead_time, timeout, confirm_then_revise

Implemented in Prompt 3.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class SupplierBehaviour(str, Enum):
    FULL_ACCEPT = "full_accept"
    PARTIAL_ACCEPT = "partial_accept"
    REJECT_MOQ_VIOLATION = "reject_moq_violation"
    ACCEPT_WITH_LONGER_LEAD_TIME = "accept_with_longer_lead_time"
    TIMEOUT = "timeout"
    CONFIRM_THEN_REVISE = "confirm_then_revise"


class SupplierSubmitResult(BaseModel):
    accepted: bool
    confirmed_qty: int | None = None
    confirmed_lead_time_days: int | None = None
    behaviour: SupplierBehaviour
    message: str = ""


class MockSupplierAPI:
    """Fixture-driven supplier gateway. Never random in eval mode."""

    def __init__(self, behaviours: dict[str, dict[str, Any]] | None = None) -> None:
        self.behaviours = behaviours or {}

    def submit_order(self, supplier_id: str, payload: dict[str, Any]) -> SupplierSubmitResult:
        raise NotImplementedError
