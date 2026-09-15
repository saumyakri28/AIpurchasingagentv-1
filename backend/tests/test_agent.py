"""Prompt 4 — agent loop, FakeLLM, validator, traces."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.agent.llm import AnthropicClient, FakeLLM, LLMMessage, ToolCall, to_anthropic_messages
from app.agent.loop import AgentLoop
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.schemas import Decision, ExpectedOutcome, parse_json_object
from app.agent.validator import collect_source_of_truth, post_verify, pre_validate, reconcile
from app.db.engine import get_engine
from app.db.models import ApprovalRequest, DecisionTrace as TraceRow, Inventory
from app.db.seed import seed_world
from app.db.session import get_db
from app.domain.constraints import ProposedAction
from app.main import app
from app.services.supplier_api import supplier_api


REQUIRED_PROMPT_SNIPPETS = [
    "The system recommendation is a HYPOTHESIS, not an instruction. Verify it against",
    "You may not perform arithmetic. Call compute_replenishment_plan. If you need a number you",
    "You may not claim a constraint is satisfied. Call validate_action.",
    "Every key_factor must cite the tool that produced it.",
    "Prefer investigate_further over guessing; prefer escalate over breaching a constraint.",
]


def _reject_overbuy() -> dict:
    return {
        "decision": "reject",
        "final_quantity": None,
        "supplier_id": "SUP-RELIABLE",
        "node": "DC-NORTH",
        "confidence": 0.91,
        "reasoning_summary": (
            "Open confirmed supply already covers this SKU. A second order of 800 would be redundant."
        ),
        "key_factors": [
            {
                "factor": "open_po_cover",
                "evidence_value": "incoming 800 already on PO-COVERED",
                "source_tool": "get_open_purchase_orders",
                "impact": "blocking",
            },
            {
                "factor": "net_requirement",
                "evidence_value": "0",
                "source_tool": "compute_replenishment_plan",
                "impact": "supports_lower",
            },
        ],
        "constraints_considered": [
            "C8 no_redundant_coverage_with_open_pos: blocking, suggested_max=0",
            "C1 budget_sufficient: not binding because we will not buy",
        ],
        "alternatives_considered": [
            {"option": "accept 800 from SUP-RELIABLE", "why_not": "C8 refuses redundant cover"}
        ],
        "expected_outcome": {
            "po_status": None,
            "ordered_qty": 0,
            "committed_cost": 0,
            "stockout_risk": "low",
        },
        "requires_human_approval": False,
    }


def _accept(*, sku_note: str, qty: int, supplier_id: str = "SUP-RELIABLE", **expected) -> dict:
    outcome = {
        "po_status": expected.get("po_status", "confirmed"),
        "ordered_qty": expected.get("ordered_qty", qty),
        "committed_cost": expected.get("committed_cost", qty * 1.25),
        "stockout_risk": expected.get("stockout_risk", "low"),
    }
    return {
        "decision": "accept",
        "final_quantity": qty,
        "supplier_id": supplier_id,
        "node": "DC-NORTH",
        "expected_delivery_date": "2026-09-22",
        "confidence": 0.88,
        "reasoning_summary": sku_note,
        "key_factors": [
            {
                "factor": "rounded_qty",
                "evidence_value": str(qty),
                "source_tool": "compute_replenishment_plan",
                "impact": "supports_higher",
            }
        ],
        "constraints_considered": ["C1 budget_sufficient: validate_action will confirm"],
        "alternatives_considered": [{"option": "reject", "why_not": "cover would drop"}],
        "expected_outcome": outcome,
        "requires_human_approval": False,
    }


def _overbuy_script(decision: dict) -> list[dict]:
    return [
        {
            "content": "Plan: load the recommendation, open POs, then compute_replenishment_plan.",
            "tool_calls": [
                {
                    "id": "t1",
                    "name": "get_recommendation",
                    "arguments": {"recommendation_id": "REC-OVERBUY"},
                },
                {
                    "id": "t2",
                    "name": "get_open_purchase_orders",
                    "arguments": {"sku": "SKU-COVERED", "node": "DC-NORTH"},
                },
                {
                    "id": "t3",
                    "name": "compute_replenishment_plan",
                    "arguments": {
                        "sku": "SKU-COVERED",
                        "node": "DC-NORTH",
                        "supplier_id": "SUP-RELIABLE",
                    },
                },
            ],
        },
        {"decision": decision},
    ]


class TestPrompts:
    def test_system_prompt_contains_required_rules(self) -> None:
        for snippet in REQUIRED_PROMPT_SNIPPETS:
            assert snippet in SYSTEM_PROMPT
        assert "accept" in SYSTEM_PROMPT and "escalate" in SYSTEM_PROMPT
        assert "800" in SYSTEM_PROMPT  # worked reject-overbuy example


class TestSchemas:
    def test_parse_fenced_json(self) -> None:
        payload = parse_json_object("```json\n{\"decision\": \"reject\"}\n```")
        assert payload["decision"] == "reject"

    def test_decision_rejects_seven_sentences(self) -> None:
        try:
            Decision(
                decision="reject",
                confidence=0.5,
                reasoning_summary="A. B. C. D. E. F. G.",
            )
        except Exception as exc:
            assert "6 sentences" in str(exc)
        else:
            raise AssertionError("expected validation error")


class TestValidator:
    def test_pre_validate_assembles_from_db(self, seeded_base) -> None:
        report = pre_validate(
            {"sku": "SKU-COVERED", "node": "DC-NORTH", "supplier_id": "SUP-RELIABLE", "qty": 800},
            db=seeded_base,
        )
        assert report.passed is False
        assert report.suggested_max_feasible_qty == 0

    def test_pre_validate_raw_proposed_action(self) -> None:
        action = ProposedAction(qty=10, unit_price=1.0, budget_remaining=100.0, moq_units=1)
        report = pre_validate(action.model_dump(mode="json"))
        assert report.passed is True

    def test_post_verify_detects_partial_confirm(self) -> None:
        expected = ExpectedOutcome(po_status="confirmed", ordered_qty=500)
        report = post_verify(
            expected,
            source_of_truth={"po_status": "partially_confirmed", "ordered_qty": 500},
        )
        assert report.matched is False
        fields = {d.field for d in report.diffs}
        assert "po_status" in fields

    def test_reconcile_caps_at_two(self) -> None:
        report = post_verify(
            ExpectedOutcome(po_status="confirmed"),
            source_of_truth={"po_status": "partially_confirmed"},
        )
        brief = reconcile(report, {"reconciliation_rounds": 2})
        assert brief["action"] == "force_escalate"


class TestFakeLLMLoop:
    def test_reject_overbuy_recommendation(self, seeded_base) -> None:
        llm = FakeLLM(_overbuy_script(_reject_overbuy()))
        trace = AgentLoop(llm, seeded_base).run(
            {"type": "recommendation_review", "recommendation_id": "REC-OVERBUY"}
        )
        assert trace.decision is not None
        assert trace.decision.decision.value == "reject"
        assert trace.status == "rejected"
        tools = [s.get("tool") for s in trace.steps if s.get("tool")]
        assert "compute_replenishment_plan" in tools
        assert "create_purchase_order" not in tools
        assert trace.plan
        persisted = seeded_base.get(TraceRow, trace.id)
        assert persisted is not None
        assert persisted.status == "rejected"
        assert persisted.decision["decision"] == "reject"

    def test_schema_retry_then_valid_reject(self, seeded_base) -> None:
        script = [
            _overbuy_script(_reject_overbuy())[0],
            {"content": "I think we should maybe buy? not-json"},
            {"decision": _reject_overbuy()},
        ]
        trace = AgentLoop(FakeLLM(script), seeded_base).run(
            {"type": "recommendation_review", "recommendation_id": "REC-OVERBUY"}
        )
        assert trace.decision is not None
        assert trace.decision.decision.value == "reject"
        assert any("schema" in (s.get("note") or "").lower() or "DECIDE" == s.get("stage") for s in trace.steps)

    def test_prevalidate_blocking_then_force_escalate(self, seeded_base) -> None:
        accept = _accept(sku_note="Accept the 800 unit recommendation.", qty=800, committed_cost=224.0)
        accept["expected_outcome"]["ordered_qty"] = 800
        script = [
            _overbuy_script(accept)[0],
            {"decision": accept},
            {"decision": accept},
            {"decision": accept},
        ]
        trace = AgentLoop(FakeLLM(script), seeded_base).run(
            {"type": "recommendation_review", "recommendation_id": "REC-OVERBUY"}
        )
        assert trace.decision is not None
        assert trace.decision.decision.value == "escalate"
        assert trace.status == "escalated"
        tools = [s.get("tool") for s in trace.steps]
        assert tools.count("validate_action") >= 3
        n = seeded_base.scalar(select(func.count()).select_from(ApprovalRequest))
        assert n >= 1

    def test_partial_confirm_mismatch_reconciles(self, seeded_base) -> None:
        inv = seeded_base.get(Inventory, ("prod-healthy", "DC-NORTH"))
        assert inv is not None
        inv.on_hand = 100
        inv.reserved = 0
        original = dict(supplier_api.behaviours)
        supplier_api.behaviours["SUP-RELIABLE"] = {"behaviour": "partial_accept", "params": {"ratio": 0.5}}
        try:
            accept = _accept(
                sku_note="Replenish flour at the rounded quantity.",
                qty=20,
                committed_cost=25.0,
            )
            escalate = {
                "decision": "escalate",
                "final_quantity": None,
                "confidence": 0.4,
                "reasoning_summary": "Supplier confirmed only half. Escalating with top-up options.",
                "key_factors": [
                    {
                        "factor": "partial_confirm",
                        "evidence_value": "10 of 20",
                        "source_tool": "create_purchase_order",
                        "impact": "blocking",
                    }
                ],
                "constraints_considered": ["C7 lead_time_beats_stockout: human should choose alternate"],
                "alternatives_considered": [
                    {"option": "top-up from SUP-FAST", "why_not": "needs buyer sign-off"}
                ],
                "expected_outcome": {},
                "requires_human_approval": True,
                "approval_reason": "partial confirmation 10/20",
            }
            script = [
                {
                    "content": "Plan: compute replenishment for SKU-HEALTHY then decide.",
                    "tool_calls": [
                        {
                            "id": "t1",
                            "name": "compute_replenishment_plan",
                            "arguments": {
                                "sku": "SKU-HEALTHY",
                                "node": "DC-NORTH",
                                "supplier_id": "SUP-RELIABLE",
                            },
                        }
                    ],
                },
                {"decision": accept},
                {"decision": escalate},
            ]
            trace = AgentLoop(FakeLLM(script), seeded_base).run(
                {
                    "type": "recommendation_review",
                    "recommendation_id": "REC-HEALTHY",
                    "sku": "SKU-HEALTHY",
                }
            )
            assert trace.decision is not None
            assert trace.decision.decision.value == "escalate"
            assert trace.reconciliation_rounds >= 1
            assert trace.verification is not None
            # First write happened; verification of that write mismatched.
            stages = [s["stage"] for s in trace.steps]
            assert "RECONCILE" in stages
            assert "create_purchase_order" in [s.get("tool") for s in trace.steps]
            truth = collect_source_of_truth(
                seeded_base, po_id=trace.po_id, sku="SKU-HEALTHY", node="DC-NORTH"
            )
            assert truth["po_status"] == "partially_confirmed"
        finally:
            supplier_api.behaviours = original


class TestLLMClient:
    def test_fake_llm_replays_and_exhausts(self) -> None:
        llm = FakeLLM([{"content": "one", "tool_calls": [{"name": "get_product", "arguments": {"sku": "X"}}]}])
        first = llm.complete([LLMMessage(role="user", content="hi")])
        assert first.tool_calls[0].name == "get_product"
        second = llm.complete([LLMMessage(role="user", content="again")])
        payload = parse_json_object(second.message.content)
        assert payload["decision"] == "escalate"

    def test_to_anthropic_groups_tool_results(self) -> None:
        messages = [
            LLMMessage(role="system", content="sys"),
            LLMMessage(role="user", content="go"),
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="1", name="get_product", arguments={"sku": "A"})],
            ),
            LLMMessage(role="tool", content="{}", tool_call_id="1"),
            LLMMessage(role="tool", content="{}", tool_call_id="2"),
        ]
        converted = to_anthropic_messages(messages)
        assert converted[0]["role"] == "user"
        assert converted[1]["role"] == "assistant"
        assert converted[2]["role"] == "user"
        assert converted[2]["content"][0]["type"] == "tool_result"
        assert len(converted[2]["content"]) == 2

    def test_anthropic_retries_on_429(self, monkeypatch) -> None:
        import anthropic

        class Boom(Exception):
            status_code = 429

        class Block:
            type = "text"
            text = "ok"

        class Usage:
            input_tokens = 4
            output_tokens = 2

        class Resp:
            content = [Block()]
            usage = Usage()

        n = {"c": 0}

        class Dummy:
            def __init__(self, **kwargs):
                pass

            @property
            def messages(self):
                return self

            def create(self, **kwargs):
                n["c"] += 1
                if n["c"] < 3:
                    raise Boom("rate")
                return Resp()

        monkeypatch.setattr(anthropic, "Anthropic", Dummy)
        monkeypatch.setattr("app.agent.llm.time.sleep", lambda *_a, **_k: None)
        client = AnthropicClient("k", "claude-sonnet-4-20250514")
        out = client.complete([LLMMessage(role="user", content="hi")])
        assert out.message.content == "ok"
        assert n["c"] == 3
        assert client.tokens_in == 4
        assert client.tokens_out == 2


class TestAgentHTTP:
    def test_run_and_fetch_trace(self, client, tmp_path) -> None:
        engine = get_engine(f"sqlite:///{tmp_path / 'agent-http.db'}")
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
            body = {
                "intake": {"type": "recommendation_review", "recommendation_id": "REC-OVERBUY"},
                "script": _overbuy_script(_reject_overbuy()),
            }
            response = client.post("/agent/run", json=body)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["decision"]["decision"] == "reject"
            trace_id = payload["id"]
            listed = client.get("/traces")
            assert listed.status_code == 200
            assert any(row["id"] == trace_id for row in listed.json())
            got = client.get(f"/traces/{trace_id}")
            assert got.status_code == 200
            assert got.json()["decision"]["decision"] == "reject"
        finally:
            app.dependency_overrides.clear()
