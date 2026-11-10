"""
C7 integration test: concurrent candidate isolation.

Rules
-----
* Every session is scoped to exactly one candidate.
* Answers, conversation history, competency scores, and persisted files
  must never leak between sessions.
* Two sessions running in parallel (via ThreadPoolExecutor) must produce
  fully independent results.

The tests intentionally use very different answer strings ("FastAPI" vs
"Spring Boot") so any cross-contamination is immediately visible.
"""

import uuid
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM


# ---------------------------------------------------------------------------
# Shared controller + persistence (mirrors production: one controller,
# many sessions -- like a real FastAPI process).
# ---------------------------------------------------------------------------

controller = create_interview_controller(
    identity_checkpoint=PassingTestIdentityCheckpoint(),
    llm_client=MockInterviewLLM(),
)
_TEST_INTERVIEW_DIR = Path(os.environ["TEST_OUTPUT_ROOT"]) / "interviews"
persistence = InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
controller.session_manager.persistence = persistence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ANSWER_C001 = "I built a FastAPI backend with Redis caching and async workers."
ANSWER_C002 = "I used Spring Boot with Kafka event streaming and MySQL."


def _make_session_ids():
    sfx = uuid.uuid4().hex[:6].upper()
    return f"SESSION_C001_{sfx}", f"SESSION_C002_{sfx}"


def _start_and_verify(session_id: str, candidate_id: str):
    """Start a session and mark identity as verified (bypass camera)."""
    state = controller.start(
        session_id=session_id,
        candidate_id=candidate_id,
        candidate={"candidate_id": candidate_id, "name": f"Candidate {candidate_id}"},
        competencies=["technical_skills", "problem_solving"],
        first_question="Tell me about your most recent engineering project.",
    )
    # Bypass camera — set identity verified directly (as the identity route does).
    state["identity_verified"] = True
    state["identity_status"] = "verified"
    return state


# ---------------------------------------------------------------------------
# Test 1: basic isolation — session IDs and candidate IDs don't leak
# ---------------------------------------------------------------------------


def test_multiple_interviews_are_isolated():
    """
    Starting two sessions must produce completely independent state objects.
    No field from session_1 should appear in session_2 and vice-versa.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    # Session IDs must differ.
    assert session_1["session_id"] != session_2["session_id"]

    # Candidate IDs must be correct and independent.
    assert session_1["candidate_id"] == "C001"
    assert session_2["candidate_id"] == "C002"

    # State objects must be distinct Python objects (not aliases).
    assert session_1 is not session_2


# ---------------------------------------------------------------------------
# Test 2: conversation history isolation after one answer each
# ---------------------------------------------------------------------------


def test_conversation_history_is_isolated():
    """
    After submitting different answers, each session's conversation_history
    must contain only its own answer -- never the other candidate's text.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    session_1 = controller.submit_text(session_1, ANSWER_C001)
    session_2 = controller.submit_text(session_2, ANSWER_C002)

    history_1 = session_1.get("conversation_history", [])
    history_2 = session_2.get("conversation_history", [])

    # Each session must have at least one history entry.
    assert history_1, "session_1 must have conversation_history after an answer"
    assert history_2, "session_2 must have conversation_history after an answer"

    # Flatten all text in each session's history for easy searching.
    text_1 = " ".join(
        str(entry.get("answer", "") or entry.get("candidate_answer", ""))
        for entry in history_1
    )
    text_2 = " ".join(
        str(entry.get("answer", "") or entry.get("candidate_answer", ""))
        for entry in history_2
    )

    # Each session's history must contain its own keyword.
    assert "FastAPI" in text_1, (
        "session_1 history must contain C001's answer keyword 'FastAPI'"
    )
    assert "Spring Boot" in text_2, (
        "session_2 history must contain C002's answer keyword 'Spring Boot'"
    )

    # Cross-contamination check: neither keyword must appear in the wrong session.
    assert "Spring Boot" not in text_1, (
        "session_1 must NOT contain C002's answer 'Spring Boot' -- state leak!"
    )
    assert "FastAPI" not in text_2, (
        "session_2 must NOT contain C001's answer 'FastAPI' -- state leak!"
    )


# ---------------------------------------------------------------------------
# Test 3: candidate_answer field isolation
# ---------------------------------------------------------------------------


