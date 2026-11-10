from app.schemas.identity import IdentityResult


class InterviewIdentityMonitor:
    """
    Performs repeated identity verification during an interview.

    Every successful or failed verification is returned to the
    interview workflow so it can decide whether processing may continue.
    """

    def __init__(self, identity_checker, identity_logger):
        self.identity_checker = identity_checker
        self.identity_logger = identity_logger

    def verify(
        self,
        reference_image: str,
        live_image: str,
        candidate_id: str,
        session_id: str,
    ) -> IdentityResult:

        result = self.identity_checker.check(
            reference_image=reference_image,
            live_image=live_image,
            candidate_id=candidate_id,
            session_id=session_id,
        )

        self.identity_logger.log(result)

        return result