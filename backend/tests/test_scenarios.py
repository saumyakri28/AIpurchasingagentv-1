"""Prompt 5 — four scenario entry points, FakeLLM scripts, insights."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db.engine import get_engine
from app.db.models import ApprovalRequest, PurchaseOrder
from app.db.seed import seed_world
from app.db.session import get_db
from app.main import app
from app.scenarios.insights import po_hygiene, supplier_scorecard
from app.scenarios.runner import execute_scenario
from app.tools.read_tools import get_demand_stats
from app.tools.schemas import DemandStatsArgs
from tests.conftest import open_seeded_session


def _override_db(tmp_path, world: str):
    engine = get_engine(f"sqlite:///{tmp_path / (world + '.db')}")
    seed_world(world, engine=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _gen():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _gen
    return engine


class TestCatalogue:
    def test_four_entry_points_with_variants(self, client) -> None:
        response = client.get("/scenarios")
        assert response.status_code == 200
        body = response.json()
        ids = {row["id"] for row in body}
        assert ids == {
            "recommendation-review",
            "supplier-shortfall",
            "demand-change",
            "constrained-buy",
        }
        s1 = next(row for row in body if row["id"] == "recommendation-review")
        assert s1["endpoint"] == "/agent/run/recommendation-review"
        assert s1["world"] == "recommendation_review"
        variant_ids = {v["id"] for v in s1["variants"]}
        assert variant_ids == {"overbuy", "moq"}
        insights = client.get("/insights")
        assert insights.status_code == 200
        assert {row["id"] for row in insights.json()} >= {
            "po-hygiene",
            "supplier-scorecard",
            "alternate-suppliers",
            "safety-stock",
        }


class TestScenarioRuns:
    def test_s1_overbuy_rejects(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s1.db", "recommendation_review")
        try:
            trace = execute_scenario(
                "recommendation-review",
                db=db,
                variant_id="overbuy",
                seed=False,
            )
            assert trace.decision is not None
            assert trace.decision.decision.value == "reject"
            tools = [s.get("tool") for s in trace.steps]
            assert "compute_replenishment_plan" in tools
            assert "create_purchase_order" not in tools
        finally:
            db.close()

    def test_s1_moq_does_not_execute_blocked_1000(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s1m.db", "recommendation_review")
        try:
            trace = execute_scenario(
                "recommendation-review",
                db=db,
                variant_id="moq",
                seed=False,
            )
            assert trace.decision is not None
            assert trace.decision.decision.value == "escalate"
            tools = [s.get("tool") for s in trace.steps]
            assert "validate_action" in tools
            assert "create_purchase_order" not in tools
            decide_payloads = [
                s.get("result")
                for s in trace.steps
                if s.get("stage") == "DECIDE" and isinstance(s.get("result"), dict)
            ]
            assert any(p.get("decision") == "modify" for p in decide_payloads)
        finally:
            db.close()

    def test_s2_shortfall_sources_quickship_and_post_verifies(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s2.db", "supplier_shortfall")
        try:
            before = db.get(PurchaseOrder, "PO-SHORTFALL")
            assert before is not None
            assert before.status == "partially_confirmed"
            trace = execute_scenario("supplier-shortfall", db=db, seed=False)
            assert trace.decision is not None
            assert trace.decision.decision.value == "modify"
            assert trace.decision.supplier_id == "SUP-FAST"
            assert trace.decision.final_quantity == 80
            assert trace.po_id is not None
            new_po = db.get(PurchaseOrder, trace.po_id)
            assert new_po is not None
            assert new_po.supplier_id == "SUP-FAST"
            assert sum(line.ordered_qty for line in new_po.lines) == 80
            assert trace.verification is not None
            assert trace.verification.matched is True
            original = db.get(PurchaseOrder, "PO-SHORTFALL")
            assert original is not None
            assert original.lines[0].confirmed_qty == 250
        finally:
            db.close()

    def test_s3_promo_rejects_and_spike_investigates(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s3.db", "demand_change")
        try:
            promo_stats = get_demand_stats(
                DemandStatsArgs(sku="SKU-PROMO", node="DC-NORTH"), db=db
            )
            spike_stats = get_demand_stats(
                DemandStatsArgs(sku="SKU-SPIKE", node="DC-NORTH"), db=db
            )
            assert promo_stats["anomaly_flag"] is True
            assert promo_stats["spike_detected"] is False
            assert spike_stats["spike_detected"] is True
            assert spike_stats["anomaly_flag"] is False

            promo = execute_scenario("demand-change", db=db, variant_id="promo", seed=False)
            assert promo.decision is not None
            assert promo.decision.decision.value == "reject"
            tools = [s.get("tool") for s in promo.steps]
            assert "get_demand_stats" in tools
            assert "create_purchase_order" not in tools

            spike = execute_scenario("demand-change", db=db, variant_id="spike", seed=False)
            assert spike.decision is not None
            assert spike.decision.decision.value == "investigate_further"
        finally:
            db.close()

    def test_s4_budget_never_executes_blocked_qty(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s4.db", "constrained_buy")
        try:
            n_before = db.scalar(select(func.count()).select_from(PurchaseOrder))
            trace = execute_scenario("constrained-buy", db=db, variant_id="budget", seed=False)
            assert trace.decision is not None
            assert trace.decision.decision.value == "escalate"
            tools = [s.get("tool") for s in trace.steps]
            assert "validate_action" in tools
            assert "create_purchase_order" not in tools
            n_after = db.scalar(select(func.count()).select_from(PurchaseOrder))
            assert n_after == n_before
            n_apr = db.scalar(select(func.count()).select_from(ApprovalRequest))
            assert n_apr >= 1
        finally:
            db.close()

    def test_s4_storage_modifies_to_suggested_max(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "s4s.db", "constrained_buy")
        try:
            trace = execute_scenario("constrained-buy", db=db, variant_id="storage", seed=False)
            assert trace.decision is not None
            assert trace.decision.decision.value == "modify"
            assert trace.decision.final_quantity == 96
            assert trace.po_id is not None
            po = db.get(PurchaseOrder, trace.po_id)
            assert po is not None
            assert sum(line.ordered_qty for line in po.lines) == 96
            assert po.node_id == "DC-SOUTH"
        finally:
            db.close()


class TestInsights:
    def test_hygiene_flags_ghost_po(self, tmp_path) -> None:
        db = open_seeded_session(tmp_path / "hyg.db", "base")
        try:
            report = po_hygiene(db)
            ids = {row["po_id"] for row in report["purchase_orders"]}
            assert "PO-GHOST" in ids
            ghost = next(row for row in report["purchase_orders"] if row["po_id"] == "PO-GHOST")
            assert "ghost" in ghost["flags"]
            assert "overdue" in ghost["flags"]
            assert ghost["overdue_days"] >= 10
            card = supplier_scorecard(db)
            assert any(s["supplier_id"] == "SUP-UNRELIABLE" for s in card["below_floor"])
        finally:
            db.close()


class TestScenarioHTTP:
    def test_post_s1_and_insights(self, client, tmp_path) -> None:
        _override_db(tmp_path, "recommendation_review")
        try:
            response = client.post(
                "/agent/run/recommendation-review",
                json={"variant": "overbuy", "seed": False},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["decision"]["decision"] == "reject"
            hyg = client.get("/insights/po-hygiene")
            assert hyg.status_code == 200
            assert any(row["po_id"] == "PO-GHOST" for row in hyg.json()["purchase_orders"])
            alts = client.get("/insights/alternate-suppliers", params={"sku": "SKU-ALT"})
            assert alts.status_code == 200
            suppliers = alts.json()["skus"][0]["suppliers"]
            assert {s["supplier_id"] for s in suppliers} >= {"SUP-RELIABLE", "SUP-FAST"}
            ss = client.get("/insights/safety-stock", params={"sku": "SKU-HEALTHY", "node": "DC-NORTH"})
            assert ss.status_code == 200
            assert ss.json()["recommendations"][0]["safety_stock"] > 0
        finally:
            app.dependency_overrides.clear()

    def test_post_s2_endpoint(self, client, tmp_path) -> None:
        _override_db(tmp_path, "supplier_shortfall")
        try:
            response = client.post(
                "/agent/run/supplier-shortfall",
                json={"po_id": "PO-SHORTFALL", "confirmed_qty": 250, "seed": False},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["decision"]["decision"] == "modify"
            assert body["decision"]["supplier_id"] == "SUP-FAST"
            assert body["verification"]["matched"] is True
        finally:
            app.dependency_overrides.clear()
