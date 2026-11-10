"""Offline evaluations for the interview reasoning agent.

These checks exercise the repository's deterministic reasoning analyzer with a
versioned scenario set. They do not make network calls or invoke a live LLM.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.stages.stage1_resume.evidence_validator import EvidenceValidator
from app.stages.stage5_recommendation.evaluation.reasoning_reliability_evaluator import (
    ReasoningReliabilityAnalyzer,
)


class AgentEvalRunner:
    """Run labeled behavior checks and write machine-readable and Markdown reports."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[3]
        self.dataset_path = self.project_root / "data" / "evaluation" / "agent_evals" / "cases.json"
        self.results_path = self.project_root / "data" / "evaluation" / "agent_evals" / "results.json"
        self.report_path = self.project_root / "data" / "evaluation" / "agent_evals" / "agent_eval_report.md"
        self.analyzer = ReasoningReliabilityAnalyzer()
        self.evidence_validator = EvidenceValidator()

    def _evaluate_case(self, case: dict[str, Any]) -> dict[str, Any]:
        kind = case["type"]
        if kind == "unsupported_claim":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"])
            actual = {
                "flagged": result.get("is_unsupported") is True,
                "decision": result["decision"],
                "evidence_strength_within_limit": result["evidence_strength"] <= case["max_evidence_strength"],
                "probed": any(term in result["next_question"].lower() for term in case["probe_terms"]),
            }
            expected = {"flagged": True, "decision": case["expected_decision"], "evidence_strength_within_limit": True, "probed": True}
        elif kind == "contradiction":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"], case["earlier_statement"])
            actual = {
                "flagged": result.get("is_contradiction") is True,
                "decision": result["decision"],
                "clarified": any(term in result["next_question"].lower() for term in ("clarify", "earlier", "specific role")),
            }
            expected = {"flagged": True, "decision": case["expected_decision"], "clarified": True}
        elif kind == "irrelevant_answer":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"])
            actual = {
                "flagged": result.get("is_irrelevant") is True,
                "decision": result["decision"],
                "redirected": any(term in result["next_question"].lower() for term in case["redirect_terms"]),
            }
            expected = {"flagged": True, "decision": case["expected_decision"], "redirected": True}
        elif kind == "missing_metric":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"])
            reasoning = result["reasoning"].lower()
            actual = {
                "flagged": result.get("has_missing_metric") is True,
                "decision": result["decision"],
                "requested_measurement": any(term in result["next_question"].lower() for term in ("metric", "measure", "benchmark")),
                "did_not_invent_forbidden_value": not any(value.lower() in reasoning for value in case["forbidden_values"]),
            }
            expected = {"flagged": True, "decision": case["expected_decision"], "requested_measurement": True, "did_not_invent_forbidden_value": True}
        elif kind == "prompt_injection":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"])
            actual = {
                "flagged": result.get("is_prompt_injection") is True,
                "decision": result["decision"],
                "low_confidence": result["confidence"] <= case["max_confidence"],
                "zero_evidence_strength": result["evidence_strength"] == 0.0,
            }
            expected = {"flagged": True, "decision": case["expected_decision"], "low_confidence": True, "zero_evidence_strength": True}
        elif kind == "evidence_grounding":
            supported = self.evidence_validator.is_valid(case["resume_text"], case["claim"])
            actual = {"claim_supported": supported}
            expected = {"claim_supported": case["expected_supported"]}
            result = {"claim_supported": supported}
        elif kind == "normal_answer":
            result = self.analyzer.analyze_answer(case["question"], case["answer"], case["competency"])
            actual = {
                "decision": result["decision"],
                "confidence_at_least_minimum": result["confidence"] >= case["minimum_confidence"],
                "has_follow_up": bool(result.get("next_question")),
            }
            expected = {"decision": case["expected_decision"], "confidence_at_least_minimum": True, "has_follow_up": True}
        else:
            raise ValueError(f"Unsupported agent eval case type: {kind}")

        checks = {name: actual.get(name) == value for name, value in expected.items()}
        return {
            "case_id": case["case_id"],
            "type": kind,
            "passed": all(checks.values()),
            "checks": checks,
            "expected": expected,
            "actual": actual,
            "agent_output": result,
        }

    def run(self) -> dict[str, Any]:
        cases = json.loads(self.dataset_path.read_text(encoding="utf-8"))
        if not cases:
            raise ValueError("Agent eval dataset is empty")
        case_ids = [case.get("case_id") for case in cases]
        if len(case_ids) != len(set(case_ids)) or any(not case_id for case_id in case_ids):
            raise ValueError("Agent eval case IDs must be present and unique")

        details = [self._evaluate_case(case) for case in cases]
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in details:
            by_type[item["type"]].append(item)
        passed = sum(item["passed"] for item in details)
        results = {
            "evaluation": "Interview Reasoning Agent Evals",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "execution_mode": "offline_deterministic_no_live_llm",
            "total_cases": len(details),
            "passed_cases": passed,
            "failed_cases": len(details) - passed,
            "pass_rate": round(passed / len(details), 4),
            "category_results": {
                kind: {"cases": len(items), "passed": sum(item["passed"] for item in items), "pass_rate": round(sum(item["passed"] for item in items) / len(items), 4)}
                for kind, items in sorted(by_type.items())
            },
            "details": details,
        }
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self.results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.report_path.write_text(self._render_report(results), encoding="utf-8")
        return results

    def _render_report(self, results: dict[str, Any]) -> str:
        lines = [
            "# Interview Reasoning Agent Evals",
            "",
            f"**Run:** {results['created_at']}  ",
            f"**Mode:** `{results['execution_mode']}`  ",
            f"**Cases passed:** {results['passed_cases']}/{results['total_cases']} ({results['pass_rate']:.1%})  ",
            f"**Cases failed:** {results['failed_cases']}",
            "",
            "## Category results",
            "",
            "| Category | Passed | Cases | Pass rate |",
            "|---|---:|---:|---:|",
        ]
        for kind, summary in results["category_results"].items():
            lines.append(f"| `{kind}` | {summary['passed']} | {summary['cases']} | {summary['pass_rate']:.1%} |")
        lines.extend(["", "## Case results", "", "| Case | Category | Result | Failed checks |", "|---|---|---:|---|"])
        for item in results["details"]:
            failed = ", ".join(key for key, ok in item["checks"].items() if not ok) or "—"
            lines.append(f"| `{item['case_id']}` | `{item['type']}` | {'PASS' if item['passed'] else 'FAIL'} | {failed} |")
        lines.extend([
            "",
            "## Production monitoring",
            "",
            "The live interview graph records aggregate checks for reasoning contracts, next-question policy, evidence quote grounding, evaluation fallback use, decision trace consistency, and prompt-injection handling. This offline run does not contain production traffic; capture `/metrics` from a running deployment and use `backend/scripts/report_agent_evals.py` for a production snapshot.",
            "",
            "## Scope and limitations",
            "",
            "This suite runs the repository's deterministic reasoning analyzer and evidence validator against labeled, synthetic scenarios. It does not call a hosted model, assess production latency, or establish that the behavior generalizes to real candidate interviews. Passing scores describe only these cases; expand and independently review the dataset before using results as a deployment gate.",
            "",
            "Machine-readable details, including expected and observed checks, are in `results.json`.",
            "",
        ])
        return "\n".join(lines)
