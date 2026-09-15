"""HTTP surface for tools — same handlers the LLM calls, independently demo-able."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.tools.errors import ConstraintRefused, EntityNotFound, ToolNotFound
from app.tools.registry import registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
def list_tools() -> dict[str, Any]:
    return {"tools": registry.json_schemas()}


@router.post("/{tool_name}")
def invoke_tool(tool_name: str, body: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> Any:
    try:
        result = registry.call(tool_name, body or {}, db=db)
    except ToolNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConstraintRefused as exc:
        raise HTTPException(status_code=409, detail=exc.as_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(result, dict) and result.get("error") == "constraint_violation":
        raise HTTPException(status_code=409, detail=result)
    return result
