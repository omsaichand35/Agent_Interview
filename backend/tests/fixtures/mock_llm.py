from app.schemas.interview import (
    InterviewReasoning,
    InterviewEvidenceEvaluation,
)

from app.stages.stage4_interview.questions.llm_question_generator import (
    InterviewQuestion,
)


class MockInterviewLLM:

    def generate_structured(
        self,
        prompt,
        response_model,
    ):

        if response_model is InterviewReasoning:

            prompt_str = str(prompt).lower()
            ans_part = prompt_str.split("latest candidate answer:")[-1] if "latest candidate answer:" in prompt_str else prompt_str
            ans_clean = ans_part.split("return:")[0].strip()
            bad_phrases = ["i don't know", "no idea", "fuck off", "refuse to answer", "i decline", "pass"]
            if any(bp in ans_clean for bp in bad_phrases):
                return InterviewReasoning(
                    trigger_phrase=None,
                    extracted_signals=[],
                    decision="recover",
                    target_competency=None,
                    rationale="The candidate gave a non-responsive answer. Trigger recovery.",
                    question_intent="Clarify and recover discussion.",
                    confidence=0.9,
                )

            return InterviewReasoning(
                trigger_phrase=(
                    "mentored two junior developers"
                ),
                extracted_signals=[
                    "leadership"
                ],
                decision="pivot",
                target_competency="leadership",
                rationale=(
                    "The candidate introduced direct "
                    "evidence of mentoring and leadership."
                ),
                question_intent=(
                    "Explore the candidate's mentoring "
                    "experience."
                ),
                confidence=0.95,
            )

        if response_model is InterviewQuestion:

            return InterviewQuestion(
                question=(
                    "Tell me about a specific situation "
                    "where you mentored one of those "
                    "developers. What did you do?"
                ),
                competency="leadership",
                intent=(
                    "Explore mentoring experience."
                ),
            )

        if response_model is InterviewEvidenceEvaluation:

            return InterviewEvidenceEvaluation(
                competency="leadership",
                score=0.85,
                evidence_quality=0.85,
                technical_depth=0.80,
                specificity=0.85,
                reasoning=(
                    "Candidate provided concrete mentoring evidence."
                ),
                evidence_quote="mentored two junior developers",
            )

        raise ValueError(
            f"Unexpected response model: "
            f"{response_model}"
        )