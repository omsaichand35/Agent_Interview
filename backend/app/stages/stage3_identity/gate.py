from app.schemas.identity import IdentityResult


class IdentityGate:

    @staticmethod
    def allow_interview(
        identity_result: IdentityResult,
    ) -> bool:
        """
        Determines whether candidate identity verification permits entry to the interview.
        Only 'passed' status permits interview progression.
        'failed', 'review', or 'pending' statuses must hold or terminate the session.
        """
        status = getattr(identity_result, "identity_status", None)
        return bool(identity_result.verified) and status in (None, "passed", "verified")
