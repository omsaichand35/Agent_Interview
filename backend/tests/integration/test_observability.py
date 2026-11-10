import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.config import settings
from app.core.logging import (
    clear_captured_logs,
    get_captured_logs,
    log_event,
)
from app.core.metrics import get_metrics_collector
from app.core.jobs import Job, JobQueue, JobStatus, JobType, JobWorker, get_job_queue
from app.main import app
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def clean_logs_and_metrics():
    clear_captured_logs()
    get_metrics_collector().reset()
    yield
    clear_captured_logs()


# ---------------------------------------------------------------------------
# 1. Request ID Middleware
# ---------------------------------------------------------------------------

def test_every_api_request_gets_request_id(client):
    # Auto-generated request ID
    res1 = client.get("/health")
    assert res1.status_code == 200
    assert "X-Request-ID" in res1.headers
    assert res1.headers["X-Request-ID"].startswith("req_")

    # Custom caller-supplied request ID propagated
    custom_id = "req_custom_obs_98765"
    res2 = client.get("/health", headers={"X-Request-ID": custom_id})
    assert res2.status_code == 200
    assert res2.headers["X-Request-ID"] == custom_id


# ---------------------------------------------------------------------------
# 2. Correlation IDs: Session ID in Interview Events
# ---------------------------------------------------------------------------

def test_interview_events_contain_session_id(client):
    session_id = f"SESS_OBS_{uuid.uuid4().hex[:6]}"
    cand_id = "C_OBS_001"
    from app.core.security import create_access_token
    client.headers["Authorization"] = (
        "Bearer " + create_access_token(user_id="U_OBS_01", role="recruiter")
    )

    # Start interview
    client.post(
        "/interview/start",
        json={
            "session_id": session_id,
            "candidate_id": cand_id,
            "candidate": {"name": "Obs Candidate"},
            "competencies": ["system_design"],
            "first_question": "Explain system scalability.",
        },
    )

    from app.stages.stage4_interview.graph.trace import record_turn
    state = registry.get(session_id)
    state["candidate_answer"] = "We used distributed caching with Redis to reduce DB load."
    state["trigger_phrase"] = "distributed caching"
    state["extracted_signals"] = ["caching", "redis"]
    state["decision"] = "pivot"
    state["next_question"] = "How do you handle cache invalidation?"
    record_turn(state)

    logs = get_captured_logs()
    reasoning_events = [l for l in logs if l.get("event") == "reasoning_completed"]
    assert len(reasoning_events) >= 1
    event = reasoning_events[0]
    assert event["session_id"] == session_id
    assert event["decision"] == "pivot"
    assert event["trigger"] == "distributed caching"


# ---------------------------------------------------------------------------
# 3. Correlation IDs: Background Jobs contain job_id
# ---------------------------------------------------------------------------

def test_background_jobs_contain_job_id(client):
    session_id = f"SESS_JOB_OBS_{uuid.uuid4().hex[:6]}"
    registry.create(
        session_id,
        {
            "session_id": session_id,
            "candidate_id": "C_JOB_OBS",
            "current_question": "Explain consistency models.",
            "current_competency": "system_design",
            "target_competencies": ["system_design"],
            "explored_competencies": ["system_design"],
            "discovered_competencies": ["system_design"],
            "conversation_history": [],
            "turn_number": 1,
            "interview_complete": False,
        },
    )

    queue = get_job_queue()
    job_id = f"JOB_CORR_{uuid.uuid4().hex[:6]}"
    job = Job(
        id=job_id,
        type=JobType.INTERVIEW_AUDIO.value,
        session_id=session_id,
        candidate_id="C_JOB_OBS",
        payload={"audio_path": "fake_test.wav"},
    )
    queue.enqueue(job)

    # Process job with mocked STT
    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="Eventual consistency"):
        worker = JobWorker(queue=queue)
        worker.process_job(job_id)

    logs = get_captured_logs()
    job_events = [l for l in logs if l.get("job_id") == job_id]
    assert len(job_events) >= 1
    assert any(l.get("event") in ["stt_completed", "interview_processing_failed"] for l in job_events)


# ---------------------------------------------------------------------------
# 4. Failures Produce Structured Logs
# ---------------------------------------------------------------------------

def test_failures_produce_structured_logs():
    clear_captured_logs()
    with TestClient(app, raise_server_exceptions=False) as client_500:
        res = client_500.get("/test/simulate-error")
        assert res.status_code == 500

        logs = get_captured_logs()
        err_events = [l for l in logs if l.get("event") == "unexpected_exception"]
        assert len(err_events) >= 1
        event = err_events[0]
        assert event["level"] == "ERROR"
        assert "request_id" in event
        assert event["error_type"] == "RuntimeError"

        # API response must NOT contain raw Python traceback
        data = res.json()
        assert "Traceback" not in json.dumps(data)
        assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"


# ---------------------------------------------------------------------------
# 5. Identity Events Don't Contain Raw Image Data
# ---------------------------------------------------------------------------

