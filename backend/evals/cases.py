"""Load eval cases from YAML. One file per case, no hidden defaults that change the score."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

CASES_DIR = Path(__file__).resolve().parent / "cases"

CONSTRAINT_CODE = {
    "C1": "budget_sufficient",
    "C2": "storage_capacity_available",
    "C3": "moq_satisfied",
    "C4": "order_multiple_satisfied",
    "C5": "max_order_qty_respected",
    "C6": "supplier_active_and_sells_product",
    "C7": "lead_time_beats_stockout",
    "C8": "no_redundant_coverage_with_open_pos",
    "C9": "shelf_life_vs_cover_days",
    "C10": "receiving_capacity_per_day",
    "C11": "supplier_reliability_floor",
    "C12": "total_cover_within_max_weeks_of_supply",
}
NAME_TO_CODE = {v: k for k, v in CONSTRAINT_CODE.items()}

DIMENSIONS = (
    "decision_correctness",
    "information_sufficiency",
    "constraint_respect",
    "action_correctness",
    "validation_performed",
    "recovery",
    "explanation_quality",
)


class ExpectedAction(BaseModel):
    type: str
    target: str | None = None
    status: str | None = None


class Expected(BaseModel):
    decision_class: str | list[str]
    quantity_range: list[float] | None = None
    must_call_tools: list[str] = Field(default_factory=list)
    must_not_violate: list[str] = Field(default_factory=list)
    expected_action: ExpectedAction | None = None
    must_post_verify: bool = True
    must_escalate_if_blocked: bool = False
    recovery: bool = False
    must_reconcile: bool = False

    @field_validator("quantity_range", mode="before")
    @classmethod
    def _range(cls, value: Any) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 2:
            raise ValueError("quantity_range must be [min, max] or null")
        return [float(value[0]), float(value[1])]

    def allowed_decisions(self) -> set[str]:
        raw = self.decision_class
        if isinstance(raw, str):
            return {raw.strip().lower()}
        return {str(x).strip().lower() for x in raw}


class IntakeSpec(BaseModel):
    scenario: str
    variant: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EvalCase(BaseModel):
    id: str
    description: str
    world: str
    intake: IntakeSpec
    expected: Expected
    llm: str = "fake"
    supplier_override: dict[str, Any] | None = None
    script_key: str | None = None

    def resolved_script_key(self) -> str:
        if self.script_key:
            return self.script_key
        variant = self.intake.variant
        if variant:
            return f"{self.intake.scenario}:{variant}"
        return self.id


def _parse_llm(raw: Any) -> str:
    if raw is None:
        return "fake"
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text.startswith("fake"):
            return "fake"
        if text.startswith("real"):
            return "real"
        return text
    if isinstance(raw, dict):
        return str(raw.get("mode") or raw.get("provider") or "fake").lower()
    return "fake"


def load_case(path: Path) -> EvalCase:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a mapping")
    data["llm"] = _parse_llm(data.get("llm"))
    return EvalCase.model_validate(data)


def load_cases(suite: str = "all") -> list[EvalCase]:
    files = sorted(CASES_DIR.glob("*.yaml"))
    cases = [load_case(path) for path in files]
    wanted = suite.strip().lower()
    if wanted in {"all", "*", ""}:
        return cases
    if wanted.startswith("e") and wanted[1:].isdigit():
        padded = f"E{int(wanted[1:])}"
        return [c for c in cases if c.id.upper() == padded.upper() or c.id.upper() == wanted.upper()]
    return [c for c in cases if c.id.lower() == wanted or c.id.lower().startswith(wanted)]
