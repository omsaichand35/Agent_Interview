"""Tests for Competency Detection Quality (E3).

Validates:
- Planned competency detection
- Unexpected competency discovery during interview turns
- False discovery prevention (noise/locations/tools rejected)
- Competency taxonomy normalization
- Graph adaptation & state transition (pivoting on discovered competency)
- Discovery latency (same-turn turnaround)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.stages.stage4_interview.graph.state import InterviewState
from app.stages.stage4_interview.graph.nodes import extract_signals, create_nodes
from app.schemas.interview import InterviewReasoning
from app.stages.stage5_recommendation.evaluation.competency_evaluator import (
    CompetencyNormalizer,
    FalseDiscoveryFilter,
    CompetencyDetector,
    CompetencyEvaluationRunner,
    AdaptiveInterviewReasoner,
)


# ==========================================
# 1. Planned Competency Detection (E3.1 & E3.3)
# ==========================================

def test_planned_competency_detection():
    detector = CompetencyDetector()
    answer = "I debugged a connection pool starvation issue in PostgreSQL and resolved the memory leak."
    planned = ["problem_solving", "databases"]

    res = detector.detect(answer, planned_competencies=planned, current_competency="problem_solving")
    assert "problem_solving" in res.detected_competencies
    assert "databases" in res.detected_competencies
    assert set(res.planned_detected) == {"problem_solving", "databases"}


# ==========================================
# 2. Unexpected Competency Discovery (E3.4)
# ==========================================

def test_unexpected_competency_discovery():
    detector = CompetencyDetector()
    answer = "I optimized our API and mentored two junior developers."
    planned = ["problem_solving", "technical_skills"]

    res = detector.detect(answer, planned_competencies=planned, current_competency="problem_solving")
    # Leadership was not planned but revealed in the answer
    assert "leadership" in res.discovered_competencies
    assert "leadership" in res.detected_competencies


# ==========================================
# 3. False Discovery Prevention (E3.5)
# ==========================================

@pytest.mark.parametrize(
    "noise_answer",
    [
        "I worked from Bangalore and used Jira.",
        "We used Slack for team communication and held Zoom calls.",
        "I had coffee with my manager and we discussed the sprint schedule.",
        "I use Confluence for documentation, Notion for personal notes, and Trello boards.",
    ],
)
def test_false_discovery_prevention(noise_answer):
    detector = CompetencyDetector()
    res = detector.detect(noise_answer, planned_competencies=["technical_skills"], current_competency="technical_skills")

    # None of the noise words should become competencies
    assert len(res.detected_competencies) == 0
    assert len(res.discovered_competencies) == 0
    assert len(res.false_discoveries) == 0


def test_false_discovery_filter_entities():
    filter_fn = FalseDiscoveryFilter.is_irrelevant_noise
    assert filter_fn("Bangalore") is True
    assert filter_fn("Jira") is True
    assert filter_fn("Slack") is True
    assert filter_fn("Zoom") is True
    assert filter_fn("Confluence") is True
    assert filter_fn("python") is False
    assert filter_fn("leadership") is False


# ==========================================
# 4. Competency Normalization (E3.6)
# ==========================================

def test_competency_normalization_leadership():
    normalizer = CompetencyNormalizer()
    variations = [
        "team leadership",
        "led developers",
        "mentored engineers",
        "managed a small engineering team",
        "mentoring",
    ]
    for phrase in variations:
        assert normalizer.normalize(phrase) == "leadership", f"Failed for {phrase}"


def test_competency_normalization_databases():
    normalizer = CompetencyNormalizer()
    variations = [
        "Postgres",
        "PostgreSQL",
        "relational database",
        "sql database",
        "mysql",
    ]
    for phrase in variations:
        assert normalizer.normalize(phrase) == "databases", f"Failed for {phrase}"


def test_competency_normalization_cloud_devops():
    normalizer = CompetencyNormalizer()
    variations = [
        "AWS EKS",
        "container orchestration",
        "k8s",
        "kubernetes",
    ]
    for phrase in variations:
        assert normalizer.normalize(phrase) == "cloud_devops", f"Failed for {phrase}"


def test_competency_normalization_software_engineering():
    normalizer = CompetencyNormalizer()
    variations = [
        "Pytest",
        "unit testing",
        "code reviews",
    ]
    for phrase in variations:
        assert normalizer.normalize(phrase) == "software_engineering", f"Failed for {phrase}"


# ==========================================
# 5. Interview Graph Adaptation Test (E3.7)
# ==========================================

def test_interview_reasoner_discovery_and_decision():
    """Requirement E3.7 from user prompt using reasoner interface."""
    reasoner = AdaptiveInterviewReasoner()
    state = {
        "target_competencies": [
            "technical_skills",
            "problem_solving",
        ],
        "current_competency": "problem_solving",
        "explored_competencies": [],
        "discovered_competencies": [],
    }

    answer = (
        "I optimized the API and also "
        "mentored two junior developers."
    )

    result = reasoner.analyze(
        state=state,
        answer=answer,
    )

    assert "leadership" in result.discovered_competencies
    assert result.decision in {
        "deepen",
        "pivot",
        "next_competency",
        "conclude",
    }
    assert result.decision == "pivot"


def test_interview_graph_nodes_reason_about_answer_adaptation():
    """Verify that graph node reason_about_answer adapts when candidate reveals unexpected competency."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = InterviewReasoning(
        decision="deepen",
        rationale="Candidate answered well.",
        question_intent="deepen technical skills",
        confidence=0.9,
    )

    reason_about_answer, _, _ = create_nodes(mock_llm)

    state: InterviewState = {
        "session_id": "test_sess_001",
        "candidate_id": "C001",
        "candidate": {"name": "Alex Mercer"},
        "target_competencies": ["technical_skills", "problem_solving"],
        "current_competency": "problem_solving",
        "explored_competencies": [],
        "discovered_competencies": [],
        "conversation_history": [],
        "current_question": "Tell me about a difficult technical problem.",
        "candidate_answer": "I optimized the API and also mentored two junior developers.",
        "trigger_phrase": None,
        "extracted_signals": [],
        "reasoning": None,
        "reasoning_confidence": 0.0,
        "decision": "deepen",
        "next_question": None,
        "evidence": {},
        "evaluation": None,
        "competency_scores": {},
        "identity_verified": True,
        "identity_status": "verified",
        "identity_failure_reason": None,
        "last_identity_confidence": 0.95,
        "identity_check_count": 1,
        "identity_checks": [],
        "current_live_frame": None,
        "turn_number": 1,
        "interview_complete": False,
        "workflow_condition": None,
        "bad_answer_count": 0,
        "recovery_attempted": False,
    }

    updated_state = reason_about_answer(state)

    # Discovered competencies must capture leadership
    assert "leadership" in updated_state["discovered_competencies"]
    # Decision must adapt to pivot to the newly discovered competency
    assert updated_state["decision"] == "pivot"


