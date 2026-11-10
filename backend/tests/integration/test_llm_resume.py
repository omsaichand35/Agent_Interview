from pathlib import Path
import pytest

pytestmark = pytest.mark.live_llm

from app.llm.provider import get_llm_client
from app.schemas.resume import LLMResumeAnalysis
from app.stages.stage1_resume.parser import ResumeParser
from app.stages.stage1_resume.resume_service import JDService
from app.stages.stage1_resume.llm_analyzer import LLMResumeAnalyzer


def test_resume_llm_analysis():

    root = Path(__file__).resolve().parents[3]

    resume_path = (
        root
        / "data"
        / "raw"
        / "resumes"
        / "test_candidate.txt"
    )

    jd_path = (
        root
        / "data"
        / "raw"
        / "job_descriptions"
        / "backend_engineer.txt"
    )

    parser = ResumeParser()

    resume_text = parser.parse(
        str(resume_path)
    )

    job_service = JDService()

    job = job_service.load_job(
        str(jd_path),
        job_id="backend-engineer",
    )

    analyzer = LLMResumeAnalyzer(
        get_llm_client()
    )

    result = analyzer.analyze(
        resume_text=resume_text,
        job=job,
    )

    assert isinstance(
        result,
        LLMResumeAnalysis,
    )

    assert len(result.assessments) == len(
        job.competencies
    )

    assert result.candidate_name == "Rahul Kumar"
