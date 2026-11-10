from app.schemas.resume import LLMResumeAnalysis


class EvidenceValidator:

    @staticmethod
    def validate(
        analysis: LLMResumeAnalysis,
        resume_text: str,
    ) -> LLMResumeAnalysis:

        normalized_resume = " ".join(
            resume_text.split()
        ).lower()

        for assessment in analysis.assessments:

            valid_evidence = []

            for evidence in assessment.evidence:

                normalized_quote = " ".join(
                    evidence.quote.split()
                ).lower()

                if normalized_quote in normalized_resume:
                    valid_evidence.append(evidence)

            assessment.evidence = valid_evidence

            if not valid_evidence:
                assessment.score = min(
                    assessment.score,
                    0.2,
                )

                assessment.reasoning = (
                    "Insufficient directly verifiable "
                    "resume evidence."
                )

        return analysis

    @staticmethod
    def is_valid(resume: str, evidence: str) -> bool:
        """Check if an evidence quote is directly present in the resume text."""
        if not resume or not evidence:
            return False
        norm_r = " ".join(resume.split()).lower()
        norm_e = " ".join(evidence.split()).lower()
        # Accommodate either argument ordering (resume, evidence) or (evidence, resume)
        if len(norm_r) < len(norm_e):
            norm_r, norm_e = norm_e, norm_r
        return norm_e in norm_r