def test_identity_events_do_not_contain_image_data():
    raw_image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 500  # JPEG header + dummy
    log_event(
        "identity_check_started",
        session_id="S_SECURE_001",
        candidate_id="C_SECURE_001",
        face_image=raw_image_bytes,
        confidence=0.98,
    )

    logs = get_captured_logs()
    id_events = [l for l in logs if l.get("event") == "identity_check_started"]
    assert len(id_events) == 1
    raw_str = json.dumps(id_events[0])

    # Assert raw binary bytes are never dumped directly
    assert "\\xff\\xd8" not in raw_str
    assert "[REDACTED]" in raw_str or "BINARY_DATA" in raw_str
    assert id_events[0]["session_id"] == "S_SECURE_001"
    assert id_events[0]["confidence"] == 0.98


# ---------------------------------------------------------------------------
# 6. Authentication Secrets Are Never Logged
# ---------------------------------------------------------------------------

def test_authentication_secrets_are_not_logged():
    clear_captured_logs()
    log_event(
        "user_auth_attempt",
        username="admin@company.com",
        password="MySecretPassword123!",
        token="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_payload",
        api_key="nvapi-supersecret-token-key",
    )

    logs = get_captured_logs()
    auth_events = [l for l in logs if l.get("event") == "user_auth_attempt"]
    assert len(auth_events) == 1
    raw_str = json.dumps(auth_events[0])

    assert "MySecretPassword123!" not in raw_str
    assert "nvapi-supersecret-token-key" not in raw_str
    assert "[REDACTED]" in raw_str


# ---------------------------------------------------------------------------
# 7. Health Endpoint Works
# ---------------------------------------------------------------------------

def test_health_endpoint_works(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["alive"] is True


# ---------------------------------------------------------------------------
# 8. Readiness Detects Unavailable Redis
# ---------------------------------------------------------------------------

def test_readiness_detects_unavailable_redis(client, monkeypatch):
    monkeypatch.setattr(settings, "redis_required", True)
    monkeypatch.setattr(settings, "redis_url", "redis://invalid-unreachable-host:9999/0")

    res = client.get("/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "not_ready"
    assert data["services"]["redis"] == "error"


# ---------------------------------------------------------------------------
# 9. Readiness Detects Unavailable Database
# ---------------------------------------------------------------------------

def test_readiness_detects_unavailable_database(client, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "")

    res = client.get("/ready")
    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "not_ready"
    assert data["services"]["database"] == "error"


# ---------------------------------------------------------------------------
# 10. Interview Decision Trace is Persisted & Accessible
# ---------------------------------------------------------------------------

def test_interview_decision_trace_is_persisted(client):
    session_id = f"SESS_TRACE_{uuid.uuid4().hex[:6]}"
    cand_id = f"C_TRACE_{uuid.uuid4().hex[:6]}"

    from app.api.dependencies import get_candidate_repository
    cand_repo = get_candidate_repository()
    cand_repo.create_or_update(candidate_id=cand_id, name="Trace Candidate")
    from app.core.security import create_access_token
    client.headers["Authorization"] = (
        "Bearer " + create_access_token(user_id="U_TRACE_01", role="recruiter")
    )

    client.post(
        "/interview/start",
        json={
            "session_id": session_id,
            "candidate_id": cand_id,
            "candidate": {"name": "Trace Candidate"},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your Python experience.",
        },
    )

    from app.stages.stage4_interview.graph.trace import record_turn
    state = registry.get(session_id)
    state["candidate_answer"] = "I implemented high throughput asyncio concurrency pipelines."
    state["trigger_phrase"] = "asyncio concurrency"
    state["extracted_signals"] = ["asyncio", "concurrency"]
    state["decision"] = "deepen"
    state["next_question"] = "How do you handle race conditions with asyncio.Lock?"
    record_turn(state)
    registry.update(session_id, state)

    # 1. State check
    state = registry.get(session_id)
    assert "decision_traces" in state
    assert len(state["decision_traces"]) >= 1
    t = state["decision_traces"][0]
    assert t["turn"] == 1
    assert t["decision"] == "deepen"
    assert t["trigger"] == "asyncio concurrency"
    assert t["question_generated"] is True

    # 2. API endpoint check: GET /interview/{session_id}/trace
    from app.core.security import create_access_token
    token = create_access_token(user_id="U_RECRUITER", role="recruiter")
    res_trace = client.get(
        f"/interview/{session_id}/trace",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_trace.status_code == 200
    trace_data = res_trace.json()
    assert trace_data["session_id"] == session_id
    assert trace_data["turn_count"] >= 1
    assert trace_data["traces"][0]["trigger"] == "asyncio concurrency"


# ---------------------------------------------------------------------------
# 11. Application Metrics Endpoint Works
# ---------------------------------------------------------------------------

def test_metrics_endpoint_records_requests(client):
    collector = get_metrics_collector()
    collector.reset()

    client.get("/health")
    client.get("/health")
    client.get("/nonexistent-404-url")

    res = client.get("/metrics")
    assert res.status_code == 200
    data = res.json()

    assert data["requests"]["total"] >= 3
    assert data["requests"]["successful"] >= 2
    assert data["requests"]["failed"] >= 1
    assert "interview" in data
    assert "identity" in data
    assert "stt" in data
    assert "llm" in data
