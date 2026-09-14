"""Agent run entry points. Full handlers land in Prompt 5."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/run")
def run_agent() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Agent loop lands in Prompt 4")


@router.post("/run/recommendation-review")
def run_recommendation_review() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 1 lands in Prompt 5")


@router.post("/run/supplier-shortfall")
def run_supplier_shortfall() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 2 lands in Prompt 5")


@router.post("/run/demand-change")
def run_demand_change() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 3 lands in Prompt 5")


@router.post("/run/constrained-buy")
def run_constrained_buy() -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Scenario 4 lands in Prompt 5")
