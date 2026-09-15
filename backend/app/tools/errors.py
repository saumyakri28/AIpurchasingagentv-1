"""Structured tool errors. Constraint refusals are data, not prompt text."""

from __future__ import annotations

from typing import Any

from app.domain.constraints import ConstraintEngine, ValidationReport


class ToolNotFound(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown tool {name!r}")
        self.name = name


class EntityNotFound(Exception):
    def __init__(self, entity: str, key: str) -> None:
        super().__init__(f"{entity} {key!r} not found")
        self.entity = entity
        self.key = key


class ConstraintRefused(Exception):
    """Write tool blocked by ConstraintEngine. The LLM cannot override this."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__("constraint_violation")
        self.report = report

    def as_dict(self) -> dict[str, Any]:
        engine = ConstraintEngine()
        binding = engine.binding_constraint(self.report)
        return {
            "ok": False,
            "error": "constraint_violation",
            "passed": False,
            "blocking_violations": [r.model_dump(mode="json") for r in self.report.blocking_violations],
            "warnings": [r.model_dump(mode="json") for r in self.report.warnings],
            "results": [r.model_dump(mode="json") for r in self.report.results],
            "suggested_max_feasible_qty": self.report.suggested_max_feasible_qty,
            "binding_constraint": binding.model_dump(mode="json") if binding else None,
        }
