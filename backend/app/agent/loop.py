"""Hand-written tool-calling loop. No LangChain / LangGraph.

Stages:
  INTAKE → PLAN → INVESTIGATE → DECIDE → PRE-VALIDATE → ACT →
  POST-VERIFY → RECONCILE → REPORT
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.llm import LLMClient, LLMMessage, LLMResponse, ToolCall
from app.agent.prompts import (
    DECIDE_USER_PROMPT,
    FORCE_ESCALATE_REASON,
    PLAN_USER_PROMPT,
    RECONCILE_PROMPT,
    SYSTEM_PROMPT,
    VALIDATE_RETRY_PROMPT,
)
from app.agent.schemas import (
    EMIT_DECISION_TOOL,
    WRITE_DECISIONS,
    Decision,
    DecisionClass,
    DecisionTrace,
    ExpectedOutcome,
    decision_tool_schema,
    parse_json_object,
)
from app.agent.validator import (
    MAX_PREVALIDATE_REVISIONS,
    MAX_RECONCILE_ROUNDS,
    collect_source_of_truth,
    post_verify,
    reconcile,
)
from app.db.clock import FROZEN_NOW, FROZEN_TODAY
from app.db.models import (
    AgentAction,
    ApprovalRequest,
    Product,
    PurchaseOrder,
    SystemRecommendation,
)
from app.db.models import DecisionTrace as TraceRow
from app.tools import registry
from app.tools.context import serialize_po, serialize_product, serialize_recommendation
from app.tools.errors import EntityNotFound, ToolNotFound

MAX_TOOL_RESULT_CHARS = 12_000
SCHEMA_RETRY_LIMIT = 1


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, default=str)


def _clip(payload: Any, limit: int = MAX_TOOL_RESULT_CHARS) -> Any:
    raw = _json_dump(payload)
    if len(raw) <= limit:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return payload
    return {"_truncated": True, "preview": raw[:limit]}


class AgentLoop:
    """Bounded plan → investigate → decide → act → verify loop."""

    def __init__(
        self,
        llm: LLMClient,
        db: Session,
        *,
        max_iterations: int = 12,
        max_tokens: int = 80_000,
    ) -> None:
        self.llm = llm
        self.db = db
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.tokens_in = 0
        self.tokens_out = 0
        self.llm_calls = 0
        self.steps: list[dict[str, Any]] = []
        self.messages: list[LLMMessage] = []
        self.trace_id = _new_id("TR")
        self.called_replenishment = False
        self.last_plan_result: dict[str, Any] | None = None
        self.action_index = 0
        self.po_id: str | None = None
        self._pending_decision: Decision | None = None
        self._closing_response: LLMResponse | None = None

    def run(self, intake: dict[str, Any]) -> DecisionTrace:
        enriched = self._intake(intake)
        row = self._open_trace(enriched)
        try:
            self._plan_and_investigate()
            decision = self._decide()
            verification = None
            reconcile_rounds = 0

            while True:
                decision = self._pre_validate(decision, enriched)
                write_result = self._act(decision, enriched)
                verification = self._post_verify(decision, enriched)
                if verification.matched or decision.decision not in WRITE_DECISIONS:
                    break
                brief = reconcile(
                    verification,
                    {"reconciliation_rounds": reconcile_rounds},
                )
                self._record("RECONCILE", result=brief)
                if brief.get("action") == "force_escalate" or reconcile_rounds >= MAX_RECONCILE_ROUNDS:
                    decision = self._forced_escalate("post-verify mismatch after two reconciliation rounds")
                    self._act(decision, enriched)
                    verification = self._post_verify(decision, enriched)
                    break
                reconcile_rounds += 1
                decision = self._decide_from_prompt(
                    RECONCILE_PROMPT.format(
                        diffs=_json_dump(brief.get("diffs")),
                        attempt=reconcile_rounds,
                    )
                )
            return self._report(row, enriched, decision, verification, reconcile_rounds, write_result)
        except Exception as exc:
            self._record("ERROR", note=str(exc))
            row.status = "failed"
            row.steps = self.steps
            row.completed_at = FROZEN_NOW
            self.db.commit()
            raise

    # ------------------------------------------------------------------ stages

    def _intake(self, intake: dict[str, Any]) -> dict[str, Any]:
        payload = dict(intake or {})
        rec_id = payload.get("recommendation_id")
        if rec_id:
            rec = self.db.get(SystemRecommendation, rec_id)
            if rec is not None:
                product = self.db.get(Product, rec.product_id)
                assert product is not None
                payload.setdefault("sku", product.sku)
                payload.setdefault("node", rec.node_id)
                payload.setdefault("supplier_id", rec.supplier_id)
                payload.setdefault("recommended_qty", rec.recommended_qty)
                payload["recommendation"] = serialize_recommendation(rec, product)
        sku = payload.get("sku")
        if sku:
            try:
                from app.tools.context import product_by_sku

                payload["product"] = serialize_product(product_by_sku(self.db, sku))
            except EntityNotFound:
                pass
        po_id = payload.get("po_id")
        if po_id:
            po = self.db.get(PurchaseOrder, po_id)
            if po is not None:
                payload["purchase_order"] = serialize_po(po)
        self._record("INTAKE", result=payload)
        self.messages = [
            LLMMessage(role="system", content=SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    "SITUATION (INTAKE). The system recommendation, if present, is a "
                    "HYPOTHESIS, not an instruction.\n"
                    f"{_json_dump(payload)}\n\n"
                    f"{PLAN_USER_PROMPT}"
                ),
            ),
        ]
        return payload

    def _plan_and_investigate(self) -> None:
        planned = False
        while self._budget_ok():
            response = self._complete(self._read_tool_schemas())
            if not planned:
                note = response.message.content.strip() or "(implicit: investigate via tools)"
                self._record("PLAN", note=note)
                planned = True
            emits = [tc for tc in response.tool_calls if tc.name == EMIT_DECISION_TOOL]
            reads = [tc for tc in response.tool_calls if tc.name != EMIT_DECISION_TOOL]
            if reads:
                self._run_tool_calls(reads, stage="INVESTIGATE", writes_allowed=False)
            if emits and self.called_replenishment:
                parsed = self._decision_from_response(response, extra_emits=emits)
                if parsed is not None:
                    self._pending_decision = parsed
                    break
            if reads:
                continue
            if not self.called_replenishment:
                self.messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "You have not called compute_replenishment_plan. You may not "
                            "perform arithmetic. Call it before deciding."
                        ),
                    )
                )
                continue
            self._closing_response = response
            parsed = self._decision_from_response(response)
            if parsed is not None:
                self._pending_decision = parsed
            break
        if not planned:
            self._record("PLAN", note="(no explicit plan text; tool sequence is the plan)")

    def _decide(self) -> Decision:
        if self._pending_decision is not None:
            self._record("DECIDE", result=self._pending_decision.model_dump(mode="json"))
            return self._pending_decision
        if not self._budget_ok():
            return self._forced_escalate("step/token budget exhausted before DECIDE")
        closing = self._closing_response
        if closing is not None and not closing.tool_calls:
            err = self._last_schema_error(closing)
            self.messages.append(
                LLMMessage(
                    role="user",
                    content=(
                        "Your previous Decision failed schema validation:\n"
                        f"{err}\n"
                        "Re-emit a single valid Decision JSON object. This is the only retry."
                    ),
                )
            )
            return self._decide_from_prompt(None, retries_used=1)
        self.messages.append(LLMMessage(role="user", content=DECIDE_USER_PROMPT))
        return self._decide_from_prompt(None)

    def _decide_from_prompt(self, extra: str | None, *, retries_used: int = 0) -> Decision:
        if extra:
            self.messages.append(LLMMessage(role="user", content=extra))
        retries = retries_used
        last_error = "invalid Decision"
        while retries <= SCHEMA_RETRY_LIMIT and self._budget_ok():
            response = self._complete(self._read_tool_schemas() + [decision_tool_schema()])
            if response.tool_calls and any(tc.name != EMIT_DECISION_TOOL for tc in response.tool_calls):
                reads = [tc for tc in response.tool_calls if tc.name != EMIT_DECISION_TOOL]
                emits = [tc for tc in response.tool_calls if tc.name == EMIT_DECISION_TOOL]
                if reads:
                    self._run_tool_calls(reads, stage="INVESTIGATE", writes_allowed=False)
                if emits:
                    parsed = self._decision_from_response(response, extra_emits=emits)
                    if parsed is not None:
                        self._record("DECIDE", result=parsed.model_dump(mode="json"))
                        return parsed
                continue
            parsed = self._decision_from_response(response)
            if parsed is not None:
                self._record("DECIDE", result=parsed.model_dump(mode="json"))
                return parsed
            retries += 1
            last_error = self._last_schema_error(response)
            if retries <= SCHEMA_RETRY_LIMIT:
                self.messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "Your previous Decision failed schema validation:\n"
                            f"{last_error}\n"
                            "Re-emit a single valid Decision JSON object. This is the only retry."
                        ),
                    )
                )
        return self._forced_escalate(f"Decision schema invalid after retry: {last_error}")

    def _pre_validate(self, decision: Decision, intake: dict[str, Any]) -> Decision:
        if decision.decision not in WRITE_DECISIONS or not decision.final_quantity:
            self._record("PRE-VALIDATE", note="no buy action to validate")
            return decision
        sku = intake.get("sku")
        node = decision.node or intake.get("node")
        supplier_id = decision.supplier_id or intake.get("supplier_id")
        if not (sku and node and supplier_id):
            return self._forced_escalate("Cannot pre-validate: missing sku/node/supplier_id")

        revisions = 0
        current = decision
        while True:
            report = self._call_tool(
                "validate_action",
                {
                    "sku": sku,
                    "node": node,
                    "supplier_id": supplier_id,
                    "qty": current.final_quantity,
                },
                stage="PRE-VALIDATE",
            )
            passed = bool(report.get("passed") or report.get("ok"))
            blocking = report.get("blocking_violations") or []
            if passed or not blocking:
                return current
            if revisions >= MAX_PREVALIDATE_REVISIONS:
                forced = self._forced_escalate(
                    "validate_action still blocking after two revisions "
                    f"(binding={report.get('binding_constraint')})"
                )
                return forced
            revisions += 1
            current = self._decide_from_prompt(
                VALIDATE_RETRY_PROMPT.format(attempt=revisions, report=_json_dump(report))
            )
            if current.decision not in WRITE_DECISIONS or not current.final_quantity:
                return current
            sku = intake.get("sku") or sku
            node = current.node or node
            supplier_id = current.supplier_id or supplier_id

    def _act(self, decision: Decision, intake: dict[str, Any]) -> dict[str, Any] | None:
        spec = self._write_spec(decision, intake)
        if spec is None:
            self._record("ACT", note=f"no write for decision={decision.decision.value}")
            return None
        name, arguments = spec
        result = self._call_tool(name, arguments, stage="ACT")
        po_id = self._extract_po_id(result)
        if po_id:
            self.po_id = po_id
        approval_id = result.get("approval_id") if isinstance(result, dict) else None
        if approval_id:
            approval = self.db.get(ApprovalRequest, approval_id)
            if approval is not None:
                approval.trace_id = self.trace_id
                self.db.commit()
        return result if isinstance(result, dict) else {"result": result}

    def _post_verify(self, decision: Decision, intake: dict[str, Any]) -> Any:
        truth = collect_source_of_truth(
            self.db,
            po_id=self.po_id or intake.get("po_id"),
            sku=intake.get("sku"),
            node=decision.node or intake.get("node"),
            supplier_id=decision.supplier_id or intake.get("supplier_id"),
        )
        report = post_verify(decision.expected_outcome or ExpectedOutcome(), source_of_truth=truth)
        self._record(
            "POST-VERIFY",
            result={
                "source_of_truth": _clip(truth),
                "verification": report.model_dump(mode="json"),
            },
        )
        return report

    def _report(
        self,
        row: TraceRow,
        intake: dict[str, Any],
        decision: Decision,
        verification: Any,
        reconcile_rounds: int,
        write_result: dict[str, Any] | None,
    ) -> DecisionTrace:
        status = _status_for(decision)
        if verification is not None and not verification.matched and decision.decision in WRITE_DECISIONS:
            status = "unmatched"
        payload = DecisionTrace(
            id=self.trace_id,
            scenario_type=intake.get("type") or intake.get("scenario_type"),
            intake=intake,
            plan=row.plan,
            steps=self.steps,
            decision=decision,
            verification=verification,
            po_id=self.po_id,
            status=status,
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            llm_calls=self.llm_calls,
            reconciliation_rounds=reconcile_rounds,
            created_at=row.created_at,
        )
        row.plan = next((s.get("note") for s in self.steps if s.get("stage") == "PLAN"), row.plan)
        payload.plan = row.plan
        row.steps = self.steps
        row.decision = decision.model_dump(mode="json")
        row.verification = verification.model_dump(mode="json") if verification is not None else None
        row.status = status
        row.completed_at = FROZEN_NOW
        row.scenario_type = payload.scenario_type
        self.db.commit()
        self._record("REPORT", result={"status": status, "po_id": self.po_id, "write": _clip(write_result)})
        # REPORT step landed after commit — flush once more.
        row.steps = self.steps
        self.db.commit()
        return payload

    # ------------------------------------------------------------------ helpers

    def _open_trace(self, intake: dict[str, Any]) -> TraceRow:
        row = TraceRow(
            id=self.trace_id,
            scenario_type=intake.get("type") or intake.get("scenario_type"),
            intake=intake,
            plan=None,
            steps=[],
            decision=None,
            verification=None,
            status="running",
            created_at=FROZEN_NOW,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _budget_ok(self) -> bool:
        return self.llm_calls < self.max_iterations and (self.tokens_in + self.tokens_out) < self.max_tokens

    def _complete(self, tools: list[dict[str, Any]] | None) -> LLMResponse:
        if not self._budget_ok():
            synthetic = LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content=_json_dump(
                        {
                            "decision": "escalate",
                            "confidence": 0.2,
                            "reasoning_summary": FORCE_ESCALATE_REASON,
                            "requires_human_approval": True,
                            "approval_reason": FORCE_ESCALATE_REASON,
                            "key_factors": [],
                            "constraints_considered": [],
                            "alternatives_considered": [],
                            "expected_outcome": {},
                        }
                    ),
                )
            )
            self.messages.append(synthetic.message)
            return synthetic
        response = self.llm.complete(self.messages, tools)
        self.llm_calls += 1
        self.tokens_in += int(response.input_tokens or 0)
        self.tokens_out += int(response.output_tokens or 0)
        self.messages.append(
            LLMMessage(
                role="assistant",
                content=response.message.content,
                tool_calls=response.tool_calls or response.message.tool_calls,
            )
        )
        self._record(
            "LLM",
            note=f"call={self.llm_calls} tokens_in={response.input_tokens} tokens_out={response.output_tokens}",
            result={"content": response.message.content, "tool_calls": [tc.model_dump() for tc in response.tool_calls]},
        )
        return response

    def _read_tool_schemas(self) -> list[dict[str, Any]]:
        return [s for s in registry.json_schemas() if not s.get("is_write")]

    def _run_tool_calls(self, calls: list[ToolCall], *, stage: str, writes_allowed: bool) -> None:
        for call in calls:
            if call.name == EMIT_DECISION_TOOL:
                continue
            write_locked = False
            try:
                spec = registry.get(call.name)
                write_locked = spec.is_write and not writes_allowed
            except ToolNotFound:
                write_locked = False
            if write_locked:
                result: Any = {
                    "error": "write_tools_locked",
                    "detail": "Write tools are available only after DECIDE and PRE-VALIDATE.",
                }
                self._record(stage, tool=call.name, arguments=call.arguments, result=result)
            else:
                result = self._call_tool(call.name, call.arguments, stage=stage)
            self.messages.append(
                LLMMessage(
                    role="tool",
                    content=_json_dump(_clip(result)),
                    tool_call_id=call.id,
                )
            )

    def _call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        stage: str,
    ) -> Any:
        started = time.perf_counter()
        try:
            result = registry.call(name, arguments or {}, db=self.db)
        except (ToolNotFound, EntityNotFound, ValueError) as exc:
            result = {"error": type(exc).__name__, "detail": str(exc)}
        latency = int((time.perf_counter() - started) * 1000)
        if name == "compute_replenishment_plan" and isinstance(result, dict) and "error" not in result:
            self.called_replenishment = True
            self.last_plan_result = result
        self._record(
            stage,
            tool=name,
            arguments=arguments,
            result=_clip(result),
            latency_ms=latency,
        )
        self._persist_action(name, arguments, result, latency)
        return result

    def _persist_action(self, name: str, arguments: dict[str, Any], result: Any, latency_ms: int) -> None:
        clipped = _clip(result)
        self.db.add(
            AgentAction(
                id=_new_id("AA"),
                trace_id=self.trace_id,
                step_index=self.action_index,
                action_type=name,
                tool_name=name,
                arguments=arguments,
                result=clipped if isinstance(clipped, dict) else {"value": clipped},
                latency_ms=latency_ms,
                created_at=FROZEN_NOW,
            )
        )
        self.action_index += 1
        self.db.commit()

    def _record(
        self,
        stage: str,
        *,
        tool: str | None = None,
        arguments: dict[str, Any] | None = None,
        result: Any = None,
        latency_ms: int | None = None,
        note: str | None = None,
    ) -> None:
        self.steps.append(
            {
                "stage": stage,
                "tool": tool,
                "arguments": arguments,
                "result": result,
                "latency_ms": latency_ms,
                "note": note,
            }
        )

    def _decision_from_response(
        self,
        response: LLMResponse,
        extra_emits: list[ToolCall] | None = None,
    ) -> Decision | None:
        for call in extra_emits or response.tool_calls or []:
            if call.name == EMIT_DECISION_TOOL:
                try:
                    return Decision.model_validate(call.arguments)
                except ValidationError:
                    continue
        try:
            return Decision.model_validate(parse_json_object(response.message.content))
        except (ValidationError, ValueError, json.JSONDecodeError):
            return None

    def _last_schema_error(self, response: LLMResponse) -> str:
        try:
            parse_json_object(response.message.content)
            Decision.model_validate(parse_json_object(response.message.content))
        except Exception as exc:
            return str(exc)
        for call in response.tool_calls or []:
            if call.name == EMIT_DECISION_TOOL:
                try:
                    Decision.model_validate(call.arguments)
                except ValidationError as exc:
                    return str(exc)
        return "Decision did not match schema"

    def _forced_escalate(self, reason: str) -> Decision:
        decision = Decision(
            decision=DecisionClass.ESCALATE,
            final_quantity=None,
            confidence=0.2,
            reasoning_summary=FORCE_ESCALATE_REASON,
            key_factors=[],
            constraints_considered=[],
            alternatives_considered=[],
            expected_outcome=ExpectedOutcome(),
            requires_human_approval=True,
            approval_reason=reason[:500],
        )
        self._record("DECIDE", note="forced_escalate", result=decision.model_dump(mode="json"))
        return decision

    def _write_spec(self, decision: Decision, intake: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        key = f"{self.trace_id}:{self.action_index}"
        if decision.decision is DecisionClass.ESCALATE or (
            decision.requires_human_approval and decision.decision not in WRITE_DECISIONS
        ):
            return (
                "escalate",
                {
                    "reason": decision.approval_reason or decision.reasoning_summary or FORCE_ESCALATE_REASON,
                    "context": {
                        "intake": {k: intake.get(k) for k in ("sku", "node", "supplier_id", "po_id", "recommendation_id")},
                        "decision": decision.decision.value,
                    },
                    "suggested_options": [a.model_dump() for a in decision.alternatives_considered],
                    "idempotency_key": f"{key}:escalate",
                },
            )
        if decision.decision not in WRITE_DECISIONS:
            return None
        sku = intake.get("sku")
        node = decision.node or intake.get("node")
        supplier_id = decision.supplier_id or intake.get("supplier_id")
        qty = decision.final_quantity
        if not (sku and node and supplier_id and qty):
            return (
                "escalate",
                {
                    "reason": "Accept/modify missing sku, node, supplier_id, or quantity.",
                    "context": {"decision": decision.model_dump(mode="json")},
                    "suggested_options": [],
                    "idempotency_key": f"{key}:escalate",
                },
            )
        delivery = decision.expected_delivery_date
        if not delivery and self.last_plan_result:
            lead = int(self.last_plan_result.get("lead_time_days") or 7)
            delivery = (FROZEN_TODAY + timedelta(days=lead)).isoformat()
        if not delivery:
            delivery = "2026-09-22"
        existing_po = intake.get("po_id")
        if existing_po and decision.decision is DecisionClass.MODIFY:
            po = self.db.get(PurchaseOrder, existing_po)
            if po is not None and po.lines:
                if supplier_id != po.supplier_id:
                    return (
                        "split_purchase_order",
                        {
                            "po_id": existing_po,
                            "remainder_supplier_id": supplier_id,
                            "qty": qty,
                            "justification": decision.reasoning_summary,
                            "idempotency_key": f"{key}:split",
                            "confidence": decision.confidence,
                        },
                    )
                return (
                    "modify_purchase_order",
                    {
                        "po_id": existing_po,
                        "line_changes": [{"line_id": po.lines[0].id, "ordered_qty": qty}],
                        "justification": decision.reasoning_summary,
                        "idempotency_key": f"{key}:modify",
                        "confidence": decision.confidence,
                    },
                )
        return (
            "create_purchase_order",
            {
                "supplier_id": supplier_id,
                "node": node,
                "lines": [{"sku": sku, "qty": qty}],
                "expected_delivery_date": delivery,
                "justification": decision.reasoning_summary or "agent decision",
                "idempotency_key": f"{key}:create",
                "confidence": decision.confidence,
            },
        )

    @staticmethod
    def _extract_po_id(result: Any) -> str | None:
        if not isinstance(result, dict):
            return None
        if isinstance(result.get("po"), dict) and result["po"].get("id"):
            return str(result["po"]["id"])
        if result.get("po_id"):
            return str(result["po_id"])
        if isinstance(result.get("remainder_po"), dict) and result["remainder_po"].get("id"):
            return str(result["remainder_po"]["id"])
        return None


def _status_for(decision: Decision) -> str:
    if decision.decision is DecisionClass.ESCALATE:
        return "escalated"
    if decision.decision is DecisionClass.REJECT:
        return "rejected"
    if decision.decision is DecisionClass.INVESTIGATE_FURTHER:
        return "investigate_further"
    return "completed"
