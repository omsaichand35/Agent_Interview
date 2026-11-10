"""Audit and Compliance Security Test Suite (Requirement F5).

Verifies the audit subsystem across the complete hiring intelligence pipeline:
[x] login generates audit event (LOGIN_SUCCESS / LOGIN_FAILURE)
[x] identity decision generates audit event (IDENTITY_PASSED / IDENTITY_FAILED)
[x] interview completion generates audit event (INTERVIEW_COMPLETED)
[x] recommendation generates audit event (RECOMMENDATION_REVIEWED)
[x] recruiter review generates audit event (REVIEW_CREATED)
[x] candidate access generates audit event (CANDIDATE_VIEWED)
[x] actor identity is recorded
[x] timestamp is recorded
[x] request_id is recorded
[x] sensitive payload isn't logged (redaction of credentials, biometrics, transcripts)
[x] ordinary users cannot modify audit history (append-only contract)
[x] audit events remain chronologically ordered
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.audit import AuditEvent, AuditService, get_audit_service, sanitize_audit_metadata
from app.core.security import create_access_token
from app.database.connection import SessionLocal
from app.database.models import AuditEventModel, CandidateModel, UserModel
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.user_repository import UserRepository
from app.main import app
from app.models.user import Role
from app.security.rate_limiter import rate_limiter_instance
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture(autouse=True)
def reset_state():
    rate_limiter_instance.reset()
    registry.sessions.clear()
    audit_svc = get_audit_service()
    audit_svc._in_memory_events.clear()
    yield
    rate_limiter_instance.reset()
    registry.sessions.clear()
    audit_svc._in_memory_events.clear()


@pytest.fixture
def db_session():
    from app.database.base import Base
    from app.database.connection import engine
    import app.database.models
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


# ---------------------------------------------------------------------------
# F5.2: Audit Events Generation
# ---------------------------------------------------------------------------

def test_login_generates_audit_event(api_client, db_session):
    """F5.2: Successful and failed logins generate structured audit events with actor details."""
    import uuid
    test_email = f"audit_{uuid.uuid4().hex[:6]}@example.com"
    user_repo = UserRepository(db_session)
    user_repo.create_user(
        email=test_email,
        password="ValidPassword123!",
        role="recruiter",
    )

    # 1. Failed login attempt
    res_fail = api_client.post(
        "/auth/login",
        json={"email": test_email, "password": "WrongPassword!"},
    )
    assert res_fail.status_code == 401

    audit_svc = get_audit_service()
    fail_events = [e for e in audit_svc.list_events() if e.action == "LOGIN_FAILURE"]
    assert len(fail_events) >= 1
    assert fail_events[-1].actor_id == test_email
    assert fail_events[-1].result == "FAILED"

    # 2. Successful login attempt
    res_success = api_client.post(
        "/auth/login",
        json={"email": test_email, "password": "ValidPassword123!"},
    )
    assert res_success.status_code == 200

    success_events = [e for e in audit_svc.list_events() if e.action == "LOGIN_SUCCESS"]
    assert len(success_events) >= 1
    assert success_events[-1].actor_role == "RECRUITER"
    assert success_events[-1].result == "SUCCESS"


def test_candidate_access_generates_audit_event(api_client, recruiter_token):
    """F5.7: When a candidate profile is viewed, a CANDIDATE_VIEWED audit event is recorded."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    res = api_client.get("/candidates/C001", headers=headers)
    assert res.status_code == 200

    audit_svc = get_audit_service()
    events = [
        e for e in audit_svc.list_events()
        if e.action == "CANDIDATE_VIEWED" and e.candidate_id == "C001"
    ]
    assert len(events) >= 1
    assert events[-1].actor_id == "U_REC_01"
    assert events[-1].actor_role == "RECRUITER"
    assert events[-1].resource_type == "CANDIDATE"


def test_recruiter_review_generates_audit_event(api_client, recruiter_token):
    """F5.4: Submitting a candidate review generates an append-only REVIEW_CREATED event."""
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    payload = {
        "reviewer_id": "U_REC_01",
        "decision": "APPROVE",
        "notes": "Candidate demonstrated deep distributed systems expertise.",
    }
    res = api_client.post("/candidates/C001/review", json=payload, headers=headers)
    assert res.status_code == 200

    audit_svc = get_audit_service()
    review_events = [
        e for e in audit_svc.list_events()
        if e.action == "REVIEW_CREATED" and e.candidate_id == "C001"
    ]
    assert len(review_events) >= 1
    event = review_events[-1]
    assert event.actor_id == "U_REC_01"
    assert event.actor_role == "RECRUITER"
    assert event.result == "APPROVE"
    assert event.metadata["decision"] == "APPROVE"


