"""Deterministic FakeLLM scripts per scenario variant.

Each script calls compute_replenishment_plan (and the scenario's required
read tools) then emits a Decision the constraint engine can live with —
or an escalate when every buy is blocked.
"""

from __future__ import annotations

from typing import Any


def _call(i: int, name: str, **arguments: Any) -> dict[str, Any]:
    return {"id": f"t{i}", "name": name, "arguments": arguments}


def _plan(text: str, *calls: dict[str, Any]) -> dict[str, Any]:
    return {"content": text, "tool_calls": list(calls)}


def _decide(payload: dict[str, Any]) -> dict[str, Any]:
    return {"decision": payload}


def _kf(factor: str, evidence_value: str, source_tool: str, impact: str) -> dict[str, str]:
    return {
        "factor": factor,
        "evidence_value": evidence_value,
        "source_tool": source_tool,
        "impact": impact,
    }


def reject_overbuy() -> dict[str, Any]:
    return {
        "decision": "reject",
        "final_quantity": None,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "confidence": 0.93,
        "reasoning_summary": (
            "PO-COVERED already confirms 800 units of still water arriving 2026-09-20. "
            "compute_replenishment_plan returns net requirement 0, so a second buy of 800 is redundant."
        ),
        "key_factors": [
            _kf("open_po_cover", "incoming 800 on PO-COVERED", "get_open_purchase_orders", "blocking"),
            _kf("net_requirement", "0", "compute_replenishment_plan", "supports_lower"),
        ],
        "constraints_considered": [
            "C8 no_redundant_coverage_with_open_pos: blocking",
            "C12 total_cover_within_max_weeks_of_supply: extra 800 would exceed 8 weeks",
        ],
        "alternatives_considered": [
            {"option": "accept 800", "why_not": "validate_action refuses; suggested_max_feasible_qty=0"}
        ],
        "expected_outcome": {"po_status": None, "ordered_qty": 0, "committed_cost": 0, "stockout_risk": "low"},
        "requires_human_approval": False,
    }


def modify_moq() -> dict[str, Any]:
    return {
        "decision": "modify",
        "final_quantity": 1000,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "expected_delivery_date": "2026-09-29",
        "confidence": 0.62,
        "reasoning_summary": (
            "Recommended 320 is below Acme MOQ 1000. compute_replenishment_plan rounds to 1000. "
            "QuickShip MOQ 80 is the other option if 1000 fails a hard constraint."
        ),
        "key_factors": [
            _kf("moq_units", "1000", "get_supplier_terms", "blocking"),
            _kf("rounded_qty", "1000", "compute_replenishment_plan", "supports_higher"),
            _kf("fast_moq", "80", "find_alternate_suppliers", "supports_lower"),
        ],
        "constraints_considered": [
            "C3 moq_satisfied: 320 fails, 1000 satisfies",
            "C7 lead_time_beats_stockout: 14-day Acme may miss the stockout — validate_action must confirm",
        ],
        "alternatives_considered": [
            {"option": "accept 320", "why_not": "below MOQ 1000"},
            {"option": "switch to SUP-FAST qty 80", "why_not": "use if 1000 is refused"},
        ],
        "expected_outcome": {"po_status": "confirmed", "ordered_qty": 1000, "stockout_risk": "medium"},
        "requires_human_approval": False,
    }


def escalate_moq_blocked() -> dict[str, Any]:
    return {
        "decision": "escalate",
        "final_quantity": None,
        "supplier_id": "SUP-FAST",
        "node": "DC-NORTH",
        "confidence": 0.55,
        "reasoning_summary": (
            "validate_action refused 1000 on C7 (lead time after stockout) and C12 (over-cover). "
            "QuickShip still arrives a day after the projected stockout. A human should expedite or approve a short-cover risk."
        ),
        "key_factors": [
            _kf("binding_constraint", "lead_time_beats_stockout suggested_max=0", "validate_action", "blocking"),
        ],
        "constraints_considered": [
            "C7 lead_time_beats_stockout: blocking for Acme 14d and QuickShip 4d",
            "C3 moq_satisfied: 1000 would pass MOQ but never executes",
        ],
        "alternatives_considered": [
            {"option": "buy 1000 from Acme", "why_not": "arrives after stockout and exceeds max weeks of supply"},
            {"option": "buy 80 from QuickShip", "why_not": "still one day late vs stockout 2026-09-18"},
        ],
        "expected_outcome": {},
        "requires_human_approval": True,
        "approval_reason": "No feasible qty beats the stockout date; buyer must expedite.",
    }


