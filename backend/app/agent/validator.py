"""Pre-validate → execute → post-verify + reconcile.

Write actions never skip this loop. Implemented in Prompt 4.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ExpectedOutcome, VerificationReport
from app.domain.constraints import ValidationReport


def pre_validate(proposed_action: dict[str, Any]) -> ValidationReport:
    """Would this action violate any invariant?"""
    raise NotImplementedError


def post_verify(
    expected: ExpectedOutcome,
    *,
    source_of_truth: dict[str, Any],
) -> VerificationReport:
    """Re-read persisted state and diff against the declared expected_outcome."""
    raise NotImplementedError


def reconcile(report: VerificationReport, context: dict[str, Any]) -> dict[str, Any]:
    """On mismatch: compensating action or escalate. Capped at 2 rounds."""
    raise NotImplementedError
