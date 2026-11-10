from app.schemas.resume import ResumeScore


class ShortlistManager:

    def rank(
        self,
        scores: list[ResumeScore],
        limit: int = 5,
    ) -> list[ResumeScore]:

        ranked = sorted(
            scores,
            key=lambda score: score.overall_score,
            reverse=True,
        )

        return ranked[:limit]