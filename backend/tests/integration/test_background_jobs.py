import io
import struct
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from starlette.testclient import TestClient

from app.core.jobs import Job, JobQueue, JobStatus, JobType, JobWorker, get_job_queue
from app.main import app
from app.stages.stage4_interview.dependencies import registry


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def setup_test_interview(client, monkeypatch):
    """Sets up an isolated interview session for testing background jobs."""
    from app.api.dependencies import get_candidate_repository
    cand_repo = get_candidate_repository()
    cand_id = f"C_JOB_{uuid.uuid4().hex[:6]}"
    cand_repo.create_or_update(
        candidate_id=cand_id,
        name="Job Test Candidate",
        email=f"{cand_id}@example.com",
    )
    from app.database.repositories.user_repository import UserRepository
    from app.database.connection import get_db_context
    email = f"{cand_id}@example.com"
    with get_db_context() as db:
        UserRepository(db).create_user(email, "JobCandidatePass123!", role="recruiter")
    login = client.post("/auth/login", json={"email": email, "password": "JobCandidatePass123!"})
    assert login.status_code == 200
    client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
    session_id = f"SESSION_{uuid.uuid4().hex[:8]}"
    start_res = client.post(
        "/interview/start",
        json={
            "session_id": session_id,
            "candidate_id": cand_id,
            "candidate": {"name": "Job Test Candidate", "email": email},
            "competencies": ["system_design"],
            "first_question": "Describe an architectural decision you made.",
        },
    )
    assert start_res.status_code == 200
    from app.stages.stage4_interview.dependencies import create_interview_controller
    from tests.fixtures.identity import PassingTestIdentityCheckpoint
    from tests.fixtures.mock_llm import MockInterviewLLM
    controller = create_interview_controller(
        identity_checkpoint=PassingTestIdentityCheckpoint(),
        llm_client=MockInterviewLLM(),
    )
    monkeypatch.setattr(
        "app.stages.stage4_interview.dependencies.create_interview_controller",
        lambda: controller,
    )
    yield session_id
    try:
        registry.delete(session_id)
    except Exception:
        pass


def make_valid_wav_bytes() -> bytes:
    """Generate 100ms of valid mono, 16-bit PCM silence."""
    sample_rate = 16_000
    pcm_silence = b"\x00\x00" * (sample_rate // 10)
    byte_rate = sample_rate * 2
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(pcm_silence)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16)
        + b"data" + struct.pack("<I", len(pcm_silence))
    )
    return header + pcm_silence


# ---------------------------------------------------------------------------
# 1. Job Creation & QUEUED Status
# ---------------------------------------------------------------------------

def test_job_created_and_queued(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()

    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="I implemented CQRS."):
        response = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )

    assert response.status_code == 202, response.text
    data = response.json()
    assert "job_id" in data
    assert data["status"] == "queued"

    job_id = data["job_id"]
    queue = get_job_queue()
    job = queue.get(job_id)
    assert job is not None
    assert job.session_id == session_id
    assert job.status in [JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.COMPLETED.value]


# ---------------------------------------------------------------------------
# 2. Worker Processes Job & Status Becomes COMPLETED
# ---------------------------------------------------------------------------

def test_worker_processes_job_to_completed(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()

    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="I implemented event sourcing."):
        response = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        # Ensure worker processes the job
        queue = get_job_queue()
        worker = JobWorker(queue=queue)
        worker.process_job(job_id)

    # Check job status via GET /jobs/{job_id}
    res_job = client.get(f"/jobs/{job_id}")
    assert res_job.status_code == 200
    job_info = res_job.json()
    assert job_info["status"] == "completed"
    assert job_info["result"] is not None
    assert job_info["result"]["transcript"] == "I implemented event sourcing."
    assert "next_question" in job_info["result"]


# ---------------------------------------------------------------------------
# 3. Transcript Persisted & Interview Advances Exactly Once
# ---------------------------------------------------------------------------

def test_interview_advances_exactly_once(client, setup_test_interview):
    session_id = setup_test_interview
    initial_state = registry.get(session_id)
    assert len(initial_state.get("conversation_history", [])) == 0

    audio_data = make_valid_wav_bytes()
    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="I redesigned our database indexing strategy."):
        response = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        queue = get_job_queue()
        worker = JobWorker(queue=queue)
        worker.process_job(job_id)

    # Verify conversation history advanced exactly once
    updated_state = registry.get(session_id)
    history = updated_state.get("conversation_history", [])
    assert len(history) == 1
    assert history[0]["answer"] == "I redesigned our database indexing strategy."
    assert updated_state.get("turn_number", 1) >= 2


# ---------------------------------------------------------------------------
# 4. Duplicate Request Idempotency (Prevents Duplicate Turns)
# ---------------------------------------------------------------------------

