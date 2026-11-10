class RecommendationEvidenceBuilder:

    def build(
        self,
        candidate,
        interview_result,
    ):

        evidence = []

        if candidate.get(
            "resume_score"
        ) is not None:

            evidence.append(
                "Resume score: "
                f"{candidate['resume_score']:.2f}"
            )

        if interview_result.get(
            "interview_score"
        ) is not None:

            evidence.append(
                "Interview score: "
                f"{interview_result['interview_score']:.2f}"
            )

        for competency, score in (
            interview_result.get(
                "competency_scores",
                {},
            ).items()
        ):

            evidence.append(
                f"{competency}: {score:.2f}"
            )

        return evidence


EvidenceBuilder = RecommendationEvidenceBuilder
