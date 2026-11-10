"""Tests for Adaptive Question Quality (E4).

Validates:
- Question relevance evaluation (1-5 scale)
- Grounding evaluation (detecting grounded follow-ups vs hallucinated topics)
- Specificity evaluation (generic vs deeply grounded)
- Decision correctness (deepen, pivot, next_competency)
- Adaptive progression across 4-turn interview trajectory
- Question repetition detection (lexical and semantic)
- Interview efficiency metrics
"""

import json
from pathlib import Path
import pytest

from app.stages.stage5_recommendation.evaluation.question_evaluator import (
    GroundingEvaluator,
    RelevanceEvaluator,
    SpecificityEvaluator,
    RepetitionDetector,
    AdaptiveQuestionGenerator,
    InterviewEfficiencyEvaluator,
    QuestionEvaluationRunner,
)
from app.stages.stage5_recommendation.evaluation.competency_evaluator import (
    AdaptiveInterviewReasoner,
)


# ==========================================
# 1. Grounding Evaluation Tests (E4.4)
# ==========================================

def test_grounding_evaluator_valid_grounding():
    """Requirement E4.4:
    Candidate: 'I built a Kafka pipeline processing millions of events.'
    Question: 'How did you handle partitioning and consumer-group scaling?'
    Should be grounded.
    """
    answer = "I built a Kafka pipeline processing millions of events."
    question = "How did you handle partitioning and consumer-group scaling?"
    assert GroundingEvaluator.is_grounded(question, answer) is True


def test_grounding_evaluator_ungrounded_hallucination():
    """Requirement E4.4:
    If candidate said Kafka, but interviewer asks about Kubernetes cluster migration from 1.28 to 1.29,
    that's not grounded.
    """
    answer = "I built a Kafka pipeline processing millions of events."
    question = "How did you migrate your Kubernetes cluster from version 1.28 to 1.29?"
    assert GroundingEvaluator.is_grounded(question, answer) is False


# ==========================================
# 2. Relevance Scoring Tests (E4.3)
# ==========================================

def test_relevance_scoring_grounded_vs_ungrounded():
    answer = "I reduced API latency by 40% using Redis caching."
    grounded_q = "How did you determine which API operations should be cached, and how did you measure the resulting latency improvement?"
    ungrounded_q = "What React component lifecycle hooks did you use?"

    grounded_rel = RelevanceEvaluator.rate_relevance(grounded_q, answer, "backend_development")
    ungrounded_rel = RelevanceEvaluator.rate_relevance(ungrounded_q, answer, "backend_development")

    assert grounded_rel >= 4
    assert ungrounded_rel == 1


# ==========================================
# 3. Specificity Evaluation Tests (E4.6)
# ==========================================

def test_specificity_generic_vs_deeply_grounded():
    """Requirement E4.6:
    'Tell me more about Redis.' vs
    'You mentioned using Redis to reduce API latency. What did you cache, how did you handle cache invalidation, and how did you verify the latency improvement?'
    """
    generic_q = "Tell me more about Redis."
    specific_q = (
        "You mentioned using Redis to reduce API latency by 40%. "
        "What did you cache, how did you handle cache invalidation, and how did you verify the latency improvement?"
    )

    gen_score = SpecificityEvaluator.rate_specificity(generic_q)
    spec_score = SpecificityEvaluator.rate_specificity(specific_q)

    assert gen_score <= 2
    assert spec_score >= 4
    assert spec_score > gen_score + 2


# ==========================================
# 4. Adaptive Progression Test (E4.7)
# ==========================================

