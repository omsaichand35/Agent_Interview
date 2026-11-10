from app.schemas.resume import ResumeScore


class ResumeScorer:

    def score(
        self,
        candidate_id: str,
        assessments,
        competencies,
    ) -> ResumeScore:

        weighted_score = 0.0

        for assessment in assessments:

            competency = next(
                (
                    c
                    for c in competencies
                    if c.name == assessment.competency
                ),
                None,
            )

            if competency:
                weighted_score += (
                    assessment.score
                    * competency.weight
                )

        overall_score = round(
            weighted_score * 100,
            2,
        )

        strengths = [
            assessment.competency
            for assessment in assessments
            if assessment.score >= 0.6
        ]

        gaps = [
            assessment.competency
            for assessment in assessments
            if assessment.score < 0.3
        ]

        return ResumeScore(
            candidate_id=candidate_id,
            overall_score=overall_score,
            competency_scores=assessments,
            strengths=strengths,
            gaps=gaps,
        )