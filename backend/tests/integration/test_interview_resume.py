"""
C4 integration test: browser / network failure recovery.

Scenario
--------
1. Start interview SESSION_RECONNECT.
2. Submit one answer (state advances, auto-persisted via registry.update).
3. Simulate "browser crash" by discarding all in-memory state.
4. New client restores: persistence.load() reads from disk.
5. Verify session_id, turn_number, and current_question are unchanged.

The critical invariant: SESSION_RECONNECT must remain SESSION_RECONNECT.
A browser failure must NEVER create a new interview session.
"""

import uuid
import os
from pathlib import Path

from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM

# Shared persistence pointing at the same dir as the application.
persistence = InterviewPersistence(
    output_dir=str(Path(os.environ["TEST_OUTPUT_ROOT"]) / "interviews")
)
controller = create_interview_controller(
    identity_checkpoint=PassingTestIdentityCheckpoint(),
    llm_client=MockInterviewLLM(),
)
controller.session_manager.persistence = persistence


def _start(session_id: str):
    state = controller.start(
        session_id=session_id,
        candidate_id="C001",
        candidate={"candidate_id": "C001", "name": "Test Candidate"},
        competencies=["technical_skills", "problem_solving"],
        first_question="Explain how you designed your backend API.",
    )
    state.identity_verified = True
    state.identity_status = "verified"
    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_interview_survives_client_reconnect():
    """
    Persisting after each answer means a browser crash loses nothing.
    Restoring from disk must return the exact same session.
    """
    session_id = f"SESSION_RECONNECT_{uuid.uuid4().hex[:6]}"

    # ── 1. Start ───────────────────────────────────────────────────────
    state = _start(session_id)
    assert state["session_id"] == session_id

    # ── 2. Submit one answer ───────────────────────────────────────────
    state = controller.submit_text(
        state,
        "I designed the backend using FastAPI with a layered architecture.",
    )

    live_turn = state.get("turn_number", 1)
    live_question = state.get("current_question") or state.get("next_question", "")

    # ── 3. Persist to disk (mirrors what registry.update now does) ─────
    persistence.save(session_id, dict(state))

    # ── 4. Simulate browser crash: discard all in-memory state ─────────
    del state

    # ── 5. New client: restore from disk ──────────────────────────────
    restored = persistence.load(session_id)

    assert restored is not None, (
        "Session must be recoverable from disk after client disconnect"
    )

    # ── 6. The core invariant: same session, same progress ────────────
    assert restored["session_id"] == session_id, (
        "Restored session_id must match original — "
        "a browser failure must NOT create a new session"
    )

    assert restored["turn_number"] == live_turn, (
        f"Expected turn_number={live_turn}, got {restored['turn_number']}"
    )

    restored_question = restored.get("current_question") or restored.get(
        "next_question", ""
    )
    assert restored_question == live_question, (
        "Restored current_question must match live state so the candidate "
        "continues exactly where they left off"
    )


def test_persistence_roundtrip_preserves_candidate_id():
    """
    The GET /interview/{session_id} endpoint reads candidate_id from the
    persisted state. A disk round-trip must not drop that field.
    """
    session_id = f"SESSION_RECONNECT_RT_{uuid.uuid4().hex[:6]}"
    state = _start(session_id)

    persistence.save(session_id, dict(state))

    restored = persistence.load(session_id)
    assert restored is not None
    assert restored["candidate_id"] == "C001"
    assert restored["session_id"] == session_id


def test_registry_update_auto_persists():
    """
    After registry.update(), a fresh persistence.load() must return the
    updated state — proving the disk is always the source of truth and
    that no explicit save() call is needed after each answer.
    """
    from app.stages.stage4_interview.registry import InterviewSessionRegistry

    session_id = f"SESSION_RECONNECT_AP_{uuid.uuid4().hex[:6]}"
    registry = InterviewSessionRegistry(persistence=persistence)

    state = _start(session_id)
    registry.create(session_id, state)

    # Submit an answer: this calls registry.update internally in the route,
    # but here we call it directly to mirror what the route does.
    updated = controller.submit_text(
        state,
        "I used event-driven design with FastAPI and Redis.",
    )
    registry.update(session_id, dict(updated))

    # Now simulate a fresh load (no in-memory cache).
    restored = persistence.load(session_id)
    assert restored is not None, (
        "registry.update must auto-persist; disk must have the updated state"
    )
    assert restored["session_id"] == session_id
    assert restored["turn_number"] == updated.get("turn_number", 1)