def source_shortfall_bridge() -> dict[str, Any]:
    return {
        "decision": "modify",
        "final_quantity": 80,
        "supplier_id": "SUP-FAST",
        "node": "DC-NORTH",
        "expected_delivery_date": "2026-09-18",
        "confidence": 0.84,
        "reasoning_summary": (
            "PO-SHORTFALL confirmed 250 of 500. On-hand 70 plus 250 arriving 22-Sep still stocks out on 20-Sep. "
            "The 250 gap matters for those two days. QuickShip can bridge 80 units in 3 days at $5.20; another Acme PO cannot beat the stockout."
        ),
        "key_factors": [
            _kf("confirmed_qty", "250 of 500", "get_open_purchase_orders", "supports_lower"),
            _kf("projected_stockout_date", "2026-09-20", "compute_replenishment_plan", "blocking"),
            _kf("fast_lead_time_days", "3", "find_alternate_suppliers", "supports_higher"),
            _kf("validate_fast_80", "passed", "validate_action", "supports_higher"),
        ],
        "constraints_considered": [
            "C7 lead_time_beats_stockout: Acme remainder fails; QuickShip 80 passes",
            "C12 total_cover_within_max_weeks_of_supply: 250 more from Acme over-covers; 80 from QuickShip does not",
            "C8 no_redundant_coverage_with_open_pos: 80 is a bridge, not a second full cover",
        ],
        "alternatives_considered": [
            {"option": "accept the short", "why_not": "stockout 20-Sep is before the 250 arrives 22-Sep"},
            {"option": "reorder 250 from Acme", "why_not": "14-day lead misses the gap and fails C7"},
        ],
        "expected_outcome": {
            "po_status": "confirmed",
            "ordered_qty": 80,
            "committed_cost": 416.0,
        },
        "requires_human_approval": False,
    }


def reject_promo() -> dict[str, Any]:
    return {
        "decision": "reject",
        "final_quantity": None,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "confidence": 0.9,
        "reasoning_summary": (
            "get_demand_stats flags a one-off anomaly, not a spike. Cover including in-transit is about 21 days. "
            "The 600-unit recommendation would over-order on a promo invoice. I will not place it."
        ),
        "key_factors": [
            _kf("anomaly_flag", "true", "get_demand_stats", "blocking"),
            _kf("spike_detected", "false", "get_demand_stats", "supports_lower"),
            _kf("coverage_days", "~21", "compute_replenishment_plan", "supports_lower"),
            _kf("rounded_qty", "205", "compute_replenishment_plan", "supports_lower"),
        ],
        "constraints_considered": [
            "C8 no_redundant_coverage_with_open_pos: not blocking, but promo is not real run-rate",
            "C12 total_cover_within_max_weeks_of_supply: 600 would inflate cover without a true trend",
        ],
        "alternatives_considered": [
            {"option": "accept 600", "why_not": "anomaly_flag; would over-order on a bulk invoice"},
            {"option": "buy rounded 205", "why_not": "still treats the promo day as demand"},
        ],
        "expected_outcome": {"po_status": None, "ordered_qty": 0, "stockout_risk": "low"},
        "requires_human_approval": False,
    }


def investigate_spike() -> dict[str, Any]:
    return {
        "decision": "investigate_further",
        "final_quantity": None,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "confidence": 0.58,
        "reasoning_summary": (
            "get_demand_stats.spike_detected is true and the last 14 days are a plateau, not a one-off. "
            "The forecast is still 18 u/day so compute_replenishment_plan understates need. I will not guess a qty until the forecast is refreshed."
        ),
        "key_factors": [
            _kf("spike_detected", "true", "get_demand_stats", "supports_higher"),
            _kf("anomaly_flag", "false", "get_demand_stats", "supports_higher"),
            _kf("forecast_daily", "18", "get_forecast", "supports_lower"),
            _kf("rounded_qty_on_stale_fcst", "144", "compute_replenishment_plan", "supports_lower"),
            _kf("projected_stockout_date", "from plan", "compute_replenishment_plan", "supports_higher"),
        ],
        "constraints_considered": [
            "C7 lead_time_beats_stockout: must recompute after a revised demand estimate",
        ],
        "alternatives_considered": [
            {"option": "accept 180", "why_not": "not a multiple and based on a stale forecast"},
            {"option": "buy 144", "why_not": "plan used fcst-v3.1 which missed the step-change"},
        ],
        "expected_outcome": {},
        "requires_human_approval": False,
    }


