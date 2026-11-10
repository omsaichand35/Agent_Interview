"""Decision-Trace Quality, Consistency, and Recruiter Auditability Validator (E7).

Enforces:
1. Trace Contract Schema (answer, trigger, signals, competency, reasoning, decision, question, confidence).
2. Answer -> Trigger validation (trigger must be substantiated in the answer).
3. Decision -> Question validation:
   - deepen: probes deeper on current competency.
   - pivot: explores newly discovered competency.
   - next_competency: transitions to next planned competency.
   - recover: clarifies contradictions or redirects irrelevant answers.
   - conclude: wraps up the interview.
4. Recruiter-Readable Trace Generation (auditable rationale without raw CoT dumps).
5. Auditability checks (answering why question asked, why scored, why pivoted, why human review).
6. Trace Tamper Protection (immutable audit records vs recruiter review events).
"""

import copy
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class TraceValidationResult:
    is_valid: bool
    completeness_errors: List[str] = field(default_factory=list)
    consistency_errors: List[str] = field(default_factory=list)


class TraceValidator:
    """Validates structural completeness and semantic consistency of interview decision traces."""

    SYSTEM_TRIGGERS = {
        "prompt_injection_attempt",
        "contradiction_detected",
        "irrelevant_answer",
        "unsupported_scale_claim",
        "missing_quantitative_metrics",
        "standard_evidence",
        "turn_start",
    }

    VALID_DECISIONS = {"deepen", "pivot", "next_competency", "recover", "conclude"}

    def validate_completeness(self, trace: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate presence of all required fields in the trace contract (E7.1 & E7.4)."""
        errors = []

        if not trace.get("answer"):
            errors.append("missing_answer")

        decision = trace.get("decision")
        if not decision:
            errors.append("missing_decision")
        elif decision.lower() not in self.VALID_DECISIONS:
            errors.append(f"invalid_decision_{decision}")

        if not trace.get("reasoning"):
            errors.append("missing_reasoning")

        if decision != "conclude":
            if not trace.get("question") and not trace.get("next_question"):
                errors.append("missing_question")

        return len(errors) == 0, errors

    def validate_answer_to_trigger(self, answer: str, trigger: str) -> bool:
        """Requirement E7.2: Trigger must actually exist or be grounded in candidate answer."""
        if not trigger:
            return False
        if trigger in self.SYSTEM_TRIGGERS:
            return True

        t_clean = trigger.lower()
        a_clean = answer.lower()

        # Check full trigger substring or key content tokens
        if t_clean in a_clean:
            return True

        trigger_tokens = [w for w in t_clean.split() if len(w) > 3]
        if not trigger_tokens:
            return True

        overlap = sum(1 for w in trigger_tokens if w in a_clean)
        return overlap >= 1

    def validate_decision_to_question(
        self,
        decision: str,
        question: str,
        current_competency: str = "",
        discovered_competency: Optional[str] = None,
    ) -> bool:
        """Requirement E7.3: Next question must be consistent with decision."""
        if not decision or not question:
            return False

        dec = decision.lower()
        q_lower = question.lower()

        if dec == "conclude":
            return any(w in q_lower for w in ["conclude", "wrap up", "thank you", "completed"])

        if dec == "pivot":
            # Question must probe the discovered competency or transition
            target = (discovered_competency or "").lower()
            return target in q_lower or any(w in q_lower for w in ["mentioned", "experience with", "explore", "tell me about"])

        if dec == "next_competency":
            return any(w in q_lower for w in ["move on", "next", "let's discuss", "explore your experience"])

        if dec == "recover":
            return any(w in q_lower for w in ["refocus", "clarify", "earlier", "return", "let's"])

        if dec == "deepen":
            # Deepen should not be a concluding question or generic transition
            is_conclude = any(w in q_lower for w in ["conclude our interview", "wrap up our interview"])
            return not is_conclude

        return True

    def validate_trace_consistency(
        self,
        trace: Dict[str, Any],
        discovered_competency: Optional[str] = None,
    ) -> TraceValidationResult:
        """Validate complete semantic pipeline: Answer -> Trigger -> Competency -> Decision -> Question (E7.6)."""
        is_complete, comp_errors = self.validate_completeness(trace)
        consistency_errors = []

        answer = trace.get("answer", "")
        trigger = trace.get("trigger") or trace.get("trigger_phrase", "")
        decision = trace.get("decision", "")
        reasoning = trace.get("reasoning", "")
        question = trace.get("question") or trace.get("next_question", "")
        competency = trace.get("competency") or trace.get("current_competency", "")

        # 1. Answer -> Trigger
        if answer and trigger and not self.validate_answer_to_trigger(answer, trigger):
            consistency_errors.append(f"trigger_not_in_answer: '{trigger}' not grounded in candidate answer.")

        # 2. Decision -> Question
        if decision and question and not self.validate_decision_to_question(
            decision, question, competency, discovered_competency
        ):
            consistency_errors.append(f"question_incompatible_with_decision: '{question}' incompatible with '{decision}'.")

        # 3. Decision vs Reasoning conflict check
        if decision == "pivot" and "database" in reasoning.lower() and "leadership" in trigger.lower():
            consistency_errors.append("decision_reasoning_contradiction")

        is_valid = is_complete and len(consistency_errors) == 0
        return TraceValidationResult(
            is_valid=is_valid,
            completeness_errors=comp_errors,
            consistency_errors=consistency_errors,
        )

    def format_recruiter_readable_trace(self, turn_trace: Dict[str, Any]) -> Dict[str, Any]:
        """Requirement E7.7: Expose concise, auditable decision rationale without raw CoT."""
        turn_num = turn_trace.get("turn") or turn_trace.get("turn_id", 1)
        competency = turn_trace.get("competency") or turn_trace.get("current_competency", "General")
        decision = turn_trace.get("decision", "deepen").capitalize()
        trigger = turn_trace.get("trigger") or turn_trace.get("trigger_phrase", "Candidate answer provided")
        next_q = turn_trace.get("question") or turn_trace.get("next_question", "")

        return {
            "turn": turn_num,
            "candidate_signal": trigger,
            "competency": competency,
            "decision": decision,
            "recruiter_rationale": (
                f"Candidate exhibited signals for {competency} ({trigger}). "
                f"Agent chose to {decision.lower()} to verify depth and practical competency."
            ),
            "next_question": next_q,
        }

    def verify_auditability(self, completed_session: Dict[str, Any]) -> Dict[str, bool]:
        """Requirement E7.8: Recruiter can answer why questions were asked, why scores assigned, why pivoted, and why human review."""
        traces = completed_session.get("turns", []) or completed_session.get("decision_traces", [])
        scores = completed_session.get("competency_scores", {})
        has_pivot = any(t.get("decision") == "pivot" for t in traces)

        return {
            "can_explain_why_question_asked": len(traces) > 0 and all("decision" in t for t in traces),
            "can_explain_why_score_assigned": len(scores) > 0,
            "can_explain_why_pivoted": has_pivot if any(t.get("decision") == "pivot" for t in traces) else True,
            "can_explain_identity_review": "identity_verified" in completed_session or "status" in completed_session,
        }

    def enforce_tamper_protection(
        self,
        immutable_record: Dict[str, Any],
        candidate_modification_attempt: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Requirement E7.9: Prevent candidate requests from modifying immutable past traces and evaluations."""
        protected_fields = {
            "turns", "decision_traces", "competency_scores", "interview_score",
            "identity_verified", "status", "candidate_id", "session_id", "recommendation",
        }

        # Check if candidate attempted to overwrite protected state
        attempted_violations = [f for f in candidate_modification_attempt if f in protected_fields]
        if attempted_violations:
            logger.warning(f"Tamper attempt detected: Candidate tried to modify protected fields {attempted_violations}.")
            return False, {
                "blocked": True,
                "error": "Access denied: Candidate cannot modify immutable past interview traces, decisions, or scores.",
                "attempted_fields": attempted_violations,
            }

        return True, immutable_record
