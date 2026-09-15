"""Tool layer: read tools, write-tool refusal, policy, idempotency, supplier mock."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models import ApprovalRequest, Budget, Inventory, PurchaseOrder
from app.domain.policy import AutonomyPolicy
from app.services.supplier_api import MockSupplierAPI, SupplierBehaviour, supplier_api
from app.tools.errors import ConstraintRefused
from app.tools.read_tools import (
    compute_replenishment_plan,
    find_alternate_suppliers,
    get_demand_stats,
    get_product,
    get_recommendation,
    validate_action,
)
from app.tools.registry import registry
from app.tools.schemas import (
    CreatePOArgs,
    DemandStatsArgs,
    LineChange,
    ModifyPOArgs,
    POLineInput,
    RecommendationId,
    ReplenishmentPlanArgs,
    SkuArg,
    SplitPOArgs,
    ValidateActionArgs,
)
from app.tools.write_tools import create_purchase_order, modify_purchase_order, split_purchase_order


@pytest.fixture
def restore_supplier_behaviours():
    original = dict(supplier_api.behaviours)
    yield
    supplier_api.behaviours = original


class TestReadTools:
    def test_get_product(self, seeded_base) -> None:
        product = get_product(SkuArg(sku="SKU-COVERED"), db=seeded_base)
        assert product["name"] == "Still Water 500ml"
        assert product["category"] == "beverages"

    def test_get_recommendation_overbuy(self, seeded_base) -> None:
        rec = get_recommendation(RecommendationId(recommendation_id="REC-OVERBUY"), db=seeded_base)
        assert rec["recommended_qty"] == 800
        assert rec["sku"] == "SKU-COVERED"

    def test_demand_stats_spike_vs_promo(self, seeded_base) -> None:
        spike = get_demand_stats(DemandStatsArgs(sku="SKU-SPIKE", node="DC-NORTH", window_days=42), db=seeded_base)
        promo = get_demand_stats(DemandStatsArgs(sku="SKU-PROMO", node="DC-NORTH", window_days=42), db=seeded_base)
        assert spike["spike_detected"] is True
        assert spike["anomaly_flag"] is False
        assert promo["anomaly_flag"] is True
        assert promo["spike_detected"] is False

    def test_alternates_ranked(self, seeded_base) -> None:
        result = find_alternate_suppliers(SkuArg(sku="SKU-ALT"), db=seeded_base)
        ids = [row["supplier_id"] for row in result["suppliers"]]
        assert "SUP-RELIABLE" in ids and "SUP-FAST" in ids
        fast = next(row for row in result["suppliers"] if row["supplier_id"] == "SUP-FAST")
        primary = next(row for row in result["suppliers"] if row["is_primary"])
        assert fast["unit_price"] > primary["unit_price"]
        assert fast["lead_time_days"] < primary["lead_time_days"]

    def test_replenishment_plan_moq_rounds_up(self, seeded_base) -> None:
        plan = compute_replenishment_plan(
            ReplenishmentPlanArgs(sku="SKU-MOQ", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            db=seeded_base,
        )
        assert plan["rounded_qty"] == 1000
        assert plan["moq_units"] == 1000
        assert plan["net_requirement_raw"] < 1000

    def test_validate_action_refuses_overbuy(self, seeded_base) -> None:
        report = validate_action(
            ValidateActionArgs(sku="SKU-COVERED", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=800),
            db=seeded_base,
        )
        assert report["passed"] is False
        names = {v["name"] for v in report["blocking_violations"]}
        assert "no_redundant_coverage_with_open_pos" in names


class TestWriteTools:
    def test_constraint_refusal_creates_no_po(self, seeded_base) -> None:
        before = seeded_base.scalar(select(func.count()).select_from(PurchaseOrder))
        with pytest.raises(ConstraintRefused) as exc:
            create_purchase_order(
                CreatePOArgs(
                    supplier_id="SUP-RELIABLE",
                    node="DC-NORTH",
                    lines=[POLineInput(sku="SKU-COVERED", qty=800)],
                    expected_delivery_date="2026-09-22",
                    justification="engine said so",
                    idempotency_key="k-overbuy",
                ),
                db=seeded_base,
            )
        seeded_base.rollback()
        after = seeded_base.scalar(select(func.count()).select_from(PurchaseOrder))
        assert after == before
        assert exc.value.as_dict()["suggested_max_feasible_qty"] == 0

    def test_policy_parks_pending_approval_without_budget(self, seeded_base) -> None:
        inv = seeded_base.get(Inventory, ("prod-healthy", "DC-NORTH"))
        assert inv is not None
        inv.on_hand = 100
        inv.reserved = 0
        budget = seeded_base.scalar(
            select(Budget).where(Budget.node_id == "DC-NORTH", Budget.category == "dry_goods")
        )
        assert budget is not None
        committed_before = budget.committed
        result = create_purchase_order(
            CreatePOArgs(
                supplier_id="SUP-RELIABLE",
                node="DC-NORTH",
                lines=[POLineInput(sku="SKU-HEALTHY", qty=20)],
                expected_delivery_date="2026-09-22",
                justification="need flour",
                idempotency_key="k-policy",
            ),
            db=seeded_base,
            policy=AutonomyPolicy(max_order_value=10),
        )
        seeded_base.commit()
        assert result["requires_human_approval"] is True
        assert result["status"] == "pending_approval"
        seeded_base.refresh(budget)
        assert budget.committed == committed_before
        approvals = seeded_base.scalars(select(ApprovalRequest)).all()
        assert any("autonomy max" in a.reason for a in approvals)

    def test_autonomous_submit_commits_budget_and_is_idempotent(self, seeded_base) -> None:
        inv = seeded_base.get(Inventory, ("prod-healthy", "DC-NORTH"))
        assert inv is not None
        inv.on_hand = 100
        inv.reserved = 0
        budget = seeded_base.scalar(
            select(Budget).where(Budget.node_id == "DC-NORTH", Budget.category == "dry_goods")
        )
        assert budget is not None
        before = budget.committed
        args = CreatePOArgs(
            supplier_id="SUP-RELIABLE",
            node="DC-NORTH",
            lines=[POLineInput(sku="SKU-HEALTHY", qty=20)],
            expected_delivery_date="2026-09-22",
            justification="replenish flour",
            idempotency_key="k-idem",
        )
        first = create_purchase_order(args, db=seeded_base)
        seeded_base.commit()
        assert first["ok"] is True
        assert first["status"] in {"submitted", "confirmed"}
        seeded_base.refresh(budget)
        assert budget.committed == pytest.approx(before + 20 * 1.25)
        po_count = seeded_base.scalar(select(func.count()).select_from(PurchaseOrder))
        second = create_purchase_order(args, db=seeded_base)
        seeded_base.commit()
        assert second.get("idempotent_replay") is True
        assert second["po"]["id"] == first["po"]["id"]
        assert seeded_base.scalar(select(func.count()).select_from(PurchaseOrder)) == po_count

    def test_partial_accept_from_supplier_api(self, seeded_base, restore_supplier_behaviours) -> None:
        inv = seeded_base.get(Inventory, ("prod-healthy", "DC-NORTH"))
        assert inv is not None
        inv.on_hand = 100
        inv.reserved = 0
        supplier_api.behaviours["SUP-RELIABLE"] = {"behaviour": "partial_accept", "params": {"ratio": 0.5}}
        result = create_purchase_order(
            CreatePOArgs(
                supplier_id="SUP-RELIABLE",
                node="DC-NORTH",
                lines=[POLineInput(sku="SKU-HEALTHY", qty=20)],
                expected_delivery_date="2026-09-22",
                justification="partial path",
                idempotency_key="k-partial",
            ),
            db=seeded_base,
        )
        seeded_base.commit()
        assert result["status"] == "partially_confirmed"
        assert result["po"]["lines"][0]["confirmed_qty"] == 10
        assert result["supplier"]["behaviour"] == "partial_accept"


class TestRegistryAndHTTP:
    def test_json_schemas_cover_read_and_write(self) -> None:
        names = {spec["name"] for spec in registry.json_schemas()}
        assert "compute_replenishment_plan" in names
        assert "validate_action" in names
        assert "create_purchase_order" in names
        write = [s for s in registry.json_schemas() if s["is_write"]]
        assert {s["name"] for s in write} >= {
            "create_purchase_order",
            "modify_purchase_order",
            "split_purchase_order",
            "cancel_purchase_order_line",
            "request_human_approval",
            "escalate",
            "log_decision",
        }

    def test_rest_get_product(self, client, tmp_path, monkeypatch) -> None:
        # Default client uses the app DB file; seed it via tool invoke against the test override.
        from sqlalchemy.orm import sessionmaker

        from app.db.engine import get_engine
        from app.db.seed import seed_world
        from app.db.session import get_db
        from app.main import app

        engine = get_engine(f"sqlite:///{tmp_path / 'http.db'}")
        seed_world("base", engine=engine)
        SessionLocal = sessionmaker(bind=engine)

        def _override():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override
        try:
            listed = client.get("/tools")
            assert listed.status_code == 200
            assert any(t["name"] == "get_product" for t in listed.json()["tools"])
            response = client.post("/tools/get_product", json={"sku": "SKU-COVERED"})
            assert response.status_code == 200
            assert response.json()["sku"] == "SKU-COVERED"
            blocked = client.post(
                "/tools/validate_action",
                json={"sku": "SKU-COVERED", "node": "DC-NORTH", "supplier_id": "SUP-RELIABLE", "qty": 800},
            )
            assert blocked.status_code == 200
            assert blocked.json()["passed"] is False
        finally:
            app.dependency_overrides.clear()


class TestSupplierAPIStandalone:
    def test_behaviours_are_deterministic(self) -> None:
        api = MockSupplierAPI(
            {
                "S1": {"behaviour": "full_accept"},
                "S2": {"behaviour": "partial_accept", "params": {"ratio": 0.5}},
                "S3": {"behaviour": "timeout"},
                "S4": {"behaviour": "reject_moq_violation", "params": {"min_qty": 1000}},
                "S5": {"behaviour": "accept_with_longer_lead_time", "params": {"extra_lead_time_days": 5}},
                "S6": {"behaviour": "confirm_then_revise", "params": {"extra_lead_time_days": 9}},
            }
        )
        payload = {"lines": [{"ordered_qty": 200}], "ordered_qty": 200, "lead_time_days": 7}
        assert api.submit_order("S1", payload).confirmed_qty == 200
        assert api.submit_order("S2", payload).confirmed_qty == 100
        timed = api.submit_order("S3", payload)
        assert timed.timed_out is True and timed.accepted is False
        rejected = api.submit_order("S4", payload)
        assert rejected.accepted is False
        longer = api.submit_order("S5", payload)
        assert longer.confirmed_lead_time_days == 12
        revised = api.submit_order("S6", payload)
        assert revised.revised_after_confirm is True
        assert revised.confirmed_lead_time_days == 16
        assert revised.behaviour is SupplierBehaviour.CONFIRM_THEN_REVISE


class TestWriteToolRefusals:
    """Every write that can create stock must refuse through ConstraintEngine."""

    def test_modify_increase_refuses_redundant_cover(self, seeded_base) -> None:
        po = seeded_base.get(PurchaseOrder, "PO-COVERED")
        assert po is not None
        before = po.lines[0].ordered_qty
        with pytest.raises(ConstraintRefused):
            modify_purchase_order(
                ModifyPOArgs(
                    po_id="PO-COVERED",
                    line_changes=[LineChange(line_id=po.lines[0].id, ordered_qty=before + 800)],
                    justification="engine said more water",
                    idempotency_key="k-mod-overbuy",
                ),
                db=seeded_base,
            )
        seeded_base.rollback()
        seeded_base.refresh(po)
        assert po.lines[0].ordered_qty == before

    def test_split_refuses_when_remainder_fails_constraints(self, seeded_base) -> None:
        with pytest.raises(ConstraintRefused):
            split_purchase_order(
                SplitPOArgs(
                    po_id="PO-COVERED",
                    remainder_supplier_id="SUP-FAST",
                    qty=200,
                    justification="split the covered water",
                    idempotency_key="k-split-overbuy",
                ),
                db=seeded_base,
            )
        seeded_base.rollback()
        n_agent = seeded_base.scalars(select(PurchaseOrder).where(PurchaseOrder.created_by == "agent")).all()
        assert n_agent == []

    def test_create_budget_block_does_not_commit(self, seeded_base) -> None:
        before = seeded_base.scalar(select(func.count()).select_from(PurchaseOrder))
        with pytest.raises(ConstraintRefused) as exc:
            create_purchase_order(
                CreatePOArgs(
                    supplier_id="SUP-RELIABLE",
                    node="DC-NORTH",
                    lines=[POLineInput(sku="SKU-BUDGET", qty=400)],
                    expected_delivery_date="2026-09-22",
                    justification="coffee over envelope",
                    idempotency_key="k-budget-block",
                ),
                db=seeded_base,
            )
        seeded_base.rollback()
        after = seeded_base.scalar(select(func.count()).select_from(PurchaseOrder))
        assert after == before
        names = {v["name"] for v in exc.value.as_dict()["blocking_violations"]}
        assert "budget_sufficient" in names

