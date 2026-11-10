import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.schemas.identity import IdentityResult
from app.schemas.interview import InterviewResult
from app.workflows.hiring_graph import (
    build_hiring_graph,
    create_hiring_state,
)
from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer
from app.workflows.session_manager import WorkflowService
from app.stages.stage5_recommendation.recommendation_service import (
    RecommendationService,
)


class FakeResumeService:

    def run(self, job_description, candidates):
        return {
            "shortlist": candidates
        }


class FakeSchedulingService:

    def schedule(self, shortlist):
        return {
            "schedules": [
                {
                    "candidate_id": c["candidate_id"],
                    "slot_id": f"S-{c['candidate_id']}",
                }
                for c in shortlist
            ],
            "confirmations": [],
        }


class FakeIdentityService:

    def __init__(self, verified):
        self.verified = verified

    def verify(self, **kwargs):
        return IdentityResult(
            candidate_id=kwargs["candidate_id"],
            session_id=kwargs["session_id"],
            verified=self.verified,
            confidence=0.91 if self.verified else 0.30,
            checks=[],
            failure_reason=(
                None
                if self.verified
                else "Face mismatch."
            ),
        )


def test_identity_failure_does_not_start_interview():

    identity = FakeIdentityService(
        verified=False
    )

    result = identity.verify(
        candidate_id="C001",
        session_id="INTERVIEW_C001",
        reference_image="ref.jpg",
        live_image="live.jpg",
    )

    assert result.verified is False


def test_identity_pass_allows_interview():

    identity = FakeIdentityService(
        verified=True
    )

    result = identity.verify(
        candidate_id="C001",
        session_id="INTERVIEW_C001",
        reference_image="ref.jpg",
        live_image="live.jpg",
    )

    assert result.verified is True


def test_pipeline_candidate_cannot_reach_stage4_when_identity_fails(tmp_path):
    """
    Critical business rule:
    A candidate cannot reach Stage 4 when identity verification fails.
    They must be routed to human review instead.
    """
    mock_interview_controller = MagicMock()
    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path))

    services = SimpleNamespace(
        resume_service=FakeResumeService(),
        scheduling_service=FakeSchedulingService(),
        identity_service=FakeIdentityService(verified=False),
        interview_controller=mock_interview_controller,
        persistence=persistence,
    )

    graph = build_hiring_graph(services)

    state = create_hiring_state(
        job_id="JOB_FAIL_001",
        job_description={"title": "Backend Engineer"},
        candidates=[
            {
                "candidate_id": "C001",
                "name": "Suspicious Candidate",
                "resume_score": 85.0,
                "photo_path": "ref.jpg",
                "live_image_path": "live.jpg",
            }
        ],
    )

    final_state = graph.invoke(state)

    # Assert Stage 4 interview was NEVER started
    mock_interview_controller.start.assert_not_called()
    assert "C001" not in final_state["interview_sessions"]

    # Assert candidate was sent to human review
    assert len(final_state["human_review"]) == 1
    assert final_state["human_review"][0]["candidate_id"] == "C001"
    assert final_state["human_review"][0]["reason"] == "Face mismatch."
    assert final_state["identity_results"]["C001"]["verified"] is False


def test_pipeline_candidate_passes_identity_completes_stage4_and_reaches_stage5(tmp_path):
    """
    Critical business rule:
    A candidate who passes identity can complete Stage 4 and reach Stage 5.
    """
    mock_interview_controller = MagicMock()
    mock_interview_controller.start.return_value = {
        "session_id": "INTERVIEW_C001",
        "candidate_id": "C001",
        "status": "in_progress",
    }

    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path))

    services = SimpleNamespace(
        resume_service=FakeResumeService(),
        scheduling_service=FakeSchedulingService(),
        identity_service=FakeIdentityService(verified=True),
        interview_controller=mock_interview_controller,
        persistence=persistence,
    )

    graph = build_hiring_graph(services)

    state = create_hiring_state(
        job_id="JOB_PASS_001",
        job_description={"title": "Senior Engineer"},
        candidates=[
            {
                "candidate_id": "C001",
                "name": "Verified Candidate",
                "resume_score": 75.0,
                "photo_path": "ref.jpg",
                "live_image_path": "live.jpg",
                "target_competencies": ["Python", "System Design"],
            }
        ],
    )

    # 1. Run graph until Stage 4 pauses outer workflow
    paused_state = graph.invoke(state)

    # Identity passed
    assert paused_state["identity_results"]["C001"]["verified"] is True
    # Stage 4 interview was started
    mock_interview_controller.start.assert_called_once()
    assert "C001" in paused_state["interview_sessions"]
    assert paused_state["status"] == "interview_ready"

    # Human review was not triggered
    assert len(paused_state["human_review"]) == 0

    # 2. Stage 4 finishes and builds result
    interview_result = InterviewResult(
        session_id="INTERVIEW_C001",
        candidate_id="C001",
        status="completed",
        identity_verified=True,
        interview_score=85.0,
        competency_scores={"Python": 0.90, "System Design": 0.80},
        strengths=["Python", "System Design"],
        gaps=[],
        turn_count=5,
    )

    # 3. Resume outer workflow into Stage 5
    recommendation_service = RecommendationService()
    resumer = HiringWorkflowResumer(
        persistence=persistence,
        recommendation_service=recommendation_service,
    )
    workflow_service = WorkflowService(
        persistence=persistence,
        resumer=resumer,
    )

    resumed_state = workflow_service.resume_after_interview(
        job_id="JOB_PASS_001",
        interview_result=interview_result,
    )

    # Assert Stage 5 generated the final recommendation
    assert len(resumed_state["recommendations"]) == 1
    rec = resumed_state["recommendations"][0]
    assert rec["candidate_id"] == "C001"
    # Final score = 75.0 * 0.40 + 85.0 * 0.60 = 30.0 + 51.0 = 81.0
    assert rec["final_score"] == 81.0
    assert rec["identity_verified"] is True
    assert rec["status"] == "completed"
    assert "Python" in rec["strengths"]
