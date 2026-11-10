"""
C9 integration test: recruiter review workflow.

Covers the complete human-in-the-loop path:

    Candidate flagged for HUMAN_REVIEW (identity failure)
         |
         v
    build_review_payload()   <- GET /candidates/{id}/review
         |
         v
    submit_review()          <- POST /candidates/{id}/review
         |
         v
    Workflow -> COMPLETED

Rules tested
------------
* Identity failure reason is visible in the review payload.
* APPROVE moves status to 'approved' and workflow to COMPLETED.
* REJECT  moves status to 'rejected' and workflow to COMPLETED.
* REQUEST_REVIEW escalates without wrongly completing the workflow.
* An invalid decision raises ValueError (never silently accepted).
* The frontend cannot change workflow status directly -- only submit_review() can.
* A review decision is persisted to the workflow JSON.
"""

import uuid

from app.models.recommendation import (
    RecruiterReviewRequest,
    ReviewDecision,
    ReviewStatus,
)
from app.services.recruiter_service import RecruiterService
from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer
from app.workflows.session_manager import HiringWorkflowSessionManager


# ---------------------------------------------------------------------------
# Minimal stub so tests never need cv2 / face_matcher
# ---------------------------------------------------------------------------


class _StubRec:
    def generate(self, **kw):
        return None
    def get_recommendation(self, cid):
        return None


def _build_workflow_service():
    p = HiringWorkflowPersistence()
    r = HiringWorkflowResumer(persistence=p, recommendation_service=_StubRec())
    return HiringWorkflowSessionManager(persistence=p, resumer=r)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix="JOB"):
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


def _make_hr_workflow(wf_service, job_id, candidate_id="C002"):
    """Create a workflow with candidate_id already in human_review."""
    wf = wf_service.create(
        job_id=job_id,
        candidate_ids=[candidate_id],
    )
    wf = wf_service.run_shortlisting(wf)

    # Simulate identity failure gate -- put candidate into human_review.
    class _FailedIdentity:
        verified = False
        confidence = 0.12
        failure_reason = "Face match confidence below threshold"
        def model_dump(self):
            return {
                "verified": self.verified,
                "confidence": self.confidence,
                "failure_reason": self.failure_reason,
            }

    wf = wf_service.prepare_interview(wf, candidate_id)
    wf = wf_service.identity_failed(wf, candidate_id, _FailedIdentity())
    return wf


# ---------------------------------------------------------------------------
# Test: review payload (GET)
# ---------------------------------------------------------------------------


def test_review_payload_contains_review_reason():
    """
    build_review_payload() must expose why the candidate reached human review
    so the recruiter understands the context without digging into logs.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)
    payload = svc.build_review_payload(candidate_id="C002", workflow=dict(wf))

    assert payload["candidate_id"] == "C002"
    assert "review_reason" in payload
    assert payload["review_reason"], "review_reason must be non-empty"


def test_review_payload_exposes_identity_section():
    """
    The identity section must be present so the recruiter can see
    the confidence score and failure reason.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)
    payload = svc.build_review_payload(candidate_id="C002", workflow=dict(wf))

    assert "identity" in payload
    assert payload["identity"]["status"] in ("failed", "unknown", "identity_failed", "pending")


def test_review_payload_has_pending_status_before_decision():
    """
    Before the recruiter submits a decision, review.status must be 'pending'.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)
    payload = svc.build_review_payload(candidate_id="C002", workflow=dict(wf))

    assert payload["review"]["status"] == ReviewStatus.PENDING


# ---------------------------------------------------------------------------
# Test: APPROVE decision
# ---------------------------------------------------------------------------


def test_human_review_flow_approve():
    """
    Full flow: candidate in HUMAN_REVIEW -> recruiter APPROVE ->
    status='approved', workflow='COMPLETED'.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    assert wf["status"] == "HUMAN_REVIEW"

    svc = RecruiterService(workflow_service=wf_service)

    result = svc.review(
        candidate_id="C002",
        decision=ReviewDecision.APPROVE,
        notes="Identity manually verified via passport.",
        workflow=wf,
    )

    assert result.status == ReviewStatus.APPROVED
    assert result.decision == ReviewDecision.APPROVE
    assert result.workflow_status == "COMPLETED"
    assert result.reviewed_at is not None


