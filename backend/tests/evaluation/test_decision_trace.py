"""Comprehensive test suite for Decision-Trace Quality and Recruiter Auditability (Requirement E7)."""

import pytest
from app.stages.stage4_interview.graph.trace_validator import (
    TraceValidator,
    TraceValidationResult,
)
from app.stages.stage5_recommendation.evaluation.decision_trace_evaluator import (
    DecisionTraceEvaluator,
    DecisionTraceRunner,
)


def test_trace_completeness_validation():
    """Requirement E7.4 & E7.5: Validating that all mandatory trace fields exist."""
    validator = TraceValidator()

    complete_trace = {
        "turn": 1,
        "answer": "I built microservices in FastAPI.",
        "trigger": "FastAPI",
        "competency": "backend_development",
        "reasoning": "Candidate demonstrated backend API experience.",
        "decision": "deepen",
        "question": "How did you structure routing and database sessions in FastAPI?",
    }
    is_valid, errors = validator.validate_completeness(complete_trace)
    assert is_valid is True
    assert len(errors) == 0

    incomplete_trace = {
        "turn": 1,
        "answer": "I built microservices.",
        # Missing decision, reasoning, question
    }
    is_valid, errors = validator.validate_completeness(incomplete_trace)
    assert is_valid is False
    assert "missing_decision" in errors
    assert "missing_reasoning" in errors
    assert "missing_question" in errors


def test_answer_to_trigger_grounding():
    """Requirement E7.2: Trigger phrase must be substantiated in candidate answer."""
    validator = TraceValidator()

    # Valid: Trigger exists in answer
    valid_answer = "I mentored two junior developers on our team."
    valid_trigger = "mentored two junior developers"
    assert validator.validate_answer_to_trigger(valid_answer, valid_trigger) is True

    # Invalid: Trigger invents experience not mentioned
    invalid_answer = "I optimized the database query index."
    invalid_trigger = "mentioned leadership experience"
    assert validator.validate_answer_to_trigger(invalid_answer, invalid_trigger) is False


def test_decision_to_question_compatibility():
    """Requirement E7.3: Next question must be consistent with the reasoning decision."""
    validator = TraceValidator()

    # 1. Deepen: Explores current competency
    assert validator.validate_decision_to_question(
        decision="deepen",
        question="How did you configure rolling deployments and horizontal autoscaling?",
        current_competency="cloud_devops",
    ) is True

    # 2. Pivot: Explores newly discovered competency
    assert validator.validate_decision_to_question(
        decision="pivot",
        question="You mentioned experience with leadership. Can you describe how you mentored them?",
        current_competency="technical_skills",
        discovered_competency="leadership",
    ) is True

    # 3. Next Competency: Transitions to next planned topic
    assert validator.validate_decision_to_question(
        decision="next_competency",
        question="Thank you for that overview. Let's move on to explore your experience with system design.",
        current_competency="technical_skills",
    ) is True

    # 4. Conclude: Concluding wrap-up
    assert validator.validate_decision_to_question(
        decision="conclude",
        question="Thank you for your time today. That concludes our technical interview.",
    ) is True

    # 5. Incompatible: Decision is conclude but question is exploratory
    assert validator.validate_decision_to_question(
        decision="conclude",
        question="What mock fixtures did you write in Pytest?",
    ) is False


def test_recruiter_readable_trace_formatting():
    """Requirement E7.7: Expose concise, auditable decision rationale answering the 5 key questions."""
    validator = TraceValidator()

    trace = {
        "turn": 4,
        "answer": "I mentored two junior developers through weekly pair programming.",
        "trigger": "mentored two junior developers",
        "competency": "leadership",
        "decision": "pivot",
        "reasoning": "Candidate introduced meaningful leadership evidence.",
        "question": "Tell me about how you mentored those junior developers.",
    }

    summary = validator.format_recruiter_readable_trace(trace)
    assert summary["turn"] == 4
    assert summary["competency"] == "leadership"
    assert summary["decision"] == "Pivot"
    assert "leadership" in summary["recruiter_rationale"].lower()
    assert summary["next_question"] == trace["question"]


def test_recruiter_auditability_verification():
    """Requirement E7.8: Verify that a completed interview enables recruiters to audit decisions."""
    validator = TraceValidator()

    sample_completed_interview = {
        "session_id": "SESS_AUDIT_101",
        "candidate_id": "CAND_101",
        "status": "completed",
        "identity_verified": True,
        "turns": [
            {
                "turn": 1,
                "competency": "backend_development",
                "decision": "deepen",
                "question": "How did you design your API?",
            },
            {
                "turn": 2,
                "competency": "problem_solving",
                "decision": "pivot",
                "question": "Tell me about your mentoring experience.",
            },
        ],
        "competency_scores": {
            "backend_development": 0.82,
            "leadership": 0.85,
        },
        "final_score": 0.84,
    }

    audit = validator.verify_auditability(sample_completed_interview)
    assert audit["can_explain_why_question_asked"] is True
    assert audit["can_explain_why_score_assigned"] is True
    assert audit["can_explain_why_pivoted"] is True
    assert audit["can_explain_identity_review"] is True


def test_trace_tamper_protection():
    """Requirement E7.9: Prevent candidate requests from modifying immutable past traces and evaluations."""
    validator = TraceValidator()

    immutable_session = {
        "session_id": "SESS_IMMUTABLE_001",
        "candidate_id": "CAND_001",
        "status": "completed",
        "identity_verified": True,
        "turns": [{"turn": 1, "answer": "I know python."}],
        "competency_scores": {"technical_skills": 0.75},
        "interview_score": 0.75,
    }

    # Malicious candidate attempt to mutate scores and answers
    candidate_tamper_attempt = {
        "interview_score": 1.0,
        "competency_scores": {"technical_skills": 1.0},
    }

    is_allowed, response = validator.enforce_tamper_protection(
        immutable_session, candidate_tamper_attempt
    )

    assert is_allowed is False
    assert response["blocked"] is True
    assert "Access denied" in response["error"]


def test_decision_trace_runner_executes_and_saves_report():
    """Verify execution of full E7 decision-trace benchmark runner."""
    runner = DecisionTraceRunner()
    results = runner.run_and_save()

    assert results["total_traces_evaluated"] >= 6
    assert results["completeness_rate"] == 1.0
    assert results["consistency_rate"] >= 0.60
    assert results["tamper_protection_verified"] is True
    assert results["auditability"]["can_explain_why_question_asked"] is True
