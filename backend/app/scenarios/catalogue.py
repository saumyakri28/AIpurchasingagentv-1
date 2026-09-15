"""First-class scenario catalogue: world, intake, variants, expected decision."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.scenarios.scripts import script_for


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    intake: dict[str, Any]
    expected_decision: str
    note: str = ""


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    title: str
    endpoint: str
    world: str
    intake_type: str
    summary: str
    brief: str
    variants: tuple[Variant, ...]
    default_variant: str

    def variant(self, variant_id: str | None) -> Variant:
        wanted = variant_id or self.default_variant
        for row in self.variants:
            if row.id == wanted:
                return row
        known = ", ".join(v.id for v in self.variants)
        raise KeyError(f"Unknown variant {wanted!r} for {self.id}. Known: {known}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "endpoint": self.endpoint,
            "world": self.world,
            "intake_type": self.intake_type,
            "summary": self.summary,
            "brief": self.brief,
            "default_variant": self.default_variant,
            "variants": [
                {
                    "id": v.id,
                    "label": v.label,
                    "intake": v.intake,
                    "expected_decision": v.expected_decision,
                    "note": v.note,
                }
                for v in self.variants
            ],
        }


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        id="recommendation-review",
        title="S1 Purchase Recommendation Review",
        endpoint="/agent/run/recommendation-review",
        world="recommendation_review",
        intake_type="recommendation_review",
        summary="System recommended a buy. Verify against inventory, incoming supply and forecast before accepting it.",
        brief=(
            "Review the system recommendation as a HYPOTHESIS. You may accept, modify, reject "
            "or investigate_further. Cite numbers from tools. Open-PO cover is a reject; MOQ "
            "rounding is a modify — unless a hard constraint blocks the rounded qty, then escalate."
        ),
        default_variant="overbuy",
        variants=(
            Variant(
                id="overbuy",
                label="REC-OVERBUY — reject (open PO already covers)",
                intake={"recommendation_id": "REC-OVERBUY"},
                expected_decision="reject",
                note="SKU-COVERED: confirmed inbound 800 already covers 28-day demand.",
            ),
            Variant(
                id="healthy",
                label="REC-HEALTHY — accept (recommendation is actually right)",
                intake={"recommendation_id": "REC-HEALTHY"},
                expected_decision="accept",
                note="SKU-HEALTHY: on-hand 100, rec 140, Acme 7-day lead beats stockout.",
            ),
            Variant(
                id="envelope",
                label="REC-ENVELOPE — accept, park pending_approval ($5500 > $5000)",
                intake={"recommendation_id": "REC-ENVELOPE"},
                expected_decision="accept",
                note="Constraint-clean 100 × $55 = $5500. Autonomy envelope parks the PO.",
            ),
            Variant(
                id="moq",
                label="REC-MOQ — modify toward MOQ (then escalate if C7 blocks)",
                intake={"recommendation_id": "REC-MOQ"},
                expected_decision="escalate",
                note="Need ~320 vs Acme MOQ 1000. Rounded 1000 misses the stockout date.",
            ),
        ),
    ),
    ScenarioSpec(
        id="supplier-shortfall",
        title="S2 Supplier Cannot Fulfil",
        endpoint="/agent/run/supplier-shortfall",
        world="supplier_shortfall",
        intake_type="supplier_shortfall",
        summary="500 ordered, 250 confirmed. Decide if the gap matters before sourcing anything.",
        brief=(
            "Supplier confirmed only part of PO-SHORTFALL. Check inventory, forecast and other "
            "open POs before buying. If cover still holds, accept the short. If a stockout lands "
            "before the remainder, compare alternate suppliers (price / lead / reliability) or escalate."
        ),
        default_variant="gap",
        variants=(
            Variant(
                id="gap",
                label="PO-SHORTFALL 500→250 — bridge with QuickShip (partial-confirm recovery)",
                intake={"po_id": "PO-SHORTFALL", "confirmed_qty": 250, "sku": "SKU-ALT", "node": "DC-NORTH"},
                expected_decision="escalate",
                note="On-hand 70 + 250 arriving 22-Sep still stocks out 20-Sep. QuickShip 80-unit bridge then partial-confirms 48; post-verify recovers.",
            ),
            Variant(
                id="covered",
                label="PO-SHORTFALL 500→250 — accept the short (cover holds)",
                intake={"po_id": "PO-SHORTFALL", "confirmed_qty": 250, "sku": "SKU-ALT", "node": "DC-NORTH"},
                expected_decision="accept",
                note="Eval overlay: on-hand 2000. The 250 gap does not stock out. No new PO.",
            ),
        ),
    ),
    ScenarioSpec(
        id="demand-change",
        title="S3 Demand / Forecast Changed",
        endpoint="/agent/run/demand-change",
        world="demand_change",
        intake_type="demand_change",
        summary="Separate a true demand step-change from a one-off promo anomaly. Do not over-order a spike.",
        brief=(
            "Use get_demand_stats (spike_detected vs anomaly_flag) and sales history. "
            "Evidence before acting: revised demand estimate, recomputed cover including in-transit, "
            "new stockout date vs lead time. Do not over-order on a promo spike."
        ),
        default_variant="promo",
        variants=(
            Variant(
                id="promo",
                label="SKU-PROMO — reject (one-off bulk invoice)",
                intake={"sku": "SKU-PROMO", "node": "DC-NORTH"},
                expected_decision="reject",
                note="anomaly_flag=true. Rec of 600 treats a promo day as the new run-rate.",
            ),
            Variant(
                id="spike",
                label="SKU-SPIKE — investigate further (true trend, stale forecast)",
                intake={"sku": "SKU-SPIKE", "node": "DC-NORTH"},
                expected_decision="investigate_further",
                note="spike_detected=true. Forecast still 18 u/day; do not guess a new qty.",
            ),
            Variant(
                id="increase",
                label="SKU-SPIKE — modify 240 (eval: treat the step-change as real demand)",
                intake={"sku": "SKU-SPIKE", "node": "DC-NORTH"},
                expected_decision="modify",
                note="Same world as spike. Eval script raises qty to a feasible multiple of 24.",
            ),
            Variant(
                id="missing",
                label="SKU-SPIKE at DC-SOUTH — investigate (no inventory row)",
                intake={"sku": "SKU-SPIKE", "node": "DC-SOUTH"},
                expected_decision="investigate_further",
                note="Contradictory / missing position. Never fabricate a South buy.",
            ),
        ),
    ),
    ScenarioSpec(
        id="constrained-buy",
        title="S4 Purchasing Constraint",
        endpoint="/agent/run/constrained-buy",
        world="constrained_buy",
        intake_type="constrained_buy",
        summary="Budget, storage or MOQ blocks the ideal qty. Surface the binding constraint and a feasible alternative.",
        brief=(
            "Identify the binding constraint via validate_action. Produce the best feasible alternative "
            "(partial buy to suggested_max_feasible_qty, alternate with a lower MOQ, different node, or "
            "a budget-exception approval). Never silently execute the blocked quantity. Explain the "
            "service-level trade-off of each option."
        ),
        default_variant="budget",
        variants=(
            Variant(
                id="budget",
                label="SKU-BUDGET — escalate (coffee envelope $600 vs $6400)",
                intake={"sku": "SKU-BUDGET", "node": "DC-NORTH"},
                expected_decision="escalate",
                note="Even MOQ 50 at $16 exceeds remaining $600. suggested_max=0.",
            ),
            Variant(
                id="storage",
                label="SKU-STORAGE — modify to 96 (South cube)",
                intake={"sku": "SKU-STORAGE", "node": "DC-SOUTH"},
                expected_decision="modify",
                note="800 cereal units will not fit. suggested_max_feasible_qty=96.",
            ),
            Variant(
                id="moq",
                label="SKU-MOQ — escalate (MOQ vs stockout date)",
                intake={"sku": "SKU-MOQ", "node": "DC-NORTH"},
                expected_decision="escalate",
                note="Acme MOQ 1000 over-covers and is too slow; QuickShip is still a day late.",
            ),
        ),
    ),
)

_BY_ID = {s.id: s for s in SCENARIOS}


def get_scenario(scenario_id: str) -> ScenarioSpec:
    if scenario_id not in _BY_ID:
        known = ", ".join(_BY_ID)
        raise KeyError(f"Unknown scenario {scenario_id!r}. Known: {known}")
    return _BY_ID[scenario_id]


def list_scenarios() -> list[dict[str, Any]]:
    return [s.as_dict() for s in SCENARIOS]


def canned_script(scenario_id: str, variant_id: str) -> list[dict[str, Any]]:
    return script_for(scenario_id, variant_id)


INSIGHT_CATALOGUE = [
    {
        "id": "po-hygiene",
        "title": "Open-PO hygiene",
        "endpoint": "/insights/po-hygiene",
        "summary": "Overdue and ghost POs: expected date passed, nothing received.",
    },
    {
        "id": "supplier-scorecard",
        "title": "Supplier reliability scorecard",
        "endpoint": "/insights/supplier-scorecard",
        "summary": "Fill rate, on-time %, lead-time variance, reliability for every supplier.",
    },
    {
        "id": "alternate-suppliers",
        "title": "Alternate-supplier comparison",
        "endpoint": "/insights/alternate-suppliers",
        "summary": "Price vs lead time vs reliability for every SKU with more than one source.",
        "default_query": {"sku": "SKU-ALT"},
    },
    {
        "id": "safety-stock",
        "title": "Safety-stock recommendation",
        "endpoint": "/insights/safety-stock",
        "summary": "z₀.₉₅ · σ_LT per SKU at its primary supplier.",
        "default_query": {"sku": "SKU-HEALTHY", "node": "DC-NORTH"},
    },
]
