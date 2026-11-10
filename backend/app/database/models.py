from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    department = Column(String(128), nullable=False, default="Engineering")
    description = Column(Text, nullable=True)
    required_skills = Column(JSON, nullable=True, default=list)
    status = Column(String(64), nullable=False, default="OPEN")
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    candidates = relationship("CandidateModel", back_populates="job", cascade="all, delete-orphan")
    sessions = relationship("InterviewSessionModel", back_populates="job")


class ProgramRecruiterAccessModel(Base):
    """Ownership boundary connecting recruiter accounts to the programs they manage."""

    __tablename__ = "program_recruiter_access"
    __table_args__ = (
        UniqueConstraint("program_id", "recruiter_id", name="uq_program_recruiter_access"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    program_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    recruiter_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class CandidateModel(Base):
    __tablename__ = "candidates"

    id = Column(String(64), primary_key=True, index=True)
    job_id = Column(String(64), ForeignKey("jobs.id"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(64), nullable=True)
    photo_path = Column(String(512), nullable=True)
    status = Column(String(64), nullable=False, default="APPLIED")
    resume_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    job = relationship("JobModel", back_populates="candidates")
    resumes = relationship("ResumeModel", back_populates="candidate", cascade="all, delete-orphan")
    identity_checks = relationship("IdentityCheckModel", back_populates="candidate", cascade="all, delete-orphan")
    interview_sessions = relationship("InterviewSessionModel", back_populates="candidate", cascade="all, delete-orphan")
    recommendations = relationship("RecommendationModel", back_populates="candidate", cascade="all, delete-orphan")
    reviews = relationship("RecruiterReviewModel", back_populates="candidate", cascade="all, delete-orphan")


class ResumeModel(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=False, index=True)
    file_path = Column(String(512), nullable=True)
    original_filename = Column(String(255), nullable=True)
    raw_text = Column(Text, nullable=True)
    parsed_skills = Column(JSON, nullable=True, default=list)
    experience_years = Column(Float, nullable=True)
    score = Column(Float, nullable=True)
    analysis = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    # Relationships
    candidate = relationship("CandidateModel", back_populates="resumes")


class ApplicationModel(Base):
    """One candidate's application to one academic program."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_id", "program_id", name="uq_application_candidate_program"),
    )

    id = Column(String(64), primary_key=True, index=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True)
    program_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    face_reference_path = Column(String(512), nullable=False)
    biometric_consent_at = Column(DateTime(timezone=True), nullable=False)
    biometric_consent_version = Column(String(64), nullable=False, default="admissions-face-consent-v1")
    status = Column(String(64), nullable=False, default="submitted")
    resume_score = Column(Float, nullable=True)
    interview_score = Column(Float, nullable=True)
    score_details = Column(JSON, nullable=True, default=dict)
    identity_status = Column(String(64), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    candidate = relationship("CandidateModel")
    program = relationship("JobModel")
    resume = relationship("ResumeModel")


class InterviewInviteModel(Base):
    """Single-use, expiring interview code issued by a recruiter."""

    __tablename__ = "interview_invites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    session_id = Column(String(64), nullable=False, unique=True, index=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    application = relationship("ApplicationModel")


class InterviewScheduleBatchModel(Base):
    """A recruiter's interview event divided into capacity-limited time slots."""

    __tablename__ = "interview_schedule_batches"

    id = Column(String(64), primary_key=True, index=True)
    program_id = Column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    first_slot_start = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    slot_duration_minutes = Column(Integer, nullable=False)
    people_per_slot = Column(Integer, nullable=False)
    number_of_slots = Column(Integer, nullable=False)
    selection_rule = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    program = relationship("JobModel")
    placements = relationship("InterviewScheduleModel", back_populates="batch", cascade="all, delete-orphan")


class InterviewScheduleModel(Base):
    """Persistent applicant-to-slot assignment, including reminder delivery state."""

    __tablename__ = "interview_schedules"
    __table_args__ = (
        UniqueConstraint("batch_id", "application_id", name="uq_schedule_batch_application"),
    )

    id = Column(String(64), primary_key=True, index=True)
    batch_id = Column(String(64), ForeignKey("interview_schedule_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(String(64), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    slot_number = Column(Integer, nullable=False)
    scheduled_start = Column(DateTime(timezone=True), nullable=False, index=True)
    scheduled_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(32), nullable=False, default="scheduled", index=True)
    reminder_claimed_at = Column(DateTime(timezone=True), nullable=True)
    reminder_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    batch = relationship("InterviewScheduleBatchModel", back_populates="placements")
    application = relationship("ApplicationModel")


class InterviewSessionModel(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(64), primary_key=True, index=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=False, index=True)
    job_id = Column(String(64), ForeignKey("jobs.id"), nullable=True, index=True)
    status = Column(String(64), nullable=False, default="pending")
    identity_verified = Column(Boolean, default=False)
    identity_status = Column(String(64), default="pending")
    identity_failure_reason = Column(String(255), nullable=True)
    gaze_warning_count = Column(Integer, nullable=False, default=0)
    gaze_flagged = Column(Boolean, nullable=False, default=False)
    gaze_flagged_at = Column(DateTime(timezone=True), nullable=True)
    gaze_events = Column(JSON, nullable=False, default=list)
    interview_score = Column(Float, nullable=True)
    turn_count = Column(Integer, default=0)
    current_question = Column(Text, nullable=True)
    competency_scores = Column(JSON, nullable=True, default=dict)
    conversation_history = Column(JSON, nullable=True, default=list)
    started_at = Column(DateTime(timezone=True), default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    candidate = relationship("CandidateModel", back_populates="interview_sessions")
    job = relationship("JobModel", back_populates="sessions")
    turns = relationship("InterviewTurnModel", back_populates="session", cascade="all, delete-orphan")


class InterviewTurnModel(Base):
    __tablename__ = "interview_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("interview_sessions.id"), nullable=False, index=True)
    turn_number = Column(Integer, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    audio_path = Column(String(512), nullable=True)
    scores = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    session = relationship("InterviewSessionModel", back_populates="turns")


class IdentityCheckModel(Base):
    __tablename__ = "identity_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    verified = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=True)
    failure_reason = Column(String(255), nullable=True)
    live_frame_path = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    candidate = relationship("CandidateModel", back_populates="identity_checks")


class RecommendationModel(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=False, index=True)
    job_id = Column(String(64), nullable=True, index=True)
    resume_score = Column(Float, nullable=True)
    interview_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=True)
    strengths = Column(JSON, nullable=True, default=list)
    gaps = Column(JSON, nullable=True, default=list)
    evidence = Column(JSON, nullable=True, default=list)
    status = Column(String(64), default="completed")
    created_at = Column(DateTime(timezone=True), default=utc_now)

    candidate = relationship("CandidateModel", back_populates="recommendations")


class RecruiterReviewModel(Base):
    __tablename__ = "recruiter_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=False, index=True)
    job_id = Column(String(64), nullable=True, index=True)
    reviewer_id = Column(String(128), nullable=False)
    decision = Column(String(64), nullable=False)
    status = Column(String(64), nullable=False, default="pending")
    notes = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), default=utc_now)

    candidate = relationship("CandidateModel", back_populates="reviews")


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(64), nullable=False, default="candidate")
    candidate_id = Column(String(64), ForeignKey("candidates.id"), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    candidate = relationship("CandidateModel")


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True, default=utc_now)
    actor_id = Column(String(128), nullable=False, index=True)
    actor_role = Column(String(64), nullable=False, index=True)
    action = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(128), nullable=True, index=True)
    candidate_id = Column(String(64), nullable=True, index=True)
    job_id = Column(String(64), nullable=True, index=True)
    result = Column(String(64), nullable=False, default="SUCCESS")
    request_id = Column(String(64), nullable=True, index=True)
    event_metadata = Column(JSON, nullable=True, default=dict)


