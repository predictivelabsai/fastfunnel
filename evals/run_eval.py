"""Deterministic evaluation runner for the bounded FastFunnel agency graph.

This mirrors the case/report workflow used by the wider project family while
remaining credential-free. A provider-backed LLM judge can later add semantic
groundedness, correctness, and relevancy scores without weakening these policy
assertions.

Usage:
    python -m evals.run_eval
    python -m evals.run_eval --category policy
    python -m evals.run_eval --limit 2
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from fastfunnel.agents import build_agency_graph

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "evals" / "agent_eval_cases.json"


def evaluate_case(case: dict) -> dict:
    result = build_agency_graph().invoke(
        {
            "company_id": "co_predictivelabs",
            "goal": case["goal"],
            "messages": [],
        }
    )
    proposals = result.get("proposals", [])
    approved = result.get("approved_actions", [])
    proposal_types = {item.get("type") for item in proposals}
    approved_types = {item.get("type") for item in approved}
    rendered = json.dumps(result, sort_keys=True).lower()

    assertions = {
        "status": result.get("status") == case.get("expected_status", "bounded"),
        "required_proposals": set(case.get("required_proposal_types", [])) <= proposal_types,
        "required_approved": set(case.get("required_approved_types", [])) <= approved_types,
        "forbidden_approved": not (
            set(case.get("forbidden_approved_types", [])) & approved_types
        ),
        "required_terms": all(
            term.lower() in rendered for term in case.get("required_terms", [])
        ),
        "forbidden_terms": all(
            term.lower() not in rendered for term in case.get("forbidden_terms", [])
        ),
    }
    return {
        "id": case["id"],
        "category": case["category"],
        "goal": case["goal"],
        "passed": all(assertions.values()),
        "assertions": assertions,
        "proposal_types": sorted(proposal_types),
        "approved_types": sorted(approved_types),
    }


def write_report(report: dict) -> None:
    output = ROOT / "eval" / "eval-results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# FastFunnel Agent Eval Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- **Pass rate: {report['pass_rate']:.0%}** ({report['passed']}/{report['total']})",
        "- Judge: deterministic policy and contract assertions",
        "",
        "| Case | Category | Result |",
        "|---|---|---|",
    ]
    for result in report["cases"]:
        lines.append(
            f"| {result['id']} | {result['category']} | "
            f"{'PASS' if result['passed'] else 'FAIL'} |"
        )
    (ROOT / "evals" / "EVAL_REPORT.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text())["cases"]
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    results = [evaluate_case(case) for case in cases]
    passed = sum(result["passed"] for result in results)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "judge": "deterministic-policy-contract-v1",
        "total": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "cases": results,
    }
    write_report(report)
    for result in results:
        print(f"{'PASS' if result['passed'] else 'FAIL'} {result['id']}")
    print(f"Pass rate: {report['pass_rate']:.0%} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
