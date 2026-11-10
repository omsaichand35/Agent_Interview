from app.schemas.resume import (
    ResumeScore,
    CompetencyAssessment,
    Evidence,
    LLMResumeAnalysis,
)


class LLMScoreAdapter:

    @staticmethod
    def convert(
        analysis: LLMResumeAnalysis,
        candidate_id: str,
        competencies,
    ) -> ResumeScore:

        competency_scores = []

        assessment_map = {
            assessment.competency_id: assessment
            for assessment in analysis.assessments
        }

        weighted_total = 0.0
        total_weight = 0.0

        for competency in competencies:

            assessment = assessment_map.get(
                competency.id
            )

            if assessment is None:
                score = 0.0
                reasoning = (
                    "No assessment was returned for "
                    "this competency."
                )
                evidence = []

            else:
                score = assessment.score
                reasoning = assessment.reasoning

                evidence = [
                    Evidence(
                        text=item.quote,
                        source="resume",
                        relevance=item.relevance,
                    )
                    for item in assessment.evidence
                ]

            competency_scores.append(
                CompetencyAssessment(
                    competency=competency.name,
                    score=score,
                    evidence=evidence,
                    reasoning=reasoning,
                )
            )

            weighted_total += score * competency.weight
            total_weight += competency.weight

        overall_score = (
            weighted_total / total_weight * 100
            if total_weight > 0
            else 0.0
        )

        strengths = [
            assessment.competency
            for assessment in competency_scores
            if assessment.score >= 0.6
        ]

        gaps = [
            assessment.competency
            for assessment in competency_scores
            if assessment.score < 0.3
        ]

        return ResumeScore(
            candidate_id=candidate_id,
            overall_score=overall_score,
            competency_scores=competency_scores,
            strengths=strengths,
            gaps=gaps,
        )