def test_duplicate_request_idempotency(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()
    idempotency_key = f"idem_{uuid.uuid4().hex[:8]}"

    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="I optimized our queries."):
        # First request
        res1 = client.post(
            f"/interview/{session_id}/audio",
            headers={"Idempotency-Key": idempotency_key},
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert res1.status_code == 202
        job_id_1 = res1.json()["job_id"]

        # Process the first job
        queue = get_job_queue()
        worker = JobWorker(queue=queue)
        worker.process_job(job_id_1)

        # Second identical request (user refreshed or re-sent)
        res2 = client.post(
            f"/interview/{session_id}/audio",
            headers={"Idempotency-Key": idempotency_key},
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        # Should return existing job without creating a duplicate
        # The idempotency key must return the already completed job.
        assert res2.status_code == 200
        assert res2.json()["job_id"] == job_id_1

    # Verify conversation history has exactly 1 entry, NOT 2!
    state = registry.get(session_id)
    assert len(state.get("conversation_history", [])) == 1


# ---------------------------------------------------------------------------
# 5. STT Failure -> Job FAILED & State Not Advanced
# ---------------------------------------------------------------------------

def test_stt_failure_job_fails_and_state_preserved(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()

    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", side_effect=RuntimeError("Whisper hardware error")):
        response = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        queue = get_job_queue()
        worker = JobWorker(queue=queue)
        worker.process_job(job_id)

    res_job = client.get(f"/jobs/{job_id}")
    assert res_job.status_code == 200
    data = res_job.json()
    assert data["status"] == "failed"
    assert "couldn't process your recording" in data["error"]

    # Critical requirement: interview state must NOT advance
    state = registry.get(session_id)
    assert len(state.get("conversation_history", [])) == 0
    assert state.get("turn_number", 1) == 1


# ---------------------------------------------------------------------------
# 6. LLM Failure -> Job FAILED & State Not Advanced
# ---------------------------------------------------------------------------

def test_llm_failure_job_fails_and_state_preserved(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()

    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="Good answer"), \
         patch("app.stages.stage4_interview.controller.InterviewController.submit_text", side_effect=RuntimeError("LLM API Rate Limit Exceeded")):
        response = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]

        queue = get_job_queue()
        worker = JobWorker(queue=queue)
        worker.process_job(job_id)

    res_job = client.get(f"/jobs/{job_id}")
    assert res_job.status_code == 200
    data = res_job.json()
    assert data["status"] == "failed"
    assert "LLM reasoning service is currently unavailable" in data["error"]

    # Critical requirement: interview state must NOT advance
    state = registry.get(session_id)
    assert len(state.get("conversation_history", [])) == 0
    assert state.get("turn_number", 1) == 1


# ---------------------------------------------------------------------------
# 7. Recovery After Failure: State Uncorrupted
# ---------------------------------------------------------------------------

def test_recovery_after_failure_allows_subsequent_success(client, setup_test_interview):
    session_id = setup_test_interview
    audio_data = make_valid_wav_bytes()

    # Step 1: Simulated failure
    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", side_effect=RuntimeError("Transient STT glitch")):
        res1 = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert res1.status_code == 202, res1.text
        job_id_fail = res1.json()["job_id"]
        queue = get_job_queue()
        JobWorker(queue=queue).process_job(job_id_fail)

    assert queue.get(job_id_fail).status == JobStatus.FAILED.value

    # Step 2: Candidate retries recording successfully
    with patch("app.stages.stage4_interview.voice.stt.WhisperSTT.transcribe", return_value="Clear recovered answer"):
        res2 = client.post(
            f"/interview/{session_id}/audio",
            files={"audio": ("voice.wav", io.BytesIO(audio_data), "audio/wav")},
        )
        assert res2.status_code == 202
        job_id_ok = res2.json()["job_id"]
        JobWorker(queue=queue).process_job(job_id_ok)

    assert queue.get(job_id_ok).status == JobStatus.COMPLETED.value
    state = registry.get(session_id)
    assert len(state.get("conversation_history", [])) == 1
    assert state["conversation_history"][0]["answer"] == "Clear recovered answer"


# ---------------------------------------------------------------------------
# 8. Backend Restart Recovery: Queued Jobs Persisted to Disk
# ---------------------------------------------------------------------------

def test_backend_restart_does_not_lose_queued_job():
    temp_dir = tempfile.mkdtemp()
    try:
        # 1. Enqueue job in initial backend process
        queue1 = JobQueue(storage_dir=temp_dir)
        job = Job(
            id="JOB_PERSISTENCE_TEST_001",
            type=JobType.INTERVIEW_AUDIO.value,
            status=JobStatus.QUEUED.value,
            session_id="SESSION_RESTART_TEST",
            payload={"audio_path": "fake/path.wav"},
        )
        queue1.enqueue(job)
        assert queue1.get("JOB_PERSISTENCE_TEST_001").status == JobStatus.QUEUED.value

        # 2. Simulate server restart: completely new JobQueue instance reading from disk
        queue2 = JobQueue(storage_dir=temp_dir)
        recovered_job = queue2.get("JOB_PERSISTENCE_TEST_001")
        assert recovered_job is not None
        assert recovered_job.id == "JOB_PERSISTENCE_TEST_001"
        assert recovered_job.status == JobStatus.QUEUED.value
        assert recovered_job.session_id == "SESSION_RESTART_TEST"
        assert recovered_job.payload["audio_path"] == "fake/path.wav"

        # 3. Oldest queued job correctly retrieved
        next_job = queue2.get_next_queued_job()
        assert next_job is not None
        assert next_job.id == "JOB_PERSISTENCE_TEST_001"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 9. Redis Queue Integration (using fakeredis)
# ---------------------------------------------------------------------------

def test_redis_queue_integration():
    fake_redis_client = fakeredis.FakeRedis()
    temp_dir = tempfile.mkdtemp()
    try:
        queue = JobQueue(storage_dir=temp_dir, redis_client=fake_redis_client)
        job = Job(
            id="JOB_REDIS_001",
            type=JobType.INTERVIEW_AUDIO.value,
            status=JobStatus.QUEUED.value,
        )
        queue.enqueue(job)

        # Verify job was pushed to Redis queue list
        queued_in_redis = fake_redis_client.lpop("interview:jobs:queued")
        assert queued_in_redis == b"JOB_REDIS_001"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
