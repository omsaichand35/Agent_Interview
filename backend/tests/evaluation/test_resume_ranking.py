"""Tests for Resume Ranking Quality (E1) metrics and evaluation runner."""

import json
from pathlib import Path
import pytest

from app.schemas.resume import (
    CompetencyAssessment as SchemaAssessment,
    Evidence as SchemaEvidence,
    LLMResumeAnalysis,
)
from app.stages.stage1_resume.evidence_validator import EvidenceValidator
from app.stages.stage5_recommendation.evaluation.ranking_metrics import (
    precision_at_k,
    recall_at_k,
    dcg_at_k,
    ndcg_at_k,
    spearman_correlation,
    kendall_rank_correlation,
    mean_reciprocal_rank,
)
from app.stages.stage5_recommendation.evaluation.evidence_metrics import (
    EvidenceCorrectness,
    verify_evidence_quote,
    score_evidence_support,
    detect_unsupported_claims,
    calculate_evidence_validity_rate,
    validate_and_penalize_competency,
)
from app.stages.stage5_recommendation.evaluation.evaluation_runner import (
    EvaluationRunner,
    BaselineKeywordRanker,
    AICompetencyEvidenceRanker,
)


# ==========================================
# 1. Ranking Metrics Tests
# ==========================================

def test_precision_at_k():
    predicted = ["C001", "C002", "C003", "C004", "C005"]
    relevant = {"C001", "C003", "C005", "C007"}

    # Top 3: C001, C002, C003 -> C001 and C003 relevant -> 2 / 3
    assert precision_at_k(predicted, relevant, k=3) == pytest.approx(2 / 3, 0.001)
    # Top 5: C001, C002, C003, C004, C005 -> 3 relevant -> 3 / 5 = 0.6
    assert precision_at_k(predicted, relevant, k=5) == 0.6
    # Edge case: empty predictions or k=0
    assert precision_at_k([], relevant, k=5) == 0.0
    assert precision_at_k(predicted, relevant, k=0) == 0.0


def test_recall_at_k():
    predicted = ["C001", "C002", "C003", "C004", "C005"]
    relevant = {"C001", "C003", "C005", "C007"}  # 4 total relevant

    # Top 3: C001, C003 -> 2 / 4 = 0.5
    assert recall_at_k(predicted, relevant, k=3) == 0.5
    # Top 5: C001, C003, C005 -> 3 / 4 = 0.75
    assert recall_at_k(predicted, relevant, k=5) == 0.75
    # Edge case: no relevant candidates
    assert recall_at_k(predicted, set(), k=5) == 0.0


def test_dcg_and_ndcg_at_k():
    relevance = {"C001": 5.0, "C002": 4.0, "C003": 3.0, "C004": 2.0, "C005": 1.0}

    # Perfect ranking matches ideal DCG -> NDCG must be 1.0
    perfect_ranking = ["C001", "C002", "C003", "C004", "C005"]
    assert ndcg_at_k(perfect_ranking, relevance, k=5) == 1.0

    # Inverted ranking must produce significantly lower NDCG
    inverted_ranking = ["C005", "C004", "C003", "C002", "C001"]
    ndcg_inverted = ndcg_at_k(inverted_ranking, relevance, k=5)
    assert 0.0 < ndcg_inverted < 0.7

    # Edge cases
    assert ndcg_at_k([], relevance, k=5) == 0.0
    assert ndcg_at_k(perfect_ranking, {}, k=5) == 0.0


def test_spearman_correlation():
    # Perfectly correlated
    assert spearman_correlation([10, 20, 30, 40], [1, 2, 3, 4]) == 1.0
    # Perfectly anti-correlated
    assert spearman_correlation([40, 30, 20, 10], [1, 2, 3, 4]) == -1.0
    # Handles tied ranks without crashing
    tied_res = spearman_correlation([10, 20, 20, 40], [1, 2, 2, 4])
    assert tied_res == 1.0


