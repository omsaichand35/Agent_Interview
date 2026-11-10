"""API and Application Security Test Suite (Requirement F3).

Verifies the platform's core HTTP defense boundaries:
[x] unauthenticated access -> 401
[x] wrong role -> 403
[x] another candidate -> 403
[x] expired JWT -> 401
[x] malformed JWT -> 401
[x] excessive login attempts -> 429
[x] excessive interview requests -> 429
[x] duplicate answer -> no duplicate turn (idempotency / replay protection)
[x] client cannot modify score
[x] client cannot modify decision
[x] client cannot skip identity gate
[x] recruiter-only endpoint protected
[x] CORS restricted & browser security headers enforced
"""

from datetime import timedelta
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import pytest

from app.core.security import create_access_token
from app.main import app
from app.models.user import Role
from app.security.rate_limiter import rate_limiter_instance
from app.stages.stage4_interview.dependencies import registry
from tests.fixtures.http import valid_live_frame_upload
import app.api.interview_routes as routes


@pytest.fixture(autouse=True)
def reset_rate_limits_and_state():
    """Reset rate limiter state and sessions before each test."""
    rate_limiter_instance.reset()
    registry.sessions.clear()
    yield
    rate_limiter_instance.reset()
    registry.sessions.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def recruiter_token():
    return create_access_token(user_id="U_REC_01", role=Role.RECRUITER.value)


@pytest.fixture
def candidate_c001_token():
    return create_access_token(
        user_id="U_CAND_01",
        role=Role.CANDIDATE.value,
        candidate_id="C001",
    )


@pytest.fixture
def candidate_c002_token():
    return create_access_token(
        user_id="U_CAND_02",
        role=Role.CANDIDATE.value,
        candidate_id="C002",
    )


# ---------------------------------------------------------------------------
# F3.8 & F3.9: Authentication & JWT Verification Tests
# ---------------------------------------------------------------------------

def test_unauthenticated_access_returns_401(api_client):
    """Requirement F3.8: Protected endpoints must reject unauthenticated requests with 401."""
    endpoints = [
        ("GET", "/candidates"),
        ("GET", "/recommendations"),
        ("POST", "/jobs"),
        ("POST", "/schedules"),
        ("GET", "/interview/SESSION001"),
        ("POST", "/interview/SESSION001/answer"),
    ]

    for method, path in endpoints:
        if method == "GET":
            res = api_client.get(path)
        else:
            res = api_client.post(path, json={})
        assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}"
        assert "Bearer" in res.headers.get("WWW-Authenticate", "")