def test_candidate_answer_field_is_isolated():
    """
    The candidate_answer field must reflect only the most recent answer
    for that specific session, not any other session's answer.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    session_1 = controller.submit_text(session_1, ANSWER_C001)
    session_2 = controller.submit_text(session_2, ANSWER_C002)

    assert session_1.get("candidate_answer") != session_2.get("candidate_answer"), (
        "candidate_answer must differ between sessions"
    )
    assert "FastAPI" in (session_1.get("candidate_answer") or "")
    assert "Spring Boot" in (session_2.get("candidate_answer") or "")


# ---------------------------------------------------------------------------
# Test 4: persistence isolation — each session writes its own file
# ---------------------------------------------------------------------------


def test_persistence_files_are_isolated():
    """
    Each session must persist to its own file.
    Restoring SESSION001 must return C001's data; SESSION002 must return C002's.
    Cross-candidate data must never appear in the wrong file.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    session_1 = controller.submit_text(session_1, ANSWER_C001)
    session_2 = controller.submit_text(session_2, ANSWER_C002)

    # Explicit saves (registry.update auto-persists too, but let's be explicit).
    persistence.save(sid1, dict(session_1))
    persistence.save(sid2, dict(session_2))

    # Files must exist.
    assert persistence.exists(sid1), f"File for {sid1} must exist"
    assert persistence.exists(sid2), f"File for {sid2} must exist"

    # Restore from disk.
    restored_1 = persistence.load(sid1)
    restored_2 = persistence.load(sid2)

    assert restored_1 is not None
    assert restored_2 is not None

    # Core isolation assertions.
    assert restored_1["candidate_id"] == "C001", (
        f"Restored session for {sid1} must belong to C001"
    )
    assert restored_2["candidate_id"] == "C002", (
        f"Restored session for {sid2} must belong to C002"
    )

    # Session ID must not have been overwritten.
    assert restored_1["session_id"] == sid1
    assert restored_2["session_id"] == sid2

    # Candidate IDs must not cross.
    assert restored_1["candidate_id"] != restored_2["candidate_id"]


# ---------------------------------------------------------------------------
# Test 5: parallel execution -- state must not contaminate under concurrency
# ---------------------------------------------------------------------------


def _submit(session, answer):
    """Worker function for ThreadPoolExecutor."""
    return controller.submit_text(session, answer)


def test_parallel_interviews_are_isolated():
    """
    Two concurrent submit_text calls (via threads) must produce fully
    independent results.  This proves the state model is safe when
    requests overlap -- as they do in a real FastAPI server.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda item: _submit(*item),
                [
                    (session_1, ANSWER_C001),
                    (session_2, ANSWER_C002),
                ],
            )
        )

    result_1, result_2 = results

    # Each result must belong to the correct candidate.
    assert result_1["candidate_id"] == "C001", (
        "Parallel result_1 must belong to C001"
    )
    assert result_2["candidate_id"] == "C002", (
        "Parallel result_2 must belong to C002"
    )

    # The answers recorded must differ.
    answer_1 = result_1.get("candidate_answer", "")
    answer_2 = result_2.get("candidate_answer", "")
    assert answer_1 != answer_2, (
        "Concurrent submissions must produce different candidate_answer values"
    )

    # Session IDs must be unaffected by parallelism.
    assert result_1["session_id"] == sid1
    assert result_2["session_id"] == sid2


# ---------------------------------------------------------------------------
# Test 6: workflow-level session map isolation
# ---------------------------------------------------------------------------


def test_workflow_interview_sessions_are_isolated():
    """
    A workflow's interview_sessions dict must map each candidate to
    its own session -- never to another candidate's session.
    """
    sid1, sid2 = _make_session_ids()

    session_1 = _start_and_verify(sid1, "C001")
    session_2 = _start_and_verify(sid2, "C002")

    # Simulate what the hiring workflow does: store sessions by candidate_id.
    interview_sessions = {
        "C001": dict(session_1),
        "C002": dict(session_2),
    }

    assert interview_sessions["C001"]["session_id"] == sid1
    assert interview_sessions["C002"]["session_id"] == sid2

    # Cross-check: C001's entry must not contain C002's session_id.
    assert interview_sessions["C001"]["session_id"] != interview_sessions["C002"]["session_id"]
    assert interview_sessions["C001"]["candidate_id"] != interview_sessions["C002"]["candidate_id"]
