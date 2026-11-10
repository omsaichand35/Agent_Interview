"""
D3 Integration Tests: API Validation & Centralized Error Handling.

Validates that all API failures produce consistent, predictable error responses
matching the D3 standard:
{
    "error": {
        "code": "...",
        "message": "...",
        "request_id": "req_..."
    }
}
and never expose raw Python tracebacks or internal credentials.
"""

import io
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import create_access_token
from app.database.connection import get_db_context
from app.database.models import InterviewSessionModel
from app.database.repositories.candidate_repository import CandidateRepository
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def recruiter_token():
    return create_access_token(user_id="U_REC_01", role="recruiter")


@pytest.fixture
def candidate_err_token():
    return create_access_token(user_id="U_CAND_ERR", role="candidate", candidate_id="C_ERR_USER")


@pytest.fixture(autouse=True)
def setup_test_candidate():
    from app.api.dependencies import get_candidate_repository
    cand_repo = get_candidate_repository()
    cand_repo.create_or_update(
        candidate_id="C_ERR_USER",
        name="Alice ErrorTest",
        email="alice.err@example.com",
    )
    with get_db_context() as db:
        repo = CandidateRepository(db)
        repo.create_or_update(
            candidate_id="C_ERR_USER",
            name="Alice ErrorTest",
            email="alice.err@example.com",
            resume_score=82.0,
        )


def _assert_standard_error(response, expected_status: int, expected_code: str):
    """
    Asserts HTTP status code, presence of X-Request-ID header,
    structured JSON error envelope, and absence of raw tracebacks.
    """
    assert response.status_code == expected_status, f"Expected {expected_status}, got {response.status_code}: {response.text}"
    assert "X-Request-ID" in response.headers
    req_id_header = response.headers["X-Request-ID"]

    data = response.json()
    assert "error" in data, f"Expected 'error' in response JSON, got: {data}"
    error_obj = data["error"]

    assert "code" in error_obj
    assert error_obj["code"] == expected_code
    assert "message" in error_obj
    assert len(error_obj["message"]) > 0
    assert "request_id" in error_obj
    assert error_obj["request_id"] == req_id_header

    # Critical security boundary: Never leak raw Python tracebacks to the client
    assert "Traceback (most recent call last)" not in response.text
    assert "File \"" not in response.text


# ---------------------------------------------------------------------------
# 1. Request Validation Tests (D3.3)
# ---------------------------------------------------------------------------

def test_malformed_json_returns_400(client, recruiter_token):
    """Malformed or invalid JSON body must return 400 Bad Request."""
    headers = {
        "Authorization": f"Bearer {recruiter_token}",
        "Content-Type": "application/json",
    }
    # Raw broken JSON string
    response = client.post(
        "/auth/login",
        content="{broken_json: true,}",
        headers=headers,
    )
    _assert_standard_error(response, 400, "INVALID_REQUEST")


def test_missing_required_field_returns_400(client):
    """Missing required fields in Pydantic models must return 400."""
    response = client.post(
        "/auth/register",
        json={"role": "recruiter"},  # missing email and password
    )
    _assert_standard_error(response, 400, "INVALID_REQUEST")


def test_empty_interview_answer_returns_400(client):
    """An empty or whitespace-only interview answer must return 400."""
    cand_token = create_access_token(user_id="U_EMPTY_TEST", role="candidate", candidate_id="C_EMPTY_TEST")
    registry.create(
        "SESSION_EMPTY_TEST",
        {
            "session_id": "SESSION_EMPTY_TEST",
            "candidate_id": "C_EMPTY_TEST",
            "turn_number": 1,
            "interview_complete": False,
        },
    )

    headers = {"Authorization": f"Bearer {cand_token}"}
    response = client.post(
        "/interview/SESSION_EMPTY_TEST/answer",
        json={"answer": "   "},
        headers=headers,
    )
    _assert_standard_error(response, 400, "INVALID_REQUEST")


# ---------------------------------------------------------------------------
# 2. Upload Validation Tests (D3.4)
# ---------------------------------------------------------------------------

def test_oversized_resume_returns_422(client, candidate_err_token):
    """A resume file exceeding the 10MB limit must be rejected."""
    headers = {"Authorization": f"Bearer {candidate_err_token}"}
    # 11 MB fake PDF
    oversized_data = b"%PDF-" + (b"0" * (11 * 1024 * 1024))
    response = client.post(
        "/candidates/C_ERR_USER/resume",
        files={"resume": ("resume.pdf", io.BytesIO(oversized_data), "application/pdf")},
        headers=headers,
    )
    _assert_standard_error(response, 422, "INVALID_UPLOAD")


