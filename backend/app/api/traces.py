"""Decision traces. Implemented in Prompt 4 / 6."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("")
def list_traces() -> list[dict[str, str]]:
    return []


@router.get("/{trace_id}")
def get_trace(trace_id: str) -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Trace persistence lands in Prompt 4")
