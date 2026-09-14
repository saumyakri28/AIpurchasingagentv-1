"""Scenario catalogue and world-state summaries. Implemented in Prompt 5."""

from fastapi import APIRouter

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
def list_scenarios() -> list[dict[str, str]]:
    return [
        {"id": "recommendation-review", "title": "S1 Purchase Recommendation Review"},
        {"id": "supplier-shortfall", "title": "S2 Supplier Cannot Fulfil"},
        {"id": "demand-change", "title": "S3 Demand / Forecast Changed"},
        {"id": "constrained-buy", "title": "S4 Purchasing Constraint"},
    ]