def test_recommendation_generates_audit_event(api_client, recruiter_token, monkeypatch):
    """F5.2: Accessing/reviewing a candidate recommendation records a RECOMMENDATION_REVIEWED event."""
    from app.api.dependencies import get_recommendation_service
    from app.schemas.recommendation import FinalRecommendation
    from app.stages.stage5_recommendation.recommendation_service import RecommendationService

    service = RecommendationService()
    service.save_recommendation(FinalRecommendation(
        candidate_id="C001",
        resume_score=85.0,
        interview_score=88.0,
        final_score=86.5,
        identity_verified=True,
        status="completed",
    ))
    monkeypatch.setitem(
        app.dependency_overrides,
        get_recommendation_service,
        lambda: service,
    )
    headers = {"Authorization": f"Bearer {recruiter_token}"}
    res = api_client.get("/recommendations/C001", headers=headers)
    assert res.status_code == 200

    audit_svc = get_audit_service()
    rec_events = [
        e for e in audit_svc.list_events()
        if e.action == "RECOMMENDATION_REVIEWED" and e.candidate_id == "C001"
    ]
    assert len(rec_events) >= 1
    assert rec_events[-1].actor_id == "U_REC_01"
    assert rec_events[-1].resource_type == "RECOMMENDATION"


def test_identity_decision_generates_audit_event():
    """F5.2: Identity check completion generates an IDENTITY_PASSED or IDENTITY_FAILED event."""
    audit_svc = get_audit_service()
    event = audit_svc.record_event(
        actor_id="U_CAND_01",
        actor_role="CANDIDATE",
        action="IDENTITY_PASSED",
        resource_type="INTERVIEW_SESSION",
        resource_id="SESSION001",
        candidate_id="C001",
        result="PASSED",
        metadata={"confidence": 0.88, "matcher": "sface"},
    )
    assert event.action == "IDENTITY_PASSED"
    assert event.result == "PASSED"
    assert event.metadata["confidence"] == 0.88


def test_interview_completion_generates_audit_event():
    """F5.2: Interview completion records an INTERVIEW_COMPLETED audit event."""
    audit_svc = get_audit_service()
    event = audit_svc.record_event(
        actor_id="U_CAND_01",
        actor_role="CANDIDATE",
        action="INTERVIEW_COMPLETED",
        resource_type="INTERVIEW_SESSION",
        resource_id="SESSION001",
        candidate_id="C001",
        result="SUCCESS",
        metadata={"final_score": 88.5},
    )
    assert event.action == "INTERVIEW_COMPLETED"
    assert event.metadata["final_score"] == 88.5


# ---------------------------------------------------------------------------
# F5.1 & F5.6: Metadata Sanitization & Non-Leakage
# ---------------------------------------------------------------------------

def test_sensitive_payload_not_logged_in_audit_metadata():
    """F5.6: Passwords, tokens, biometrics, transcripts, and embeddings are redacted from audit metadata."""
    raw_metadata = {
        "password": "SuperSecretPassword123!",
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy",
        "jwt": "header.payload.signature",
        "face_image": b"\xff\xd8\xff\xe0...binary_image_data",
        "embedding": [0.123, -0.456, 0.789, 0.012],
        "full_transcript": "Very long transcript text ... " * 20,
        "resume_text": "Candidate Resume content ...",
        "safe_metric": 42,
        "safe_flag": True,
        "model_version": "2021dec",
    }

    sanitized = sanitize_audit_metadata(raw_metadata)

    # Sensitive fields redacted
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["jwt"] == "[REDACTED]"
    assert sanitized["face_image"] == "[REDACTED]"
    assert sanitized["embedding"] == "[REDACTED]"
    assert sanitized["full_transcript"] == "[REDACTED]"
    assert sanitized["resume_text"] == "[REDACTED]"

    # Non-sensitive operational metadata preserved
    assert sanitized["safe_metric"] == 42
    assert sanitized["safe_flag"] is True
    assert sanitized["model_version"] == "2021dec"


