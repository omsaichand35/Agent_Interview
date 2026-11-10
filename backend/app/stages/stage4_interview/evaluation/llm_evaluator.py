from app.schemas.interview import InterviewEvidenceEvaluation


INTERVIEW_EVALUATION_PROMPT = """
You are evaluating a candidate's interview answer.

Evaluate the answer fairly against the named competency and the question.
Use the same standard for every candidate.

Give credit for each relevant idea that is accurate. Award partial credit when
the answer is partly correct or covers only part of the expected knowledge. The
score should reflect the share of the relevant answer that is correct: an answer
that is about 70% correct should usually score about 0.70, not be pushed down for
being concise or for minor wording issues.

Do not give credit to incorrect claims, and lower the score when errors affect
important parts of the answer. Do not award points for unrelated material,
unsupported claims, or confidence alone. Do not require examples, personal
experience, metrics, or complex terminology unless the question or competency
calls for them. Accept a clear, simple explanation when its meaning is correct.

COMPETENCY:
{competency}

INTERVIEW QUESTION:
{question}

CANDIDATE ANSWER:
{answer}

Evaluate:

1. evidence_quality
   How much of the answer is relevant and correct for this competency?

2. technical_depth
   How clearly and accurately does the answer explain the subject? This applies
   to every field, not only technical subjects.

3. specificity
   Does the answer address the question directly and include the relevant facts
   or reasoning? Do not require examples or metrics when they are not needed.

Then produce an overall score from 0.0 to 1.0.

Scoring guide:

0.00 - blank, unrelated, or wholly incorrect
0.25 - a small amount is correct; most is missing or incorrect
0.50 - about half of the important points are correct
0.70 - about 70% of the important points are correct; give fair credit
0.85 - most important points are correct, with only minor gaps
1.00 - accurate and complete for what the question asked

Use values between these anchors. Do not inflate a wrong answer, and do not
penalize a substantially correct answer just because it is brief or simply worded.

Use only the candidate's answer.

Return ONLY valid JSON:

{{
    "competency": "...",
    "score": 0.0,
    "evidence_quality": 0.0,
    "technical_depth": 0.0,
    "specificity": 0.0,
    "reasoning": "...",
    "evidence_quote": "..."
}}
"""


class LLMInterviewEvaluator:

    def __init__(self, client):
        self.client = client

    def evaluate(
        self,
        competency: str,
        question: str,
        answer: str,
    ) -> InterviewEvidenceEvaluation:

        prompt = INTERVIEW_EVALUATION_PROMPT.format(
            competency=competency,
            question=question,
            answer=answer,
        )

        return self.client.generate_structured(
            prompt=prompt,
            response_model=InterviewEvidenceEvaluation,
        )
