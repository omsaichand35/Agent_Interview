"""Tests for Evidence Extraction Quality (E2).

Validates:
- EvidenceValidator.is_valid contract
- Classification into SUPPORTED, WEAKLY_SUPPORTED, UNSUPPORTED
- Precision, Recall, F1 metrics
- Hallucinated evidence detection & rate calculation
- Evidence strength, specificity, and directness comparison
- Adversarial / hedged phrasing detection
- Complete chain contract: invalid evidence caps competency score at <= 0.20
"""

import json
from pathlib import Path
import pytest

from app.stages.stage1_resume.evidence_validator import EvidenceValidator
from app.schemas.resume import (
    LLMResumeAnalysis,
    LLMCompetencyAssessment,
    LLMEvidence,
)
from app.stages.stage5_recommendation.evaluation.evidence_strength_evaluator import (
    EvidenceCategory,
    EvidenceStrengthEvaluator,
    EvidenceEvaluationRunner,
    calculate_classification_metrics,
    calculate_hallucination_rate,
)


# ==========================================
# 1. EvidenceValidator is_valid Tests (E2.3)
# ==========================================

def test_evidence_validator_is_valid_direct():
    resume = "Built REST APIs using Spring Boot."
    evidence = "Built REST APIs using Spring Boot."
    assert EvidenceValidator.is_valid(resume, evidence)


def test_evidence_validator_is_valid_rejected():
    resume = "Built REST APIs using Spring Boot."
    evidence = "Led a team of 20 engineers."
    assert not EvidenceValidator.is_valid(resume, evidence)


def test_evidence_validator_is_valid_argument_ordering():
    # Supports both (resume, evidence) and (evidence, resume)
    resume = "Alex Mercer designed microservices architecture with FastAPI."
    evidence = "designed microservices architecture"
    assert EvidenceValidator.is_valid(resume, evidence)
    assert EvidenceValidator.is_valid(evidence, resume)


# ==========================================
# 2. Evidence Categorization Tests (E2.1)
# ==========================================

def test_evidence_categorization_supported():
    evaluator = EvidenceStrengthEvaluator()
    resume = "Built a Spring Boot REST API used by 20,000 users."
    evidence = "Built a Spring Boot REST API used by 20,000 users."

    res = evaluator.evaluate_evidence(resume, evidence, "backend_development")
    assert res.classification == EvidenceCategory.SUPPORTED
    assert res.evidence_strength >= 0.85
    assert res.is_valid is True
    assert res.is_hallucinated is False


def test_evidence_categorization_weakly_supported():
    evaluator = EvidenceStrengthEvaluator()
    resume = "Software Engineer with 4 years experience. Worked on backend systems."
    evidence = "Worked on backend systems."

    res = evaluator.evaluate_evidence(resume, evidence, "distributed_systems")
    assert res.classification == EvidenceCategory.WEAKLY_SUPPORTED
    assert 0.20 <= res.evidence_strength <= 0.55
    assert res.is_valid is True


def test_evidence_categorization_unsupported_irrelevant():
    evaluator = EvidenceStrengthEvaluator()
    resume = "Java, Python, SQL"
    evidence = "Java, Python, SQL"

    res = evaluator.evaluate_evidence(resume, evidence, "leadership")
    assert res.classification == EvidenceCategory.UNSUPPORTED
    assert res.evidence_strength <= 0.15


# ==========================================
# 3. Evidence Strength & Specificity (E2.6)
# ==========================================

def test_evidence_strength_comparison():
    """'I know Python' vs 'Built a Python ETL pipeline processing 5 million records per day'."""
    evaluator = EvidenceStrengthEvaluator()

    weak_resume = "Skills: Python, Django, HTML, CSS. I know Python."
    weak_res = evaluator.evaluate_evidence(weak_resume, "I know Python.", "python")

    strong_resume = "Built a Python ETL pipeline processing 5 million records per day."
    strong_res = evaluator.evaluate_evidence(
        strong_resume,
        "Built a Python ETL pipeline processing 5 million records per day.",
        "python",
    )

    # Strong evidence should significantly surpass weak evidence across all dimensions
    assert strong_res.evidence_strength > weak_res.evidence_strength + 0.40
    assert strong_res.specificity > weak_res.specificity + 0.40
    assert strong_res.directness > weak_res.directness + 0.30

    assert weak_res.classification == EvidenceCategory.WEAKLY_SUPPORTED
    assert strong_res.classification == EvidenceCategory.SUPPORTED


# ==========================================
# 4. Hallucination Detection & Rate (E2.5)
# ==========================================

def test_hallucination_detection():
    evaluator = EvidenceStrengthEvaluator()
    resume = "Python, Java, SQL"
    hallucinated_evidence = "Led a team of 10 engineers."

    res = evaluator.evaluate_evidence(resume, hallucinated_evidence, "leadership")
    assert res.is_hallucinated is True
    assert res.is_valid is False
    assert res.classification == EvidenceCategory.UNSUPPORTED
    assert res.evidence_strength == 0.0


