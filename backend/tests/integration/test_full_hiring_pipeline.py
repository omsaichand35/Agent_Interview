"""
C10 Integration Test: Full Hiring Pipeline End-to-End Validation.

This suite provides complete end-to-end verification of the hiring platform:
1. Full happy path:
   JD -> Stage 1 (Shortlist) -> Stage 2 (Schedule) -> Stage 3 (Identity PASS)
      -> Stage 4 (Interview) -> Stage 5 (Recommendation) -> Recruiter Review -> COMPLETED.
2. Identity failure hard-gate path:
   Identity FAIL -> HUMAN_REVIEW -> Recruiter review.
3. Backend restart recovery:
   Mid-workflow crash simulation -> reload from disk -> continue to completion.
4. Concurrent candidate isolation:
   Simultaneous candidate interviews without cross-contamination.
5. System health and readiness verification:
   /health and /ready endpoints validate operational status and model availability.
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.stages.stage3_identity.identity_service import IdentityService
from app.stages.stage3_identity.identity_logger import IdentityLogger
from app.config import settings
from app.main import app
from app.models.recommendation import (
    RecruiterReviewRequest,
    ReviewDecision,
    ReviewStatus,
)
from app.services.recruiter_service import RecruiterService
from app.stages.stage4_interview.dependencies import create_interview_controller
from app.stages.stage4_interview.persistence import InterviewPersistence
from app.stages.stage2_scheduling.scheduling_service import SchedulingService
from tests.fixtures.identity import PassingTestIdentityCheckpoint
from tests.fixtures.mock_llm import MockInterviewLLM
from app.stages.stage5_recommendation.recommendation_service import (
    RecommendationService,
)
from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer
from app.workflows.session_manager import HiringWorkflowSessionManager


def _build_test_workflow_service(tmp_path):
    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    recommendation_service = RecommendationService()
    resumer = HiringWorkflowResumer(
        persistence=persistence,
        recommendation_service=recommendation_service,
    )
    return HiringWorkflowSessionManager(persistence=persistence, resumer=resumer)


# ---------------------------------------------------------------------------
# Test 1: Full Happy Path End-to-End
# ---------------------------------------------------------------------------
def test_full_pipeline_happy_path(tmp_path):
    """
    Exercises the complete end-to-end pipeline from job requisition through
    recruiter review to COMPLETED status.
    """
    job_id = f"JOB_E2E_{uuid.uuid4().hex[:6].upper()}"
    candidate_id = "C001"
    session_id = f"SESSION_E2E_{uuid.uuid4().hex[:6].upper()}"

    root = Path(__file__).resolve().parents[3]
    photo_path = str(root / "data/raw/identity_validation/genuine/pair01_reference.jpg")
    live_photo_path = str(root / "data/raw/identity_validation/genuine/pair01_live.jpg")
    assert Path(photo_path).exists(), f"Reference photo not found at {photo_path}"

    workflow_service = _build_test_workflow_service(tmp_path)
    recommendation_service = workflow_service.resumer.recommendation_service
    identity_service = IdentityService(
        logger=IdentityLogger(output_dir=str(tmp_path / "identity_logs")),
        log_dir=str(tmp_path / "identity_logs"),
    )
    interview_controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    recruiter_service = RecruiterService(workflow_service=workflow_service)

    # 1. Job Description & Workflow Creation
    workflow = workflow_service.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
        candidates=[
            {
                "candidate_id": candidate_id,
                "name": "Alex Chen",
                "email": "alex.chen@example.com",
                "resume_score": 85.0,
                "photo_path": photo_path,
            }
        ],
        job_description={
            "title": "Senior Backend Engineer",
            "department": "Core Platform",
            "required_skills": ["Python", "FastAPI", "Distributed Systems"],
        },
    )
    assert workflow.status == "CREATED"

    # 2. Stage 1: AI Shortlisting
    workflow = workflow_service.run_shortlisting(workflow)
    assert workflow.status == "SHORTLISTED"
    assert len(workflow.shortlist) > 0
    assert candidate_id in workflow.shortlist

    # 3. Stage 2: Scheduling
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [{
        "slot_id": f"test-slot-{uuid.uuid4().hex[:6]}",
        "start_time": "2026-10-01T10:00:00",
        "end_time": "2026-10-01T10:30:00",
        "available": True,
    }]}), encoding="utf-8")
    workflow = workflow_service.run_scheduling(
        workflow,
        scheduling_service=SchedulingService(
            calendar_path=str(calendar_path),
            confirmation_dir=str(tmp_path / "confirmations"),
        ),
    )
    calendar_path.unlink(missing_ok=True)
    assert workflow.status == "SCHEDULED"
    schedule = workflow.get("schedules")
    assert schedule is not None
    assert len(schedule) > 0

    # 4. Identity Check Preparation
    workflow = workflow_service.prepare_interview(workflow, candidate_id)
    assert workflow.status == "IDENTITY_CHECK"

    # 5. Stage 3: Identity Verification (Live Frame vs Reference)
    identity_result = identity_service.verify(
        reference_image=photo_path,
        live_image=live_photo_path,
        candidate_id=candidate_id,
        session_id=session_id,
    )
    assert identity_result.verified is True
    assert identity_result.confidence is not None

    workflow = workflow_service.identity_passed(
        workflow, candidate_id, identity_result
    )
    assert workflow.status == "INTERVIEW_READY"

    # 6. Stage 4: AI Interview Execution
    session = interview_controller.start(
        candidate_id=candidate_id,
        session_id=session_id,
        competencies=["technical_skills", "problem_solving"],
        first_question="Describe how you structure asynchronous microservices in Python.",
    )
    session["identity_verified"] = True
    session["identity_status"] = "verified"

    session = interview_controller.submit_text(
        session,
        "I use FastAPI with asyncio, clean dependency injection, Celery for background workers, and PostgreSQL.",
    )
    assert session.turn_number > 1

    interview_result = interview_controller.complete(session)
    assert interview_result is not None
    assert interview_result.interview_score is not None

    workflow = workflow_service.interview_completed(
        workflow, candidate_id, interview_result
    )
    assert workflow.status == "INTERVIEW_COMPLETED"

    # 7. Stage 5: Final Recommendation Scoring
    workflow = workflow_service.generate_recommendation(workflow, candidate_id)
    assert workflow.status == "RECOMMENDATION_READY"
    assert candidate_id in workflow.recommendations

    recommendation = recommendation_service.generate(
        candidate_id=candidate_id,
        resume_score=0.85,
        interview_score=interview_result.interview_score,
        identity_verified=True,
        identity_confidence=identity_result.confidence,
        competency_scores=interview_result.competency_scores,
    )
    assert recommendation is not None
    assert recommendation.final_score is not None
    assert recommendation.status == "completed"

    # 8. Recruiter Review & Decision
    review_req = RecruiterReviewRequest(
        reviewer_id="recruiter_lead",
        decision=ReviewDecision.APPROVE,
        notes="Candidate performed exceptionally well across all evaluations.",
    )
    review_record = recruiter_service.submit_review(
        job_id=job_id,
        candidate_id=candidate_id,
        request=review_req,
    )
    assert review_record.review_status == ReviewStatus.APPROVED

    # Reload workflow to verify state
    final_workflow = workflow_service.get_session(job_id)
    assert final_workflow.status == "COMPLETED"


# ---------------------------------------------------------------------------
# Test 2: Identity Failure Path (Hard Gate to HUMAN_REVIEW)
# ---------------------------------------------------------------------------
def test_identity_failure_flow_to_human_review(tmp_path):
    """
    Verifies that identity mismatch stops the interview and routes the candidate
    strictly to HUMAN_REVIEW without allowing them to enter the interview.
    """
    job_id = f"JOB_IDFAIL_{uuid.uuid4().hex[:6].upper()}"
    candidate_id = "C001"
    session_id = f"SESSION_IDFAIL_{uuid.uuid4().hex[:6].upper()}"

    root = Path(__file__).resolve().parents[3]
    photo_path = str(root / "data/raw/identity_validation/genuine/pair01_reference.jpg")
    impostor_path = str(root / "data/raw/identity_validation/impostor/pair01_live.jpg")

    workflow_service = _build_test_workflow_service(tmp_path)
    identity_service = IdentityService(
        logger=IdentityLogger(output_dir=str(tmp_path / "identity_logs")),
        log_dir=str(tmp_path / "identity_logs"),
    )
    recruiter_service = RecruiterService(workflow_service=workflow_service)

    workflow = workflow_service.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
    )
    workflow = workflow_service.prepare_interview(workflow, candidate_id)
    assert workflow.status == "IDENTITY_CHECK"

    identity_result = identity_service.verify(
        reference_image=photo_path,
        live_image=impostor_path,
        candidate_id=candidate_id,
        session_id=session_id,
    )
    assert identity_result.verified is False

    workflow = workflow_service.identity_failed(
        workflow, candidate_id, identity_result
    )
    assert workflow.status == "HUMAN_REVIEW"
    assert candidate_id in workflow.human_review

    # Recruiter review resolves the flagged identity review
    review_req = RecruiterReviewRequest(
        reviewer_id="recruiter_security",
        decision=ReviewDecision.REJECT,
        notes="Identity could not be confirmed. Photo mismatch confirmed.",
    )
    review_record = recruiter_service.submit_review(
        job_id=job_id,
        candidate_id=candidate_id,
        request=review_req,
    )
    assert review_record.review_status == ReviewStatus.REJECTED

    final_workflow = workflow_service.get_session(job_id)
    assert final_workflow.status == "COMPLETED"


# ---------------------------------------------------------------------------
# Test 3: Backend Restart and Workflow Resume
# ---------------------------------------------------------------------------
def test_backend_restart_and_workflow_resume(tmp_path):
    """
    Verifies that a workflow in progress survives a server crash / process restart
    by reloading from persistent storage and continuing execution seamlessly.
    """
    job_id = f"JOB_RESTART_{uuid.uuid4().hex[:6].upper()}"
    candidate_id = "C001"
    session_id = f"SESSION_RESTART_{uuid.uuid4().hex[:6].upper()}"

    persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    interview_persistence = InterviewPersistence(output_dir=str(tmp_path / "interviews"))
    controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    controller.session_manager.persistence = interview_persistence

    # Pre-restart: Create and advance workflow to INTERVIEW_READY
    workflow_service_1 = _build_test_workflow_service(tmp_path)
    wf = workflow_service_1.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
        candidates=[{"candidate_id": candidate_id, "name": "Test Candidate", "resume_score": 85.0}],
    )
    wf = workflow_service_1.run_shortlisting(wf)
    calendar_path = tmp_path / "restart-calendar.json"
    calendar_path.write_text(json.dumps({"slots": [{
        "slot_id": "restart-test-slot",
        "start_time": "2026-10-01T10:00:00",
        "end_time": "2026-10-01T10:30:00",
        "available": True,
    }]}), encoding="utf-8")
    wf = workflow_service_1.run_scheduling(
        wf,
        scheduling_service=SchedulingService(
            calendar_path=str(calendar_path),
            confirmation_dir=str(tmp_path / "confirmations"),
        ),
    )

    # Start interview session and persist
    session = controller.start(
        candidate_id=candidate_id,
        session_id=session_id,
        competencies=["technical_skills"],
        first_question="Describe your experience with distributed queues.",
    )
    session["identity_verified"] = True
    session["identity_status"] = "verified"
    session = controller.submit_text(
        session, "I worked with Kafka partitions and offset management."
    )
    interview_persistence.save(session_id, session)

    wf["status"] = "INTERVIEW_READY"
    wf["interview_sessions"][candidate_id] = session_id
    persistence.save(wf)

    # ── SIMULATE CRASH & RESTART ──
    # Instantiate completely clean services without shared in-memory references
    new_persistence = HiringWorkflowPersistence(output_dir=str(tmp_path / "workflows"))
    new_resumer = HiringWorkflowResumer(persistence=new_persistence)
    new_workflow_service = HiringWorkflowSessionManager(
        persistence=new_persistence, resumer=new_resumer
    )
    new_controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    new_interview_persistence = InterviewPersistence(output_dir=str(tmp_path / "interviews"))
    new_controller.session_manager.persistence = new_interview_persistence

    # Verify workflow and interview survived on disk
    assert new_persistence.exists(job_id) is True
    assert new_interview_persistence.exists(session_id) is True

    loaded_wf = new_workflow_service.get_session(job_id)
    assert loaded_wf["job_id"] == job_id
    assert loaded_wf["status"] == "INTERVIEW_READY"

    loaded_session = new_interview_persistence.load(session_id)
    assert loaded_session["session_id"] == session_id
    assert len(loaded_session["conversation_history"]) >= 1
    assert "Kafka" in loaded_session["conversation_history"][0]["answer"]

    # Continue interview to completion on restarted backend
    result = new_controller.complete(loaded_session)
    resumed_wf = new_workflow_service.interview_completed(
        loaded_wf, candidate_id, result
    )
    assert resumed_wf["status"] == "INTERVIEW_COMPLETED"


# ---------------------------------------------------------------------------
# Test 4: Concurrent Candidate Isolation
# ---------------------------------------------------------------------------
def test_concurrent_candidate_isolation(tmp_path):
    """
    Ensures that concurrent candidates running interviews simultaneously maintain
    strict session isolation without crosstalk or state leaks.
    """
    controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    persistence = InterviewPersistence(output_dir=str(tmp_path / "interviews"))
    controller.session_manager.persistence = persistence

    cand_a = f"CAND_A_{uuid.uuid4().hex[:4]}"
    cand_b = f"CAND_B_{uuid.uuid4().hex[:4]}"
    sess_a = f"SESS_A_{uuid.uuid4().hex[:4]}"
    sess_b = f"SESS_B_{uuid.uuid4().hex[:4]}"

    ans_a = "Candidate A specialized in Python asyncio and FastAPI services."
    ans_b = "Candidate B specialized in Go goroutines and gRPC streaming."

    def run_candidate(c_id, s_id, answer):
        state = controller.start(
            session_id=s_id,
            candidate_id=c_id,
            candidate={"candidate_id": c_id, "name": f"Candidate {c_id}"},
            competencies=["technical_skills"],
            first_question="Describe your core technical stack.",
        )
        state["identity_verified"] = True
        state["identity_status"] = "verified"
        state = controller.submit_text(state, answer)
        persistence.save(s_id, state)
        return state

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(run_candidate, cand_a, sess_a, ans_a)
        future_b = executor.submit(run_candidate, cand_b, sess_b, ans_b)

        state_a = future_a.result()
        state_b = future_b.result()

    # Candidate A assertions
    assert state_a["candidate_id"] == cand_a
    assert state_a["session_id"] == sess_a
    history_a_text = " ".join(
        t.get("answer", "") for t in state_a["conversation_history"]
    )
    assert ans_a in history_a_text
    assert ans_b not in history_a_text

    # Candidate B assertions
    assert state_b["candidate_id"] == cand_b
    assert state_b["session_id"] == sess_b
    history_b_text = " ".join(
        t.get("answer", "") for t in state_b["conversation_history"]
    )
    assert ans_b in history_b_text
    assert ans_a not in history_b_text


# ---------------------------------------------------------------------------
# Test 5: Health and Readiness Endpoints
# ---------------------------------------------------------------------------
def test_health_and_readiness_endpoints():
    """
    Tests GET /health and GET /ready for production readiness and diagnostics.
    """
    client = TestClient(app)

    # 1. /health
    res_health = client.get("/health")
    assert res_health.status_code == 200
    data_health = res_health.json()
    assert data_health["status"] == "ok"
    assert "services" in data_health

    # 2. /ready - when models are properly located
    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    assert data_ready["status"] == "ready"
    assert data_ready["services"]["identity_model"] == "ok"

    # 3. /ready - when critical model is missing
    orig_sface = settings.sface_model_path
    try:
        settings.sface_model_path = "models/face/missing_model.onnx"
        res_fail = client.get("/ready")
        assert res_fail.status_code == 503
        data_fail = res_fail.json()
        assert data_fail["status"] == "not_ready"
        assert data_fail["reason"] == "identity_model_unavailable"
    finally:
        settings.sface_model_path = orig_sface
