import io
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.stages.stage4_interview.dependencies import registry
import app.api.interview_routes as routes


@pytest.fixture
def mock_controller():
    controller = MagicMock()
    # mock start
    controller.start.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 1,
        "current_competency": "technical_skills",
        "current_question": "Tell me about your backend experience.",
        "next_question": "Tell me about your backend experience.",
        "decision": "continue",
        "competency_scores": {"technical_skills": 0.86},
        "interview_score": 86.0,
        "interview_complete": False,
        "identity_verified": True,
    }
    controller.voice_service = MagicMock()
    controller.voice_service.speak.return_value = "data/outputs/interviews/SESSION001_turn_1.wav"

    # mock submit_text
    controller.submit_text.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "turn_number": 2,
        "decision": "pivot",
        "current_competency": "leadership",
        "interview_score": 78.4,
        "next_question": "Tell me about a time you led a challenging engineering initiative.",
        "competency_scores": {
            "technical_skills": 0.86,
            "leadership": 0.81,
        },
        "interview_complete": False,
        "identity_verified": True,
    }

    # mock submit_audio
    controller.submit_audio.return_value = {
        "state": {
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "turn_number": 2,
            "decision": "pivot",
            "current_competency": "leadership",
            "interview_score": 78.4,
            "competency_scores": {
                "technical_skills": 0.86,
                "leadership": 0.81,
            },
            "interview_complete": False,
            "identity_verified": True,
        },
        "transcript": "I built a FastAPI backend with PostgreSQL and Docker.",
        "next_question": "Tell me about a time you led a challenging engineering initiative.",
        "audio_path": "data/outputs/interviews/SESSION001_turn_2.wav",
    }

    # mock build_result
    controller.session_manager.build_result.return_value = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "status": "completed",
        "identity_verified": True,
        "interview_score": 82.4,
        "competency_scores": {
            "technical_skills": 0.86,
            "leadership": 0.81,
            "databases": 0.79,
        },
        "turn_count": 8,
    }

    return controller


@pytest.fixture
def client(mock_controller, monkeypatch):
    from app.core.security import create_access_token
    token = create_access_token(user_id="U_TEST_RECRUITER", role="recruiter")
    registry.sessions.clear()
    monkeypatch.setattr(routes, "controller", mock_controller)
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client
    registry.sessions.clear()


