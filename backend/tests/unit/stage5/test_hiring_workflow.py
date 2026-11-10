class FakeResumeService:

    def run(
        self,
        job_id,
        candidates,
        job_description,
    ):

        return {
            "shortlist": [
                candidates[0]
            ]
        }


class FakeSchedulingService:

    def schedule(self, shortlist):

        return {
            "schedules": [
                {
                    "candidate_id": shortlist[0][
                        "candidate_id"
                    ],
                    "slot_id": "S001",
                }
            ]
        }


class FakeIdentityService:

    def verify(
        self,
        **kwargs,
    ):

        from app.schemas.identity import (
            IdentityResult,
        )

        return IdentityResult(
            candidate_id=kwargs["candidate_id"],
            session_id=kwargs["session_id"],
            verified=True,
            confidence=0.92,
            checks=[],
        )


class FakeInterviewController:

    def start(self, **kwargs):

        return {
            "session_id": kwargs["session_id"],
            "next_question": (
                "Tell me about your backend experience."
            ),
        }


class FakeRecommendationService:

    def generate(self, **kwargs):

        return {
            "candidate_id": kwargs[
                "candidate"
            ]["candidate_id"],
            "final_score": 85.0,
            "status": "recommended",
        }