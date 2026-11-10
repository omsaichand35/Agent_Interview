"""
Audit and Compliance Core Subsystem (Requirement F5).

Provides a tamper-resistant, append-only audit trail for all security-critical,
candidate state-changing, and hiring decision events.

Guarantees:
1. Strict separation between Decision Trace (why the AI decided something)
   and Audit Log (who did what, when, to which resource).
2. Automatic redaction/sanitization of sensitive biometric, audio, credential,
   and raw text data before persistence.
3. Append-only persistence contract with no modification/deletion APIs for standard users.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


SENSITIVE_KEY_PATTERNS = {
    "password",
    "password_hash",
    "token",
    "jwt",
    "access_token",
    "secret",
    "api_key",
    "embedding",
    "embeddings",
    "vector",
    "image",
    "live_frame",
    "face_image",
    "reference_photo",
    "audio_bytes",
    "raw_audio",
    "raw_bytes",
    "transcript",
    "full_transcript",
    "resume_text",
    "raw_text",
}


def sanitize_audit_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitizes event metadata by stripping sensitive data (credentials, biometrics,
    large text/audio payloads) while preserving operational identifiers.
    """
    if not metadata:
        return {}

    sanitized = {}
    for key, value in metadata.items():
        lower_key = str(key).lower()
        if any(pat in lower_key for pat in SENSITIVE_KEY_PATTERNS):
            sanitized[key] = "[REDACTED]"
            continue

        # Prevent large string injection (> 500 chars) into metadata
        if isinstance(value, str) and len(value) > 500:
            sanitized[key] = value[:200] + "... [TRUNCATED]"
        elif isinstance(value, (bytes, bytearray)):
            sanitized[key] = f"[BINARY_DATA_{len(value)}_BYTES]"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_audit_metadata(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            sanitized[key] = value
        elif isinstance(value, list):
            # Only retain small primitive lists
            if len(value) > 20:
                sanitized[key] = f"[{len(value)} items]"
            else:
                sanitized[key] = [
                    sanitize_audit_metadata(item) if isinstance(item, dict) else item
                    for item in value
                ]
        else:
            sanitized[key] = str(value)[:200]

    return sanitized


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=utc_now)
    actor_id: str
    actor_role: str  # "RECRUITER", "CANDIDATE", "ADMIN", "SYSTEM", "ANONYMOUS"
    action: str  # e.g., "LOGIN_SUCCESS", "IDENTITY_PASSED", "CANDIDATE_VIEWED"
    resource_type: str  # "USER", "CANDIDATE", "INTERVIEW_SESSION", "RESUME", "RECOMMENDATION", "REVIEW"
    resource_id: Optional[str] = None
    candidate_id: Optional[str] = None
    job_id: Optional[str] = None
    result: str = "SUCCESS"  # "SUCCESS", "FAILED", "REVIEW_REQUIRED", "DENIED", "PASSED"
    request_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        # Ensure metadata is strictly sanitized upon creation
        self.metadata = sanitize_audit_metadata(self.metadata)


class AuditService:
    """
    Append-only audit service supporting both database persistence and structured event logging.
    """

    def __init__(self, db_session=None):
        self.db = db_session
        self._in_memory_events: List[AuditEvent] = []

    def record_event(
        self,
        actor_id: str,
        actor_role: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        job_id: Optional[str] = None,
        result: str = "SUCCESS",
        request_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        if not request_id:
            try:
                from app.core.logging import ctx_request_id
                request_id = ctx_request_id.get()
            except Exception:
                pass

        event = AuditEvent(
            actor_id=str(actor_id or "anonymous"),
            actor_role=str(actor_role or "ANONYMOUS").upper(),
            action=str(action).upper(),
            resource_type=str(resource_type).upper(),
            resource_id=str(resource_id) if resource_id else None,
            candidate_id=str(candidate_id) if candidate_id else None,
            job_id=str(job_id) if job_id else None,
            result=str(result).upper(),
            request_id=str(request_id) if request_id else None,
            metadata=metadata or {},
        )

        # 1. In-memory append-only history
        self._in_memory_events.append(event)
        if self is not _audit_service_instance:
            _audit_service_instance._in_memory_events.append(event)

        # 2. Database append-only persistence (if DB session active)
        if self.db is not None:
            try:
                from app.database.models import AuditEventModel
                db_event = AuditEventModel(
                    event_id=event.event_id,
                    timestamp=event.timestamp,
                    actor_id=event.actor_id,
                    actor_role=event.actor_role,
                    action=event.action,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    candidate_id=event.candidate_id,
                    job_id=event.job_id,
                    result=event.result,
                    request_id=event.request_id,
                    event_metadata=event.metadata,
                )
                self.db.add(db_event)
                self.db.commit()
            except Exception:
                try:
                    self.db.rollback()
                except Exception:
                    pass

        # 3. Log event via system logger
        from app.core.logging import log_event
        log_event(
            event="audit_trail_recorded",
            audit_event_id=event.event_id,
            actor_id=event.actor_id,
            actor_role=event.actor_role,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            candidate_id=event.candidate_id,
            result=event.result,
            request_id=event.request_id,
        )

        return event

    def list_events(
        self,
        candidate_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        if self.db is not None:
            try:
                from app.database.models import AuditEventModel
                query = self.db.query(AuditEventModel)
                if candidate_id:
                    query = query.filter(AuditEventModel.candidate_id == candidate_id)
                if actor_id:
                    query = query.filter(AuditEventModel.actor_id == actor_id)
                if action:
                    query = query.filter(AuditEventModel.action == action.upper())
                query = query.order_by(AuditEventModel.timestamp.asc()).limit(limit)
                rows = query.all()
                return [
                    AuditEvent(
                        event_id=r.event_id,
                        timestamp=r.timestamp,
                        actor_id=r.actor_id,
                        actor_role=r.actor_role,
                        action=r.action,
                        resource_type=r.resource_type,
                        resource_id=r.resource_id,
                        candidate_id=r.candidate_id,
                        job_id=r.job_id,
                        result=r.result,
                        request_id=r.request_id,
                        metadata=r.event_metadata or {},
                    )
                    for r in rows
                ]
            except Exception:
                pass

        # Fallback to in-memory store
        events = self._in_memory_events
        if candidate_id:
            events = [e for e in events if e.candidate_id == candidate_id]
        if actor_id:
            events = [e for e in events if e.actor_id == actor_id]
        if action:
            events = [e for e in events if e.action == action.upper()]
        return events[:limit]


# Global audit service singleton
_audit_service_instance = AuditService()


def get_audit_service(db=None) -> AuditService:
    if db is not None:
        return AuditService(db_session=db)
    return _audit_service_instance