def escalate_budget() -> dict[str, Any]:
    return {
        "decision": "escalate",
        "final_quantity": None,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "confidence": 0.88,
        "reasoning_summary": (
            "Ideal coffee buy is about 370-400 units at $16. Remaining budget is $600, so even MOQ 50 ($800) is blocked. "
            "I will not silently place 400. Asking for a budget-exception approval; partial buy to suggested_max is 0."
        ),
        "key_factors": [
            _kf("budget_remaining", "600", "get_budget", "blocking"),
            _kf("recommended_cost", "6400", "compute_replenishment_plan", "blocking"),
            _kf("suggested_max_feasible_qty", "0", "validate_action", "blocking"),
            _kf("binding_constraint", "budget_sufficient", "validate_action", "blocking"),
        ],
        "constraints_considered": [
            "C1 budget_sufficient: 400 units at $16 needs $6400 vs $600 remaining — blocking",
            "C3 moq_satisfied: MOQ 50 costs $800, still over remaining budget",
        ],
        "alternatives_considered": [
            {"option": "partial buy to suggested_max", "why_not": "suggested_max_feasible_qty is 0"},
            {"option": "execute 400 anyway", "why_not": "would breach C1; never silent-execute a blocked qty"},
        ],
        "expected_outcome": {},
        "requires_human_approval": True,
        "approval_reason": "Coffee budget remaining $600 cannot fund MOQ 50 at $16. Request budget exception or cut other coffee POs.",
    }


def modify_storage() -> dict[str, Any]:
    return {
        "decision": "modify",
        "final_quantity": 96,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-SOUTH",
        "expected_delivery_date": "2026-09-22",
        "confidence": 0.86,
        "reasoning_summary": (
            "DC-SOUTH has 15 m3 and cereal is 0.05 m3/unit. 800 units cannot fit. "
            "validate_action binding constraint is storage_capacity_available with suggested_max_feasible_qty 96. Service level will be thinner than the 800-unit ask."
        ),
        "key_factors": [
            _kf("storage_free_m3", "5.0 of 15.0", "get_storage_capacity", "blocking"),
            _kf("suggested_max_feasible_qty", "96", "validate_action", "supports_lower"),
            _kf("binding_constraint", "storage_capacity_available", "validate_action", "blocking"),
        ],
        "constraints_considered": [
            "C2 storage_capacity_available: 800 blocked; 96 is the feasible cap",
            "C3 moq_satisfied: 96 meets MOQ 24",
        ],
        "alternatives_considered": [
            {"option": "accept 800", "why_not": "physically will not fit at DC-SOUTH"},
            {"option": "split to DC-NORTH", "why_not": "this SKU is only stocked at South in the fixture"},
            {"option": "QuickShip max 400", "why_not": "still over South cube; 96 from Acme is enough cube"},
        ],
        "expected_outcome": {
            "po_status": "confirmed",
            "ordered_qty": 96,
            "committed_cost": 297.6,
        },
        "requires_human_approval": False,
    }


