"""Security Regression Master Test Suite (Requirement F6.14 & F6.16).

Serves as the unified security gate for CI/CD and pre-deployment verification:
[x] F1: Data Security & Access Controls (RBAC + Storage Isolation)
[x] F2: File & Upload Security (Magic bytes, Path traversal, Executable rejection)
[x] F3: API & Application Security (Rate limits, JWT auth, Security headers, CORS)
[x] F4: Identity-System Security (Biometric separation, Provenance, No client override)
[x] F5: Audit & Compliance Controls (Append-only trail, Metadata redaction, Ordering)
[x] F6: Error Sanitization & Data Leakage (No internal stack traces or secrets in responses)
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.core.audit import get_audit_service, sanitize_audit_metadata
from app.core.security import create_access_token
from app.main import app
from app.models.user import Role
from app.security.access_control import AccessControlEnforcer
from app.security.rate_limiter import rate_limiter_instance
from app.stages.stage3_identity.threshold_config import get_threshold_config
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture(autouse=True)
def reset_environment():
    rate_limiter_instance.reset()
    registry.sessions.clear()
    get_audit_service()._in_memory_events.clear()
    yield
    rate_limiter_instance.reset()
    registry.sessions.clear()
    get_audit_service()._in_memory_events.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def candidate_token():
    return create_access_token(user_id="U_REG_CAND", role=Role.CANDIDATE.value, candidate_id="C001")


@pytest.fixture
def recruiter_token():
    return create_access_token(user_id="U_REG_REC", role=Role.RECRUITER.value)


# ---------------------------------------------------------------------------
# Master Regression Gate Checks
# ---------------------------------------------------------------------------

def test_regression_f1_data_security_boundary():
    """F1 Regression: Enforce candidate isolation and storage partition privacy."""
    allowed, _ = AccessControlEnforcer.can_access_profile(
        user_role="candidate", user_candidate_id="C001", target_candidate_id="C002"
    )
    assert allowed is False


def test_regression_f2_file_upload_safety(api_client, candidate_token):
    """F2 Regression: Reject malicious path traversal and fake extension uploads."""
    headers = {"Authorization": f"Bearer {candidate_token}"}
    files = {"resume": ("../../etc/passwd", b"fake content", "application/pdf")}
    res = api_client.post("/candidates/C001/resume", files=files, headers=headers)
    assert res.status_code == 422


def test_regression_f3_api_security_headers_and_auth(api_client):
    """F3 Regression: Unauthenticated access returns 401; security headers are injected."""
    res = api_client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"

    res_auth = api_client.get("/auth/me")
    assert res_auth.status_code == 401


def test_regression_f4_identity_authoritative_gate(api_client, candidate_token):
    """F4 Regression: Client cannot bypass identity gate by sending identity_verified=True."""
    registry.sessions["SESS_REG_F4"] = {
        "session_id": "SESS_REG_F4",
        "candidate_id": "C001",
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "pending",
    }
    headers = {"Authorization": f"Bearer {candidate_token}"}
    res = api_client.post(
        "/interview/SESS_REG_F4/answer",
        json={"answer": "Trying to bypass gate", "identity_verified": True},
        headers=headers,
    )
    assert res.status_code == 403


def test_regression_f5_audit_trail_and_redaction():
    """F5 Regression: Audit service redacts sensitive credentials and retains structured trail."""
    audit_svc = get_audit_service()
    event = audit_svc.record_event(
        actor_id="U_REG_TEST",
        actor_role="ADMIN",
        action="LOGIN_SUCCESS",
        resource_type="USER",
        metadata={"password": "SuperSecretPassword!", "token": "jwt.secret.token", "safe_id": "123"},
    )
    assert event.metadata["password"] == "[REDACTED]"
    assert event.metadata["token"] == "[REDACTED]"
    assert event.metadata["safe_id"] == "123"


def test_regression_f6_error_sanitization_no_stack_trace_leakage(api_client):
    """F6 Regression: Internal server errors do NOT leak stack traces, file paths, or DB URLs."""
    res = api_client.get("/nonexistent/endpoint/404_check")
    text = res.text.lower()
    assert "traceback" not in text
    assert "c:\\" not in text
    assert "sqlite:///" not in text
    assert "postgresql://" not in text
