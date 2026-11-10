import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Context variables for correlation across request lifecycle
ctx_request_id: ContextVar[Optional[str]] = ContextVar("ctx_request_id", default=None)
ctx_session_id: ContextVar[Optional[str]] = ContextVar("ctx_session_id", default=None)
ctx_candidate_id: ContextVar[Optional[str]] = ContextVar("ctx_candidate_id", default=None)
ctx_job_id: ContextVar[Optional[str]] = ContextVar("ctx_job_id", default=None)
ctx_user_id: ContextVar[Optional[str]] = ContextVar("ctx_user_id", default=None)

# Patterns for sensitive data that must NEVER appear in logs
SENSITIVE_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r'"password"\s*:\s*"[^"]*"', re.IGNORECASE), '"password": "[REDACTED]"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"', re.IGNORECASE), '"token": "[REDACTED]"'),
    (re.compile(r'"api_key"\s*:\s*"[^"]*"', re.IGNORECASE), '"api_key": "[REDACTED]"'),
    (re.compile(r"ey[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*"), "[JWT_REDACTED]"),
]

# Sensitive keys in dictionaries
SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "jwt",
    "api_key",
    "secret",
    "face_image",
    "face_reference",
    "image_bytes",
    "live_image",
    "audio_bytes",
    "raw_audio",
    "resume_content",
    "full_resume",
    "transcript",
    "full_transcript",
    "embedding",
    "embeddings",
    "biometrics",
}


def sanitize_value(key: str, val: Any) -> Any:
    """Sanitizes sensitive data keys and values."""
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(val, bytes):
        return f"[BINARY_DATA_{len(val)}_BYTES]"
    if isinstance(val, str):
        # Truncate extremely long strings (like base64 or raw text dumps)
        if len(val) > 2000 and ("base64" in val or val.startswith("data:image")):
            return "[IMAGE_DATA_REDACTED]"
        for pattern, repl in SENSITIVE_PATTERNS:
            val = pattern.sub(repl, val)
        return val
    if isinstance(val, dict):
        return {k: sanitize_value(k, v) for k, v in val.items()}
    if isinstance(val, list):
        return [sanitize_value(key, item) for item in val]
    return val


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured, machine-readable JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Correlate via ContextVars if available
        req_id = ctx_request_id.get() or getattr(record, "request_id", None)
        if req_id:
            payload["request_id"] = req_id

        sess_id = ctx_session_id.get() or getattr(record, "session_id", None)
        if sess_id:
            payload["session_id"] = sess_id

        cand_id = ctx_candidate_id.get() or getattr(record, "candidate_id", None)
        if cand_id:
            payload["candidate_id"] = cand_id

        job_id = ctx_job_id.get() or getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = job_id

        user_id = ctx_user_id.get() or getattr(record, "user_id", None)
        if user_id:
            payload["user_id"] = user_id

        # Merge extra attributes if passed in logger call
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            for k, v in record.extra_fields.items():
                if k not in payload:
                    payload[k] = sanitize_value(k, v)

        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "extra_fields",
        }
        for k, v in record.__dict__.items():
            if k not in standard_attrs and k not in payload:
                payload[k] = sanitize_value(k, v)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class LogCaptureHandler(logging.Handler):
    """Thread-safe in-memory handler for inspecting structured logs during testing."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self.capacity = capacity
        self.records: List[Dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = self.format(record)
            parsed = json.loads(formatted)
            self.records.append(parsed)
            if len(self.records) > self.capacity:
                self.records.pop(0)
        except Exception:
            pass

    def clear(self) -> None:
        self.records.clear()


# Global capture handler for test verification
captured_log_handler = LogCaptureHandler()
captured_log_handler.setFormatter(StructuredJsonFormatter())

root_logger = logging.getLogger()
root_logger.addHandler(captured_log_handler)

event_logger = logging.getLogger("platform.events")
event_logger.setLevel(logging.INFO)


def log_event(event: str, level: str = "INFO", **kwargs) -> None:
    """Logs a structured domain event with correlation IDs and sanitization."""
    sanitized = {k: sanitize_value(k, v) for k, v in kwargs.items()}

    # Extract correlation fields from kwargs or fallback to ContextVars
    req_id = sanitized.pop("request_id", None) or ctx_request_id.get()
    sess_id = sanitized.pop("session_id", None) or ctx_session_id.get()
    cand_id = sanitized.pop("candidate_id", None) or ctx_candidate_id.get()
    job_id = sanitized.pop("job_id", None) or ctx_job_id.get()
    user_id = sanitized.pop("user_id", None) or ctx_user_id.get()

    extra = {
        "event": event,
        "request_id": req_id,
        "session_id": sess_id,
        "candidate_id": cand_id,
        "job_id": job_id,
        "user_id": user_id,
        "extra_fields": sanitized,
    }

    log_method = getattr(event_logger, level.lower(), event_logger.info)
    log_method(f"Event: {event}", extra=extra)


def get_captured_logs() -> List[Dict[str, Any]]:
    """Returns in-memory captured structured log records for assertions."""
    return list(captured_log_handler.records)


def clear_captured_logs() -> None:
    """Clears captured log records."""
    captured_log_handler.clear()
