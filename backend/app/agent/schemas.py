"""Pydantic v2 schemas for decisions, expected outcomes, and traces.

Full field set lands in Prompt 4. These stubs keep imports stable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DecisionClass(str, Enum):
    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"
    INVESTIGATE_FURTHER = "investigate_further"
    ESCALATE = "escalate"


class ExpectedOutcome(BaseModel):
    """Contract the agent MUST declare before executing any write action."""

    po_status: str | None = None
    ordered_qty: int | None = None
    committed_cost: float | None = None
    budget_remaining_after: float | None = None
    storage_used_after: float | None = None
    projected_cover_days: float | None = None
    stockout_risk: str | None = None


class KeyFactor(BaseModel):
    factor: str
    evidence_value: str
    source_tool: str
    impact: str


class Alternative(BaseModel):
    option: str
    why_not: str


class Decision(BaseModel):
    """Structured output emitted at the DECIDE stage."""

    decision: DecisionClass
    final_quantity: int | None = None
    supplier_id: str | None = None
    node: str | None = None
    expected_delivery_date: str | None = None
    confidence: float = 0.0
    reasoning_summary: str = ""
    key_factors: list[KeyFactor] = Field(default_factory=list)
    constraints_considered: list[str] = Field(default_factory=list)
    alternatives_considered: list[Alternative] = Field(default_factory=list)
    expected_outcome: ExpectedOutcome = Field(default_factory=ExpectedOutcome)
    requires_human_approval: bool = False
    approval_reason: str | None = None


class VerificationDiff(BaseModel):
    field: str
    expected: Any
    actual: Any


class VerificationReport(BaseModel):
    matched: bool
    diffs: list[VerificationDiff] = Field(default_factory=list)


class DecisionTrace(BaseModel):
    """Persisted audit of one agent run: tools, computations, decision, verify."""

    id: str | None = None
    intake: dict[str, Any] = Field(default_factory=dict)
    plan: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    decision: Decision | None = None
    verification: VerificationReport | None = None
    created_at: datetime | None = None
