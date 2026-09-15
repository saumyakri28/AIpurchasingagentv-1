"""Pydantic input schemas for every tool (LLM JSON schema source of truth)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RecommendationId(BaseModel):
    recommendation_id: str


class SkuArg(BaseModel):
    sku: str


class SkuNode(BaseModel):
    sku: str
    node: str


class DemandStatsArgs(BaseModel):
    sku: str
    node: str
    window_days: int = 42


class ForecastArgs(BaseModel):
    sku: str
    node: str
    horizon_days: int = 28


class SalesHistoryArgs(BaseModel):
    sku: str
    node: str
    days: int = 120


class OpenPOArgs(BaseModel):
    sku: str | None = None
    node: str | None = None
    supplier: str | None = None


class SupplierTermsArgs(BaseModel):
    supplier_id: str
    sku: str


class SupplierIdArg(BaseModel):
    supplier_id: str


class BudgetArgs(BaseModel):
    node: str
    category: str
    period: str = ""


class NodeArg(BaseModel):
    node: str


class ReplenishmentPlanArgs(BaseModel):
    sku: str
    node: str
    supplier_id: str


class ValidateActionArgs(BaseModel):
    sku: str | None = None
    node: str | None = None
    supplier_id: str | None = None
    qty: int | None = None
    proposed_action: dict[str, Any] | None = None


class POLineInput(BaseModel):
    sku: str
    qty: int
    unit_price: float | None = None


class CreatePOArgs(BaseModel):
    supplier_id: str
    node: str
    lines: list[POLineInput]
    expected_delivery_date: str
    justification: str
    idempotency_key: str
    confidence: float | None = None


class LineChange(BaseModel):
    line_id: str
    ordered_qty: int


class ModifyPOArgs(BaseModel):
    po_id: str
    line_changes: list[LineChange]
    justification: str
    idempotency_key: str
    confidence: float | None = None


class SplitPOArgs(BaseModel):
    po_id: str
    remainder_supplier_id: str
    qty: int
    justification: str
    idempotency_key: str
    confidence: float | None = None


class CancelLineArgs(BaseModel):
    po_id: str
    line_id: str
    justification: str
    idempotency_key: str


class RequestApprovalArgs(BaseModel):
    action_payload: dict[str, Any]
    reason: str
    urgency: str = "normal"
    options_considered: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str


class EscalateArgs(BaseModel):
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)
    suggested_options: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str


class LogDecisionArgs(BaseModel):
    decision_payload: dict[str, Any]
    idempotency_key: str