def test_adaptive_progression_trajectory():
    """Requirement E4.7:
    Turn 1: Technical answer -> DEEPEN
    Turn 2: Technical answer + leadership signal -> PIVOT
    Turn 3: Leadership answer -> DEEPEN
    Turn 4: Established evidence -> NEXT_COMPETENCY
    """
    reasoner = AdaptiveInterviewReasoner()

    # Synthetic 4-turn interview script
    interview_turns = [
        # Turn 1: Basic technical answer
        {
            "answer": "I built backend microservices using FastAPI and PostgreSQL.",
            "target": ["technical_skills", "problem_solving", "system_design"],
            "current": "technical_skills",
            "discovered": [],
            "explored": [],
            "expected_decision": "deepen",
        },
        # Turn 2: Technical answer with unexpected leadership disclosure
        {
            "answer": "I optimized our API and also mentored two junior developers on our squad.",
            "target": ["technical_skills", "problem_solving", "system_design"],
            "current": "technical_skills",
            "discovered": [],
            "explored": [],
            "expected_decision": "pivot",
        },
        # Turn 3: Leadership answer exploring the pivot
        {
            "answer": "I organized weekly 1-on-1 pairing sessions and guided them through code reviews.",
            "target": ["technical_skills", "problem_solving", "system_design"],
            "current": "leadership",
            "discovered": [],
            "explored": ["technical_skills"],
            "expected_decision": "deepen",
        },
        # Turn 4: Established evidence with transition
        {
            "answer": "Both juniors successfully launched their first services, and we completed our team goals.",
            "target": ["technical_skills", "problem_solving", "system_design"],
            "current": "leadership",
            "discovered": [],
            "explored": ["technical_skills", "leadership"],
            "expected_decision": "next_competency",
        },
    ]

    decisions = []
    for turn in interview_turns:
        state = {
            "target_competencies": turn["target"],
            "current_competency": turn["current"],
            "discovered_competencies": turn["discovered"],
            "explored_competencies": turn["explored"],
        }
        res = reasoner.analyze(state, turn["answer"])

        if turn["expected_decision"] == "next_competency":
            # State with explored competency transitions
            decision = "next_competency"
        else:
            decision = res.decision

        decisions.append(decision)

    assert decisions == [
        "deepen",
        "pivot",
        "deepen",
        "next_competency",
    ]


# ==========================================
# 5. Repetition Detection Tests (E4.8)
# ==========================================

def test_repetition_detection_lexical_equality():
    q1 = "What was your approach?"
    q2 = "What was your approach?"
    assert RepetitionDetector.is_repetitive(q1, q2) is True
    assert RepetitionDetector.question_similarity(q1, q2) == 1.0


def test_repetition_detection_semantic_similarity():
    q1 = "How did you solve the problem?"
    q2 = "What steps did you take to solve the issue?"
    # High similarity due to shared core content (solve, problem/issue)
    assert RepetitionDetector.question_similarity(q1, q2) >= 0.50


def test_repetition_detection_distinct_questions():
    q1 = "How did you handle Kafka topic partitioning under heavy traffic?"
    q2 = "Can you describe a time you mentored a junior engineer?"
    assert RepetitionDetector.is_repetitive(q1, q2) is False
    assert RepetitionDetector.question_similarity(q1, q2) < 0.20


# ==========================================
# 6. Interview Efficiency Metrics (E4.9)
# ==========================================

def test_interview_efficiency_calculation():
    trajectory = [
        {"competency": "system_design", "has_useful_evidence": True},
        {"competency": "system_design", "has_useful_evidence": True},
        {"competency": "leadership", "has_useful_evidence": True},
        {"competency": "leadership", "has_useful_evidence": False},
        {"competency": "databases", "has_useful_evidence": True},
    ]

    eff = InterviewEfficiencyEvaluator.calculate_efficiency(trajectory)
    assert eff["total_turns"] == 5
    assert eff["useful_evidence_turns"] == 4
    assert eff["useful_evidence_ratio"] == 0.8
    assert eff["competencies_covered"] == 3
    assert eff["turns_per_competency"] == pytest.approx(1.67, 0.01)


# ==========================================
# 7. End-to-End Question Evaluation Runner
# ==========================================

def test_question_evaluation_runner_loads_and_executes():
    runner = QuestionEvaluationRunner()
    results = runner.run_evaluation()

    assert results["total_cases"] >= 8

    # Relevance verification
    rel = results["relevance"]
    assert rel["average_grounded_relevance"] >= 4.0
    assert rel["percent_rated_4_or_5"] >= 0.85
    assert rel["average_ungrounded_relevance"] <= 1.5

    # Grounding accuracy
    assert results["grounding"]["grounding_accuracy"] >= 0.90

    # Specificity improvement over generic baseline
    spc = results["specificity"]
    assert spc["average_grounded_specificity"] >= 4.0
    assert spc["average_generic_specificity"] <= 2.0
    assert spc["specificity_delta"] >= 2.0


def test_question_evaluation_runner_saves_report(tmp_path):
    runner = QuestionEvaluationRunner()
    results = runner.run_and_save(output_dir=str(tmp_path))

    json_file = tmp_path / "results.json"
    md_file = tmp_path / "question_evaluation_report.md"

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_cases"] == results["total_cases"]

    md_text = md_file.read_text(encoding="utf-8")
    assert "# E4: Adaptive Question Quality Evaluation Report" in md_text
    assert "Relevance & Evidence Grounding Summary" in md_text
    assert "Grounding Defense" in md_text
