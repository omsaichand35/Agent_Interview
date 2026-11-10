"""Tests for Sensitive Log Sanitization (Requirement F1.8 & F1.9)."""

import json
import logging
from app.core.logging import (
    SENSITIVE_KEYS,
    StructuredJsonFormatter,
    sanitize_value,
)


def test_sensitive_passwords_and_tokens_redacted():
    """Requirement F1.8: Passwords, JWTs, and API keys must be redacted."""
    assert sanitize_value("password", "super_secret_pass_123") == "[REDACTED]"
    assert sanitize_value("token", "xyz_token_secret") == "[REDACTED]"
    assert sanitize_value("api_key", "sk-proj-1234567890abcdef") == "[REDACTED]"
    assert sanitize_value("jwt", "eyJh.eyJzdWIiOiIxIn0.sig") == "[REDACTED]"


def test_sensitive_media_and_biometrics_redacted():
    """Requirement F1.8: Face images, raw audio, and biometrics must be redacted."""
    assert sanitize_value("face_image", "base64_encoded_image_bytes...") == "[REDACTED]"
    assert sanitize_value("face_reference", "/path/to/face.jpg") == "[REDACTED]"
    assert sanitize_value("raw_audio", b"\x00\x01\x02\x03") == "[REDACTED]"
    assert sanitize_value("audio_bytes", b"RIFF...") == "[REDACTED]"
    assert sanitize_value("biometrics", {"vector": [0.12, 0.45]}) == "[REDACTED]"


def test_sensitive_full_transcripts_and_resumes_redacted():
    """Requirement F1.8: Full resumes and transcripts under sensitive keys are redacted."""
    assert sanitize_value("full_resume", "Complete resume text dump...") == "[REDACTED]"
    assert sanitize_value("full_transcript", "Turn 1: hello. Turn 2: answer...") == "[REDACTED]"
    assert sanitize_value("transcript", "Transcript text...") == "[REDACTED]"


def test_embedded_sensitive_patterns_in_string_redacted():
    """Requirement F1.8: Embedded tokens or passwords in string payloads are scrubbed."""
    raw_string = '{"user": "alice", "password": "superSecretPassword123"}'
    sanitized = sanitize_value("payload", raw_string)
    assert "superSecretPassword123" not in sanitized
    assert '"password": "[REDACTED]"' in sanitized


def test_structured_log_event_only_contains_metadata():
    """Requirement F1.8: Operational logs contain identifiers and event metadata, not sensitive data."""
    formatter = StructuredJsonFormatter()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="identity_check_completed",
        args=(),
        exc_info=None,
    )
    record.candidate_id = "C001"
    record.session_id = "S001"
    record.status = "passed"
    record.confidence = 0.91

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["message"] == "identity_check_completed"
    assert parsed["candidate_id"] == "C001"
    assert parsed["status"] == "passed"
    assert "password" not in parsed
    assert "face_image" not in parsed
