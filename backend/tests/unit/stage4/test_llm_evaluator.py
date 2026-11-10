from app.schemas.interview import InterviewEvidenceEvaluation
from app.stages.stage4_interview.evaluation.llm_evaluator import (
    LLMInterviewEvaluator,
)


class MockEvaluatorLLM:

    def generate_structured(
        self,
        prompt,
        response_model,
    ):

        return InterviewEvidenceEvaluation(
            competency="problem_solving",
            score=0.86,
            evidence_quality=0.90,
            technical_depth=0.85,
            specificity=0.80,
            reasoning=(
                "The candidate explains a concrete production "
                "problem, its cause, and the corrective action."
            ),
            evidence_quote=(
                "I identified a lock-order issue and "
                "redesigned the transaction boundary."
            ),
        )


def test_llm_evaluator():

    evaluator = LLMInterviewEvaluator(
        MockEvaluatorLLM()
    )

    result = evaluator.evaluate(
        competency="problem_solving",
        question=(
            "Tell me about a difficult production "
            "problem you solved."
        ),
        answer=(
            "We had a production deadlock. "
            "I identified a lock-order issue and "
            "redesigned the transaction boundary."
        ),
    )

    assert result.score == 0.86
    assert result.evidence_quality == 0.90
    assert result.technical_depth == 0.85
    assert result.specificity == 0.80