def test_invalid_pdf_signature_returns_422(client, candidate_err_token):
    """A file with a .pdf extension that does not start with %PDF- magic bytes must be rejected."""
    headers = {"Authorization": f"Bearer {candidate_err_token}"}
    fake_pdf = b"Plain text file masquerading as a PDF document"
    response = client.post(
        "/candidates/C_ERR_USER/resume",
        files={"resume": ("malicious.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        headers=headers,
    )
    _assert_standard_error(response, 422, "INVALID_UPLOAD")


def test_invalid_identity_image_returns_422_or_400(client, recruiter_token):
    """A corrupted or non-image upload to identity checks must be rejected."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    fake_img = b"Not an image at all - random corrupted binary data"
    response = client.post(
        "/identity/SESSION001/check",
        data={"candidate_id": "C_ERR_USER"},
        files={"image": ("corrupted.jpg", io.BytesIO(fake_img), "image/jpeg")},
        headers=headers,
    )
    _assert_standard_error(response, 422, "INVALID_UPLOAD")


def test_invalid_audio_returns_422(client):
    """An unsupported or corrupted audio format must be rejected."""
    candidate_token = create_access_token(
        user_id="U_CAND_ERR", role="candidate", candidate_id="C_ERR_USER"
    )
    registry.create(
        "SESSION_INVALID_AUDIO",
        {
            "session_id": "SESSION_INVALID_AUDIO",
            "candidate_id": "C_ERR_USER",
            "identity_status": "verified",
            "identity_verified": True,
            "interview_complete": False,
        },
    )
    fake_audio = b"Corrupted bytes that do not match WAV, MP3, or WEBM signatures"
    response = client.post(
        "/interview/SESSION_INVALID_AUDIO/answer/audio",
        files={
            "audio": ("corrupted.wav", io.BytesIO(fake_audio), "audio/wav"),
            "live_frame": ("live_frame.jpg", io.BytesIO(b"invalid image"), "image/jpeg"),
        },
        headers={"Authorization": f"Bearer {candidate_token}"},
    )
    _assert_standard_error(response, 422, "INVALID_UPLOAD")


# ---------------------------------------------------------------------------
# 3. Authentication & Authorization Failure Tests
# ---------------------------------------------------------------------------

def test_unauthorized_request_returns_401(client):
    """Unauthenticated requests to protected endpoints return 401."""
    response = client.get("/candidates/C_ERR_USER")
    _assert_standard_error(response, 401, "UNAUTHORIZED")


def test_forbidden_candidate_access_returns_403(client, candidate_err_token):
    """A candidate attempting to access another candidate's resources returns 403."""
    headers = {"Authorization": f"Bearer {candidate_err_token}"}
    response = client.get("/candidates/C999", headers=headers)
    _assert_standard_error(response, 403, "FORBIDDEN")


# ---------------------------------------------------------------------------
# 4. Resource Not Found & Duplicate Tests
# ---------------------------------------------------------------------------

def test_invalid_candidate_id_returns_404(client, recruiter_token):
    """Querying an unknown candidate ID returns 404 with CANDIDATE_NOT_FOUND code."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    response = client.get("/candidates/NON_EXISTENT_CANDIDATE_999", headers=headers)
    _assert_standard_error(response, 404, "CANDIDATE_NOT_FOUND")


def test_invalid_session_id_returns_404(client, recruiter_token):
    """Querying an unknown interview session returns 404 with INTERVIEW_NOT_FOUND code."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    response = client.get("/interview/NON_EXISTENT_SESSION_999", headers=headers)
    _assert_standard_error(response, 404, "INTERVIEW_NOT_FOUND")


def test_duplicate_schedule_returns_409(client, candidate_err_token):
    """Attempting to schedule a candidate who already has an active interview returns 409 DUPLICATE_SCHEDULE."""
    with get_db_context() as db:
        existing = db.query(InterviewSessionModel).filter_by(candidate_id="C_ERR_USER").first()
        if not existing:
            sess = InterviewSessionModel(id="SESS_EXISTING_ERR", candidate_id="C_ERR_USER", status="scheduled")
            db.add(sess)
            db.commit()

    headers = {"Authorization": f"Bearer {candidate_err_token}"}
    response = client.post(
        "/candidates/C_ERR_USER/schedule?slot_id=slot_test", headers=headers
    )
    _assert_standard_error(response, 409, "DUPLICATE_SCHEDULE")


# ---------------------------------------------------------------------------
# 5. External Service Failures & Unexpected Exceptions
# ---------------------------------------------------------------------------

def test_simulated_llm_failure_returns_503(client):
    """LLM connection timeout or provider outages return 503 LLM_UNAVAILABLE."""
    response = client.get("/test/simulate-llm-failure")
    _assert_standard_error(response, 503, "LLM_UNAVAILABLE")


def test_simulated_stt_failure_returns_503(client):
    """STT speech-to-text service outages return 503 STT_UNAVAILABLE."""
    response = client.get("/test/simulate-stt-failure")
    _assert_standard_error(response, 503, "STT_UNAVAILABLE")


def test_unexpected_exception_returns_500_without_traceback():
    """Unhandled internal errors return 500 without leaking stack trace or file paths."""
    # When testing 500 responses with Starlette TestClient, disable raise_server_exceptions
    # so the client receives the generated 500 response from the exception handler.
    with TestClient(app, raise_server_exceptions=False) as client_500:
        response = client_500.get("/test/simulate-error")
        _assert_standard_error(response, 500, "INTERNAL_SERVER_ERROR")
        # Verify internal python error string and stack trace are hidden from client
        assert "Simulated unexpected backend database failure" not in response.text
        assert "RuntimeError" not in response.text
