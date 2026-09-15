"""Markdown + JSON report writers. Sample committed at evals/report.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.cases import DIMENSIONS

ROOT = Path(__file__).resolve().parent
REPORT_MD = ROOT / "report.md"
REPORTS_DIR = ROOT / "reports"

SHORT = {
    "decision_correctness": "Decision",
    "information_sufficiency": "Info",
    "constraint_respect": "Constraint",
    "action_correctness": "Action",
    "validation_performed": "Validation",
    "recovery": "Recovery",
    "explanation_quality": "Explain",
}


def _cell(passed: bool) -> str:
    return "pass" if passed else "FAIL"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Purchasing agent eval report",
        "",
        "Each column is a separate grader. There is no single opaque score.",
        "Stability is the share of repeats that matched the modal (decision, pass-vector).",
        "",
        f"- id: `{report.get('id')}`",
        f"- llm: `{report.get('llm')}`",
        f"- suite: `{report.get('suite')}`",
        f"- repeat: {report.get('repeat')}",
        f"- created: {report.get('created_at')}",
        f"- cases passed: {report.get('cases_passed')}/{report.get('cases_total')}",
        f"- mean stability: {report.get('stability_mean')}",
        "",
        "| Case | " + " | ".join(SHORT[n] for n in DIMENSIONS) + " | Stability | Overall |",
        "| --- | " + " | ".join("---" for _ in DIMENSIONS) + " | --- | --- |",
    ]
    for row in report.get("cases") or []:
        dims = row.get("dimensions") or {}
        cells = [_cell(bool((dims.get(n) or {}).get("passed"))) for n in DIMENSIONS]
        lines.append(
            f"| {row['id']} | " + " | ".join(cells) + f" | {row.get('stability')} | {_cell(bool(row.get('passed')))} |"
        )
    lines += ["", "## Case notes", ""]
    for row in report.get("cases") or []:
        lines.append(f"### {row['id']} — {row.get('description')}")
        lines.append("")
        lines.append(f"Decision: `{row.get('decision')}` · stability {row.get('stability')}")
        lines.append("")
        for n in DIMENSIONS:
            dim = (row.get("dimensions") or {}).get(n) or {}
            rate = dim.get("pass_rate")
            extra = f" (pass_rate={rate})" if rate is not None else ""
            # first-repeat notes, if present
            notes = ""
            repeats = row.get("repeats") or []
            if repeats:
                notes = ((repeats[0].get("dimensions") or {}).get(n) or {}).get("notes") or ""
            lines.append(f"- **{SHORT[n]}**: {_cell(bool(dim.get('passed')))}{extra} — {notes}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], *, markdown_path: Path | None = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md = render_markdown(report)
    report = {**report, "markdown": md}
    json_path = REPORTS_DIR / f"{report['id']}.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    (REPORTS_DIR / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    target = markdown_path or REPORT_MD
    target.write_text(md)
    return target


def load_latest() -> dict[str, Any] | None:
    path = REPORTS_DIR / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_report(run_id: str) -> dict[str, Any] | None:
    path = REPORTS_DIR / f"{run_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    if run_id in {"latest", "harness"}:
        return load_latest()
    return None


def list_reports() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(REPORTS_DIR.glob("EV-*.json"), reverse=True):
        data = json.loads(path.read_text())
        rows.append({k: data.get(k) for k in (
            "id", "kind", "suite", "llm", "repeat", "created_at", "passed",
            "cases_passed", "cases_total", "stability_mean", "status",
            "assertions", "scenario_type", "decision", "matched",
        )})
    return rows
