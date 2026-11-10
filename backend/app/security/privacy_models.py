"""Domain-Segregated Candidate Privacy and Storage Models (Requirement F1.2)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataClassificationLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class CandidateProfileRecord(BaseModel):
    """General candidate profile domain."""
    candidate_id: str
    name: str
    email: str
    phone: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification: DataClassificationLevel = DataClassificationLevel.CONFIDENTIAL


class ResumeRecord(BaseModel):
    """Resume and qualification evidence domain."""
    candidate_id: str
    resume_file_path: str
    extracted_text: str
    detected_skills: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification: DataClassificationLevel = DataClassificationLevel.CONFIDENTIAL


class InterviewRecord(BaseModel):
    """Conversational interview and scoring domain."""
    session_id: str
    candidate_id: str
    audio_file_path: Optional[str] = None
    transcript_text: str = ""
    competency_scores: Dict[str, float] = Field(default_factory=dict)
    final_score: Optional[float] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification: DataClassificationLevel = DataClassificationLevel.CONFIDENTIAL


class IdentityRecord(BaseModel):
    """Sensitive biometric and anti-proxy verification domain [RESTRICTED]."""
    candidate_id: str
    session_id: str
    face_reference_path: str
    confidence: float
    liveness_passed: bool
    status: str  # verified, failed, pending
    fraud_flags: List[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification: DataClassificationLevel = DataClassificationLevel.RESTRICTED


class RecruiterReviewRecord(BaseModel):
    """Human recruiter review and decision override domain."""
    candidate_id: str
    recruiter_id: str
    recommendation_decision: str  # HIRE, CONSIDER, REJECT
    human_notes: str
    override_applied: bool = False
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    classification: DataClassificationLevel = DataClassificationLevel.INTERNAL


class AuditLogEvent(BaseModel):
    """Immutable audit trail for compliance, access, and deletion events."""
    event_id: str
    event_type: str  # candidate_deleted, access_denied, identity_verified
    actor_id: str
    actor_role: str
    target_candidate_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
