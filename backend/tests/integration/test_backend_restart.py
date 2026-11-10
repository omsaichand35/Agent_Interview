"""
C5 integration test: backend restart recovery.

Scenario
--------
1. Start interview SESSION_RESTART.
2. Submit one answer (state advances, conversation_history grows).
3. Persist to disk.
4. Simulate backend restart: instantiate a *brand-new* persistence and
   registry — zero in-memory state from the previous run.
5. Load SESSION_RESTART from the new persistence.
6. Assert session_id, candidate_id, and conversation_history all survive.

The critical invariant: the candidate must be able to continue their
interview after a full backend restart without any data loss.
"""

import uuid
import os
from pathlib import Path

from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM

_TEST_INTERVIEW_DIR = Path(os.environ["TEST_OUTPUT_ROOT"]) / "interviews"

# "Old" server — the process that was running before the restart.
_persistence = InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
_controller = create_interview_controller(
    identity_checkpoint=PassingTestIdentityCheckpoint(),
    llm_client=MockInterviewLLM(),
)
_controller.session_manager.persistence = _persistence


def _start(session_id: str):
    state = _controller.start(
        session_id=session_id,
        candidate_id="C001",
        candidate={"candidate_id": "C001", "name": "Restart Test"},
        competencies=["technical_skills", "problem_solving"],
        first_question="Explain your approach to API design.",
    )
    state.identity_verified = True
    state.identity_status = "verified"
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_session_survives_backend_restart():
    """
    After a full backend restart (new persistence + registry instances),
    the session must be fully restorable from disk.
    """
    session_id = f"SESSION_RESTART_{uuid.uuid4().hex[:6]}"

    # ── "Old" server: start and answer ────────────────────────────────
    state = _start(session_id)
    assert state["session_id"] == session_id

    state = _controller.submit_text(
        state,
        "I built the API using FastAPI with a clean layered architecture.",
    )

    # Conversation must have grown.
    assert state.get("conversation_history"), (
        "conversation_history must be non-empty after an answer"
    )

    # Persist (mirrors what registry.update does automatically in prod).
    _persistence.save(session_id, dict(state))

    # ── Simulate restart: new process, zero in-memory state ───────────
    new_persistence = InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))   # fresh instance — no shared state

    restored = new_persistence.load(session_id)

    # ── Assertions ────────────────────────────────────────────────────
    assert restored is not None, (
        "Session must survive a backend restart and be loadable from disk"
    )

    assert restored["session_id"] == session_id, (
        "session_id must match after restart"
    )

    assert restored["candidate_id"] == "C001", (
        "candidate_id must survive the restart"
    )

    assert restored["conversation_history"], (
        "conversation_history must be preserved across restart so the "
        "candidate does not have to answer the same question again"
    )


def test_new_session_persisted_at_creation():
    """
    registry.create() must persist the session immediately.
    A restart right after /start (before any answer) must still be recoverable.
    """
    from app.stages.stage4_interview.registry import InterviewSessionRegistry

    session_id = f"SESSION_RESTART_EARLY_{uuid.uuid4().hex[:6]}"
    registry = InterviewSessionRegistry(
        persistence=InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
    )

    state = _start(session_id)
    registry.create(session_id, state)   # should auto-persist

    # Simulate restart: fresh persistence, no in-memory cache.
    new_persistence = InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
    restored = new_persistence.load(session_id)

    assert restored is not None, (
        "Session must be recoverable even if the backend restarts before "
        "the candidate has answered a single question"
    )
    assert restored["session_id"] == session_id
    assert restored["candidate_id"] == "C001"


def test_exists_check():
    """exists() must reflect whether the session has been persisted."""
    session_id = f"SESSION_EXISTS_{uuid.uuid4().hex[:6]}"

    p = InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
    assert not p.exists(session_id), "should not exist before save"

    state = _start(session_id)
    p.save(session_id, dict(state))

    assert p.exists(session_id), "should exist after save"


def test_restart_registry_falls_back_to_disk():
    """
    After a backend restart, registry.get() must hydrate from disk
    automatically -- the route handler must not need to change.
    """
    from app.stages.stage4_interview.registry import InterviewSessionRegistry
    from app.stages.stage4_interview.controller import SessionState

    session_id = f"SESSION_RESTART_REG_{uuid.uuid4().hex[:6]}"

    # Old server persists the session.
    state = _start(session_id)
    _persistence.save(session_id, dict(state))

    # New server: brand-new registry with empty in-memory store.
    new_registry = InterviewSessionRegistry(
        persistence=InterviewPersistence(output_dir=str(_TEST_INTERVIEW_DIR))
    )

    restored = new_registry.get(session_id)   # must fall back to disk

    assert restored is not None
    assert restored["session_id"] == session_id
    assert isinstance(restored, SessionState), (
        "Registry must wrap the restored dict in SessionState so attribute "
        "access (state.turn_number) works throughout the route handlers"
    )

