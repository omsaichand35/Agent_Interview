from unittest.mock import MagicMock
import pytest

from app.workflows.session_manager import HiringWorkflowSessionManager


def test_workflow_session_manager_resume_interview():
    mock_persistence = MagicMock()
    mock_resumer = MagicMock()

    mock_state = {
        "job_id": "JOB100",
        "current_candidate_id": "C001",
        "candidates": [{"candidate_id": "C001", "name": "Rahul Kumar"}],
        "interview_results": {},
        "identity_results": {"C001": {"verified": True}},
        "recommendations": [],
    }
    mock_persistence.load.return_value = mock_state

    interview_result = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "status": "completed",
        "interview_score": 85.0,
    }

    mock_resumed_state = dict(mock_state)
    mock_resumed_state["status"] = "recommendation_ready"
    mock_resumer.resume_after_interview.return_value = mock_resumed_state

    manager = HiringWorkflowSessionManager(
        persistence=mock_persistence,
        resumer=mock_resumer,
    )

    result = manager.resume_interview("JOB100", interview_result)

    mock_persistence.load.assert_called_once_with("JOB100")
    mock_resumer.resume_after_interview.assert_called_once_with(
        mock_state,
        interview_result,
    )
    assert result["status"] == "recommendation_ready"


def test_workflow_service_resume_after_interview_full_flow(tmp_path):
    from app.schemas.interview import InterviewResult
    from app.workflows.persistence import HiringWorkflowPersistence
    from app.workflows.resume import HiringWorkflowResumer
    from app.workflows.session_manager import WorkflowService
    from app.stages.stage5_recommendation.recommendation_service import (
        RecommendationService,
    )

    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path))
    recommendation_service = RecommendationService()
    resumer = HiringWorkflowResumer(
        persistence=persistence,
        recommendation_service=recommendation_service,
    )
    workflow_service = WorkflowService(
        persistence=persistence,
        resumer=resumer,
    )

    # Initial persisted state (saved at Stage 4 pause)
    initial_state = {
        "job_id": "JOB001",
        "current_candidate_id": "C001",
        "candidates": [
            {
                "candidate_id": "C001",
                "name": "Jane Doe",
                "resume_score": 71.3,
            }
        ],
        "identity_results": {
            "C001": {
                "candidate_id": "C001",
                "verified": True,
                "confidence": 0.95,
            }
        },
        "interview_sessions": {},
        "interview_results": {},
        "recommendations": [],
        "status": "interview_ready",
    }
    persistence.save(initial_state)

    interview_result = InterviewResult(
        session_id="INTERVIEW_C001",
        candidate_id="C001",
        status="completed",
        identity_verified=True,
        interview_score=82.5,
        competency_scores={"Python": 0.85, "System Design": 0.80},
        strengths=["Python", "System Design"],
        gaps=[],
        turn_count=5,
    )

    # Invoke resume_after_interview
    resumed_state = workflow_service.resume_after_interview(
        job_id="JOB001",
        interview_result=interview_result,
    )

    # Verify state loaded and populated
    assert "C001" in resumed_state["interview_results"]
    assert isinstance(resumed_state["interview_results"]["C001"], dict)
    assert resumed_state["interview_results"]["C001"]["interview_score"] == 82.5

    # Verify Stage 5 executed and produced recommendation
    assert len(resumed_state["recommendations"]) == 1
    rec = resumed_state["recommendations"][0]
    assert rec["candidate_id"] == "C001"
    # Final score = 71.3 * 0.40 + 82.5 * 0.60 = 28.52 + 49.50 = 78.02
    assert rec["final_score"] == 78.02
    assert rec["identity_verified"] is True
    assert rec["status"] == "completed"

    # Verify saved to disk as JOB001_workflow.json
    saved_on_disk = persistence.load("JOB001")
    assert saved_on_disk["recommendations"][0]["final_score"] == 78.02
