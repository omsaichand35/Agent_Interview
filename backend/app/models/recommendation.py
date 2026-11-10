"""
Recruiter review data model.

A RecruiterReview records the outcome of a human decision on any candidate
that could not be automatically processed by Stage 5 (typically an identity
failure, but extensible to any workflow flag).

Decision values
---------------
APPROVE        -- Recruiter accepts the candidate despite the flag.
REJECT         -- Recruiter rejects the candidate.
REQUEST_REVIEW -- Recruiter escalates for a second opinion.

Status values
-------------
pending   -- Review created but not yet decided.
approved  -- Recruiter approved the candidate.
rejected  -- Recruiter rejected the candidate.
escalated -- Forwarded for second opinion.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class ReviewDecision:
    APPROVE        = "APPROVE"
    REJECT         = "REJECT"
    REQUEST_REVIEW = "REQUEST_REVIEW"

    ALL = {APPROVE, REJECT, REQUEST_REVIEW}


class ReviewStatus:
    PENDING   = "pending"
    APPROVED  = "approved"
    REJECTED  = "rejected"
    ESCALATED = "escalated"

    # Decision -> status mapping so service code stays in one place.
    FROM_DECISION = {
        ReviewDecision.APPROVE:        APPROVED,
        ReviewDecision.REJECT:         REJECTED,
        ReviewDecision.REQUEST_REVIEW: ESCALATED,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RecruiterReview(BaseModel):
    """Persisted record of a recruiter's decision on a flagged candidate."""

    model_config = ConfigDict()

    candidate_id: str

    # Why the candidate reached human review.
    review_reason: str = "identity_verification_failed"
    identity_failure_reason: Optional[str] = None

    # Recruiter identity.
    reviewer_id: str = "recruiter"

    # The decision itself.
    reviewer_decision: Optional[str] = None     # APPROVE | REJECT | REQUEST_REVIEW
    reviewer_notes: Optional[str] = None

    # Lifecycle.
    review_status: str = ReviewStatus.PENDING
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RecruiterReviewRequest(BaseModel):
    """Request body for POST /candidates/{id}/review."""

    model_config = ConfigDict()

    decision: str           # APPROVE | REJECT | REQUEST_REVIEW
    notes: Optional[str] = None
    reviewer_id: str = "recruiter"


class RecruiterReviewResponse(BaseModel):
    """Response body after a recruiter submits a review."""

    model_config = ConfigDict()

    candidate_id: str
    status: str                    # approved | rejected | escalated
    decision: str
    notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    workflow_status: Optional[str] = None   # updated workflow status

    @property
    def review_status(self) -> str:
        return self.status
