"""Seeded worlds must keep the eval trade-offs honest — no silent fixture drift."""

from __future__ import annotations

import statistics
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.clock import FORECAST_HORIZON_DAYS, FROZEN_TODAY, HISTORY_DAYS
from app.db.models import (
    OPEN_PO_STATUSES,
    Budget,
    Forecast,
    Inventory,
    Node,
    POLine,
    Product,
    PurchaseOrder,
    SalesHistory,
    Supplier,
    SupplierProduct,
    SystemRecommendation,
)
from app.db.seed import list_worlds, seed_world
from tests.conftest import open_seeded_session

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _product_by_sku(session: Session, sku: str) -> Product:
    product = session.scalar(select(Product).where(Product.sku == sku))
    assert product is not None, f"missing product {sku}"
    return product


def _inventory(session: Session, product_id: str, node_id: str) -> Inventory:
    row = session.get(Inventory, (product_id, node_id))
    assert row is not None, f"missing inventory {product_id} @ {node_id}"
    return row


def _primary_link(session: Session, product_id: str) -> SupplierProduct:
    link = session.scalar(
        select(SupplierProduct).where(
            SupplierProduct.product_id == product_id,
            SupplierProduct.is_primary.is_(True),
        )
    )
    assert link is not None, f"no primary supplier for {product_id}"
    return link


def _recommendation(session: Session, product_id: str) -> SystemRecommendation:
    rec = session.scalar(
        select(SystemRecommendation).where(SystemRecommendation.product_id == product_id)
    )
    assert rec is not None, f"no system recommendation for {product_id}"
    return rec


def _available(inv: Inventory) -> int:
    return inv.on_hand - inv.reserved - inv.damaged


def _incoming_qty(session: Session, product_id: str, node_id: str) -> int:
    total = 0
    orders = session.scalars(select(PurchaseOrder).where(PurchaseOrder.node_id == node_id)).all()
    for po in orders:
        if po.status not in OPEN_PO_STATUSES:
            continue
        for line in po.lines:
            if line.product_id != product_id:
                continue
            if po.status == "partially_confirmed" or line.confirmed_qty > 0:
                total += line.confirmed_qty
            else:
                total += line.ordered_qty
    return total


def _sales_window(session: Session, product_id: str, node_id: str, start_ago: int, end_ago: int) -> list[int]:
    """end_ago..start_ago days before today, inclusive, with start_ago >= end_ago >= 1."""
    start = FROZEN_TODAY - timedelta(days=start_ago)
    end = FROZEN_TODAY - timedelta(days=end_ago)
    rows = session.scalars(
        select(SalesHistory)
        .where(
            SalesHistory.product_id == product_id,
            SalesHistory.node_id == node_id,
            SalesHistory.date >= start,
            SalesHistory.date <= end,
        )
        .order_by(SalesHistory.date)
    ).all()
    return [r.units_sold for r in rows]


def _forecast_sum(session: Session, product_id: str, node_id: str, days: int) -> float:
    end = FROZEN_TODAY + timedelta(days=days - 1)
    total = session.scalar(
        select(func.coalesce(func.sum(Forecast.forecast_units), 0.0)).where(
            Forecast.product_id == product_id,
            Forecast.node_id == node_id,
            Forecast.date >= FROZEN_TODAY,
            Forecast.date <= end,
        )
    )
    return float(total or 0.0)


