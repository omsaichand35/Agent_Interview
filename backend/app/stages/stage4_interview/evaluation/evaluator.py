from app.stages.stage4_interview.evaluation.llm_evaluator import (
    LLMInterviewEvaluator,
)


class InterviewEvaluator:

    def __init__(self, llm_client):
        self.llm_evaluator = LLMInterviewEvaluator(
            llm_client
        )

    def evaluate(
        self,
        competency: str,
        question: str,
        answer: str,
    ):

        try:
            return self.llm_evaluator.evaluate(
                competency=competency,
                question=question,
                answer=answer,
            )

        except Exception:
            return self._fallback(
                competency,
                answer,
            )

    @staticmethod
    def _fallback(
        competency: str,
        answer: str,
    ):

        from app.schemas.interview import (
            InterviewEvidenceEvaluation,
        )

        score = 0.3 if answer.strip() else 0.0

        return InterviewEvidenceEvaluation(
            competency=competency,
            score=score,
            evidence_quality=score,
            technical_depth=score,
            specificity=score,
            reasoning="Fallback evaluation used because LLM evaluation failed.",
            evidence_quote=answer[:300],
        )