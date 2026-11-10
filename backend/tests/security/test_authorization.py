"""Authorization and Privilege Escalation Security Test Suite (Requirements F6.3 & F6.4).

Verifies the access control and authorization matrix:
[x] IDOR: Candidate A cannot read Candidate B profile (403)
[x] IDOR: Candidate A cannot read Candidate B resume (403)
[x] IDOR: Candidate A cannot access Candidate B interview session (403)
[x] IDOR: Candidate A cannot submit answers for Candidate B session (403)
[x] Privilege Escalation: Candidate cannot review candidates (403)
[x] Privilege Escalation: Candidate cannot list all recommendations (403)
[x] Privilege Escalation: Candidate cannot create jobs (403)
[x] Privilege Escalation: Candidate cannot list candidate pool (403)
[x] Authorized Recruiter can access candidate profiles, recommendations, and reviews (200)
"""

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.models.user import Role
from app.security.rate_limiter import rate_limiter_instance
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture(autouse=True)
def reset_state():
    rate_limiter_instance.reset()
    registry.sessions.clear()
    yield
    rate_limiter_instance.reset()
    registry.sessions.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def candidate_a_token():
    """Candidate A owning resource C001."""
    return create_access_token(
        user_id="U_CAND_A",
        role=Role.CANDIDATE.value,
        candidate_id="C001",
    )


@pytest.fixture
def candidate_b_token():
    """Candidate B owning resource C002."""
    return create_access_token(
        user_id="U_CAND_B",
        role=Role.CANDIDATE.value,
        candidate_id="C002",
    )


@pytest.fixture
def recruiter_token():
    """Authorized recruiter."""
    return create_access_token(
        user_id="U_REC_01",
        role=Role.RECRUITER.value,
    )


# ---------------------------------------------------------------------------
# F6.3: Insecure Direct Object Reference (IDOR) Attacks
# ---------------------------------------------------------------------------

def test_candidate_a_cannot_view_candidate_b_profile(api_client, candidate_a_token):
    """F6.3: Candidate A cannot access Candidate B's candidate profile (403 Forbidden)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.get("/candidates/C002", headers=headers)
    assert res.status_code == 403


def test_candidate_a_cannot_view_candidate_b_resume(api_client, candidate_a_token):
    """F6.3: Candidate A cannot download Candidate B's resume (403 Forbidden)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.get("/candidates/C002/resume", headers=headers)
    assert res.status_code == 403


def test_candidate_a_cannot_access_candidate_b_interview_session(api_client, candidate_a_token):
    """F6.3: Candidate A cannot view Candidate B's live interview state (403 Forbidden)."""
    registry.sessions["SESS_C002"] = {
        "session_id": "SESS_C002",
        "candidate_id": "C002",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": True,
        "identity_status": "verified",
    }
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.get("/interview/SESS_C002", headers=headers)
    assert res.status_code == 403


def test_candidate_a_cannot_submit_answers_for_candidate_b(api_client, candidate_a_token):
    """F6.3: Candidate A cannot inject answers into Candidate B's session (403 Forbidden)."""
    registry.sessions["SESS_C002"] = {
        "session_id": "SESS_C002",
        "candidate_id": "C002",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": True,
        "identity_status": "verified",
    }
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.post(
        "/interview/SESS_C002/answer",
        json={"answer": "Malicious injected answer from Candidate A"},
        headers=headers,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# F6.4: Recruiter Privilege Escalation Attacks
# ---------------------------------------------------------------------------

def test_candidate_cannot_review_candidate(api_client, candidate_a_token):
    """F6.4: Candidates cannot submit recruiter reviews or alter hiring decisions (403)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    payload = {
        "reviewer_id": "U_CAND_A",
        "decision": "APPROVE",
        "notes": "Candidate attempting self-review approval.",
    }
    res = api_client.post("/candidates/C001/review", json=payload, headers=headers)
    assert res.status_code == 403


def test_candidate_cannot_list_recommendations(api_client, candidate_a_token):
    """F6.4: Candidates cannot browse the overall candidate recommendation pool (403)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.get("/recommendations", headers=headers)
    assert res.status_code == 403


def test_candidate_cannot_create_jobs(api_client, candidate_a_token):
    """F6.4: Candidates cannot post or manage job requisitions (403)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    job_payload = {
        "title": "Malicious Job",
        "department": "Engineering",
        "required_skills": ["Python"],
    }
    res = api_client.post("/jobs", json=job_payload, headers=headers)
    assert res.status_code == 403


def test_candidate_cannot_list_all_candidates(api_client, candidate_a_token):
    """F6.4: Candidates cannot enumerate or browse all candidate records in the pipeline (403)."""
    headers = {"Authorization": f"Bearer {candidate_a_token}"}
    res = api_client.get("/candidates", headers=headers)
    assert res.status_code == 403


def test_authorized_recruiter_can_access_pipeline_operations(api_client, recruiter_token):
    """F6.4: Authorized recruiters have legitimate access to candidate evaluations and pool data."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}

    # 1. Candidate pool
    res_cand = api_client.get("/candidates", headers=headers)
    assert res_cand.status_code == 200

    # 2. Recommendations
    res_rec = api_client.get("/recommendations", headers=headers)
    assert res_rec.status_code == 200

    # 3. Individual candidate
    res_one = api_client.get("/candidates/C001", headers=headers)
    assert res_one.status_code == 200
