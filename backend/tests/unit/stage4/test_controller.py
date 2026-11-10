from unittest.mock import MagicMock
import pytest
from app.stages.stage4_interview.controller import InterviewController


def test_interview_controller_start():
    mock_session_mgr = MagicMock()
    mock_session_mgr.create_state.return_value = {
        "session_id": "S1",
        "candidate_id": "C1",
        "current_question": None,
        "next_question": None,
    }

    controller = InterviewController(session_manager=mock_session_mgr)
    state = controller.start(
        session_id="S1",
        candidate_id="C1",
        candidate={"name": "Alice"},
        competencies=["Python"],
        first_question="Tell me about your Python background.",
    )

    mock_session_mgr.create_state.assert_called_once_with(
        session_id="S1",
        candidate_id="C1",
        candidate={"name": "Alice"},
        competencies=["Python"],
    )
    assert state["current_question"] == "Tell me about your Python background."
    assert state["next_question"] == "Tell me about your Python background."


def test_interview_controller_submit_text():
    mock_session_mgr = MagicMock()
    mock_session_mgr.submit_answer.return_value = {"status": "ok"}
    mock_identity = MagicMock()
    mock_identity.check.return_value = MagicMock(verified=True, identity_status="passed", confidence=0.9, failure_reason=None)

    controller = InterviewController(
        session_manager=mock_session_mgr,
        identity_checkpoint=mock_identity,
    )
    state = {
        "session_id": "S1",
        "candidate_id": "C1",
        "interview_complete": False,
    }
    result = controller.submit_text(state=state, answer="My answer")

    mock_session_mgr.submit_answer.assert_called_once_with(
        state, "My answer"
    )
    assert result == {"status": "ok"}
    assert state["identity_status"] == "verified"


def test_interview_controller_submit_audio_success():
    mock_session_mgr = MagicMock()
    mock_session_mgr.submit_answer.return_value = {
        "session_id": "S1",
        "turn_number": 2,
        "next_question": "What is dependency injection?",
    }

    mock_voice = MagicMock()
    mock_voice.transcribe.return_value = "I use FastAPI for web services."
    mock_voice.speak.return_value = "data/outputs/interviews/S1_turn_2.wav"
    mock_identity = MagicMock()
    mock_identity.check.return_value = MagicMock(verified=True, identity_status="passed", confidence=0.9, failure_reason=None)

    controller = InterviewController(
        session_manager=mock_session_mgr,
        voice_service=mock_voice,
        identity_checkpoint=mock_identity,
    )

    state = {
        "session_id": "S1",
        "candidate_id": "C1",
        "interview_complete": False,
    }

    response = controller.submit_audio(
        state=state,
        audio_path="audio/in.wav",
    )

    mock_voice.transcribe.assert_called_once_with("audio/in.wav")
    mock_session_mgr.submit_answer.assert_called_once_with(
        state, "I use FastAPI for web services."
    )
    mock_voice.speak.assert_called_once_with(
        "What is dependency injection?",
        "data/outputs/interviews/S1_turn_2.wav",
    )

    assert response["transcript"] == "I use FastAPI for web services."
    assert response["next_question"] == "What is dependency injection?"
    assert response["audio_path"] == "data/outputs/interviews/S1_turn_2.wav"
    assert state["identity_status"] == "verified"


def test_interview_controller_submit_audio_no_voice_service():
    mock_session_mgr = MagicMock()
    controller = InterviewController(session_manager=mock_session_mgr, voice_service=None)

    with pytest.raises(RuntimeError, match="Voice service is not configured"):
        controller.submit_audio(state={}, audio_path="audio.wav")


def test_interview_controller_submit_audio_concluded_no_next_question():
    mock_session_mgr = MagicMock()
    mock_session_mgr.submit_answer.return_value = {
        "session_id": "S1",
        "turn_number": 5,
        "next_question": None,
    }

    mock_voice = MagicMock()
    mock_voice.transcribe.return_value = "Final answer."
    mock_identity = MagicMock()
    mock_identity.check.return_value = MagicMock(verified=True, identity_status="passed", confidence=0.9, failure_reason=None)

    controller = InterviewController(
        session_manager=mock_session_mgr,
        voice_service=mock_voice,
        identity_checkpoint=mock_identity,
    )

    state = {
        "session_id": "S1",
        "candidate_id": "C1",
        "interview_complete": False,
    }

    response = controller.submit_audio(state=state, audio_path="test.wav")
    mock_voice.speak.assert_not_called()
    assert response["audio_path"] is None
    assert response["next_question"] is None


