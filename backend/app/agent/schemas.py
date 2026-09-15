"""Pydantic v2 schemas for decisions, expected outcomes, traces, and intake."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionClass(str, Enum):
    ACCEPT = "accept"
    MODIFY = "modify"
    REJECT = "reject"
    INVESTIGATE_FURTHER = "investigate_further"
    ESCALATE = "escalate"


class FactorImpact(str, Enum):
    SUPPORTS_HIGHER = "supports_higher"
    SUPPORTS_LOWER = "supports_lower"
    BLOCKING = "blocking"


class ExpectedOutcome(BaseModel):
    """Contract the agent MUST declare before executing any write action."""

    model_config = ConfigDict(extra="ignore")

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
    impact: FactorImpact | str


class Alternative(BaseModel):
    option: str
    why_not: str


class Decision(BaseModel):
    """Structured output emitted at the DECIDE stage."""

    model_config = ConfigDict(extra="ignore")

    decision: DecisionClass
    final_quantity: int | None = None
    supplier_id: str | None = None
    node: str | None = None
    expected_delivery_date: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str = ""
    key_factors: list[KeyFactor] = Field(default_factory=list)
    constraints_considered: list[str] = Field(default_factory=list)
    alternatives_considered: list[Alternative] = Field(default_factory=list)
    expected_outcome: ExpectedOutcome = Field(default_factory=ExpectedOutcome)
    requires_human_approval: bool = False
    approval_reason: str | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def _norm_decision(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("reasoning_summary")
    @classmethod
    def _six_sentences_max(cls, value: str) -> str:
        text = value.strip()
        parts = [p for p in re.split(r"[.!?]+", text) if p.strip()]
        if len(parts) > 6:
            raise ValueError("reasoning_summary must be at most 6 sentences")
        return value


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
    scenario_type: str | None = None
    intake: dict[str, Any] = Field(default_factory=dict)
    plan: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    decision: Decision | None = None
    verification: VerificationReport | None = None
    po_id: str | None = None
    status: str = "running"
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    reconciliation_rounds: int = 0
    created_at: datetime | None = None


class IntakeType(str, Enum):
    RECOMMENDATION_REVIEW = "recommendation_review"
    SUPPLIER_SHORTFALL = "supplier_shortfall"
    DEMAND_CHANGE = "demand_change"
    BUYER_QUESTION = "buyer_question"


WRITE_DECISIONS = frozenset({DecisionClass.ACCEPT, DecisionClass.MODIFY})

CONSTRAINT_CODES = (
    "C1 budget_sufficient",
    "C2 storage_capacity_available",
    "C3 moq_satisfied",
    "C4 order_multiple_satisfied",
    "C5 max_order_qty_respected",
    "C6 supplier_active_and_sells_product",
    "C7 lead_time_beats_stockout",
    "C8 no_redundant_coverage_with_open_pos",
    "C9 shelf_life_vs_cover_days",
    "C10 receiving_capacity_per_day",
    "C11 supplier_reliability_floor",
    "C12 total_cover_within_max_weeks_of_supply",
)

EMIT_DECISION_TOOL = "emit_decision"


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from a model reply (raw or fenced)."""
    blob = (text or "").strip()
    if not blob:
        raise ValueError("empty response")
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob)
        blob = re.sub(r"\s*```$", "", blob)
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        start = blob.find("{")
        end = blob.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in response") from None
        payload = json.loads(blob[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("JSON payload is not an object")
    return payload


def decision_tool_schema() -> dict[str, Any]:
    return {
        "name": EMIT_DECISION_TOOL,
        "description": "Emit a validated Decision object. Use this instead of free-form prose when deciding.",
        "input_schema": Decision.model_json_schema(),
    }
