import json
from pathlib import Path
import pytest

from app.stages.stage3_identity.identity_service import IdentityService
from app.stages.stage3_identity.identity_logger import IdentityLogger
from app.stages.stage2_scheduling.scheduling_service import SchedulingService
from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.session_manager import HiringWorkflowSessionManager
from app.workflows.resume import HiringWorkflowResumer
from app.stages.stage5_recommendation.recommendation_service import RecommendationService
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM


def test_full_hiring_flow(tmp_path):
    job_id = "JOB001"
    candidate_id = "C001"
    root = Path(__file__).resolve().parents[3]
    reference_image = str(root / "data/raw/identity_validation/genuine/pair01_reference.jpg")
    live_image = str(root / "data/raw/identity_validation/genuine/pair01_live.jpg")

    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    recommendation_service = RecommendationService()
    resumer = HiringWorkflowResumer(persistence=persistence, recommendation_service=recommendation_service)
    workflow_service = HiringWorkflowSessionManager(persistence=persistence, resumer=resumer)
    identity_service = IdentityService(
        logger=IdentityLogger(output_dir=str(tmp_path / "identity_logs")),
        log_dir=str(tmp_path / "identity_logs"),
    )
    interview_controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    interview_controller.session_manager.persistence = InterviewPersistence(
        output_dir=str(tmp_path / "interviews")
    )
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [{
        "slot_id": "flow-test-slot",
        "start_time": "2026-10-01T10:00:00",
        "end_time": "2026-10-01T10:30:00",
        "available": True,
    }]}), encoding="utf-8")
    scheduling_service = SchedulingService(
        calendar_path=str(calendar_path),
        confirmation_dir=str(tmp_path / "confirmations"),
    )
    workflow_service.resumer.recommendation_service = recommendation_service

    # 1. Create hiring workflow
    workflow = workflow_service.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
        candidates=[{"candidate_id": candidate_id, "name": "Test Candidate", "resume_score": 85.0}],
    )

    assert workflow.status == "CREATED"

    # 2. Run Stage 1 (AI Shortlisting)
    workflow = workflow_service.run_shortlisting(
        workflow
    )

    assert workflow.status == "SHORTLISTED"
    assert candidate_id in workflow.shortlist

    # 3. Run Stage 2 (Scheduling)
    workflow = workflow_service.run_scheduling(workflow, scheduling_service=scheduling_service)

    assert workflow.status == "SCHEDULED"

    # 4. Candidate reaches interview
    workflow = workflow_service.prepare_interview(
        workflow,
        candidate_id,
    )

    assert workflow.status == "IDENTITY_CHECK"

    # 5. Identity verification (Real YuNet & SFace matcher)
    identity_result = identity_service.verify(
        reference_image=reference_image,
        live_image=live_image,
        candidate_id=candidate_id,
        session_id="SESSION001",
    )

    assert identity_result.verified is True

    workflow = workflow_service.identity_passed(
        workflow,
        candidate_id,
        identity_result,
    )

    assert workflow.status == "INTERVIEW_READY"

    # 6. Start interview
    session = interview_controller.start(
        candidate_id=candidate_id,
        session_id="SESSION001",
    )

    assert session.identity_status == "pending"

    # 7. Submit candidate answer
    session = interview_controller.submit_text(
        session,
        "I designed the backend using FastAPI "
        "with separate service and repository layers.",
    )

    assert session.turn_number > 1

    # 8. Finish interview
    result = interview_controller.complete(
        session
    )

    assert result is not None

    # 9. Resume workflow
    workflow = workflow_service.interview_completed(
        workflow,
        candidate_id,
        result,
    )

    assert workflow.status == "INTERVIEW_COMPLETED"

    # 10. Stage 5 Recommendation
    workflow = workflow_service.generate_recommendation(
        workflow,
        candidate_id,
    )

    assert workflow.status == "RECOMMENDATION_READY"
    assert candidate_id in workflow.recommendations
