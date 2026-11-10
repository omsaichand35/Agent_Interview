from datetime import datetime
from unittest.mock import MagicMock
import pytest

from app.schemas.identity import IdentityResult
from app.schemas.schedule import Schedule
from app.workflows.hiring_graph import (
    create_hiring_state,
    run_stage1,
    run_stage2,
    run_stage3,
    build_hiring_graph,
)
from app.workflows.services import HiringServices


def test_workflow_stages_standardized():
    services = MagicMock(spec=HiringServices)

    # Stage 1 Mock
    services.resume_service = MagicMock()
    services.resume_service.run.return_value = {
        "shortlist": [
            {"candidate_id": "C001", "name": "Rahul", "resume_score": 88.0}
        ]
    }

    # Stage 2 Mock
    services.scheduling_service = MagicMock()
    services.scheduling_service.schedule.return_value = {
        "schedules": [
            Schedule(
                candidate_id="C001",
                slot_id="SLOT_01",
                start_time=datetime(2026, 10, 1, 10, 0),
                end_time=datetime(2026, 10, 1, 10, 30),
                status="scheduled",
            )
        ],
        "confirmations": ["data/outputs/confirmations/C001.json"],
    }

    # Stage 3 Mock
    services.identity_service = MagicMock()
    services.identity_service.verify.return_value = IdentityResult(
        candidate_id="C001",
        session_id="INTERVIEW_C001",
        verified=True,
        confidence=0.95,
        checks=[],
    )

    state = create_hiring_state(
        job_id="JOB_BACKEND",
        job_description={"title": "Backend Engineer", "competencies": []},
        candidates=[
            {
                "candidate_id": "C001",
                "name": "Rahul",
                "photo_path": "photos/c001.jpg",
                "live_image_path": "live/c001.jpg",
            }
        ],
    )

    # 1. Run Stage 1
    state = run_stage1(state, services)
    assert state["status"] == "shortlisted"
    assert len(state["shortlist"]) == 1
    services.resume_service.run.assert_called_once_with(
        job_description=state["job_description"],
        candidates=state["candidates"],
    )

    # 2. Run Stage 2
    state = run_stage2(state, services)
    assert state["status"] == "scheduled"
    assert len(state["schedules"]) == 1
    services.scheduling_service.schedule.assert_called_once_with(
        shortlist=state["shortlist"],
    )

    # 3. Run Stage 3
    state["current_candidate_id"] = "C001"
    state = run_stage3(state, services)
    assert state["identity_results"]["C001"]["verified"] is True
    services.identity_service.verify.assert_called_once_with(
        candidate_id="C001",
        session_id="INTERVIEW_C001",
        reference_image="photos/c001.jpg",
        live_image="live/c001.jpg",
    )


def test_route_after_identity_strict():
    from app.workflows.hiring_graph import route_after_identity

    # Verified -> interview
    state_pass = {
        "current_candidate_id": "C001",
        "identity_results": {"C001": {"verified": True}},
    }
    assert route_after_identity(state_pass) == "interview"

    # Unverified -> human_review
    state_fail = {
        "current_candidate_id": "C002",
        "identity_results": {"C002": {"verified": False}},
    }
    assert route_after_identity(state_fail) == "human_review"


def test_stage4_pauses_workflow():
    from app.workflows.hiring_graph import run_stage4

    services = MagicMock()
    services.interview_controller.start.return_value = {
        "session_id": "INTERVIEW_C001",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
    }
    services.persistence.save.return_value = "saved_workflow.json"

    state = {
        "current_candidate_id": "C001",
        "candidates": [
            {
                "candidate_id": "C001",
                "name": "Rahul",
                "target_competencies": ["technical_skills"],
            }
        ],
        "interview_sessions": {},
        "status": "identity_verified",
    }

    res_state = run_stage4(state, services)

    # Controller is started with session_id INTERVIEW_C001
    services.interview_controller.start.assert_called_once()
    assert res_state["status"] == "interview_ready"
    assert "C001" in res_state["interview_sessions"]
    # State is saved to persistence
    services.persistence.save.assert_called_once_with(res_state)

