"""Hand-written tool-calling loop. No LangChain / LangGraph.

Stages (Prompt 4):
  INTAKE → PLAN → INVESTIGATE → DECIDE → PRE-VALIDATE → ACT →
  POST-VERIFY → RECONCILE → REPORT
"""

from __future__ import annotations

from typing import Any

from app.agent.llm import LLMClient
from app.agent.schemas import DecisionTrace


class AgentLoop:
    """Bounded plan → act → observe → decide loop."""

    def __init__(self, llm: LLMClient, *, max_iterations: int = 12) -> None:
        self.llm = llm
        self.max_iterations = max_iterations

    def run(self, intake: dict[str, Any]) -> DecisionTrace:
        raise NotImplementedError
