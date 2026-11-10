"""
D2 Integration Tests: Authentication & Role-Based Access Control (RBAC).

Tests:
1. Recruiter registration and login -> JWT token -> candidate endpoint -> 200 OK
2. Candidate registration and login -> JWT token -> own candidate data -> 200 OK
3. Candidate accessing another candidate's data -> 403 FORBIDDEN
4. Unauthenticated request to protected endpoints -> 401 UNAUTHORIZED
5. Invalid/malformed token -> 401 UNAUTHORIZED
6. Candidate attempting recruiter review -> 403 FORBIDDEN
7. Candidate attempting candidate listing -> 403 FORBIDDEN
8. Sensitive endpoints protection:
   - GET /candidates/{id}
   - GET /interview/{session_id}
   - GET /interview/{session_id}/result
   - GET /identity/{session_id}
   - GET /recommendations/{candidate_id}
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import decode_access_token, verify_password
from app.database.connection import get_db_context
from app.database.repositories.candidate_repository import CandidateRepository
from app.database.repositories.user_repository import UserRepository
from app.database.repositories.interview_repository import InterviewRepository
from app.stages.stage4_interview.dependencies import registry


def _provision_user(email, password, role="candidate", candidate_id=None):
    """Test-only trusted provisioning for roles and links unavailable to public signup."""
    with get_db_context() as db:
        return UserRepository(db).create_user(email, password, role=role, candidate_id=candidate_id)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def setup_test_data():
    """
    Ensure candidates C001 and C002 exist in database and interview sessions are registered.
    """
    with get_db_context() as db:
        cand_repo = CandidateRepository(db)
        cand_repo.create_or_update(
            candidate_id="C001",
            name="Alex Chen",
            email="alex.chen@example.com",
            resume_score=85.0,
        )
        cand_repo.create_or_update(
            candidate_id="C002",
            name="Sarah Connor",
            email="sarah.connor@example.com",
            resume_score=92.0,
        )

        interview_repo = InterviewRepository(db)
        sess1 = interview_repo.get_session("SESSION001")
        if not sess1:
            interview_repo.create_session("SESSION001", "C001")
        sess2 = interview_repo.get_session("SESSION002")
        if not sess2:
            interview_repo.create_session("SESSION002", "C002")

    # The candidate API uses the stage-3 repository abstraction; seed the same
    # test candidates there as well as in the persistence repository above.
    from app.api.dependencies import get_candidate_repository
    candidate_store = get_candidate_repository()
    candidate_store.create_or_update(
        "C001", name="Alex Chen", email="alex.chen@example.com", resume_score=85.0
    )
    candidate_store.create_or_update(
        "C002", name="Sarah Connor", email="sarah.connor@example.com", resume_score=92.0
    )

    registry.create(
        "SESSION001",
        {
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "current_question": "Tell me about distributed systems.",
            "current_competency": "system_design",
            "decision": "continue",
            "conversation_history": [],
            "competency_scores": {"system_design": 0.88},
            "interview_score": 88.0,
            "interview_complete": False,
            "identity_verified": True,
            "last_identity_confidence": 0.95,
            "identity_status": "verified",
            "turn_number": 1,
        },
    )

    registry.create(
        "SESSION002",
        {
            "session_id": "SESSION002",
            "candidate_id": "C002",
            "current_question": "Explain consistency models in databases.",
            "current_competency": "databases",
            "decision": "continue",
            "conversation_history": [],
            "competency_scores": {"databases": 0.91},
            "interview_score": 91.0,
            "interview_complete": False,
            "identity_verified": True,
            "last_identity_confidence": 0.96,
            "identity_status": "verified",
            "turn_number": 1,
        },
    )


# ---------------------------------------------------------------------------
# 1. Registration & Login Tests
# ---------------------------------------------------------------------------

def test_register_and_login_recruiter(client):
    unique_email = f"recruiter_{uuid.uuid4().hex[:6]}@example.com"
    reg_res = client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "SecretPassword123!",
            "role": "recruiter",
        },
    )
    assert reg_res.status_code == 403
    assert "limited to candidate" in reg_res.json()["detail"]


def test_register_and_login_candidate(client):
    unique_email = f"cand_{uuid.uuid4().hex[:6]}@example.com"
    reg_res = client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "CandidatePassword123!",
            "role": "candidate",
        },
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["candidate_id"] is None
    assert reg_data["role"] == "candidate"

    # Login
    login_res = client.post(
        "/auth/login",
        json={
            "email": unique_email,
            "password": "CandidatePassword123!",
        },
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Verify /auth/me
    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == unique_email
    assert me_data["role"] == "candidate"
    assert me_data["candidate_id"] is None


def test_login_invalid_password_fails(client):
    unique_email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    _provision_user(unique_email, "CorrectPassword123")

    res = client.post(
        "/auth/login",
        json={
            "email": unique_email,
            "password": "WrongPassword456",
        },
    )
    assert res.status_code == 401
    assert "Incorrect email or password" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 2. Unauthenticated and Invalid Token Tests (D2.7)
# ---------------------------------------------------------------------------

def test_unauthenticated_requests_denied(client):
    """
    Unauthenticated requests must return 401 UNAUTHORIZED.
    """
    res1 = client.get("/candidates/C001")
    assert res1.status_code == 401

    res2 = client.get("/interview/SESSION001")
    assert res2.status_code == 401

    res3 = client.get("/identity/SESSION001")
    assert res3.status_code == 401

    res4 = client.get("/recommendations/C001")
    assert res4.status_code == 401

    res5 = client.get("/candidates")
    assert res5.status_code == 401


def test_invalid_token_denied(client):
    """
    Invalid or garbage tokens must return 401 UNAUTHORIZED.
    """
    headers = {"Authorization": "Bearer garbage"}
    res = client.get("/candidates/C001", headers=headers)
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Recruiter Authorization Tests (D2.7)
# ---------------------------------------------------------------------------

def test_recruiter_can_access_candidate_endpoints(client):
    """
    Recruiter login -> JWT -> candidate endpoint -> 200 OK.
    """
    email = f"rec_{uuid.uuid4().hex[:6]}@example.com"
    _provision_user(email, "RecruiterPass123!", role="recruiter")
    login_res = client.post(
        "/auth/login",
        json={"email": email, "password": "RecruiterPass123!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Can access candidate C001
    res1 = client.get("/candidates/C001", headers=headers)
    assert res1.status_code == 200
    assert res1.json()["candidate_id"] == "C001"

    # Can access candidate C002
    res2 = client.get("/candidates/C002", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["candidate_id"] == "C002"

    # Can list all candidates
    res_list = client.get("/candidates", headers=headers)
    assert res_list.status_code == 200
    assert isinstance(res_list.json(), list)

    # Can access recruiter review endpoint
    res_rev = client.get("/candidates/C001/review", headers=headers)
    assert res_rev.status_code == 200

    # Can access interview sessions
    res_sess = client.get("/interview/SESSION001", headers=headers)
    assert res_sess.status_code == 200


# ---------------------------------------------------------------------------
# 4. Candidate Ownership Tests (D2.7 Critical Boundary)
# ---------------------------------------------------------------------------

def test_candidate_accessing_own_data(client):
    """
    Candidate C001 accessing C001 data -> 200 OK.
    """
    email = f"c001_{uuid.uuid4().hex[:6]}@example.com"
    _provision_user(email, "PasswordC001!", candidate_id="C001")
    login_res = client.post(
        "/auth/login",
        json={"email": email, "password": "PasswordC001!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Own candidate profile
    res_cand = client.get("/candidates/C001", headers=headers)
    assert res_cand.status_code == 200
    assert res_cand.json()["candidate_id"] == "C001"

    # Own interview session
    res_sess = client.get("/interview/SESSION001", headers=headers)
    assert res_sess.status_code == 200
    assert res_sess.json()["candidate_id"] == "C001"

    # Own identity verification check
    res_id = client.get("/identity/SESSION001", headers=headers)
    assert res_id.status_code == 200
    assert res_id.json()["candidate_id"] == "C001"


def test_candidate_accessing_another_candidate_forbidden(client):
    """
    Candidate C001 accessing C002 resources -> 403 FORBIDDEN.
    """
    email = f"c001_{uuid.uuid4().hex[:6]}@example.com"
    _provision_user(email, "PasswordC001!", candidate_id="C001")
    login_res = client.post(
        "/auth/login",
        json={"email": email, "password": "PasswordC001!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Accessing other candidate's profile
    res_c002 = client.get("/candidates/C002", headers=headers)
    assert res_c002.status_code == 403
    assert "Forbidden" in res_c002.json()["detail"]

    # 2. Accessing other candidate's interview session
    res_sess_c002 = client.get("/interview/SESSION002", headers=headers)
    assert res_sess_c002.status_code == 403
    assert "Forbidden" in res_sess_c002.json()["detail"]

    # 3. Accessing other candidate's interview result
    res_result_c002 = client.get("/interview/SESSION002/result", headers=headers)
    assert res_result_c002.status_code == 403

    # 4. Accessing other candidate's identity data
    res_identity_c002 = client.get("/identity/SESSION002", headers=headers)
    assert res_identity_c002.status_code == 403

    # 5. Accessing other candidate's recommendation
    res_rec_c002 = client.get("/recommendations/C002", headers=headers)
    assert res_rec_c002.status_code == 403

    res_cand_rec_c002 = client.get("/candidates/C002/recommendation", headers=headers)
    assert res_cand_rec_c002.status_code == 403

    # 6. Candidate attempting to list all candidates
    res_list = client.get("/candidates", headers=headers)
    assert res_list.status_code == 403

    # 7. Candidate attempting to access recruiter review endpoint
    res_review = client.get("/candidates/C001/review", headers=headers)
    assert res_review.status_code == 403

    # 8. Candidate attempting to submit a recruiter review
    res_post_review = client.post(
        "/candidates/C001/review",
        json={"reviewer_id": "C001", "decision": "APPROVE"},
        headers=headers,
    )
    assert res_post_review.status_code == 403

    # 9. Candidate accessing other candidate's interview route
    res_cand_interview = client.get("/candidates/C002/interview", headers=headers)
    assert res_cand_interview.status_code == 403


def test_inactive_user_access_blocked(client):
    """
    Deactivated user accounts must be rejected with 403 FORBIDDEN.
    """
    email = f"inactive_{uuid.uuid4().hex[:6]}@example.com"
    _provision_user(email, "Password123!", candidate_id="C001")
    login_res = client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login_res.json()["access_token"]

    # Deactivate user in database
    with get_db_context() as db:
        user_repo = UserRepository(db)
        u = user_repo.get_by_email(email)
        u.is_active = False
        db.commit()

    # Now requests using this token must be forbidden
    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/candidates/C001", headers=headers)
    assert res.status_code == 403
    assert "inactive" in res.json()["detail"].lower()

