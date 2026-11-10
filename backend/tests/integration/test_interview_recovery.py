import uuid
import os
from pathlib import Path
import pytest
from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM

controller = create_interview_controller(
    identity_checkpoint=PassingTestIdentityCheckpoint(),
    llm_client=MockInterviewLLM(),
)
controller.session_manager.persistence = InterviewPersistence(
    output_dir=str(Path(os.environ["TEST_OUTPUT_ROOT"]) / "interviews")
)


def start_interview():
    session_id = f"SESSION_REC_{uuid.uuid4().hex[:8]}"
    state = controller.start(
        session_id=session_id,
        candidate_id="C001",
        candidate={"candidate_id": "C001", "name": "Candidate"},
        competencies=["technical_skills", "problem_solving", "leadership"],
        first_question="Explain a technical challenge you solved.",
    )
    state.identity_verified = True
    state.identity_status = "verified"
    return state


def test_single_bad_answer_recovers():

    state = start_interview()

    state = controller.submit_text(
        state,
        "I don't know.",
    )

    assert state.interview_complete is False
    assert state.bad_answer_count == 1
    assert state.current_question is not None
    assert "Let's continue" in state.current_question


def test_repeated_bad_answers_conclude():

    state = start_interview()

    state = controller.submit_text(
        state,
        "I don't know.",
    )

    state = controller.submit_text(
        state,
        "I don't know.",
    )

    assert state.interview_complete is True


def test_bad_answer_recovery_then_good_answer_resets():

    state = start_interview()

    # Turn 1: Bad answer triggers recovery
    state = controller.submit_text(
        state,
        "I don't know.",
    )
    assert state.interview_complete is False
    assert state.bad_answer_count == 1
    assert state.recovery_attempted is True

    # Turn 2: Helpful answer resets bad_answer_count
    state = controller.submit_text(
        state,
        "I optimized our PostgreSQL database indexes and reduced query latency by 80%.",
    )
    assert state.interview_complete is False
    assert state.bad_answer_count == 0


def test_adaptive_pivot_on_new_signal():

    state = start_interview()

    # Answer contains technical challenge + database optimization + leadership/mentoring
    answer = "We had a slow API. I optimized the database queries. I also mentored two juniors while fixing it."

    state = controller.submit_text(
        state,
        answer,
    )

    assert state.interview_complete is False
    assert state.decision == "pivot"
    assert "leadership" in state.extracted_signals or "leadership" in state.discovered_competencies
    assert state.current_competency == "leadership"
    assert state.current_question is not None
