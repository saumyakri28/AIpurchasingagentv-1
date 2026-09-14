"""SQLAlchemy ORM models — the world the agent investigates."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.engine import Base


class POStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    RECEIVED = "received"
    CANCELLED = "cancelled"


OPEN_PO_STATUSES = frozenset(
    {
        POStatus.SUBMITTED.value,
        POStatus.CONFIRMED.value,
        POStatus.PARTIALLY_CONFIRMED.value,
        POStatus.PENDING_APPROVAL.value,
    }
)


class CreatedBy(str, Enum):
    SYSTEM = "system"
    AGENT = "agent"
    BUYER = "buyer"


class ABCClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


class Product(Base):
    __tablename__ = "product"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    unit_cost: Mapped[float] = mapped_column(Float, nullable=False)
    units_per_case: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    volume_per_unit_m3: Mapped[float] = mapped_column(Float, nullable=False)
    shelf_life_days: Mapped[int] = mapped_column(Integer, nullable=False)
    abc_class: Mapped[str] = mapped_column(String(1), nullable=False, default="B")

    inventory_rows: Mapped[list[Inventory]] = relationship(back_populates="product")
    supplier_links: Mapped[list[SupplierProduct]] = relationship(back_populates="product")


class Node(Base):
    __tablename__ = "node"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_capacity_m3: Mapped[float] = mapped_column(Float, nullable=False)
    receiving_capacity_units_per_day: Mapped[int] = mapped_column(Integer, nullable=False)

    inventory_rows: Mapped[list[Inventory]] = relationship(back_populates="node")
    budgets: Mapped[list[Budget]] = relationship(back_populates="node")


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("product_id", "node_id", name="uq_inventory_product_node"),)

    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    damaged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    product: Mapped[Product] = relationship(back_populates="inventory_rows")
    node: Mapped[Node] = relationship(back_populates="inventory_rows")


class SalesHistory(Base):
    __tablename__ = "sales_history"
    __table_args__ = (
        UniqueConstraint("product_id", "node_id", "date", name="uq_sales_product_node_date"),
    )

    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    units_sold: Mapped[int] = mapped_column(Integer, nullable=False)


class Forecast(Base):
    __tablename__ = "forecast"
    __table_args__ = (
        UniqueConstraint("product_id", "node_id", "date", name="uq_forecast_product_node_date"),
    )

    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    forecast_units: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_low: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_high: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Supplier(Base):
    __tablename__ = "supplier"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    avg_lead_time_days: Mapped[float] = mapped_column(Float, nullable=False)
    lead_time_std_days: Mapped[float] = mapped_column(Float, nullable=False)
    fill_rate_pct: Mapped[float] = mapped_column(Float, nullable=False)
    on_time_pct: Mapped[float] = mapped_column(Float, nullable=False)
    # Fixture-driven mock-API behaviour (Prompt 3). Never randomised in evals.
    api_behaviour: Mapped[str] = mapped_column(String(64), nullable=False, default="full_accept")
    api_behaviour_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    products: Mapped[list[SupplierProduct]] = relationship(back_populates="supplier")
    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="supplier")


class SupplierProduct(Base):
    __tablename__ = "supplier_product"
    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", name="uq_supplier_product"),
    )

    supplier_id: Mapped[str] = mapped_column(ForeignKey("supplier.id"), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), primary_key=True)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    moq_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    order_multiple_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_units_per_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    supplier: Mapped[Supplier] = relationship(back_populates="products")
    product: Mapped[Product] = relationship(back_populates="supplier_links")


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("supplier.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=POStatus.DRAFT.value)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default=CreatedBy.SYSTEM.value)

    supplier: Mapped[Supplier] = relationship(back_populates="purchase_orders")
    node: Mapped[Node] = relationship()
    lines: Mapped[list[POLine]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )


class POLine(Base):
    __tablename__ = "po_line"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    po_id: Mapped[str] = mapped_column(ForeignKey("purchase_order.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), nullable=False)
    ordered_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class Budget(Base):
    __tablename__ = "budget"
    __table_args__ = (
        UniqueConstraint("node_id", "category", "period_start", name="uq_budget_node_cat_period"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    allocated: Mapped[float] = mapped_column(Float, nullable=False)
    committed: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    node: Mapped[Node] = relationship(back_populates="budgets")

    @property
    def remaining(self) -> float:
        return self.allocated - self.committed - self.spent


class SystemRecommendation(Base):
    __tablename__ = "system_recommendation"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("node.id"), nullable=False)
    recommended_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("supplier.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    product: Mapped[Product] = relationship()
    node: Mapped[Node] = relationship()
    supplier: Mapped[Supplier] = relationship()


class DecisionTrace(Base):
    __tablename__ = "decision_trace"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intake: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    actions: Mapped[list[AgentAction]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
    )
    approvals: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
    )


class AgentAction(Base):
    __tablename__ = "agent_action"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(ForeignKey("decision_trace.id"), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    trace: Mapped[DecisionTrace] = relationship(back_populates="actions")


class ApprovalRequest(Base):
    __tablename__ = "approval_request"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(ForeignKey("decision_trace.id"), nullable=True)
    action_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    urgency: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    options_considered: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ApprovalStatus.PENDING.value)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    trace: Mapped[DecisionTrace | None] = relationship(back_populates="approvals")


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