def assert_tradeoffs(session: Session) -> None:
    # 120 days of history and a forecast horizon on every stocked position.
    positions = session.scalars(select(Inventory)).all()
    assert positions, "world has no inventory"
    for inv in positions:
        sales_n = session.scalar(
            select(func.count()).where(
                SalesHistory.product_id == inv.product_id,
                SalesHistory.node_id == inv.node_id,
            )
        )
        fcst_n = session.scalar(
            select(func.count()).where(
                Forecast.product_id == inv.product_id,
                Forecast.node_id == inv.node_id,
            )
        )
        assert sales_n == HISTORY_DAYS, f"{inv.product_id}: expected {HISTORY_DAYS} sales days, got {sales_n}"
        assert fcst_n == FORECAST_HORIZON_DAYS, f"{inv.product_id}: expected {FORECAST_HORIZON_DAYS} forecast days, got {fcst_n}"

    # 1. Open PO already covers demand — 800 extra units would be over-buying.
    covered = _product_by_sku(session, "SKU-COVERED")
    rec = _recommendation(session, covered.id)
    inv = _inventory(session, covered.id, rec.node_id)
    incoming = _incoming_qty(session, covered.id, rec.node_id)
    cover = _available(inv) + incoming
    demand_28 = _forecast_sum(session, covered.id, rec.node_id, 28)
    assert rec.recommended_qty == 800
    assert incoming >= 800
    assert cover >= demand_28, f"SKU-COVERED not covered: available+incoming={cover} vs 28d forecast={demand_28}"

    # 2. MOQ 1000 exceeds true need ~320.
    moq_prod = _product_by_sku(session, "SKU-MOQ")
    primary = _primary_link(session, moq_prod.id)
    rec_moq = _recommendation(session, moq_prod.id)
    inv_moq = _inventory(session, moq_prod.id, rec_moq.node_id)
    last_28 = _sales_window(session, moq_prod.id, rec_moq.node_id, 28, 1)
    mean_28 = statistics.fmean(last_28)
    review_plus_lt = primary.lead_time_days + 7
    implied_need = mean_28 * review_plus_lt - _available(inv_moq)
    assert primary.moq_units == 1000
    assert rec_moq.recommended_qty == 320
    assert primary.moq_units > rec_moq.recommended_qty
    assert 200 <= implied_need <= 450, f"SKU-MOQ implied need drifted: {implied_need:.1f}"

    # 3. Budget remaining < cost of needed quantity.
    budget_prod = _product_by_sku(session, "SKU-BUDGET")
    rec_b = _recommendation(session, budget_prod.id)
    price = _primary_link(session, budget_prod.id).unit_price
    needed_cost = rec_b.recommended_qty * price
    budget = session.scalar(
        select(Budget).where(
            Budget.node_id == rec_b.node_id,
            Budget.category == budget_prod.category,
        )
    )
    assert budget is not None
    assert budget.remaining < needed_cost, (
        f"SKU-BUDGET remaining {budget.remaining} should be < cost {needed_cost}"
    )
    assert rec_b.recommended_qty == 400

    # 4. Storage cannot physically hold the recommended quantity.
    storage_prod = _product_by_sku(session, "SKU-STORAGE")
    rec_s = _recommendation(session, storage_prod.id)
    node = session.get(Node, rec_s.node_id)
    assert node is not None
    occupying = session.scalars(select(Inventory).where(Inventory.node_id == rec_s.node_id)).all()
    used_m3 = 0.0
    for row in occupying:
        prod = session.get(Product, row.product_id)
        assert prod is not None
        used_m3 += row.on_hand * prod.volume_per_unit_m3
    added_m3 = rec_s.recommended_qty * storage_prod.volume_per_unit_m3
    assert used_m3 + added_m3 > node.storage_capacity_m3, (
        f"SKU-STORAGE {used_m3:.2f}+{added_m3:.2f} m3 should exceed {node.storage_capacity_m3}"
    )
    assert rec_s.recommended_qty == 800

    # 5. Genuine demand spike last 14d vs prior 28d and vs forecast — not a one-off.
    spike = _product_by_sku(session, "SKU-SPIKE")
    rec_sp = _recommendation(session, spike.id)
    last14 = _sales_window(session, spike.id, rec_sp.node_id, 14, 1)
    prior28 = _sales_window(session, spike.id, rec_sp.node_id, 42, 15)
    assert len(last14) == 14 and len(prior28) == 28
    last14_mean = statistics.fmean(last14)
    prior28_mean = statistics.fmean(prior28)
    assert last14_mean > prior28_mean * 1.5, (
        f"SKU-SPIKE last14 {last14_mean:.1f} vs prior28 {prior28_mean:.1f}"
    )
    fcst_daily = _forecast_sum(session, spike.id, rec_sp.node_id, 14) / 14
    assert last14_mean > fcst_daily * 1.5
    assert max(last14) / sum(last14) < 0.20, "SKU-SPIKE should be a plateau, not a single-day spike"

    # 6. Promo / bulk-order anomaly: one day dominates the window.
    promo = _product_by_sku(session, "SKU-PROMO")
    rec_p = _recommendation(session, promo.id)
    window = _sales_window(session, promo.id, rec_p.node_id, 14, 1)
    peak = max(window)
    others = [u for u in window if u != peak] or window[:-1]
    other_mean = statistics.fmean(others)
    other_std = statistics.pstdev(others) or 1.0
    z = (peak - other_mean) / other_std
    assert z > 3, f"SKU-PROMO peak z={z:.1f} expected > 3"
    assert peak / sum(window) > 0.35, "SKU-PROMO peak should dominate the 14d window"

    # 7. Viable alternate supplier: higher price, shorter lead time.
    alt = _product_by_sku(session, "SKU-ALT")
    links = session.scalars(select(SupplierProduct).where(SupplierProduct.product_id == alt.id)).all()
    primary_alt = next(link for link in links if link.is_primary)
    cheaper_faster = [
        link
        for link in links
        if not link.is_primary
        and link.unit_price > primary_alt.unit_price
        and link.lead_time_days < primary_alt.lead_time_days
    ]
    assert cheaper_faster, "SKU-ALT needs a dearer/faster alternate"

    # 8. Unreliable supplier (buffer or re-source).
    bad = session.scalar(
        select(Supplier).where(
            Supplier.reliability_score < 0.5,
            Supplier.fill_rate_pct < 70,
        )
    )
    assert bad is not None, "expected a poor-reliability supplier"
    assert bad.id == "SUP-UNRELIABLE"
    noodles = _product_by_sku(session, "SKU-UNRELIABLE")
    noodle_primary = _primary_link(session, noodles.id)
    assert noodle_primary.supplier_id == bad.id


