from pathlib import Path
import pytest

from app.stages.stage3_identity.identity_service import IdentityService
from app.stages.stage3_identity.identity_logger import IdentityLogger
from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer
from app.workflows.session_manager import HiringWorkflowSessionManager


def test_identity_failure_blocks_interview(tmp_path):
    job_id = "JOB001"
    candidate_id = "C001"
    session_id = "SESSION_FAIL_001"

    root = Path(__file__).resolve().parents[3]
    reference_image = str(root / "data/raw/identity_validation/genuine/pair01_reference.jpg")
    impostor_image = str(root / "data/raw/identity_validation/impostor/pair01_live.jpg")

    workflow_persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    workflow_service = HiringWorkflowSessionManager(
        persistence=workflow_persistence,
        resumer=HiringWorkflowResumer(persistence=workflow_persistence),
    )
    identity_service = IdentityService(
        logger=IdentityLogger(output_dir=str(tmp_path / "identity_logs")),
        log_dir=str(tmp_path / "identity_logs"),
    )

    # 1. Create hiring workflow
    workflow = workflow_service.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
    )

    # 2. Candidate reaches interview checkpoint
    workflow = workflow_service.prepare_interview(
        workflow,
        candidate_id,
    )

    assert workflow.status == "IDENTITY_CHECK"

    # 3. Deliberately use an impostor image against real YuNet face detector
    identity_result = identity_service.verify(
        reference_image=reference_image,
        live_image=impostor_image,
        candidate_id=candidate_id,
        session_id=session_id,
    )

    assert identity_result.verified is False

    # 4. Identity gate triggers failure routing
    workflow = workflow_service.identity_failed(
        workflow,
        candidate_id,
        identity_result,
    )

    # 5. Assert hard gate: Workflow routed to HUMAN_REVIEW
    assert workflow.status == "HUMAN_REVIEW"
    assert candidate_id in workflow.human_review

    # 6. Critical security assertion: Interview was NEVER started
    assert candidate_id not in workflow.interview_sessions
    assert workflow.current_candidate_id == candidate_id