def test_api_start_interview(client):
    payload = {
        "session_id": "SESSION001",
        "candidate_id": "C001",
        "candidate": {"name": "Alex Smith"},
        "competencies": ["technical_skills", "leadership", "databases"],
        "first_question": "Tell me about your backend experience.",
    }
    response = client.post("/interview/start", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION001"
    assert data["candidate_id"] == "C001"
    assert data["next_question"] == "Tell me about your backend experience."


def test_api_submit_answer_text(client):
    # First start
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    response = client.post(
        "/interview/SESSION001/answer",
        json={"answer": "I built microservices using Python and asyncio."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "I built microservices using Python and asyncio."
    assert data["decision"] == "pivot"
    assert data["interview_score"] == 78.4
    assert data["next_question"] == "Tell me about a time you led a challenging engineering initiative."


def test_api_submit_answer_multipart_with_live_frame(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION_MP_01",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    fake_frame = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpg")
    response = client.post(
        "/interview/SESSION_MP_01/answer",
        data={"answer": "I developed distributed systems with Python and Kafka."},
        files={"live_frame": ("identity.jpg", fake_frame, "image/jpeg")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "I developed distributed systems with Python and Kafka."
    assert data["decision"] == "pivot"
    assert data["identity_verified"] is True


def test_api_submit_answer_audio(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    fake_audio = io.BytesIO(b"RIFF....WAVEfmt ....")
    response = client.post(
        "/interview/SESSION001/audio?sync=true",
        files={"audio": ("candidate_voice.wav", fake_audio, "audio/wav")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["transcript"] == "I built a FastAPI backend with PostgreSQL and Docker."
    assert data["decision"] == "pivot"
    assert data["interview_score"] == 78.4


def test_api_submit_answer_session_not_found(client):
    response = client.post(
        "/interview/NONEXISTENT/answer",
        json={"answer": "Hello"},
    )
    assert response.status_code == 404


def test_api_submit_answer_already_complete(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )
    # Finish interview
    client.post("/interview/SESSION001/finish")

    # Try to answer after completion
    response = client.post(
        "/interview/SESSION001/answer",
        json={"answer": "Another answer"},
    )
    assert response.status_code == 409
    assert "already complete" in response.json()["detail"]


def test_api_finish_interview(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    response = client.post("/interview/SESSION001/finish")
    assert response.status_code == 200
    data = response.json()
    assert data["interview_complete"] is True
    assert data["interview_score"] == 82.4
    assert "technical_skills" in data["competency_scores"]


def test_api_finish_session_not_found(client):
    response = client.post("/interview/NONEXISTENT/finish")
    assert response.status_code == 404


def test_api_get_interview(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    response = client.get("/interview/SESSION001")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION001"
    assert data["candidate_id"] == "C001"
    assert data["current_question"] == "Tell me about your backend experience."
    assert data["turn_number"] == 1
    assert data["interview_complete"] is False


def test_api_get_interview_not_found(client):
    response = client.get("/interview/NONEXISTENT")
    assert response.status_code == 404


def test_api_get_interview_result_incomplete(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    response = client.get("/interview/SESSION001/result")
    assert response.status_code == 409
    assert "Interview is not complete" in response.json()["detail"]


def test_api_get_interview_result_success(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )
    client.post("/interview/SESSION001/finish")

    response = client.get("/interview/SESSION001/result")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION001"
    assert data["status"] == "completed"
    assert data["interview_score"] == 82.4


def test_api_get_interview_result_not_found(client):
    response = client.get("/interview/NONEXISTENT/result")
    assert response.status_code == 404


def test_api_complete_interview_not_found(client):
    response = client.post("/interview/NONEXISTENT/complete")
    assert response.status_code == 404


def test_api_complete_interview_incomplete(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    response = client.post("/interview/SESSION001/complete")
    assert response.status_code == 409
    assert "Interview is not complete" in response.json()["detail"]


def test_api_complete_interview_success(client):
    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )
    client.post("/interview/SESSION001/finish")

    response = client.post("/interview/SESSION001/complete")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "SESSION001"
    assert data["candidate_id"] == "C001"
    assert data["status"] == "completed"
    assert data["interview_score"] == 82.4


def test_api_complete_interview_triggers_workflow_resumer_callable(client, mock_controller):
    callback_mock = MagicMock()
    # Ensure it doesn't have resume_after_interview or resume
    del callback_mock.resume_after_interview
    del callback_mock.resume
    mock_controller.workflow_resumer = callback_mock

    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )
    client.post("/interview/SESSION001/finish")

    response = client.post("/interview/SESSION001/complete")
    assert response.status_code == 200
    callback_mock.assert_called_once()
    args, _ = callback_mock.call_args
    assert args[0] == "SESSION001"
    assert args[1]["session_id"] == "SESSION001"


def test_api_complete_interview_triggers_workflow_resumer_object(client, mock_controller):
    resumer_mock = MagicMock()
    mock_controller.workflow_resumer = resumer_mock

    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {},
            "competencies": ["technical_skills"],
            "first_question": "Tell me about your backend experience.",
        },
    )
    client.post("/interview/SESSION001/finish")

    response = client.post("/interview/SESSION001/complete")
    assert response.status_code == 200
    resumer_mock.resume_after_interview.assert_called_once()
    args, _ = resumer_mock.resume_after_interview.call_args
    assert args[0]["session_id"] == "SESSION001"
    assert args[1]["session_id"] == "SESSION001"


def test_api_check_identity_success(client):
    from app.api.dependencies import get_identity_service
    from app.schemas.identity import IdentityResult

    mock_service = MagicMock()
    mock_service.verify.return_value = IdentityResult(
        candidate_id="C001",
        session_id="SESSION001",
        verified=True,
        confidence=0.82,
        failure_reason=None,
    )

    app.dependency_overrides[get_identity_service] = lambda: mock_service
    try:
        client.post(
            "/interview/start",
            json={
                "session_id": "SESSION001",
                "candidate_id": "C001",
                "candidate": {"photo_path": "data/ref.jpg"},
                "competencies": ["technical_skills"],
                "first_question": "Tell me about your experience.",
            },
        )

        fake_frame = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpg")
        response = client.post(
            "/interview/SESSION001/check",
            data={"candidate_id": "C001"},
            files={"live_frame": ("live.jpg", fake_frame, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["candidate_id"] == "C001"
        assert data["session_id"] == "SESSION001"
        assert data["verified"] is True
        assert data["confidence"] == 0.82
        assert data["failure_reason"] is None

        # Verify session state updated
        state = registry.get("SESSION001")
        assert state["identity_verified"] is True
        assert state["identity_status"] == "verified"
    finally:
        app.dependency_overrides.pop(get_identity_service, None)


def test_api_check_identity_failure(client):
    from app.api.dependencies import get_identity_service
    from app.schemas.identity import IdentityResult

    mock_service = MagicMock()
    mock_service.verify.return_value = IdentityResult(
        candidate_id="C001",
        session_id="SESSION001",
        verified=False,
        confidence=0.35,
        failure_reason="Face mismatch",
    )

    app.dependency_overrides[get_identity_service] = lambda: mock_service
    try:
        client.post(
            "/interview/start",
            json={
                "session_id": "SESSION001",
                "candidate_id": "C001",
                "candidate": {"photo_path": "data/ref.jpg"},
                "competencies": ["technical_skills"],
                "first_question": "Tell me about your experience.",
            },
        )

        fake_frame = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIFfakejpg")
        response = client.post(
            "/interview/SESSION001/check",
            data={"candidate_id": "C001"},
            files={"live_frame": ("live.jpg", fake_frame, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verified"] is False
        assert data["failure_reason"] == "Face mismatch"

        # Verify session state reflects failure
        state = registry.get("SESSION001")
        assert state["identity_verified"] is False
        assert state["identity_status"] == "failed"
        assert state["interview_complete"] is True
    finally:
        app.dependency_overrides.pop(get_identity_service, None)


def test_submit_audio_answer_end_to_end(client):
    from pathlib import Path

    client.post(
        "/interview/start",
        json={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "candidate": {"photo_path": "data/ref.jpg"},
            "competencies": ["technical_skills", "problem_solving"],
            "first_question": "Tell me about your backend experience.",
        },
    )

    fake_audio = io.BytesIO(b"\x1a\x45\xdf\xa3webm_fake_speech_bytes")
    with patch.object(
        routes.stt,
        "transcribe",
        return_value="I designed the backend using FastAPI with clean architecture.",
    ) as mock_stt, patch.object(
        routes.controller,
        "submit_text",
        return_value={
            "session_id": "SESSION001",
            "candidate_id": "C001",
            "current_question": "Tell me about your backend experience.",
            "next_question": "How do you handle database connection pooling in FastAPI?",
            "decision": "deepen",
            "interview_complete": False,
        },
    ) as mock_controller:
        response = client.post(
            "/interview/SESSION001/answer/audio",
            files={"audio": ("answer.webm", fake_audio, "audio/webm")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "SESSION001"
        assert data["transcript"] == "I designed the backend using FastAPI with clean architecture."
        assert data["question"] == "How do you handle database connection pooling in FastAPI?"
        assert data["decision"] == "deepen"
        assert data["complete"] is False
        mock_stt.assert_called_once()
        mock_controller.assert_called_once()

        assert "audio_path" not in data
        saved_audio = Path(mock_stt.call_args.args[0])
        assert not saved_audio.exists()


def test_submit_audio_answer_session_not_found(client):
    fake_audio = io.BytesIO(b"\x1a\x45\xdf\xa3webm_fake_speech_bytes")
    with patch.object(routes.stt, "transcribe", return_value="Test answer"):
        response = client.post(
            "/interview/NONEXISTENT_SESSION/answer/audio",
            files={"audio": ("answer.webm", fake_audio, "audio/webm")},
        )
        assert response.status_code == 404


def test_submit_audio_answer_empty_speech(client):
    fake_audio = io.BytesIO(b"\x1a\x45\xdf\xa3webm_fake_silent_audio")
    with patch.object(
        routes.stt,
        "transcribe",
        side_effect=ValueError("Whisper returned an empty transcription."),
    ):
        response = client.post(
            "/interview/SESSION001/answer/audio",
            files={"audio": ("answer.webm", fake_audio, "audio/webm")},
        )
        assert response.status_code == 422
        assert "No speech detected" in response.json()["detail"]



def test_transcribe_answer(client):
    from pathlib import Path

    fake_audio = io.BytesIO(b"\x1a\x45\xdf\xa3webm_fake_speech_bytes")
    with patch.object(
        routes.stt,
        "transcribe",
        return_value="I designed the backend using FastAPI with separate service and repository layers.",
    ) as mock_transcribe:
        response = client.post(
            "/interview/SESSION001/answer/transcribe",
            files={"audio": ("answer.webm", fake_audio, "audio/webm")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "SESSION001"
        assert (
            data["transcript"]
            == "I designed the backend using FastAPI with separate service and repository layers."
        )
        assert "audio_path" not in data
        saved_audio = Path(mock_transcribe.call_args.args[0])
        assert not saved_audio.exists()
        mock_transcribe.assert_called_once()