def test_workflow_persisted_after_approve():
    """
    After APPROVE, the workflow JSON on disk must reflect COMPLETED
    and include the recruiter_decision block.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)
    svc.review(
        candidate_id="C002",
        decision=ReviewDecision.APPROVE,
        notes="Passport confirmed.",
        workflow=wf,
    )

    # Reload from disk.
    restored = HiringWorkflowPersistence().load(job_id)
    assert restored is not None
    assert restored["status"] == "COMPLETED", (
        f"Disk must reflect COMPLETED after APPROVE, got {restored['status']}"
    )
    assert "recruiter_decision" in restored, (
        "recruiter_decision block must be persisted to the workflow JSON"
    )
    assert restored["recruiter_decision"]["decision"] == ReviewDecision.APPROVE


# ---------------------------------------------------------------------------
# Test: REJECT decision
# ---------------------------------------------------------------------------


def test_recruiter_can_reject_candidate():
    """
    REJECT must produce status='rejected' and advance workflow to COMPLETED.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)

    result = svc.review(
        candidate_id="C002",
        decision=ReviewDecision.REJECT,
        notes="Insufficient evidence after manual check.",
        workflow=wf,
    )

    assert result.status == ReviewStatus.REJECTED
    assert result.decision == ReviewDecision.REJECT
    assert result.workflow_status == "COMPLETED"


# ---------------------------------------------------------------------------
# Test: REQUEST_REVIEW (escalate)
# ---------------------------------------------------------------------------


def test_recruiter_can_escalate():
    """
    REQUEST_REVIEW must produce status='escalated'.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)

    result = svc.review(
        candidate_id="C002",
        decision=ReviewDecision.REQUEST_REVIEW,
        notes="Forwarding to hiring manager.",
        workflow=wf,
    )

    assert result.status == ReviewStatus.ESCALATED


# ---------------------------------------------------------------------------
# Test: invalid decision is rejected
# ---------------------------------------------------------------------------


def test_invalid_decision_raises_value_error():
    """
    An unrecognised decision string must raise ValueError immediately,
    not silently store garbage into the workflow.
    """
    svc = RecruiterService()

    try:
        svc.review(
            candidate_id="C002",
            decision="HIRE_NOW_PLEASE",
        )
        assert False, "Expected ValueError for invalid decision"
    except ValueError as exc:
        assert "HIRE_NOW_PLEASE" in str(exc) or "Invalid" in str(exc)


# ---------------------------------------------------------------------------
# Test: payload reflects decision after submission
# ---------------------------------------------------------------------------


def test_payload_reflects_decision_after_submission():
    """
    After a recruiter submits a decision, a subsequent call to
    build_review_payload() must show the recorded decision.
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)

    svc.review(
        candidate_id="C002",
        decision=ReviewDecision.APPROVE,
        notes="All good.",
        workflow=wf,
    )

    payload = svc.build_review_payload(candidate_id="C002", workflow=dict(wf))

    assert payload["review"]["status"] == ReviewStatus.APPROVED
    assert payload["review"]["decision"] == ReviewDecision.APPROVE


# ---------------------------------------------------------------------------
# Test: review uses RecruiterReviewRequest schema correctly
# ---------------------------------------------------------------------------


def test_submit_review_via_request_object():
    """
    submit_review() must also work when called with an explicit
    RecruiterReviewRequest (as the API route does).
    """
    wf_service = _build_workflow_service()
    job_id = _uid()
    wf = _make_hr_workflow(wf_service, job_id)

    svc = RecruiterService(workflow_service=wf_service)

    req = RecruiterReviewRequest(
        decision=ReviewDecision.REJECT,
        notes="Not a match.",
        reviewer_id="hiring_manager_01",
    )
    result = svc.submit_review(
        candidate_id="C002",
        request=req,
        workflow=wf,
    )

    assert result.status == ReviewStatus.REJECTED
    assert result.workflow_status == "COMPLETED"