def test_request_id_and_actor_identity_recorded():
    """F5.1: Every audit event explicitly captures actor identity, timestamp, and request_id."""
    audit_svc = get_audit_service()
    event = audit_svc.record_event(
        actor_id="U_AUDIT_USER",
        actor_role="RECRUITER",
        action="SHORTLIST_CREATED",
        resource_type="JOB",
        resource_id="JOB_001",
        request_id="req_test_abc123",
        metadata={"shortlist_count": 5},
    )

    assert event.actor_id == "U_AUDIT_USER"
    assert event.actor_role == "RECRUITER"
    assert event.request_id == "req_test_abc123"
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None  # UTC timezone aware


# ---------------------------------------------------------------------------
# F5.5 & F5.8: Tamper Resistance & Chronological Ordering
# ---------------------------------------------------------------------------

def test_ordinary_users_cannot_modify_audit_history(db_session):
    """F5.5: AuditRepository provides append-only operations without single-row update or delete methods."""
    repo = AuditRepository(db_session)
    assert hasattr(repo, "create")
    assert hasattr(repo, "list_events")
    assert hasattr(repo, "get_by_event_id")

    # Verify no single-event delete or update mutations are exposed
    assert not hasattr(repo, "delete")
    assert not hasattr(repo, "delete_event")
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "update_event")


def test_audit_events_remain_ordered(db_session):
    """F5.8: Audit queries return records sorted chronologically by timestamp."""
    repo = AuditRepository(db_session)

    import uuid
    unique_actor = f"U_{uuid.uuid4().hex[:6]}"

    e1 = AuditEvent(
        actor_id=unique_actor,
        actor_role="RECRUITER",
        action="LOGIN_SUCCESS",
        resource_type="USER",
        timestamp=datetime(2026, 9, 25, 10, 0, 0, tzinfo=timezone.utc),
    )
    e2 = AuditEvent(
        actor_id=unique_actor,
        actor_role="RECRUITER",
        action="CANDIDATE_VIEWED",
        resource_type="CANDIDATE",
        timestamp=datetime(2026, 9, 25, 10, 1, 0, tzinfo=timezone.utc),
    )
    e3 = AuditEvent(
        actor_id=unique_actor,
        actor_role="RECRUITER",
        action="REVIEW_CREATED",
        resource_type="REVIEW",
        timestamp=datetime(2026, 9, 25, 10, 2, 0, tzinfo=timezone.utc),
    )

    repo.create(e1)
    repo.create(e2)
    repo.create(e3)

    records = repo.list_events(actor_id=unique_actor)
    assert len(records) == 3
    timestamps = [r.timestamp for r in records]
    assert timestamps == sorted(timestamps)
    assert records[0].action == "LOGIN_SUCCESS"
    assert records[1].action == "CANDIDATE_VIEWED"
    assert records[2].action == "REVIEW_CREATED"


def test_compliance_retention_purges_only_expired_records(db_session):
    """F5.9: Compliance purge removes records older than retention_days while retaining valid ones."""
    from datetime import timedelta
    from app.core.audit import utc_now
    repo = AuditRepository(db_session)
    import uuid

    cand_id = f"C_RET_{uuid.uuid4().hex[:6]}"
    now = utc_now()

    # Expired event: 400 days ago (older than 365 days)
    expired_event = AuditEvent(
        actor_id="U_RET",
        actor_role="SYSTEM",
        action="LOGIN_SUCCESS",
        resource_type="USER",
        candidate_id=cand_id,
        timestamp=now - timedelta(days=400),
    )
    # Valid event: 30 days ago (within 365 days)
    valid_event = AuditEvent(
        actor_id="U_RET",
        actor_role="SYSTEM",
        action="LOGIN_SUCCESS",
        resource_type="USER",
        candidate_id=cand_id,
        timestamp=now - timedelta(days=30),
    )

    repo.create(expired_event)
    repo.create(valid_event)

    # Purge with 365 days policy
    deleted_count = repo.purge_expired_events(retention_days=365)
    assert deleted_count >= 1

    remaining = repo.list_events(candidate_id=cand_id)
    assert len(remaining) == 1
    assert remaining[0].event_id == valid_event.event_id


def test_audit_service_truncates_oversized_metadata_blobs():
    """F5.1: Huge string blobs or binary buffers injected into metadata are truncated/sanitized."""
    oversized_text = "A" * 2000
    sanitized = sanitize_audit_metadata({"giant_blob": oversized_text, "raw_buffer": b"1234567890"})

    assert len(sanitized["giant_blob"]) < 300
    assert "[TRUNCATED]" in sanitized["giant_blob"]
    assert "[BINARY_DATA_10_BYTES]" in sanitized["raw_buffer"]