@pytest.mark.parametrize("world", list_worlds())
def test_every_world_preserves_tradeoffs(world: str, tmp_path: Path) -> None:
    session = open_seeded_session(tmp_path / f"{world}.db", world)
    try:
        assert_tradeoffs(session)
    finally:
        session.close()


def test_seed_is_deterministic(tmp_path: Path) -> None:
    first = open_seeded_session(tmp_path / "a.db", "base")
    second = open_seeded_session(tmp_path / "b.db", "base")
    try:
        q = (
            select(SalesHistory.product_id, SalesHistory.date, SalesHistory.units_sold)
            .order_by(SalesHistory.product_id, SalesHistory.date)
        )
        assert first.execute(q).all() == second.execute(q).all()
        recs = select(SystemRecommendation.id, SystemRecommendation.recommended_qty).order_by(
            SystemRecommendation.id
        )
        assert first.execute(recs).all() == second.execute(recs).all()
    finally:
        first.close()
        second.close()


def test_supplier_shortfall_overlay_partial_confirm(tmp_path: Path) -> None:
    session = open_seeded_session(tmp_path / "shortfall.db", "supplier_shortfall")
    try:
        po = session.get(PurchaseOrder, "PO-SHORTFALL")
        assert po is not None
        assert po.status == "partially_confirmed"
        line = session.get(POLine, "POL-SHORTFALL-1")
        assert line is not None
        assert line.ordered_qty == 500
        assert line.confirmed_qty == 250
        # Overlay must not drop the covering PO used by SKU-COVERED.
        assert session.get(PurchaseOrder, "PO-COVERED") is not None
    finally:
        session.close()


def test_base_po_shortfall_still_unconfirmed(seeded_base: Session) -> None:
    po = seeded_base.get(PurchaseOrder, "PO-SHORTFALL")
    assert po is not None
    assert po.status == "submitted"
    line = seeded_base.get(POLine, "POL-SHORTFALL-1")
    assert line is not None
    assert line.confirmed_qty == 0


def test_seed_cli_writes_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "cli.db"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.db.seed",
            "--world",
            "base",
            "--db-url",
            f"sqlite:///{db_path}",
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert db_path.exists()
    assert "seeded world=base" in result.stdout
    assert "as_of=2026-09-15" in result.stdout


def test_unknown_world_raises() -> None:
    with pytest.raises(FileNotFoundError):
        seed_world("does-not-exist", db_url="sqlite:///:memory:")
