"""Unit and benchmark tests for Interview Scoring Consistency (Requirement E5)."""

import pytest
from app.stages.stage4_interview.evaluation.evidence_aggregator import EvidenceAggregator
from app.stages.stage4_interview.evaluation.interview_scorer import InterviewScorer
from app.stages.stage5_recommendation.evaluation.interview_scoring_evaluator import (
    ConsistencyMetrics,
    DeterministicAnswerEvaluator,
    InterviewScoringRunner,
)


def test_equivalent_answers_receive_similar_scores():
    """Requirement E5.2: Semantically equivalent answers must receive similar scores."""
    evaluator = DeterministicAnswerEvaluator()

    answer_a = "I reduced API latency by 40% using Redis caching. I measured latency before and after the change."
    answer_b = "We used Redis to cache frequently accessed API data. After implementing it, I compared the response times and saw roughly a 40% reduction."

    res_a = evaluator.evaluate("problem_solving", answer_a)
    res_b = evaluator.evaluate("problem_solving", answer_b)

    score_diff = abs(res_a.score - res_b.score)
    assert score_diff <= 0.08, f"Score difference {score_diff} exceeded tolerance 0.08"
    assert 0.70 <= res_a.score <= 1.0
    assert 0.70 <= res_b.score <= 1.0


def test_evidence_sensitivity_stronger_evidence_raises_score():
    """Requirement E5.4: Evaluator must respond when evidence quality changes."""
    evaluator = DeterministicAnswerEvaluator()

    weak_answer = "I worked on APIs."
    strong_answer = "I designed the REST API, introduced Redis caching, and reduced p95 latency from 420 ms to 180 ms."

    res_weak = evaluator.evaluate("backend_development", weak_answer)
    res_strong = evaluator.evaluate("backend_development", strong_answer)

    assert res_strong.score > res_weak.score
    assert (res_strong.score - res_weak.score) >= 0.30
    assert res_weak.score <= 0.45
    assert res_strong.score >= 0.75
    assert res_strong.evidence_quality > res_weak.evidence_quality
    assert res_strong.technical_depth > res_weak.technical_depth
    assert res_strong.specificity > res_weak.specificity


def test_unsupported_claims_do_not_become_strong_evidence():
    """Requirement E5.5: Grand claims without supporting details must be capped."""
    evaluator = DeterministicAnswerEvaluator()

    unsupported_answer = "I designed a distributed system handling 10 million requests per second."
    res = evaluator.evaluate("system_design", unsupported_answer)

    assert res.score <= 0.35
    assert res.evidence_quality <= 0.35
    assert "unsubstantiated" in res.reasoning.lower()


def test_score_stability_across_repeated_evaluations():
    """Requirement E5.6: Repeated evaluation of identical answer must be stable with negligible variance."""
    evaluator = DeterministicAnswerEvaluator()
    answer = "I architected partitioned PostgreSQL clusters with Redis caching, reducing p99 latency to 28ms."

    scores = [
        evaluator.evaluate("system_design", answer).score
        for _ in range(10)
    ]

    variance = ConsistencyMetrics.score_variance(scores)
    std = ConsistencyMetrics.standard_deviation(scores)

    assert variance < 0.001
    assert std < 0.03
    assert all(scores[0] == s for s in scores)


def test_competency_aggregation_weak_start_does_not_erase_accumulated_evidence():
    """Requirement E5.7: One accidental weak answer must not erase strong evidence accumulated across turns."""
    aggregator = EvidenceAggregator()

    # Turn 1 weak (0.35), Turn 2 strong (0.85), Turn 3 strong (0.88)
    evidence_history = {
        "backend_development": [
            {"score": 0.35},
            {"score": 0.85},
            {"score": 0.88},
        ]
    }

    aggregated = aggregator.aggregate(evidence_history)
    final_score = aggregated["backend_development"]

    # In EvidenceAggregator: average (0.693) * 0.7 + max (0.88) * 0.3 = 0.749
    assert final_score >= 0.70
    assert 0.0 <= final_score <= 1.0


def test_competency_aggregation_unsupported_turn_does_not_dominate():
    """Requirement E5.7: An unsupported claim at the end must not wipe out prior demonstrated expertise."""
    aggregator = EvidenceAggregator()

    # Turn 1 excellent (0.90), Turn 2 excellent (0.92), Turn 3 unsupported claim (0.30)
    evidence_history = {
        "databases": [
            {"score": 0.90},
            {"score": 0.92},
            {"score": 0.30},
        ]
    }

    aggregated = aggregator.aggregate(evidence_history)
    final_score = aggregated["databases"]

    # Robust preservation of demonstrated mastery
    assert final_score >= 0.75
    assert 0.0 <= final_score <= 1.0


def test_final_interview_scorer_contract():
    """Requirement E5.8: InterviewScorer calculates overall score strictly bounded [0.0, 1.0]."""
    scorer = InterviewScorer()

    competency_scores = {
        "technical_skills": 0.80,
        "problem_solving": 0.75,
        "leadership": 0.70,
    }

    score_result = scorer.calculate(competency_scores=competency_scores)
    assert score_result is not None
    assert 0.0 <= score_result <= 1.0
    assert score_result == 0.75

    # Backwards compatibility check
    percent_score = scorer.score(competency_scores=competency_scores)
    assert percent_score == 75.0


def test_interview_scoring_runner_executes_and_saves_report():
    """Verify end-to-end benchmark execution and report persistence."""
    runner = InterviewScoringRunner()
    results = runner.run_and_save()

    assert results["equivalent_pairs"]["total_pairs"] >= 4
    assert results["equivalent_pairs"]["tolerance_pass_rate"] == 1.0
    assert results["evidence_sensitivity"]["all_passed"] is True
    assert results["unsupported_claims"]["all_properly_capped"] is True
    assert results["multi_turn_aggregation"]["all_passed"] is True
    assert results["stability"]["is_stable"] is True
    assert 0.0 <= results["interview_scorer"]["final_interview_score"] <= 1.0
