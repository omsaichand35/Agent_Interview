from app.llm.client import LLMClient
from app.llm.prompts import RESUME_ANALYSIS_PROMPT
from app.schemas import JobDescription
from app.schemas.resume import LLMResumeAnalysis


class LLMResumeAnalyzer:

    def __init__(self, client: LLMClient):
        self.client = client

    def analyze(
        self,
        resume_text: str,
        job: JobDescription,
    ) -> LLMResumeAnalysis:

        competencies = "\n".join(
            f"""
            ID: {competency.id}
            Name: {competency.name}
            Description: {competency.description}
            Weight: {competency.weight}
            """
            for competency in job.competencies
        )

        prompt = RESUME_ANALYSIS_PROMPT.format(
            competencies=competencies,
            resume=resume_text,
        )

        analysis = self.client.generate_structured(
            prompt=prompt,
            response_model=LLMResumeAnalysis,
        )

        from app.stages.stage1_resume.evidence_validator import (
            EvidenceValidator,
        )

        return EvidenceValidator.validate(
            analysis=analysis,
            resume_text=resume_text,
        )