def test_kendall_rank_correlation():
    # Perfectly concordant
    assert kendall_rank_correlation([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0
    # Perfectly discordant
    assert kendall_rank_correlation([5, 4, 3, 2, 1], [10, 20, 30, 40, 50]) == -1.0


def test_mean_reciprocal_rank():
    ranked = ["C002", "C001", "C003"]
    # First relevant at index 1 (rank 2)
    assert mean_reciprocal_rank(ranked, {"C001"}) == 0.5
    # First relevant at rank 1
    assert mean_reciprocal_rank(["C001", "C002"], {"C001"}) == 1.0
    # None relevant
    assert mean_reciprocal_rank(["C001", "C002"], {"C099"}) == 0.0


# ==========================================
# 2. Evidence Metrics & Unsupported Claim Tests
# ==========================================

def test_verify_evidence_quote():
    resume = "Alex Mercer is a Senior Engineer with 6 years experience in Python and FastAPI."
    assert verify_evidence_quote("6 years experience in Python and FastAPI", resume) is True
    assert verify_evidence_quote("experience in python", resume) is True
    assert verify_evidence_quote("Led a team of 50 engineers", resume) is False


def test_score_evidence_support():
    resume = "Built asynchronous REST services with FastAPI and PostgreSQL."
    # Direct match -> 5
    assert score_evidence_support("FastAPI and PostgreSQL", resume) == EvidenceCorrectness.DIRECTLY_SUPPORTED
    # High token overlap -> 4
    assert score_evidence_support("built asynchronous REST APIs with FastAPI and Postgres", resume) in (
        EvidenceCorrectness.STRONGLY_SUPPORTED,
        EvidenceCorrectness.DIRECTLY_SUPPORTED,
    )
    # Fabricated / completely ungrounded -> 1
    assert score_evidence_support("Architected quantum computing infrastructure", resume) == EvidenceCorrectness.UNSUPPORTED


def test_detect_unsupported_claim_user_example():
    """Requirement E1.5:
    Resume: 'Python, Java, SQL'
    AI evidence: 'Led a team of 10 engineers.'
    That should fail validation.
    """
    resume_text = "Python, Java, SQL"
    evidence_claims = [
        {"quote": "Led a team of 10 engineers."},
    ]

    # 1. Detection via detect_unsupported_claims
    unsupported = detect_unsupported_claims(evidence_claims, resume_text, strict=True)
    assert len(unsupported) == 1
    assert unsupported[0]["quote"] == "Led a team of 10 engineers."
    assert unsupported[0]["support_score"] == int(EvidenceCorrectness.UNSUPPORTED)

    # 2. Rejection & capping via validate_and_penalize_competency
    assessment = {
        "competency_id": "leadership",
        "score": 0.85,
        "evidence": evidence_claims,
    }
    penalized = validate_and_penalize_competency(assessment, resume_text, penalty_cap=0.2)
    assert penalized["score"] <= 0.2
    assert len(penalized["evidence"]) == 0
    assert penalized["is_supported"] is False
    assert "Insufficient directly verifiable resume evidence" in penalized["reasoning"]


def test_existing_evidence_validator_with_unsupported_claim():
    """Verify integration with existing EvidenceValidator in Stage 1."""
    from app.schemas.resume import (
        LLMCompetencyAssessment,
        LLMEvidence,
        LLMResumeAnalysis,
    )

    resume_text = "Python, Java, SQL"
    unsupported_analysis = LLMResumeAnalysis(
        candidate_name="Test Candidate",
        candidate_email="test@example.com",
        assessments=[
            LLMCompetencyAssessment(
                competency_id="leadership",
                competency_name="Leadership",
                score=0.9,
                evidence=[
                    LLMEvidence(
                        quote="Led a team of 10 engineers.",
                        relevance=1.0,
                    )
                ],
                reasoning="Claimed leadership over 10 engineers.",
            )
        ],
    )

    validated = EvidenceValidator.validate(unsupported_analysis, resume_text)
    # Evidence must be stripped and score capped at 0.2
    assert len(validated.assessments[0].evidence) == 0
    assert validated.assessments[0].score <= 0.2
    assert "Insufficient directly verifiable resume evidence" in validated.assessments[0].reasoning


def test_evidence_validity_rate():
    evals = [
        {"is_valid": True},
        {"is_valid": True},
        {"is_valid": False},
        {"is_valid": True},
    ]
    # 3 out of 4 valid -> 0.75
    assert calculate_evidence_validity_rate(evals) == 0.75


# ==========================================
# 3. End-to-End Evaluation Runner Tests
# ==========================================

def test_evaluation_runner_loads_dataset():
    runner = EvaluationRunner()
    candidates, labels, job = runner.load_data()

    assert len(candidates) >= 20
    assert len(labels) >= 20
    assert job.get("job_id") == "JOB001"
    assert "required_skills" in job


def test_evaluation_runner_executes_and_compares():
    runner = EvaluationRunner()
    results = runner.run_evaluation(k=10)

    assert results["job_id"] == "JOB001"
    assert results["candidate_count"] >= 20
    assert results["shortlist_k"] == 10

    base = results["baseline"]
    ai = results["ai_system"]

    # Verify presence of all key metrics
    for m in ["precision_at_10", "recall_at_10", "ndcg_at_10", "spearman_correlation", "kendall_tau", "evidence_validity"]:
        assert m in base, f"Missing {m} in baseline"
        assert m in ai, f"Missing {m} in ai_system"

    # AI system semantic reasoning + evidence validation should outperform or equal pure keyword baseline
    assert ai["precision_at_10"] >= base["precision_at_10"]
    assert ai["ndcg_at_10"] >= base["ndcg_at_10"]
    assert ai["evidence_validity"] >= 0.85

    # Unsupported claims must be detected and filtered
    assert len(results["unsupported_claims_detected"]) >= 2


def test_evaluation_runner_saves_results(tmp_path):
    runner = EvaluationRunner()
    results = runner.run_and_save(k=10, output_dir=str(tmp_path))

    json_file = tmp_path / "results.json"
    md_file = tmp_path / "evaluation_report.md"

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        saved_json = json.load(f)
    assert saved_json["job_id"] == results["job_id"]

    md_content = md_file.read_text(encoding="utf-8")
    assert "# E1: Resume Ranking Quality Evaluation Report" in md_content
    assert "Precision@10" in md_content
    assert "NDCG@10" in md_content
