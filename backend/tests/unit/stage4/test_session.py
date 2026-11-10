import pytest
from app.schemas.interview import InterviewResult
from app.stages.stage4_interview.session import (
    InterviewSessionManager,
)


class FakePersistence:

    def save_state(self, state):
        return "fake.json"


class FakeGraph:

    def invoke(self, state):

        state["competency_scores"] = {
            "technical_skills": 0.8
        }

        state["next_question"] = (
            "Tell me about a difficult bug you solved."
        )

        state["turn_number"] += 1

        return state


def test_create_session():

    manager = InterviewSessionManager(
        graph=FakeGraph(),
        persistence=FakePersistence(),
    )

    state = manager.create_state(
        session_id="SESSION001",
        candidate_id="C001",
        candidate={
            "name": "Rahul"
        },
        competencies=[
            "technical_skills",
            "leadership",
        ],
    )

    assert state["session_id"] == "SESSION001"
    assert state["candidate_id"] == "C001"
    assert (
        state["current_competency"]
        == "technical_skills"
    )


def test_submit_answer():

    manager = InterviewSessionManager(
        graph=FakeGraph(),
        persistence=FakePersistence(),
    )

    state = manager.create_state(
        session_id="SESSION001",
        candidate_id="C001",
        candidate={},
        competencies=[
            "technical_skills"
        ],
    )

    result = manager.submit_answer(
        state,
        "I fixed a production issue.",
    )

    assert result["competency_scores"][
        "technical_skills"
    ] == 0.8

    assert result["current_question"] == (
        "Tell me about a difficult bug you solved."
    )


def test_build_result_completed():
    manager = InterviewSessionManager(
        graph=FakeGraph(),
        persistence=FakePersistence(),
    )

    state = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "identity_verified": True,
        "interview_complete": True,
        "competency_scores": {"technical_skills": 0.86, "leadership": 0.81},
        "turn_number": 9,
    }

    result = manager.build_result(state)
    assert isinstance(result, InterviewResult)
    assert result.status == "completed"
    assert result["status"] == "completed"
    assert result.identity_verified is True
    assert result.interview_score == 83.5
    assert result.turn_count == 8


def test_build_result_identity_failed():
    manager = InterviewSessionManager(
        graph=FakeGraph(),
        persistence=FakePersistence(),
    )

    state = {
        "session_id": "SESSION002",
        "candidate_id": "C002",
        "identity_verified": False,
        "interview_complete": True,
        "competency_scores": {},
        "turn_number": 3,
    }

    result = manager.build_result(state)
    assert isinstance(result, InterviewResult)
    assert result.status == "identity_failed"
    assert result.identity_verified is False
    assert result.interview_score == 0.0
    assert result.turn_count == 2


def test_build_result_not_complete_raises():
    manager = InterviewSessionManager(
        graph=FakeGraph(),
        persistence=FakePersistence(),
    )

    state = {
        "session_id": "SESSION003",
        "candidate_id": "C003",
        "identity_verified": True,
        "interview_complete": False,
        "competency_scores": {},
        "turn_number": 2,
    }

    with pytest.raises(
        RuntimeError, match="Cannot build result before interview completion."
    ):
        manager.build_result(state)