def test_expired_jwt_returns_401(api_client):
    """Requirement F3.8: Expired JWT tokens must be rejected with 401 Unauthorized."""
    expired_token = create_access_token(
        user_id="U_EXPIRED",
        role=Role.RECRUITER.value,
        expires_delta=timedelta(minutes=-30),
    )
    res = api_client.get(
        "/candidates",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "expired" in res.json().get("detail", "").lower()


def test_malformed_jwt_returns_401(api_client):
    """Requirement F3.8: Malformed or forged tokens must be rejected with 401."""
    res = api_client.get(
        "/candidates",
        headers={"Authorization": "Bearer not.a.valid.jwt.signature"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# F3.2 & F3.6: Authorization & Session Ownership Boundaries
# ---------------------------------------------------------------------------

def test_wrong_role_returns_403(api_client, candidate_c001_token):
    """Requirement F3.6: Candidates cannot call recruiter-only endpoints."""
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}

    # 1. Listing all candidates
    res_cand = api_client.get("/candidates", headers=headers)
    assert res_cand.status_code == 403

    # 2. Creating background jobs
    res_jobs = api_client.post("/jobs", json={"session_id": "S1"}, headers=headers)
    assert res_jobs.status_code == 403

    # 3. Creating interview schedules
    res_sched = api_client.post(
        "/schedules",
        json={"candidate_id": "C001", "slot_id": "SLOT_01"},
        headers=headers,
    )
    assert res_sched.status_code == 403

    # 4. Listing all recommendations
    res_rec = api_client.get("/recommendations", headers=headers)
    assert res_rec.status_code == 403

    # 5. Submitting recruiter human review
    res_rev = api_client.post(
        "/candidates/C001/review",
        json={"decision": "APPROVE", "notes": "Hired"},
        headers=headers,
    )
    assert res_rev.status_code == 403


def test_another_candidate_access_returns_403(
    api_client,
    candidate_c001_token,
    candidate_c002_token,
):
    """Requirement F3.2 & F3.3: Candidate C002 cannot access Candidate C001's session or records."""
    # Seed session belonging to C001
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": True,
        "current_question": "Explain concurrency.",
    }

    # C002 attempts to fetch C001's interview session
    c002_headers = {"Authorization": f"Bearer {candidate_c002_token}"}
    res_sess = api_client.get("/interview/SESSION001", headers=c002_headers)
    assert res_sess.status_code == 403

    # C002 attempts to submit an answer to C001's session
    res_ans = api_client.post(
        "/interview/SESSION001/answer",
        json={"answer": "Hacked answer"},
        headers=c002_headers,
    )
    assert res_ans.status_code == 403

    # C001 accessing own session -> OK
    c001_headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res_own = api_client.get("/interview/SESSION001", headers=c001_headers)
    assert res_own.status_code == 200


def test_server_authoritative_session_derivation(
    api_client,
    candidate_c001_token,
    monkeypatch,
):
    """Requirement F3.2: Server derives candidate from session, ignoring client-supplied candidate_id."""
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": True,
        "current_question": "What is dependency injection?",
    }

    mock_controller = MagicMock()
    mock_controller.submit_text.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 2,
        "decision": "continue",
        "next_question": "How does IoC relate to DI?",
        "interview_score": 80.0,
        "interview_complete": False,
        "identity_verified": True,
    }
    monkeypatch.setattr(routes, "controller", mock_controller)

    # Client claims candidate_id="C002" in payload
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res = api_client.post(
        "/interview/SESSION001/answer",
        data={"answer": "DI decouples object creation.", "candidate_id": "C002"},
        files={"live_frame": valid_live_frame_upload()},
        headers=headers,
    )
    assert res.status_code == 200
    # Server returned response for authenticated owner C001
    assert res.json()["candidate_id"] == "C001"


# ---------------------------------------------------------------------------
# F3.1: Rate Limiting & Abuse Prevention Tests
# ---------------------------------------------------------------------------

def test_excessive_login_attempts_returns_429(api_client):
    """Requirement F3.1: Rate limiting stops brute-force login attempts (limit: 5/min)."""
    # 5 allowed requests
    for i in range(5):
        res = api_client.post(
            "/auth/login",
            json={"email": f"user{i}@test.com", "password": "wrongpassword"},
        )
        assert res.status_code in (400, 401)

    # 6th request within window -> 429 Too Many Requests
    res_blocked = api_client.post(
        "/auth/login",
        json={"email": "attacker@test.com", "password": "password123"},
    )
    assert res_blocked.status_code == 429
    assert "Rate limit exceeded" in res_blocked.json()["detail"]
    assert "Retry-After" in res_blocked.headers


def test_excessive_interview_requests_returns_429(api_client, candidate_c001_token):
    """Requirement F3.1: Rate limiting stops interview endpoint abuse (limit: 20/min)."""
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": True,
        "current_question": "Question?",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}

    # Exhaust limit
    for _ in range(20):
        # Empty answer fails validation (400), but counts towards rate limiter
        api_client.post(
            "/interview/SESSION001/answer",
            json={"answer": ""},
            headers=headers,
        )

    # 21st request -> 429
    res = api_client.post(
        "/interview/SESSION001/answer",
        json={"answer": "Valid text"},
        headers=headers,
    )
    assert res.status_code == 429


# ---------------------------------------------------------------------------
# F3.4 & F3.5: Replay Protection & Tamper Resistance Tests
# ---------------------------------------------------------------------------

