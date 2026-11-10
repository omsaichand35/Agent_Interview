from app.schemas.interview import InterviewReasoning

from app.stages.stage4_interview.reasoning.prompts import (
    INTERVIEW_REASONING_PROMPT,
)


class LLMInterviewReasoner:

    def __init__(self, client):
        self.client = client

    def analyze(
        self,
        candidate_answer: str,
        current_competency: str | None,
        target_competencies: list[str],
        explored_competencies: list[str],
        conversation_history: list[dict],
    ) -> InterviewReasoning:

        prompt = INTERVIEW_REASONING_PROMPT.format(
            current_competency=current_competency,
            target_competencies=", ".join(
                target_competencies
            ),
            explored_competencies=", ".join(
                explored_competencies
            ),
            conversation_history=conversation_history,
            candidate_answer=candidate_answer,
        )

        return self.client.generate_structured(
            prompt=prompt,
            response_model=InterviewReasoning,
        )