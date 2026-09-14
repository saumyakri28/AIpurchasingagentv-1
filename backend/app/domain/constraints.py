"""Constraint / invariant engine.

The LLM never decides whether a constraint is satisfied. Every write
action is evaluated here. Implemented in Prompt 2.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConstraintStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


class ConstraintResult(BaseModel):
    name: str
    status: ConstraintStatus
    actual: float | str | None = None
    limit: float | str | None = None
    slack: float | None = None
    message: str = ""


class ValidationReport(BaseModel):
    passed: bool
    results: list[ConstraintResult] = Field(default_factory=list)
    blocking_violations: list[ConstraintResult] = Field(default_factory=list)
    warnings: list[ConstraintResult] = Field(default_factory=list)
    suggested_max_feasible_qty: int | None = None


class ConstraintEngine:
    """Individually named, individually reportable invariant checks (C1–C12)."""

    def evaluate(self, proposed_action: dict[str, Any]) -> ValidationReport:
        raise NotImplementedError

    def binding_constraint(self, report: ValidationReport) -> ConstraintResult | None:
        """The single constraint that is the limiting factor."""
        raise NotImplementedError
