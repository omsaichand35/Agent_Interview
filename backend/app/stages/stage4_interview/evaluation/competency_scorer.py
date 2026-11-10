from app.stages.stage4_interview.evaluation.evidence import InterviewEvidence


class CompetencyScorer:

    def score(
        self,
        evidence: list[InterviewEvidence],
    ) -> dict[str, float]:

        scores: dict[str, list[float]] = {}

        for item in evidence:
            scores.setdefault(item.competency, [])
            scores[item.competency].append(
                item.evidence_strength
            )

        return {
            competency: round(sum(values) / len(values), 3)
            for competency, values in scores.items()
        }