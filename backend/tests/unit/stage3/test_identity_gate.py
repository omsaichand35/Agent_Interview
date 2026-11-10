from app.schemas.identity import IdentityResult

from app.stages.stage3_identity.gate import (
    IdentityGate,
)


def test_verified_candidate_can_enter_interview():

    result = IdentityResult(
        candidate_id="C001",
        session_id="S001",
        verified=True,
        confidence=0.92,
    )

    assert (
        IdentityGate.allow_interview(result)
        is True
    )


def test_unverified_candidate_cannot_enter_interview():

    result = IdentityResult(
        candidate_id="C001",
        session_id="S002",
        verified=False,
        confidence=0.40,
        failure_reason="Face verification failed.",
    )

    assert (
        IdentityGate.allow_interview(result)
        is False
    )


def test_failed_verification_cannot_be_overridden_by_pass_status():
    result = IdentityResult(
        candidate_id="C001",
        session_id="S001",
        verified=False,
        identity_status="passed",
    )

    assert IdentityGate.allow_interview(result) is False