def test_duplicate_answer_no_duplicate_turn(api_client, candidate_c001_token, monkeypatch):
    """Requirement F3.4: Replaying the same request with an Idempotency-Key returns cached response

    without advancing the interview turn.
    """
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 4,
        "interview_complete": False,
        "identity_verified": True,
        "current_question": "Explain Redis caching.",
    }

    mock_controller = MagicMock()
    mock_controller.submit_text.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 5,
        "decision": "deepen",
        "next_question": "How do you handle cache invalidation?",
        "interview_score": 85.0,
        "interview_complete": False,
        "identity_verified": True,
    }
    monkeypatch.setattr(routes, "controller", mock_controller)

    headers = {
        "Authorization": f"Bearer {candidate_c001_token}",
        "Idempotency-Key": "unique-idem-token-turn-4",
    }
    payload = {"answer": "We use Redis as a write-through cache."}

    # 1. First submission
    res_1 = api_client.post(
        "/interview/SESSION001/answer",
        data=payload,
        files={"live_frame": valid_live_frame_upload()},
        headers=headers,
    )
    assert res_1.status_code == 200
    assert mock_controller.submit_text.call_count == 1

    # 2. Network retry with identical idempotency key
    res_2 = api_client.post(
        "/interview/SESSION001/answer",
        data=payload,
        files={"live_frame": valid_live_frame_upload()},
        headers=headers,
    )
    assert res_2.status_code == 200
    # Controller was NOT called a second time
    assert mock_controller.submit_text.call_count == 1
    # Turn was not duplicated to turn 6
    assert res_2.json()["next_question"] == "How do you handle cache invalidation?"


def test_client_cannot_modify_score_or_decision(api_client, candidate_c001_token, monkeypatch):
    """Requirement F3.5: Client cannot inject fabricated score or decision values into interview state."""
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 2,
        "interview_complete": False,
        "identity_verified": True,
        "current_question": "Explain Docker.",
    }

    mock_controller = MagicMock()
    # Controller decides actual score is 65.0 and decision is continue
    mock_controller.submit_text.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 3,
        "decision": "continue",
        "next_question": "What are multi-stage builds?",
        "interview_score": 65.0,
        "interview_complete": False,
        "identity_verified": True,
    }
    monkeypatch.setattr(routes, "controller", mock_controller)

    # Malicious client attempts to claim 99.0 score and conclude interview
    malicious_payload = {
        "answer": "Docker isolates processes using cgroups and namespaces.",
        "interview_score": 99.0,
        "decision": "conclude",
        "turn_number": 15,
        "interview_complete": True,
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}

    res = api_client.post(
        "/interview/SESSION001/answer",
        data=malicious_payload,
        files={"live_frame": valid_live_frame_upload()},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()

    # Client-injected scores/decisions discarded
    assert data["interview_score"] == 65.0
    assert data["decision"] == "continue"
    assert data["interview_complete"] is False


def test_client_cannot_skip_identity_gate(api_client, candidate_c001_token):
    """Requirement F3.5: Candidates cannot complete interview or view recommendation

    if identity verification has not passed.
    """
    registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 3,
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "failed",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}

    # Attempting to fetch recommendation when identity failed -> blocked (404/not available)
    res_rec = api_client.get("/candidates/C001/recommendation", headers=headers)
    assert res_rec.status_code == 404


# ---------------------------------------------------------------------------
# F3.7: CORS & Browser Security Headers Tests
# ---------------------------------------------------------------------------

def test_security_headers_present_on_responses(api_client):
    """Requirement F3.7: HTTP responses must include strict browser security headers."""
    res = api_client.get("/")
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert "strict-origin" in res.headers.get("Referrer-Policy", "")
    assert "Strict-Transport-Security" in res.headers
    assert "Content-Security-Policy" in res.headers


def test_cors_restricted_origins(api_client):
    """Requirement F3.7: Cross-origin requests from unauthorized domains must be rejected."""
    # Preflight request from unauthorized origin
    res = api_client.options(
        "/candidates",
        headers={
            "Origin": "https://malicious-attacker.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Disallowed origin should NOT have Access-Control-Allow-Origin matching attacker
    allow_origin = res.headers.get("Access-Control-Allow-Origin")
    assert allow_origin != "https://malicious-attacker.com"