def test_hallucination_rate_calculation():
    evaluator = EvidenceStrengthEvaluator()
    resume = "Built APIs with Python."

    results = [
        evaluator.evaluate_evidence(resume, "Built APIs with Python.", "python"),
        evaluator.evaluate_evidence(resume, "Architected petabyte scale streaming platform.", "system_design"),
        evaluator.evaluate_evidence(resume, "Scaled Kubernetes to 500 nodes.", "cloud_devops"),
        evaluator.evaluate_evidence(resume, "Built APIs with Python.", "python"),
    ]

    rate = calculate_hallucination_rate(results)
    # 2 out of 4 are hallucinated -> 0.5
    assert rate == 0.5


# ==========================================
# 5. Adversarial Passive Phrasing (E2.8)
# ==========================================

@pytest.mark.parametrize(
    "passive_phrase,competency",
    [
        ("Familiar with microservices architectures and distributed caching.", "system_design"),
        ("Exposure to Kubernetes cluster deployments in staging.", "cloud_devops"),
        ("Assisted with PostgreSQL database schema migration.", "databases"),
        ("Worked alongside senior engineers who built the payment gateway.", "backend_development"),
        ("Currently learning FastAPI and asynchronous I/O.", "technical_skills"),
    ],
)
def test_adversarial_passive_phrases_penalized(passive_phrase, competency):
    evaluator = EvidenceStrengthEvaluator()
    res = evaluator.evaluate_evidence(passive_phrase, passive_phrase, competency)

    assert res.is_adversarial_passive is True
    # Must be penalized down to WEAKLY_SUPPORTED or UNSUPPORTED, never SUPPORTED
    assert res.classification in (EvidenceCategory.WEAKLY_SUPPORTED, EvidenceCategory.UNSUPPORTED)
    assert res.evidence_strength <= 0.50
    assert res.directness <= 0.45


def test_adversarial_pure_interest_unsupported():
    evaluator = EvidenceStrengthEvaluator()
    text = "Interested in learning distributed systems and high-throughput streaming."
    res = evaluator.evaluate_evidence(text, text, "distributed_systems")

    # Aspirational interest must be classified as UNSUPPORTED
    assert res.classification == EvidenceCategory.UNSUPPORTED
    assert res.evidence_strength <= 0.15


# ==========================================
# 6. Complete Chain: Evidence -> Competency Score (E2.7)
# ==========================================

def test_complete_chain_invalid_evidence_caps_score():
    """An invalid/hallucinated evidence quote must not produce a high competency score."""
    resume_text = "Python, Java, SQL"
    claimed_quote = "Led a team of 10 engineers."

    # Step 1: Evidence validation
    is_valid = EvidenceValidator.is_valid(resume_text, claimed_quote)
    assert is_valid is False

    # Step 2: Evidence Strength evaluation
    evaluator = EvidenceStrengthEvaluator()
    strength_res = evaluator.evaluate_evidence(resume_text, claimed_quote, "leadership")
    assert strength_res.is_valid is False
    assert strength_res.classification == EvidenceCategory.UNSUPPORTED

    # Step 3: LLM Stage 1 Pipeline validation contract
    analysis = LLMResumeAnalysis(
        candidate_name="Test Candidate",
        candidate_email="test@example.com",
        assessments=[
            LLMCompetencyAssessment(
                competency_id="leadership",
                competency_name="Leadership",
                score=0.95,  # Inflated score
                evidence=[LLMEvidence(quote=claimed_quote, relevance=1.0)],
                reasoning="Claimed leadership.",
            )
        ],
    )

    validated_analysis = EvidenceValidator.validate(analysis, resume_text)
    assessment = validated_analysis.assessments[0]

    # Verify contract: score capped at <= 0.20 and evidence stripped
    assert len(assessment.evidence) == 0
    assert assessment.score <= 0.20
    assert "Insufficient directly verifiable resume evidence" in assessment.reasoning


# ==========================================
# 7. End-to-End Evidence Evaluation Runner
# ==========================================

def test_evidence_evaluation_runner_loads_and_executes():
    runner = EvidenceEvaluationRunner()
    results = runner.run_evaluation()

    assert results["total_cases"] >= 30
    metrics = results["metrics"]

    assert metrics["accuracy"] >= 0.85
    assert metrics["macro_f1"] >= 0.85

    # High performance on supported category
    assert metrics["SUPPORTED"]["precision"] >= 0.90
    assert metrics["SUPPORTED"]["recall"] >= 0.90

    # 100% catch rate on hallucination cases
    assert results["hallucination_catch_rate"] == 1.0
    assert results["adversarial_accuracy"] >= 0.85


def test_evidence_evaluation_runner_saves_report(tmp_path):
    runner = EvidenceEvaluationRunner()
    results = runner.run_and_save(output_dir=str(tmp_path))

    json_file = tmp_path / "results.json"
    md_file = tmp_path / "evidence_evaluation_report.md"

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_cases"] == results["total_cases"]

    md_text = md_file.read_text(encoding="utf-8")
    assert "# E2: Evidence Extraction Quality Evaluation Report" in md_text
    assert "SUPPORTED" in md_text
    assert "WEAKLY_SUPPORTED" in md_text
    assert "UNSUPPORTED" in md_text
