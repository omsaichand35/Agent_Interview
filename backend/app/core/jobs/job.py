from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobType(str, Enum):
    INTERVIEW_AUDIO = "INTERVIEW_AUDIO"
    RESUME_EXTRACTION = "RESUME_EXTRACTION"
    RECOMMENDATION = "RECOMMENDATION"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job(BaseModel):
    id: str
    type: str = JobType.INTERVIEW_AUDIO.value
    status: str = JobStatus.QUEUED.value
    session_id: Optional[str] = None
    candidate_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    def mark_running(self) -> None:
        self.status = JobStatus.RUNNING.value
        self.started_at = utc_now_iso()

    def mark_completed(self, result: Optional[Dict[str, Any]] = None) -> None:
        self.status = JobStatus.COMPLETED.value
        self.completed_at = utc_now_iso()
        if result is not None:
            self.result = result

    def mark_failed(self, error: str) -> None:
        self.status = JobStatus.FAILED.value
        self.completed_at = utc_now_iso()
        self.error = error

    def should_retry(self, error: Any) -> bool:
        """Determines if a failure is transient and eligible for bounded retry."""
        if self.retry_count >= self.max_retries:
            return False
        error_msg = str(error).lower()
        non_retryable_markers = [
            "invalid",
            "not found",
            "corrupt",
            "malformed",
            "identity",
            "unsupported",
            "empty transcription",
            "bad request",
            "422",
            "404",
            "400",
        ]
        if any(marker in error_msg for marker in non_retryable_markers):
            return False
        return True

    def record_retry(self, error: str) -> None:
        """Records a retry attempt and resets job to QUEUED state."""
        self.retry_count += 1
        self.status = JobStatus.QUEUED.value
        self.started_at = None
        self.error = f"Attempt {self.retry_count} failed transiently: {error}"

    def to_api_dict(self) -> Dict[str, Any]:
        """User-friendly API representation"""
        return {
            "job_id": self.id,
            "status": self.status.lower(),
            "type": self.type,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "result": self.result,
            "error": self.error,
        }

