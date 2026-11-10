"""
RecruiterService: handles the human-in-the-loop review step.

Flow
----
    Candidate flagged for HUMAN_REVIEW
         |
         v
    GET /candidates/{id}/review       -> build_review_payload()
         |
         v
    POST /candidates/{id}/review      -> submit_review()
         |
         v
    WorkflowService.complete_review() -> persist updated workflow
         |
         v
    Workflow status -> COMPLETED

Rules
-----
* Only the backend updates workflow status (never the frontend directly).
* Identity-failure reason is always surfaced in the payload so the
  recruiter understands *why* the candidate reached human review.
* A submitted decision is persisted both in-memory and in the workflow
  JSON file so it survives a backend restart.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.models.recommendation import (
    RecruiterReview,
    RecruiterReviewRequest,
    RecruiterReviewResponse,
    ReviewDecision,
    ReviewStatus,
)


class RecruiterService:

    def __init__(
        self,
        workflow_service=None,
        recommendation_service=None,
        interview_registry=None,
    ):
        self.workflow_service = workflow_service
        self.recommendation_service = recommendation_service
        self.interview_registry = interview_registry

        # In-memory store: candidate_id -> RecruiterReview
        self._reviews: Dict[str, RecruiterReview] = {}

    # ------------------------------------------------------------------
    # GET payload
    # ------------------------------------------------------------------

    def build_review_payload(
        self,
        candidate_id: str,
        workflow=None,
    ) -> Dict[str, Any]:
        """
        Aggregate all evidence needed by the recruiter dashboard:
        resume, interview transcript, identity checks, and the reason
        the candidate reached human review.

        Returns a plain dict that the API route serialises directly.
        """
        payload: Dict[str, Any] = {"candidate_id": candidate_id}

        # ── Identity info ──────────────────────────────────────────────
        identity_info = {
            "status": "unknown",
            "confidence": None,
            "checks": [],
            "failure_reason": None,
        }

        # ── Interview info ─────────────────────────────────────────────
        interview_info = {
            "transcript": [],
            "competency_scores": {},
            "interview_score": None,
            "interview_complete": False,
        }

        interview_state = None
        if self.interview_registry:
            try:
                interview_state = self.interview_registry.get_by_candidate(candidate_id)
            except Exception:
                pass

        if interview_state:
            interview_info["transcript"]        = interview_state.get("conversation_history", [])
            interview_info["competency_scores"] = interview_state.get("competency_scores", {})
            interview_info["interview_score"]   = interview_state.get("interview_score")
            interview_info["interview_complete"] = interview_state.get("interview_complete", False)
            identity_info["status"]     = interview_state.get("identity_status", "unknown")
            identity_info["confidence"] = interview_state.get("last_identity_confidence")
            identity_info["failure_reason"] = interview_state.get("identity_failure_reason")
            if interview_state.get("identity_check_count", 0) > 0:
                identity_info["checks"] = [
                    {
                        "timestamp": interview_state.get("reviewed_at", datetime.now(timezone.utc).isoformat()),
                        "confidence": identity_info["confidence"],
                        "status": identity_info["status"],
                    }
                ]

        payload["interview"] = interview_info
        payload["identity"]  = identity_info

        # ── Resume + interview scores ──────────────────────────────────
        payload["resume_score"]    = None
        payload["interview_score"] = interview_info["interview_score"]

        # ── Workflow human_review entry ────────────────────────────────
        review_reason = "human_review_requested"
        if workflow:
            for entry in workflow.get("human_review", []):
                if isinstance(entry, dict) and entry.get("candidate_id") == candidate_id:
                    review_reason = entry.get("reason", review_reason)
                    if not identity_info["failure_reason"]:
                        identity_info["failure_reason"] = entry.get("identity_result", {}).get("failure_reason")
                    break
                elif entry == candidate_id:
                    review_reason = "identity_verification_failed"
                    break

        elif self.workflow_service:
            try:
                for wf in self.workflow_service.persistence.list_all():
                    for entry in wf.get("human_review", []):
                        if (isinstance(entry, dict) and entry.get("candidate_id") == candidate_id) or entry == candidate_id:
                            review_reason = (entry.get("reason", review_reason) if isinstance(entry, dict) else review_reason)
                            # Also grab candidate resume_score from workflow candidates list
                            for cand in wf.get("candidates", []):
                                if isinstance(cand, dict) and cand.get("candidate_id") == candidate_id:
                                    payload["resume_score"] = cand.get("resume_score")
                            break
            except Exception:
                pass

        if identity_info["status"] in ("failed", "identity_failed"):
            review_reason = "identity_verification_failed"

        payload["review_reason"] = review_reason

        # ── Human review status & reason ──────────────────────────────
        requires_review = False
        reason = review_reason
        if self.recommendation_service:
            try:
                hr_rec = self.recommendation_service.get_human_review(candidate_id)
                if hr_rec and hr_rec.get("requires_review"):
                    requires_review = True
                    reason = hr_rec.get("reason", review_reason)
            except Exception:
                pass

        if not requires_review and (identity_info["status"] in ("failed", "identity_failed") or review_reason in ("identity_verification_failed", "Face mismatch")):
            requires_review = True

        payload["requires_review"] = requires_review
        payload["reason"] = reason

        # ── Existing review decision (if already submitted) ────────────
        existing = self._reviews.get(candidate_id)
        payload["review"] = {
            "status": existing.review_status if existing else ReviewStatus.PENDING,
            "decision": existing.reviewer_decision if existing else None,
            "notes": existing.reviewer_notes if existing else None,
            "reviewed_at": existing.reviewed_at.isoformat() if existing and existing.reviewed_at else None,
        }

        return payload

    # ------------------------------------------------------------------
    # POST decision
    # ------------------------------------------------------------------

    def submit_review(
        self,
        candidate_id: str,
        request: Optional[RecruiterReviewRequest] = None,
        workflow=None,
        job_id: Optional[str] = None,
        review_request: Optional[RecruiterReviewRequest] = None,
    ) -> RecruiterReviewResponse:
        """
        Record the recruiter's decision and advance the workflow to COMPLETED.

        Parameters
        ----------
        candidate_id : str
            The candidate being reviewed.
        request : RecruiterReviewRequest
            Contains decision, notes, reviewer_id.
        workflow : WorkflowState | None
            If provided, this exact workflow is updated; otherwise the
            service looks it up from workflow_service.
        job_id : str | None
            Used to look up the workflow when *workflow* is None.
        """
        req = request or review_request
        if req is None:
            raise ValueError("Review request must be provided")
        request = req
        if request.decision not in ReviewDecision.ALL:
            raise ValueError(
                f"Invalid decision '{request.decision}'. "
                f"Must be one of: {sorted(ReviewDecision.ALL)}"
            )

        reviewed_at = datetime.now(timezone.utc)
        status = ReviewStatus.FROM_DECISION[request.decision]

        review = RecruiterReview(
            candidate_id=candidate_id,
            reviewer_id=request.reviewer_id,
            reviewer_decision=request.decision,
            reviewer_notes=request.notes,
            review_status=status,
            reviewed_at=reviewed_at,
        )
        self._reviews[candidate_id] = review

        # ── Advance workflow status ────────────────────────────────────
        workflow_status = None
        wf = workflow

        if wf is None and self.workflow_service and job_id:
            wf = self.workflow_service.get(job_id)

        if wf is None and self.workflow_service:
            # Find the workflow containing this candidate.
            try:
                for candidate_wf in self.workflow_service.persistence.list_all():
                    hr = candidate_wf.get("human_review", [])
                    in_review = any(
                        (isinstance(e, dict) and e.get("candidate_id") == candidate_id) or e == candidate_id
                        for e in hr
                    )
                    if in_review:
                        wf = self.workflow_service.get(candidate_wf["job_id"])
                        break
            except Exception:
                pass

        if wf is not None:
            wf["recruiter_decision"] = {
                "candidate_id": candidate_id,
                "decision": request.decision,
                "status": status,
                "notes": request.notes,
                "reviewer_id": request.reviewer_id,
                "reviewed_at": reviewed_at.isoformat(),
            }
            wf["status"] = "COMPLETED"
            workflow_status = "COMPLETED"

            if self.workflow_service:
                try:
                    self.workflow_service.persistence.save(wf["job_id"], dict(wf))
                except Exception:
                    pass

        return RecruiterReviewResponse(
            candidate_id=candidate_id,
            status=status,
            decision=request.decision,
            notes=request.notes,
            reviewed_at=reviewed_at,
            workflow_status=workflow_status,
        )

    # ------------------------------------------------------------------
    # Convenience alias used in tests
    # ------------------------------------------------------------------

    def review(
        self,
        candidate_id: str,
        decision: str,
        notes: str = "",
        reviewer_id: str = "recruiter",
        workflow=None,
        job_id: Optional[str] = None,
    ) -> RecruiterReviewResponse:
        """Shorthand for submit_review() without constructing a request object."""
        return self.submit_review(
            candidate_id=candidate_id,
            request=RecruiterReviewRequest(
                decision=decision,
                notes=notes,
                reviewer_id=reviewer_id,
            ),
            workflow=workflow,
            job_id=job_id,
        )

    def get_review(self, candidate_id: str) -> Optional[RecruiterReview]:
        return self._reviews.get(candidate_id)
