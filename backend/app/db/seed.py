"""Deterministic world seeder.

Usage:
    python -m app.db.seed --world base
    python -m app.db.seed --world supplier_shortfall --db-url sqlite:///./purchasing_agent.db
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.clock import (
    DEFAULT_RANDOM_SEED,
    FORECAST_HORIZON_DAYS,
    FROZEN_NOW,
    FROZEN_TODAY,
    HISTORY_DAYS,
)
from app.db.engine import Base, get_engine
from app.db.models import (  # noqa: F401 — register metadata
    AgentAction,
    ApprovalRequest,
    Budget,
    DecisionTrace,
    EventLog,
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

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

_SKIP_KEYS = {"include", "world", "as_of", "random_seed", "trade_offs", "notes"}


@dataclass
class SeedReport:
    world: str
    as_of: date
    random_seed: int
    products: int = 0
    nodes: int = 0
    suppliers: int = 0
    sales_rows: int = 0
    forecast_rows: int = 0
    purchase_orders: int = 0
    recommendations: int = 0
    extra: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"seeded world={self.world} as_of={self.as_of.isoformat()} "
            f"seed={self.random_seed} products={self.products} "
            f"sales={self.sales_rows} forecasts={self.forecast_rows} "
            f"pos={self.purchase_orders} recs={self.recommendations}"
        )


def fixtures_dir() -> Path:
    return FIXTURES_DIR


def list_worlds() -> list[str]:
    names: list[str] = []
    for path in sorted(FIXTURES_DIR.glob("*.yaml")):
        stem = path.stem
        if stem.endswith("_world"):
            names.append(stem[: -len("_world")])
        else:
            names.append(stem)
    return names


def resolve_world_path(world: str) -> Path:
    candidates = [
        FIXTURES_DIR / f"{world}.yaml",
        FIXTURES_DIR / f"{world}_world.yaml",
    ]
    for path in candidates:
        if path.exists():
            return path
    known = ", ".join(list_worlds()) or "(none)"
    raise FileNotFoundError(f"Unknown world {world!r}. Known: {known}")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Fixture {path} must be a mapping")
    return data


def _merge_by_identity(base_list: list[dict], overlay_list: list[dict]) -> list[dict]:
    """Replace or append dict rows keyed by id, or (product_id, node_id), or (supplier_id, product_id)."""

    def key_of(row: dict) -> tuple:
        if "id" in row:
            return ("id", row["id"])
        if "supplier_id" in row and "product_id" in row and "node_id" not in row:
            return ("sp", row["supplier_id"], row["product_id"])
        if "product_id" in row and "node_id" in row:
            extra = row.get("date")
            return ("pn", row["product_id"], row["node_id"], extra)
        raise ValueError(f"Cannot identity-merge row without id: {row!r}")

    merged = {key_of(row): deepcopy(row) for row in base_list}
    for row in overlay_list:
        merged[key_of(row)] = deepcopy(row)
    return list(merged.values())


def merge_world(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in _SKIP_KEYS and key not in {"as_of", "random_seed", "world", "trade_offs"}:
            continue
        if key in {"as_of", "random_seed", "world", "trade_offs", "notes"}:
            result[key] = deepcopy(value)
            continue
        if isinstance(value, list) and value and isinstance(value[0], dict):
            result[key] = _merge_by_identity(result.get(key) or [], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_world_fixture(world: str, *, _stack: tuple[str, ...] = ()) -> dict[str, Any]:
    if world in _stack:
        raise ValueError(f"Cyclic fixture include: {' -> '.join(_stack + (world,))}")
    path = resolve_world_path(world)
    raw = _load_yaml(path)
    include = raw.get("include")
    if include:
        parent = load_world_fixture(str(include), _stack=_stack + (world,))
        return merge_world(parent, raw)
    return raw


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_datetime(value: Any, default: datetime) -> datetime:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, 8, 0, 0)
    text = str(value)
    if "T" in text:
        return datetime.fromisoformat(text)
    d = date.fromisoformat(text[:10])
    return datetime(d.year, d.month, d.day, 8, 0, 0)


def _pattern_rng(world_seed: int, product_id: str, node_id: str) -> random.Random:
    digest = hashlib.sha256(f"{world_seed}:{product_id}:{node_id}".encode()).digest()
    seed = int.from_bytes(digest[:8], "big") % (2**31)
    return random.Random(seed)


def expand_sales_history(
    pattern: dict[str, Any],
    *,
    today: date,
    world_seed: int,
    history_days: int = HISTORY_DAYS,
) -> list[SalesHistory]:
    product_id = pattern["product_id"]
    node_id = pattern["node_id"]
    kind = pattern.get("kind", "stable")
    mean = float(pattern["mean"])
    std = float(pattern.get("std", 2.0))
    rng = _pattern_rng(world_seed, product_id, node_id)
    spike_mean = float(pattern.get("spike_mean", mean * 2))
    spike_days = int(pattern.get("spike_days", 14))
    promo_offset = int(pattern.get("promo_day_offset", 7))
    promo_units = int(pattern.get("promo_units", 0))
    overrides = {
        int(item["offset_days"]): int(item["units_sold"])
        for item in pattern.get("overrides") or []
    }

    rows: list[SalesHistory] = []
    for ago in range(history_days, 0, -1):
        day = today - timedelta(days=ago)
        offset = -ago
        if offset in overrides:
            units = max(0, overrides[offset])
        elif kind == "promo_anomaly" and ago == promo_offset:
            units = max(0, promo_units)
        else:
            local_mean = mean
            if kind == "genuine_spike" and ago <= spike_days:
                local_mean = spike_mean
            units = max(0, int(round(rng.gauss(local_mean, std))))
        rows.append(
            SalesHistory(
                product_id=product_id,
                node_id=node_id,
                date=day,
                units_sold=units,
            )
        )
    return rows


def expand_forecast(
    pattern: dict[str, Any],
    *,
    today: date,
    now: datetime,
    horizon_days: int = FORECAST_HORIZON_DAYS,
) -> list[Forecast]:
    product_id = pattern["product_id"]
    node_id = pattern["node_id"]
    daily = float(pattern["daily_units"])
    spread = float(pattern.get("confidence_spread", max(1.0, daily * 0.2)))
    model_version = str(pattern.get("model_version", "fcst-v3.2"))
    generated_at = _as_datetime(pattern.get("generated_at"), now - timedelta(days=1))
    rows: list[Forecast] = []
    for ahead in range(horizon_days):
        day = today + timedelta(days=ahead)
        rows.append(
            Forecast(
                product_id=product_id,
                node_id=node_id,
                date=day,
                forecast_units=daily,
                confidence_low=max(0.0, daily - spread),
                confidence_high=daily + spread,
                model_version=model_version,
                generated_at=generated_at,
            )
        )
    return rows


def _add_all(session: Session, rows: list[Any]) -> None:
    session.add_all(rows)


def seed_into_session(session: Session, data: dict[str, Any], *, world_name: str) -> SeedReport:
    today = _as_date(data.get("as_of") or FROZEN_TODAY)
    now = datetime(today.year, today.month, today.day, FROZEN_NOW.hour, FROZEN_NOW.minute, 0)
    world_seed = int(data.get("random_seed") or DEFAULT_RANDOM_SEED)
    report = SeedReport(world=world_name, as_of=today, random_seed=world_seed)

    nodes = [Node(**{k: n[k] for k in ("id", "name", "storage_capacity_m3", "receiving_capacity_units_per_day")}) for n in data.get("nodes") or []]
    _add_all(session, nodes)
    report.nodes = len(nodes)

    products = [
        Product(
            **{
                k: p[k]
                for k in (
                    "id",
                    "sku",
                    "name",
                    "category",
                    "unit_cost",
                    "units_per_case",
                    "volume_per_unit_m3",
                    "shelf_life_days",
                    "abc_class",
                )
            }
        )
        for p in data.get("products") or []
    ]
    _add_all(session, products)
    report.products = len(products)

    suppliers = []
    for s in data.get("suppliers") or []:
        suppliers.append(
            Supplier(
                id=s["id"],
                name=s["name"],
                active=bool(s.get("active", True)),
                payment_terms_days=int(s.get("payment_terms_days", 30)),
                reliability_score=float(s["reliability_score"]),
                avg_lead_time_days=float(s["avg_lead_time_days"]),
                lead_time_std_days=float(s["lead_time_std_days"]),
                fill_rate_pct=float(s["fill_rate_pct"]),
                on_time_pct=float(s["on_time_pct"]),
                api_behaviour=str(s.get("api_behaviour", "full_accept")),
                api_behaviour_params=s.get("api_behaviour_params"),
            )
        )
    _add_all(session, suppliers)
    report.suppliers = len(suppliers)
    session.flush()

    links = [
        SupplierProduct(
            supplier_id=sp["supplier_id"],
            product_id=sp["product_id"],
            unit_price=float(sp["unit_price"]),
            moq_units=int(sp.get("moq_units", 1)),
            order_multiple_units=int(sp.get("order_multiple_units", 1)),
            lead_time_days=int(sp["lead_time_days"]),
            is_primary=bool(sp.get("is_primary", False)),
            max_units_per_order=sp.get("max_units_per_order"),
        )
        for sp in data.get("supplier_products") or []
    ]
    _add_all(session, links)

    inventories = [
        Inventory(
            product_id=inv["product_id"],
            node_id=inv["node_id"],
            on_hand=int(inv.get("on_hand", 0)),
            reserved=int(inv.get("reserved", 0)),
            in_transit=int(inv.get("in_transit", 0)),
            damaged=int(inv.get("damaged", 0)),
            last_counted_at=_as_datetime(inv.get("last_counted_at"), now - timedelta(days=2)),
        )
        for inv in data.get("inventory") or []
    ]
    _add_all(session, inventories)

    sales_rows: list[SalesHistory] = []
    for pattern in data.get("sales_patterns") or []:
        sales_rows.extend(expand_sales_history(pattern, today=today, world_seed=world_seed))
    _add_all(session, sales_rows)
    report.sales_rows = len(sales_rows)

    forecast_rows: list[Forecast] = []
    for pattern in data.get("forecast_patterns") or []:
        forecast_rows.extend(expand_forecast(pattern, today=today, now=now))
    _add_all(session, forecast_rows)
    report.forecast_rows = len(forecast_rows)

    budgets = [
        Budget(
            id=b["id"],
            node_id=b["node_id"],
            category=b["category"],
            period_start=_as_date(b["period_start"]),
            period_end=_as_date(b["period_end"]),
            allocated=float(b["allocated"]),
            committed=float(b.get("committed", 0)),
            spent=float(b.get("spent", 0)),
        )
        for b in data.get("budgets") or []
    ]
    _add_all(session, budgets)

    pos: list[PurchaseOrder] = []
    for po in data.get("purchase_orders") or []:
        order = PurchaseOrder(
            id=po["id"],
            supplier_id=po["supplier_id"],
            node_id=po["node_id"],
            status=po["status"],
            created_at=_as_datetime(po.get("created_at"), now - timedelta(days=4)),
            expected_delivery_date=_as_date(po["expected_delivery_date"]) if po.get("expected_delivery_date") else None,
            total_cost=float(po.get("total_cost", 0)),
            created_by=po.get("created_by", "system"),
        )
        for line in po.get("lines") or []:
            order.lines.append(
                POLine(
                    id=line["id"],
                    product_id=line["product_id"],
                    ordered_qty=int(line["ordered_qty"]),
                    confirmed_qty=int(line.get("confirmed_qty", 0)),
                    received_qty=int(line.get("received_qty", 0)),
                    unit_price=float(line["unit_price"]),
                )
            )
        pos.append(order)
    _add_all(session, pos)
    report.purchase_orders = len(pos)

    recs = [
        SystemRecommendation(
            id=r["id"],
            product_id=r["product_id"],
            node_id=r["node_id"],
            recommended_qty=int(r["recommended_qty"]),
            supplier_id=r["supplier_id"],
            reason=r["reason"],
            generated_at=_as_datetime(r.get("generated_at"), now),
        )
        for r in data.get("system_recommendations") or []
    ]
    _add_all(session, recs)
    report.recommendations = len(recs)

    session.add(
        EventLog(
            id=f"evt-seed-{world_name}",
            ts=now,
            event_type="world_seeded",
            entity_type="world",
            entity_id=world_name,
            payload={
                "as_of": today.isoformat(),
                "random_seed": world_seed,
                "trade_offs": data.get("trade_offs") or {},
            },
            trace_id=None,
        )
    )
    report.extra = {
        "inventory": len(inventories),
        "supplier_products": len(links),
        "budgets": len(budgets),
    }
    return report


def reset_schema(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed_world(
    world: str,
    *,
    reset: bool = True,
    db_url: str | None = None,
    engine: Engine | None = None,
) -> SeedReport:
    """Reset the database and load a named YAML fixture world."""
    data = load_world_fixture(world)
    eng = engine or get_engine(db_url)
    if reset:
        reset_schema(eng)
    else:
        Base.metadata.create_all(eng)
    SessionLocal = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        report = seed_into_session(session, data, world_name=world)
        session.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset and seed a fixture world.")
    parser.add_argument("--world", default="base", help="Fixture world name (default: base)")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Load fixtures without dropping existing tables.",
    )
    parser.add_argument("--db-url", default=None, help="Override DB_URL / settings db_url")
    parser.add_argument("--list", action="store_true", help="List available worlds and exit")
    args = parser.parse_args(argv)
    if args.list:
        for name in list_worlds():
            print(name)
        return 0
    report = seed_world(args.world, reset=not args.no_reset, db_url=args.db_url)
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
