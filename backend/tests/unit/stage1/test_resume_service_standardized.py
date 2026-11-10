from unittest.mock import MagicMock
import pytest
from app.stages.stage1_resume.resume_service import ResumeService


def test_resume_service_run_contract():
    service = ResumeService()

    candidates = [
        {"candidate_id": "C001", "name": "Alice", "resume_score": 85.0},
        {"candidate_id": "C002", "name": "Bob", "resume_score": 92.0},
        {"candidate_id": "C003", "name": "Charlie", "resume_score": 78.0},
    ]

    job_description = {
        "job_id": "JOB001",
        "title": "Backend Engineer",
        "competencies": [],
    }

    result = service.run(
        job_description=job_description,
        candidates=candidates,
    )

    assert "shortlist" in result
    shortlist = result["shortlist"]
    assert len(shortlist) == 3
    # Top candidate should be ranked first (Bob with 92.0)
    assert shortlist[0]["candidate_id"] == "C002"
    assert shortlist[0]["resume_score"] == 92.0
    assert shortlist[1]["candidate_id"] == "C001"
    assert shortlist[2]["candidate_id"] == "C003"
