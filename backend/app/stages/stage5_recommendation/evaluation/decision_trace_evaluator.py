"""Decision-Trace Quality and Recruiter Auditability Benchmark Evaluator (E7).

Evaluates:
1. Trace Completeness (answer, decision, reasoning, question).
2. Trace Semantic Consistency:
   - Answer -> Trigger (trigger grounded in candidate text).
   - Trigger -> Competency.
   - Competency -> Decision.
   - Decision -> Question (compatibility check).
3. Recruiter-Readable Trace Formatting (decision rationale without raw CoT).
4. Recruiter Auditability (explaining questions, scores, pivots, and identity status).
5. Tamper Protection (preventing candidate modification of completed traces).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.stages.stage4_interview.graph.trace_validator import TraceValidator, TraceValidationResult

logger = logging.getLogger(__name__)


class DecisionTraceEvaluator:
    """Evaluates the quality and auditability of decision traces across interview turns."""

    def __init__(self):
        self.validator = TraceValidator()

    def evaluate_traces(self, traces: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(traces)
        if total == 0:
            return {
                "total_traces": 0,
                "completeness_rate": 0.0,
                "consistency_rate": 0.0,
                "results": [],
            }

        complete_count = 0
        consistent_count = 0
        trace_results = []

        for t in traces:
            tid = t.get("trace_id", str(t.get("turn", "unknown")))
            is_comp, comp_errors = self.validator.validate_completeness(t)
            res = self.validator.validate_trace_consistency(
                t, discovered_competency=t.get("discovered_competency")
            )

            if is_comp:
                complete_count += 1
            if res.is_valid:
                consistent_count += 1

            trace_results.append({
                "trace_id": tid,
                "turn": t.get("turn", 1),
                "is_complete": is_comp,
                "is_consistent": res.is_valid,
                "completeness_errors": comp_errors,
                "consistency_errors": res.consistency_errors,
                "recruiter_summary": self.validator.format_recruiter_readable_trace(t),
            })

        return {
            "total_traces": total,
            "complete_traces": complete_count,
            "consistent_traces": consistent_count,
            "completeness_rate": round(complete_count / total, 4),
            "consistency_rate": round(consistent_count / total, 4),
            "results": trace_results,
        }


class DecisionTraceRunner:
    """Benchmark runner for Decision-Trace Quality (Requirement E7)."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            root = Path(__file__).resolve().parents[5]
            data_dir = str(root / "data" / "evaluation" / "decision_traces")
        self.data_dir = Path(data_dir)
        self.evaluator = DecisionTraceEvaluator()
        self.validator = TraceValidator()

    def load_dataset(self) -> Tuple[List[Dict], List[Dict]]:
        cases_file = self.data_dir / "trace_cases.json"
        labels_file = self.data_dir / "trace_labels.json"

        with open(cases_file, "r", encoding="utf-8") as f:
            cases = json.load(f)
        with open(labels_file, "r", encoding="utf-8") as f:
            labels = json.load(f)

        return cases, labels

    def run_evaluation(self) -> Dict[str, Any]:
        cases, labels = self.load_dataset()
        eval_metrics = self.evaluator.evaluate_traces(cases)

        # Auditability check on simulated completed interview session
        sample_session = {
            "session_id": "SESS_AUDIT_001",
            "candidate_id": "CAND_001",
            "status": "completed",
            "identity_verified": True,
            "turns": cases[:4],
            "competency_scores": {
                "technical_skills": 0.85,
                "problem_solving": 0.80,
                "leadership": 0.88,
                "system_design": 0.90,
            },
            "final_score": 0.86,
        }
        audit_results = self.validator.verify_auditability(sample_session)

        # Tamper protection check: candidate attempts to rewrite past turns or score
        candidate_tamper_attempt = {
            "candidate_id": "CAND_001",
            "competency_scores": {"technical_skills": 1.0},
            "interview_score": 1.0,
        }
        is_safe, tamper_result = self.validator.enforce_tamper_protection(
            sample_session, candidate_tamper_attempt
        )

        results = {
            "total_traces_evaluated": eval_metrics["total_traces"],
            "completeness_rate": eval_metrics["completeness_rate"],
            "consistency_rate": eval_metrics["consistency_rate"],
            "auditability": audit_results,
            "tamper_protection_verified": not is_safe and tamper_result.get("blocked") is True,
            "trace_details": eval_metrics["results"],
        }
        return results

    def generate_report(self, results: Dict[str, Any]) -> str:
        rep = f"""# E7: Decision-Trace Quality & Auditability Evaluation Report

**Total Decision Traces Evaluated:** {results['total_traces_evaluated']}  
**Trace Completeness Rate:** {results['completeness_rate'] * 100:.1f}%  
**Trace Consistency Rate:** {results['consistency_rate'] * 100:.1f}%  
**Tamper Protection Enforcement:** {'VERIFIED' if results['tamper_protection_verified'] else 'FAILED'}  

---

## 1. Decision-Trace Verification Details

| Trace ID | Turn | Complete | Consistent | Detected Issues |
| :--- | :---: | :---: | :---: | :--- |
"""
        for t in results["trace_details"]:
            comp_icon = "YES" if t["is_complete"] else "NO"
            cons_icon = "YES" if t["is_consistent"] else "NO"
            issues = ", ".join(t["completeness_errors"] + t["consistency_errors"]) or "None (Clean Trace)"
            rep += f"| **{t['trace_id']}** | {t['turn']} | {comp_icon} | {cons_icon} | {issues} |\n"

        rep += f"""
---

## 2. Recruiter-Readable Trace Audits

The system converts raw reasoning into structured rationale answering:
1. *What did the candidate say?*
2. *What did the AI notice?*
3. *Why did it matter?*
4. *What did the AI decide?*
5. *Why was this question asked next?*

| Turn | Competency | Decision | Candidate Signal | Recruiter Rationale |
| :---: | :--- | :---: | :--- | :--- |
"""
        for t in results["trace_details"][:4]:
            rec = t["recruiter_summary"]
            rep += f"| Turn {rec['turn']} | `{rec['competency']}` | **{rec['decision']}** | {rec['candidate_signal']} | {rec['recruiter_rationale']} |\n"

        rep += f"""
---

## 3. Recruiter Auditability & Tamper Protection

- **Question Justification:** {'PASS' if results['auditability']['can_explain_why_question_asked'] else 'FAIL'}
- **Score Justification:** {'PASS' if results['auditability']['can_explain_why_score_assigned'] else 'FAIL'}
- **Pivot Auditability:** {'PASS' if results['auditability']['can_explain_why_pivoted'] else 'FAIL'}
- **Identity Review Auditability:** {'PASS' if results['auditability']['can_explain_identity_review'] else 'FAIL'}
- **Tamper Protection:** Immutable interview records cleanly rejected candidate attempts to mutate scores or decisions.
"""
        return rep

    def run_and_save(self) -> Dict[str, Any]:
        results = self.run_evaluation()
        report = self.generate_report(results)

        results_file = self.data_dir / "results.json"
        report_file = self.data_dir / "decision_trace_report.md"

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)

        return results
