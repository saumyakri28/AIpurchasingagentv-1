"""Human approval: execute parked POs and re-verify."""

from __future__ import annotations

from app.db.models import Inventory, PurchaseOrder
from app.domain.policy import AutonomyPolicy
from app.tools.schemas import CreatePOArgs, POLineInput
from app.tools.write_tools import create_purchase_order
from tests.conftest import open_seeded_session


def _park_po(db):
    inv = db.get(Inventory, ("prod-healthy", "DC-NORTH"))
    assert inv is not None
    inv.on_hand = 100
    inv.reserved = 0
    result = create_purchase_order(
        CreatePOArgs(
            supplier_id="SUP-RELIABLE",
            node="DC-NORTH",
            lines=[POLineInput(sku="SKU-HEALTHY", qty=20)],
            expected_delivery_date="2026-09-22",
            justification="policy envelope test",
            idempotency_key="k-approve",
            confidence=0.1,
        ),
        db=db,
        policy=AutonomyPolicy(max_order_value=5_000, min_confidence=0.60),
    )
    db.commit()
    return result


class TestApprovals:
    def test_approve_submits_and_reverifies(self, tmp_path, client) -> None:
        from sqlalchemy.orm import sessionmaker

        from app.db.engine import get_engine
        from app.db.seed import seed_world
        from app.db.session import get_db
        from app.main import app

        engine = get_engine(f"sqlite:///{tmp_path / 'apr.db'}")
        seed_world("base", engine=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        try:
            created = _park_po(db)
            assert created["status"] == "pending_approval"
            approval_id = created["approval_id"]
            po_id = created["po"]["id"]
        finally:
            db.close()

        def _override():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = _override
        try:
            listed = client.get("/approvals")
            assert listed.status_code == 200
            assert any(row["id"] == approval_id for row in listed.json())
            response = client.post(f"/approvals/{approval_id}/approve", json={"decided_by": "buyer"})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["approval"]["status"] == "approved"
            assert body["po"]["status"] in {"confirmed", "submitted", "partially_confirmed"}
            po = SessionLocal().get(PurchaseOrder, po_id)
            assert po is not None
            assert po.status != "pending_approval"
        finally:
            app.dependency_overrides.clear()

    def test_reject_cancels_pending_po(self, tmp_path, client) -> None:
        from sqlalchemy.orm import sessionmaker

        from app.db.engine import get_engine
        from app.db.seed import seed_world
        from app.db.session import get_db
        from app.main import app

        engine = get_engine(f"sqlite:///{tmp_path / 'rej.db'}")
        seed_world("base", engine=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        created = _park_po(db)
        db.close()
        approval_id = created["approval_id"]
        po_id = created["po"]["id"]

        def _override():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = _override
        try:
            response = client.post(f"/approvals/{approval_id}/reject", json={"decided_by": "buyer"})
            assert response.status_code == 200, response.text
            session = SessionLocal()
            po = session.get(PurchaseOrder, po_id)
            assert po is not None
            assert po.status == "cancelled"
            session.close()
        finally:
            app.dependency_overrides.clear()

    def test_modify_and_approve_changes_qty(self, tmp_path, client) -> None:
        from sqlalchemy.orm import sessionmaker

        from app.db.engine import get_engine
        from app.db.seed import seed_world
        from app.db.session import get_db
        from app.main import app

        engine = get_engine(f"sqlite:///{tmp_path / 'mod.db'}")
        seed_world("base", engine=engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        db = SessionLocal()
        created = _park_po(db)
        db.close()
        approval_id = created["approval_id"]

        def _override():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = _override
        try:
            response = client.post(
                f"/approvals/{approval_id}/modify",
                json={"qty": 40, "decided_by": "buyer"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["po"]["lines"][0]["ordered_qty"] == 40
            assert response.json()["approval"]["status"] == "modified"
        finally:
            app.dependency_overrides.clear()
