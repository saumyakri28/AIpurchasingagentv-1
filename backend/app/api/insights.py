"""One-click insights used by the buyer console."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.scenarios.catalogue import INSIGHT_CATALOGUE
from app.scenarios.insights import (
    alternate_supplier_comparison,
    po_hygiene,
    safety_stock_recommendation,
    supplier_scorecard,
)
from app.tools.errors import EntityNotFound

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
def list_insights() -> list[dict[str, Any]]:
    return INSIGHT_CATALOGUE


@router.get("/po-hygiene")
def open_po_hygiene(db: Session = Depends(get_db)) -> dict[str, Any]:
    return po_hygiene(db)


@router.get("/supplier-scorecard")
def scorecard(db: Session = Depends(get_db)) -> dict[str, Any]:
    return supplier_scorecard(db)


@router.get("/alternate-suppliers")
def alternates(sku: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return alternate_supplier_comparison(db, sku=sku)
    except EntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/safety-stock")
def safety_stock(sku: str | None = None, node: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return safety_stock_recommendation(db, sku=sku, node=node)
    except EntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
