"""Human approval queue. Implemented in Prompt 3 / 6."""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("")
def list_approvals() -> list[dict[str, str]]:
    return []


@router.post("/{approval_id}/approve")
def approve(approval_id: str) -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Approval flow lands in Prompt 6")


@router.post("/{approval_id}/reject")
def reject(approval_id: str) -> dict[str, str]:
    raise HTTPException(status_code=501, detail="Approval flow lands in Prompt 6")
