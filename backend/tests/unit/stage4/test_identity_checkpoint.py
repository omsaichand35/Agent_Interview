from app.stages.stage4_interview.identity_checkpoint import (
    apply_identity_result,
)
from app.schemas.identity import IdentityResult


class FakeIdentityResult:

    def __init__(
        self,
        verified,
        confidence,
        failure_reason=None,
    ):
        self.verified = verified
        self.confidence = confidence
        self.failure_reason = failure_reason


class FakeIdentityCheckpoint:

    def __init__(self, result):
        self.result = result

    def check(self, session_id):
        return self.result


def apply_result(state, result):
    return apply_identity_result(state, result)


def test_identity_pass():

    state = {
        "identity_verified": True,
        "last_identity_confidence": None,
        "identity_check_count": 0,
        "identity_failure_reason": None,
        "decision": None,
        "interview_complete": False,
    }

    result = FakeIdentityResult(
        verified=True,
        confidence=0.92,
    )

    state = apply_result(
        state,
        result,
    )

    assert state["identity_verified"] is True
    assert state["last_identity_confidence"] == 0.92
    assert state["identity_check_count"] == 1
    assert state["interview_complete"] is False
    assert state.get("workflow_condition") == "identity_pass"


def test_identity_failure_stops_interview():

    state = {
        "identity_verified": True,
        "last_identity_confidence": None,
        "identity_check_count": 0,
        "identity_failure_reason": None,
        "decision": None,
        "interview_complete": False,
    }

    result = FakeIdentityResult(
        verified=False,
        confidence=0.42,
        failure_reason="Face mismatch.",
    )

    state = apply_result(
        state,
        result,
    )

    assert state["identity_verified"] is False
    assert state["identity_failure_reason"] == "Face mismatch."
    assert state["decision"] is None
    assert state.get("workflow_condition") == "identity_failure"
    assert state["interview_complete"] is True


def test_unverified_result_cannot_pass_from_a_contradictory_status():
    state = {
        "identity_verified": True,
        "last_identity_confidence": None,
        "identity_check_count": 0,
        "identity_failure_reason": None,
        "decision": None,
        "interview_complete": False,
    }
    result = IdentityResult(
        candidate_id="C_TEST",
        session_id="S_TEST",
        verified=False,
        identity_status="passed",
        failure_reason="Face mismatch.",
    )

    state = apply_result(state, result)

    assert state["identity_verified"] is False
    assert state["identity_status"] == "failed"
    assert state["workflow_condition"] == "identity_failure"
    assert state["interview_complete"] is True