def test_controller_submit_text_already_complete_raises():
    mock_session_mgr = MagicMock()
    controller = InterviewController(session_manager=mock_session_mgr)

    with pytest.raises(RuntimeError, match="Interview is already complete."):
        controller.submit_text(
            state={"session_id": "S1", "interview_complete": True},
            answer="Answer after completion",
        )


def test_controller_submit_audio_already_complete_raises():
    mock_session_mgr = MagicMock()
    controller = InterviewController(session_manager=mock_session_mgr)

    with pytest.raises(RuntimeError, match="Interview is already complete."):
        controller.submit_audio(
            state={"session_id": "S1", "interview_complete": True},
            audio_path="test.wav",
        )


def test_submit_without_identity_checkpoint_raises():
    mock_session_mgr = MagicMock()
    controller = InterviewController(session_manager=mock_session_mgr, identity_checkpoint=None)

    with pytest.raises(RuntimeError, match="Identity checkpoint is not configured."):
        controller.submit_text(state={"session_id": "S1", "candidate_id": "C1"}, answer="hi")


def test_submit_audio_identity_failure_prevents_stt():

    events = []

    class FakeIdentityResult:
        verified = False
        confidence = 0.20
        failure_reason = "Face mismatch"

    class FakeIdentityCheckpoint:

        def check(self, candidate_id, session_id):
            events.append("identity")
            return FakeIdentityResult()

    class FakeVoiceService:

        def transcribe(self, audio_path):
            events.append("stt")
            raise AssertionError(
                "STT must not run after identity failure."
            )

    class FakePersistence:

        def save_state(self, state):
            pass

    class FakeSessionManager:

        persistence = FakePersistence()

    controller = InterviewController(
        session_manager=FakeSessionManager(),
        voice_service=FakeVoiceService(),
        identity_checkpoint=FakeIdentityCheckpoint(),
    )

    state = {
        "candidate_id": "C001",
        "session_id": "S001",
        "identity_verified": False,
        "identity_status": "pending",
        "identity_failure_reason": None,
        "last_identity_confidence": None,
        "identity_check_count": 0,
        "interview_complete": False,
    }

    result = controller.submit_audio(
        state,
        "answer.wav",
    )

    assert events == ["identity"]
    assert result["transcript"] is None
    assert state["identity_status"] == "failed"
    assert state["interview_complete"] is True


def test_submit_audio_identity_pass_allows_stt():

    events = []

    class FakeIdentityResult:
        verified = True
        confidence = 0.91
        failure_reason = None

    class FakeIdentityCheckpoint:

        def check(self, candidate_id, session_id):
            events.append("identity")
            return FakeIdentityResult()

    class FakeVoiceService:

        def transcribe(self, audio_path):
            events.append("stt")
            return "I designed a distributed backend."

    class FakeSessionManager:

        class Persistence:
            def save_state(self, state):
                pass

        persistence = Persistence()

        def submit_answer(self, state, answer):
            events.append("interview")
            return {
                **state,
                "next_question": None,
                "turn_number": 2,
            }

    controller = InterviewController(
        session_manager=FakeSessionManager(),
        voice_service=FakeVoiceService(),
        identity_checkpoint=FakeIdentityCheckpoint(),
    )

    state = {
        "candidate_id": "C001",
        "session_id": "S001",
        "identity_verified": False,
        "identity_status": "pending",
        "identity_failure_reason": None,
        "last_identity_confidence": None,
        "identity_check_count": 0,
        "interview_complete": False,
    }

    result = controller.submit_audio(
        state,
        "answer.wav",
    )

    assert events == [
        "identity",
        "stt",
        "interview",
    ]

    assert result["transcript"] == (
        "I designed a distributed backend."
    )