def test_extract_signals_node():
    """Verify extract_signals node in graph extracts leadership from candidate answer."""
    state = {
        "candidate_answer": "I optimized the API and mentored two junior developers.",
        "target_competencies": ["problem_solving"],
        "extracted_signals": [],
    }
    updated = extract_signals(state)
    assert "leadership" in updated["extracted_signals"]
    assert "problem_solving" in updated["extracted_signals"]


# ==========================================
# 6. Discovery Latency Evaluation (E3.8)
# ==========================================

def test_discovery_latency_within_turn_cycle():
    detector = CompetencyDetector()
    answer = "I optimized our API and mentored two junior developers."

    res = detector.detect(answer, planned_competencies=["problem_solving"])
    # Turn turnaround latency must be sub-millisecond to 50ms
    assert res.latency_ms < 50.0
    assert "leadership" in res.discovered_competencies


# ==========================================
# 7. End-to-End Competency Evaluation Runner
# ==========================================

def test_competency_evaluation_runner_loads_and_executes():
    runner = CompetencyEvaluationRunner()
    results = runner.run_evaluation()

    assert results["total_cases"] >= 20

    # Detection & Discovery Metrics
    assert results["overall_detection"]["precision"] >= 0.90
    assert results["overall_detection"]["recall"] >= 0.85
    assert results["overall_detection"]["f1"] >= 0.85

    assert results["discovery_metrics"]["recall"] >= 0.85

    # False discovery must be 0%
    assert results["false_discovery"]["false_discovery_rate"] == 0.0
    assert results["false_discovery"]["noise_rejection_rate"] == 1.0

    # Normalization accuracy
    assert results["normalization"]["normalization_accuracy"] >= 0.95

    # Latency check
    assert results["latency"]["within_turn_cycle"] is True
    assert results["latency"]["turn_delay"] == 0


def test_competency_evaluation_runner_saves_report(tmp_path):
    runner = CompetencyEvaluationRunner()
    results = runner.run_and_save(output_dir=str(tmp_path))

    json_file = tmp_path / "results.json"
    md_file = tmp_path / "competency_evaluation_report.md"

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_cases"] == results["total_cases"]

    md_text = md_file.read_text(encoding="utf-8")
    assert "# E3: Competency Detection & Discovery Quality Evaluation Report" in md_text
    assert "Unexpected Competency Discovery" in md_text
    assert "False Discovery Prevention" in md_text