SCRIPTS: dict[str, list[dict[str, Any]]] = {
    "recommendation-review:overbuy": [
        _plan(
            "Plan: load REC-OVERBUY, open POs, replenishment plan, then decide. Hypothesis only.",
            _call(1, "get_recommendation", recommendation_id="REC-OVERBUY"),
            _call(2, "get_open_purchase_orders", sku="SKU-COVERED", node="DC-NORTH"),
            _call(3, "get_inventory", sku="SKU-COVERED", node="DC-NORTH"),
            _call(4, "compute_replenishment_plan", sku="SKU-COVERED", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            _call(5, "validate_action", sku="SKU-COVERED", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=800),
        ),
        _decide(reject_overbuy()),
    ],
    "recommendation-review:moq": [
        _plan(
            "Plan: load REC-MOQ, supplier terms, alternates, replenishment, validate 1000.",
            _call(1, "get_recommendation", recommendation_id="REC-MOQ"),
            _call(2, "get_supplier_terms", supplier_id="SUP-RELIABLE", sku="SKU-MOQ"),
            _call(3, "find_alternate_suppliers", sku="SKU-MOQ"),
            _call(4, "compute_replenishment_plan", sku="SKU-MOQ", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            _call(5, "validate_action", sku="SKU-MOQ", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=1000),
        ),
        _decide(modify_moq()),
        _decide(escalate_moq_blocked()),
    ],
    "supplier-shortfall:gap": [
        _plan(
            "Plan: inspect PO-SHORTFALL, inventory, forecast, other POs, replenishment, alternates, then validate a QuickShip bridge.",
            _call(1, "get_open_purchase_orders", sku="SKU-ALT", node="DC-NORTH"),
            _call(2, "get_inventory", sku="SKU-ALT", node="DC-NORTH"),
            _call(3, "get_forecast", sku="SKU-ALT", node="DC-NORTH", horizon_days=28),
            _call(4, "compute_replenishment_plan", sku="SKU-ALT", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            _call(5, "find_alternate_suppliers", sku="SKU-ALT"),
            _call(6, "validate_action", sku="SKU-ALT", node="DC-NORTH", supplier_id="SUP-FAST", qty=80),
        ),
        _decide(source_shortfall_bridge()),
    ],
    "demand-change:promo": [
        _plan(
            "Plan: demand stats vs sales history vs forecast; recompute cover; do not over-order a promo.",
            _call(1, "get_demand_stats", sku="SKU-PROMO", node="DC-NORTH", window_days=42),
            _call(2, "get_sales_history", sku="SKU-PROMO", node="DC-NORTH", days=28),
            _call(3, "get_forecast", sku="SKU-PROMO", node="DC-NORTH", horizon_days=28),
            _call(4, "get_inventory", sku="SKU-PROMO", node="DC-NORTH"),
            _call(5, "get_open_purchase_orders", sku="SKU-PROMO", node="DC-NORTH"),
            _call(6, "compute_replenishment_plan", sku="SKU-PROMO", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
        ),
        _decide(reject_promo()),
    ],
    "demand-change:spike": [
        _plan(
            "Plan: distinguish genuine spike from anomaly; compare stockout vs lead time; do not guess a new qty.",
            _call(1, "get_demand_stats", sku="SKU-SPIKE", node="DC-NORTH", window_days=42),
            _call(2, "get_sales_history", sku="SKU-SPIKE", node="DC-NORTH", days=28),
            _call(3, "get_forecast", sku="SKU-SPIKE", node="DC-NORTH", horizon_days=28),
            _call(4, "get_open_purchase_orders", sku="SKU-SPIKE", node="DC-NORTH"),
            _call(5, "compute_replenishment_plan", sku="SKU-SPIKE", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
        ),
        _decide(investigate_spike()),
    ],
    "constrained-buy:budget": [
        _plan(
            "Plan: budget vs landed cost, validate 400, never execute the blocked qty.",
            _call(1, "get_recommendation", recommendation_id="REC-BUDGET"),
            _call(2, "get_budget", node="DC-NORTH", category="coffee"),
            _call(3, "compute_replenishment_plan", sku="SKU-BUDGET", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            _call(4, "validate_action", sku="SKU-BUDGET", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=400),
            _call(5, "validate_action", sku="SKU-BUDGET", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=50),
        ),
        _decide(escalate_budget()),
    ],
    "constrained-buy:storage": [
        _plan(
            "Plan: storage cube vs 800 cereal; take suggested_max_feasible_qty.",
            _call(1, "get_recommendation", recommendation_id="REC-STORAGE"),
            _call(2, "get_storage_capacity", node="DC-SOUTH"),
            _call(3, "compute_replenishment_plan", sku="SKU-STORAGE", node="DC-SOUTH", supplier_id="SUP-RELIABLE"),
            _call(4, "validate_action", sku="SKU-STORAGE", node="DC-SOUTH", supplier_id="SUP-RELIABLE", qty=800),
            _call(5, "validate_action", sku="SKU-STORAGE", node="DC-SOUTH", supplier_id="SUP-RELIABLE", qty=96),
        ),
        _decide(modify_storage()),
    ],
    "constrained-buy:moq": [
        _plan(
            "Plan: MOQ 1000 vs need ~320; check QuickShip lower MOQ; escalate if C7 blocks every path.",
            _call(1, "get_recommendation", recommendation_id="REC-MOQ"),
            _call(2, "get_supplier_terms", supplier_id="SUP-RELIABLE", sku="SKU-MOQ"),
            _call(3, "find_alternate_suppliers", sku="SKU-MOQ"),
            _call(4, "compute_replenishment_plan", sku="SKU-MOQ", node="DC-NORTH", supplier_id="SUP-RELIABLE"),
            _call(5, "validate_action", sku="SKU-MOQ", node="DC-NORTH", supplier_id="SUP-RELIABLE", qty=1000),
        ),
        _decide(modify_moq()),
        _decide(escalate_moq_blocked()),
    ],
}


def script_for(scenario_id: str, variant_id: str) -> list[dict[str, Any]]:
    key = f"{scenario_id}:{variant_id}"
    if key not in SCRIPTS:
        raise KeyError(f"No FakeLLM script for {key}")
    return SCRIPTS[key]
