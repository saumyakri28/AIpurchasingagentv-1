"""Eval dashboard API. Implemented in Prompt 7."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/evals", tags=["evals"])


@router.get("")
def list_eval_runs() -> list[dict[str, str]]:
    return []


@router.get("/{run_id}")
def get_eval_run(run_id: str) -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Eval harness lands in Prompt 7")
