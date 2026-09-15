"""Eval harness: YAML cases, seven dimensions, FakeLLM suite."""

from __future__ import annotations

from pathlib import Path

from evals.cases import DIMENSIONS, load_cases
from evals.grader import grade_decision, grade_explanation, grade_information
from evals.report import render_markdown
from evals.runner import run_once, run_suite
from tests.conftest import open_seeded_session


def test_twelve_plus_yaml_cases() -> None:
    cases = load_cases("all")
    ids = [c.id for c in cases]
    assert len(ids) >= 12
    assert "E1" in ids and "E13" in ids
    assert DIMENSIONS == (
        "decision_correctness",
        "information_sufficiency",
        "constraint_respect",
        "action_correctness",
        "validation_performed",
        "recovery",
        "explanation_quality",
    )


def test_grader_decision_range() -> None:
    from evals.cases import EvalCase

    case = load_cases("E1")[0]
    assert isinstance(case, EvalCase)

    class _Trace:
        decision = type("D", (), {"model_dump": lambda self, mode="json": {"decision": "accept", "final_quantity": 140}})()
        steps = []
        status = "completed"
        po_id = None
        verification = None
        intake = {}
        id = "TR-x"

    assert grade_decision(case, _Trace())["passed"] is True  # type: ignore[arg-type]


def test_information_sufficiency_requires_tools_before_decide() -> None:
    case = load_cases("E2")[0]

    class _Trace:
        decision = {"decision": "reject"}
        steps = [
            {"stage": "INVESTIGATE", "tool": "get_recommendation", "arguments": {}, "result": {}},
            {"stage": "DECIDE", "result": {"decision": "reject"}},
        ]
        status = "rejected"
        po_id = None
        verification = None
        intake = {}
        id = "TR-x"

    result = grade_information(case, _Trace())  # type: ignore[arg-type]
    assert result["passed"] is False
    assert "compute_replenishment_plan" in result["missing"]


def test_uncited_number_fails_explanation() -> None:
    class _Trace:
        decision = {
            "decision": "reject",
            "reasoning_summary": "I will buy 99999 units because vibes.",
            "key_factors": [
                {"factor": "x", "evidence_value": "1", "source_tool": "get_inventory", "impact": "blocking"}
            ],
        }
        steps = [{"stage": "INVESTIGATE", "tool": "get_inventory", "arguments": {}, "result": {"on_hand": 1}}]
        status = "rejected"
        po_id = None
        verification = None
        intake = {}
        id = "TR-x"

    result = grade_explanation(_Trace())  # type: ignore[arg-type]
    assert result["passed"] is False
    assert "99999" in result["uncited_numbers"]


def test_e1_once_on_seeded_world(tmp_path: Path) -> None:
    case = load_cases("E1")[0]
    db = open_seeded_session(tmp_path / "e1.db", case.world)
    try:
        graded = run_once(case, db=db, llm="fake")
        assert graded["error"] is None, graded
        assert graded["decision"] == "accept"
        assert graded["passed"] is True, graded["assertions"]
    finally:
        db.close()


def test_suite_fake_repeat_one_writes_markdown(tmp_path: Path) -> None:
    report = run_suite(suite="all", repeat=1, llm="fake", db_dir=tmp_path)
    assert report["cases_total"] >= 12
    failed = [c["id"] for c in report["cases"] if not c["passed"]]
    assert failed == [], {c["id"]: c["assertions"] for c in report["cases"] if not c["passed"]}
    md = render_markdown(report)
    assert "Decision" in md and "E1" in md
    assert report["stability_mean"] == 1.0
