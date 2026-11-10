from pathlib import Path

from app.stages.stage1_resume.resume_service import (
    ResumeService,
)


def test_stage1_resume_pipeline():

    project_root = Path(__file__).resolve().parents[3]

    resume_path = (
        project_root
        / "data"
        / "raw"
        / "resumes"
        / "Omsaichand (1).pdf"
    )

    competency_path = (
        project_root
        / "config"
        / "competencies.yaml"
    )

    service = ResumeService(
        competency_config=str(competency_path)
    )

    result = service.evaluate_resume(
        candidate_id="C001",
        resume_path=str(resume_path),
    )

    candidate = result["candidate"]
    score = result["resume_score"]

    assert candidate.name == "Boppudi Omsaichand"

    assert (
        candidate.email
        == "saichandboppudi@gmail.com"
    )

    assert len(candidate.skills) > 0

    assert score.candidate_id == "C001"

    assert 0 <= score.overall_score <= 100

    assert len(score.competency_scores) == 10