from app.config import settings


class FinalScorer:

    def score(
        self,
        resume_score: float,
        interview_score: float,
    ) -> float:

        result = (
            resume_score
            * settings.resume_weight
            +
            interview_score
            * settings.interview_weight
        )

        return round(
            result,
            2,
        )
