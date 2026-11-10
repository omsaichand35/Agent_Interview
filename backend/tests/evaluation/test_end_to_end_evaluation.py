"""Comprehensive test suite for End-to-End AI Hiring Pipeline Evaluation (Requirement E8)."""

from pathlib import Path
import pytest
from app.evaluation.dataset_loader import EndToEndDatasetLoader
from app.evaluation.end_to_end_runner import EndToEndPipelineRunner
from app.evaluation.error_analysis import CriticalInvariantsVerifier, ErrorPropagationAnalyzer
from app.evaluation.metrics import PipelineEvaluationMetrics


def test_dataset_loader_loads_all_components():
    """Verify that E8 dataset loader loads hiring cases, shortlists, interviews, and recommendations."""
    loader = EndToEndDatasetLoader()
    data = loader.load_all()

    assert "cases" in data
    assert "shortlists" in data
    assert "interviews" in data
    assert "recommendations" in data

    assert len(data["cases"]) >= 1
    case = data["cases"][0]
    assert "required_competencies" in case
    assert len(case["candidates"]) >= 4


def test_critical_invariant_1_identity_failure_blocks_automated_recommendation():
    """Invariant 1: If identity is FAIL, automatic recommendation is FORBIDDEN."""
    verifier = CriticalInvariantsVerifier()

    # Violation case: candidate failed identity but system gave HIRE
    invalid_rec = {"decision": "HIRE", "human_review_required": False}
    is_ok, msg = verifier.verify_invariant_1_identity_gate(identity_verified=False, final_recommendation=invalid_rec)
    assert is_ok is False
    assert "Violation of Invariant 1" in msg

    # Compliant case: candidate failed identity and was routed to HUMAN_REVIEW
    compliant_rec = {"decision": "HUMAN_REVIEW", "human_review_required": True}
    is_ok, msg = verifier.verify_invariant_1_identity_gate(identity_verified=False, final_recommendation=compliant_rec)
    assert is_ok is True


def test_critical_invariant_2_unsupported_evidence_cannot_become_strong_evidence():
    """Invariant 2: Unsupported claims cannot be treated as validated strong evidence."""
    verifier = CriticalInvariantsVerifier()

    resume_text = "Junior developer with knowledge of Python and HTML."
    unsupported_claim = "Designed high-throughput Kafka streaming architecture processing 50k events/sec."

    is_ok, msg = verifier.verify_invariant_2_evidence_support(resume_text, unsupported_claim)
    assert is_ok is True
    assert "correctly prevented" in msg


def test_critical_invariant_3_cross_candidate_data_isolation():
    """Invariant 3: Candidate A cannot access Candidate B data (FORBIDDEN)."""
    verifier = CriticalInvariantsVerifier()

    is_ok, msg = verifier.verify_invariant_3_authorization_isolation(
        requesting_candidate_id="CAND_001", target_candidate_id="CAND_002"
    )
    assert is_ok is True
    assert "strictly blocked" in msg


def test_critical_invariant_4_failed_identity_prevents_interview_start():
    """Invariant 4: Failed identity -> STT/Reasoning should not start."""
    verifier = CriticalInvariantsVerifier()

    # Violation: failed identity started interview
    leaked_session = {"interview_started": True, "turns": [{"turn": 1}]}
    is_ok, msg = verifier.verify_invariant_4_interview_identity_gate(identity_verified=False, session_state=leaked_session)
    assert is_ok is False
    assert "Violation of Invariant 4" in msg

    # Compliant: failed identity halted session before turns
    halted_session = {"interview_started": False, "turns": []}
    is_ok, msg = verifier.verify_invariant_4_interview_identity_gate(identity_verified=False, session_state=halted_session)
    assert is_ok is True


def test_critical_invariant_5_persistence_immutability():
    """Invariant 5: Completed stages remain completed after backend restart/reload."""
    verifier = CriticalInvariantsVerifier()

    original_stage = {"stage": "stage1_resume", "status": "completed"}
    reloaded_stage = {"stage": "stage1_resume", "status": "completed"}

    is_ok, msg = verifier.verify_invariant_5_persistence_immutability(original_stage, reloaded_stage)
    assert is_ok is True


def test_error_propagation_containment():
    """Requirement E8.5: Error propagation analysis contains identity failures at Stage 3."""
    analyzer = ErrorPropagationAnalyzer()
    loader = EndToEndDatasetLoader()
    data = loader.load_all()

    case = data["cases"][0]
    cascade = analyzer.analyze_error_cascade(case)

    # CAND_FAIL_IDENT_03 must be contained at Stage 3
    fail_cand = cascade["CAND_FAIL_IDENT_03"]
    assert fail_cand["contained_at"] == "Stage 3 (Identity Gate)"
    assert fail_cand["error_propagated_to_recommendation"] is False
    assert fail_cand["invariant_1_passed"] is True
    assert fail_cand["invariant_4_passed"] is True


def test_end_to_end_pipeline_runner_and_report_generation():
    """Requirement E8.2 & E8.8: EndToEndPipelineRunner runs real components and generates report."""
    runner = EndToEndPipelineRunner()
    results = runner.run()

    assert results["total_cases"] >= 1
    assert results["total_candidates"] >= 4

    metrics = results["metrics"]
    assert metrics["resume_ranking"]["precision_at_10"] >= 0.80
    assert metrics["evidence"]["precision"] >= 0.90
    assert metrics["competency_detection"]["f1"] >= 0.90
    assert metrics["questions"]["relevance"] >= 4.0
    assert metrics["interview_scoring"]["consistency"] >= 0.90
    assert metrics["decision_trace"]["completeness"] == 1.0

    # Verify report existence
    root_dir = Path(__file__).resolve().parents[3]
    report_file = root_dir / "docs" / "ai_evaluation_report.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# AI Hiring Pipeline Evaluation Report" in content
    assert "## 14. Future Improvements" in content
