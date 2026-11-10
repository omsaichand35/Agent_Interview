import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies import get_recommendation_service, get_candidate_repository
from app.stages.stage4_interview.dependencies import registry as interview_registry


from app.core.security import create_access_token


@pytest.fixture
def client(monkeypatch):
    from app.api.dependencies import get_candidate_repository, get_recommendation_service

    token = create_access_token(user_id="U_TEST_RECRUITER", role="recruiter")
    candidate_repo = get_candidate_repository()
    recommendation_service = get_recommendation_service()
    previous_candidates = dict(candidate_repo._candidates)
    previous_sessions = dict(interview_registry.sessions)
    previous_recommendations = dict(recommendation_service._recommendations)
    previous_reviews = dict(recommendation_service._reviews)
    candidate_repo._candidates.clear()
    interview_registry.sessions.clear()
    recommendation_service._recommendations.clear()
    recommendation_service._reviews.clear()

    for candidate_id, name, score in (
        ("C001", "Alex Chen", 71.3),
        ("C002", "Jordan Lee", 68.0),
        ("C003", "Sam Taylor", 74.2),
    ):
        candidate_repo.create_or_update(
            candidate_id=candidate_id,
            name=name,
            email=f"{candidate_id.lower()}@test.invalid",
            resume_score=score,
        )

    interview_registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "interview_complete": True,
        "identity_verified": True,
        "identity_status": "passed",
        "interview_score": 82.5,
        "competency_scores": {"Python": 0.85},
        "conversation_history": [],
    }
    recommendation_service.generate(
        candidate_id="C001",
        resume_score=71.3,
        interview_score=82.5,
        identity_verified=True,
        competency_scores={"Python": 0.85},
    )

    class NoopAuditService:
        def record_event(self, **kwargs):
            return None

    monkeypatch.setattr("app.core.audit.get_audit_service", lambda: NoopAuditService())
    try:
        with TestClient(app) as c:
            c.headers["Authorization"] = f"Bearer {token}"
            yield c
    finally:
        candidate_repo._candidates.clear()
        candidate_repo._candidates.update(previous_candidates)
        interview_registry.sessions.clear()
        interview_registry.sessions.update(previous_sessions)
        recommendation_service._recommendations.clear()
        recommendation_service._recommendations.update(previous_recommendations)
        recommendation_service._reviews.clear()
        recommendation_service._reviews.update(previous_reviews)


def test_list_candidates(client):
    response = client.get("/candidates")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    candidate_ids = [c["candidate_id"] for c in data]
    assert "C001" in candidate_ids
    assert "C002" in candidate_ids
    assert "C003" in candidate_ids

    c001 = next(c for c in data if c["candidate_id"] == "C001")
    assert c001["resume_score"] == pytest.approx(71.3, 0.1)


def test_get_candidate_by_id(client):
    response = client.get("/candidates/C001")
    assert response.status_code == 200
    data = response.json()
    assert data["candidate_id"] == "C001"
    assert data["name"] in ("Alex Chen", "Alex Smith")

    # Non-existent candidate
    response_404 = client.get("/candidates/NON_EXISTENT")
    assert response_404.status_code == 404


def test_get_candidate_interview(client):
    # C001 has existing session data in data/outputs/interviews/
    response = client.get("/candidates/C001/interview")
    assert response.status_code == 200
    data = response.json()
    assert data["candidate_id"] == "C001"
    assert "conversation_history" in data
    assert "competency_scores" in data

    # Non-existent candidate interview
    response_404 = client.get("/candidates/NON_EXISTENT/interview")
    assert response_404.status_code == 404


def test_recruiter_ui_endpoint(client):
    response = client.get("/recruiter-ui")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Recruiter workspace" in response.text


def test_candidate_recommendation_success(client):
    # C001 is verified and has completed interview data
    interview_registry.sessions["SESSION001"] = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "interview_complete": True,
        "identity_verified": True,
        "identity_status": "passed",
        "interview_score": 82.5,
        "competency_scores": {"Python": 0.85},
    }
    response = client.get("/candidates/C001/recommendation")
    assert response.status_code == 200

    data = response.json()
    assert data["candidate_id"] == "C001"
    assert "resume_score" in data
    assert "interview_score" in data
    assert "final_score" in data
    assert data["identity_verified"] is True
    assert data["status"] == "completed"


def test_candidate_recommendation_not_available(client):
    # Non-existent candidate
    response_404 = client.get("/candidates/NON_EXISTENT/recommendation")
    assert response_404.status_code == 404
    assert "Recommendation not available" in response_404.json()["detail"]


def test_candidate_recommendation_identity_failure_hard_gate(client):
    # Register a candidate with failed identity
    rec_service = get_recommendation_service()
    rec_service.save_human_review(
        "C_FAIL",
        {
            "candidate_id": "C_FAIL",
            "requires_review": True,
            "reason": "Identity verification failed.",
            "identity_failure_reason": "Face mismatch detected.",
        }
    )

    # When identity fails, recommendation must not be available automatically
    response = client.get("/candidates/C_FAIL/recommendation")
    assert response.status_code == 404

    # Human review endpoint must flag requires_review = True
    rev_response = client.get("/candidates/C_FAIL/review")
    assert rev_response.status_code == 200
    rev_data = rev_response.json()
    assert rev_data["requires_review"] is True
    assert "Identity verification" in rev_data["reason"]


def test_candidate_review_normal(client):
    # Candidate without review required
    response = client.get("/candidates/C001/review")
    assert response.status_code == 200
    data = response.json()
    assert data["candidate_id"] == "C001"
    assert data["requires_review"] is False
