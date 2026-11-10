from app.schemas.identity import IdentityResult


class PassingTestIdentityCheckpoint:
    """Explicit successful identity result for non-biometric interview tests."""

    def check(self, candidate_id=None, session_id=None, **_kwargs):
        return IdentityResult(
            candidate_id=candidate_id or "test-candidate",
            session_id=session_id or "test-session",
            verified=True,
            identity_status="passed",
            confidence=0.99,
            face_match_score=0.99,
        )
