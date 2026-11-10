"""Identity-System Security Test Suite (Requirement F4).

Verifies the security and integrity of candidate biometric verification:
[x] identity pending -> interview blocked (403)
[x] identity failed -> interview blocked (403)
[x] identity review -> interview blocked (403)
[x] identity passed -> interview allowed (200)
[x] client cannot set identity_verified=True in request
[x] multiple faces -> correct review/failure reason (MULTIPLE_FACES)
[x] no face -> correct failure reason (NO_FACE)
[x] invalid image -> rejected (422)
[x] threshold comes from configuration (calibrated decision bounds)
[x] biometric image/embedding isn't written to normal logs
[x] identity check is recorded with model provenance
[x] repeated checkpoint works during interview
[x] identity failure during interview stops progression
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.models.user import Role
from app.schemas.identity import IdentityCheck, IdentityResult
from app.security.rate_limiter import rate_limiter_instance
from app.stages.stage3_identity.identity_checker import IdentityChecker
from app.stages.stage3_identity.identity_logger import IdentityLogger
from app.stages.stage3_identity.identity_service import IdentityService
from app.stages.stage3_identity.threshold_config import (
    IdentityThresholdConfig,
    get_threshold_config,
)
from app.stages.stage4_interview.controller import InterviewController
from app.stages.stage4_interview.dependencies import registry
from app.stages.stage4_interview.identity_checkpoint import (
    IdentityCheckpoint,
    apply_identity_result,
)
from tests.fixtures.http import valid_live_frame_upload
import app.api.interview_routes as routes


# ---------------------------------------------------------------------------
# Test Fixtures & Fakes
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_environment():
    """Reset rate limiter and sessions before and after each test."""
    rate_limiter_instance.reset()
    registry.sessions.clear()
    yield
    rate_limiter_instance.reset()
    registry.sessions.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def candidate_c001_token():
    return create_access_token(
        user_id="U_CAND_01",
        role=Role.CANDIDATE.value,
        candidate_id="C001",
    )


class FakeDetector:
    def __init__(self, reference_faces=None, live_faces=None, faces=None):
        self.reference_faces = reference_faces
        self.live_faces = live_faces
        self.faces = faces if faces is not None else [(10, 10, 100, 100)]

    def detect(self, image_path):
        if "reference" in str(image_path) and self.reference_faces is not None:
            return self.reference_faces
        if "live" in str(image_path) and self.live_faces is not None:
            return self.live_faces
        return self.faces


class FakeMatcher:
    def __init__(self, confidence: float):
        self.confidence = confidence

    def compare(self, reference_path, live_path, reference_face, live_face):
        return self.confidence

    def match(self, reference_image, live_image):
        return self.confidence


# ---------------------------------------------------------------------------
# F4.4: Identity Gate & Status Enforcement
# ---------------------------------------------------------------------------

def test_identity_pending_blocks_interview_turn(api_client, candidate_c001_token):
    """F4.4: A session in 'pending' identity verification cannot submit interview answers."""
    registry.sessions["SESS_PENDING"] = {
        "session_id": "SESS_PENDING",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "pending",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res = api_client.post(
        "/interview/SESS_PENDING/answer",
        json={"answer": "I have extensive FastAPI experience."},
        headers=headers,
    )
    assert res.status_code == 403
    assert "pending" in res.json()["detail"].lower()


def test_identity_failed_blocks_interview_turn(api_client, candidate_c001_token):
    """F4.4: A session where identity failed cannot proceed."""
    registry.sessions["SESS_FAILED"] = {
        "session_id": "SESS_FAILED",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "failed",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res = api_client.post(
        "/interview/SESS_FAILED/answer",
        json={"answer": "I have extensive FastAPI experience."},
        headers=headers,
    )
    assert res.status_code == 403
    assert "failed" in res.json()["detail"].lower()


def test_identity_review_blocks_interview_turn(api_client, candidate_c001_token):
    """F4.4: A session flagged for human recruiter review holds interview progression."""
    registry.sessions["SESS_REVIEW"] = {
        "session_id": "SESS_REVIEW",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "review",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res = api_client.post(
        "/interview/SESS_REVIEW/answer",
        json={"answer": "I have extensive FastAPI experience."},
        headers=headers,
    )
    assert res.status_code == 403
    assert "review" in res.json()["detail"].lower()


def test_identity_passed_allows_interview_turn(api_client, candidate_c001_token, monkeypatch):
    """F4.4: A session with passed/verified identity status successfully executes answer turns."""
    registry.sessions["SESS_PASS"] = {
        "session_id": "SESS_PASS",
        "candidate_id": "C001",
        "turn_number": 1,
        "current_competency": "technical_skills",
        "interview_complete": False,
        "identity_verified": True,
        "identity_status": "verified",
        "interview_score": 80.0,
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}

    # Mock controller.submit_text for fast, deterministic response
    monkeypatch.setattr(
        routes.controller,
        "submit_text",
        lambda state, ans, **kwargs: {
            "session_id": "SESS_PASS",
            "candidate_id": "C001",
            "next_question": "Explain database indexing.",
            "decision": "deepen",
            "competency_scores": {"technical_skills": 0.85},
            "interview_score": 85.0,
            "interview_complete": False,
            "identity_verified": True,
        },
    )

    res = api_client.post(
        "/interview/SESS_PASS/answer",
        data={"answer": "I built backend microservices using Python and asyncio."},
        files={"live_frame": valid_live_frame_upload()},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == "SESS_PASS"
    assert data["identity_verified"] is True
    assert data["next_question"] == "Explain database indexing."


def test_client_cannot_set_identity_verified_true(api_client, candidate_c001_token):
    """F4.4: Client payload attempting to inject identity_verified=True is ignored by the backend."""
    registry.sessions["SESS_TAMPER"] = {
        "session_id": "SESS_TAMPER",
        "candidate_id": "C001",
        "turn_number": 1,
        "interview_complete": False,
        "identity_verified": False,
        "identity_status": "pending",
    }
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    res = api_client.post(
        "/interview/SESS_TAMPER/answer",
        json={
            "answer": "Here is my answer",
            "identity_verified": True,
            "identity_status": "passed",
        },
        headers=headers,
    )
    # The server checks server-side state, sees "pending", and rejects
    assert res.status_code == 403
    assert registry.get("SESS_TAMPER")["identity_verified"] is False


# ---------------------------------------------------------------------------
# F4.6: Suspicious Condition Detection
# ---------------------------------------------------------------------------

def test_multiple_faces_detected_returns_review_and_reason():
    """F4.6: Multiple faces in live frame triggers 'review' status with MULTIPLE_FACES reason."""
    detector = FakeDetector(
        reference_faces=[(10, 10, 100, 100)],
        live_faces=[(10, 10, 100, 100), (200, 10, 100, 100)],
    )
    matcher = FakeMatcher(confidence=0.95)
    checker = IdentityChecker(face_detector=detector, face_matcher=matcher)

    result = checker.verify(
        candidate_id="C001",
        session_id="S_MULTI",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False
    assert result.identity_status == "review"
    assert result.reason_code == "MULTIPLE_FACES"
    assert "Invalid live face state." in result.failure_reason


def test_no_face_detected_returns_failure_and_reason():
    """F4.6: Zero faces in live frame triggers 'failed' status with NO_FACE reason."""
    detector = FakeDetector(
        reference_faces=[(10, 10, 100, 100)],
        live_faces=[],
    )
    matcher = FakeMatcher(confidence=0.95)
    checker = IdentityChecker(face_detector=detector, face_matcher=matcher)

    result = checker.verify(
        candidate_id="C001",
        session_id="S_NOFACE",
        reference_path="reference.jpg",
        live_path="live.jpg",
    )

    assert result.verified is False
    assert result.identity_status == "failed"
    assert result.reason_code == "NO_FACE"
    assert result.face_detected is False


# ---------------------------------------------------------------------------
# F4.2 & F4.3: Configurable Thresholds & Uncertainty Calibration
# ---------------------------------------------------------------------------

def test_threshold_comes_from_configuration():
    """F4.2 & F4.3: Biometric thresholds are configurable and support 3-tier PASS/REVIEW/FAIL."""
    detector = FakeDetector(
        reference_faces=[(10, 10, 100, 100)],
        live_faces=[(10, 10, 100, 100)],
    )
    # Score 0.60: Borderline score
    matcher = FakeMatcher(confidence=0.60)

    # Standard configuration: pass=0.70, review=0.50
    config_std = IdentityThresholdConfig(pass_threshold=0.70, review_threshold=0.50)
    checker_std = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
        threshold_config=config_std,
    )
    res_std = checker_std.verify("C001", "S_CONF1", "ref.jpg", "live.jpg")
    assert res_std.identity_status == "review"
    assert res_std.verified is False
    assert res_std.reason_code == "LOW_CONFIDENCE"

    # Lenient configuration: pass=0.55, review=0.40 -> 0.60 passes!
    config_lenient = IdentityThresholdConfig(pass_threshold=0.55, review_threshold=0.40)
    checker_lenient = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
        threshold_config=config_lenient,
    )
    res_lenient = checker_lenient.verify("C001", "S_CONF2", "ref.jpg", "live.jpg")
    assert res_lenient.identity_status == "passed"
    assert res_lenient.verified is True

    # Strict configuration: pass=0.85, review=0.65 -> 0.60 fails!
    config_strict = IdentityThresholdConfig(pass_threshold=0.85, review_threshold=0.65)
    checker_strict = IdentityChecker(
        face_detector=detector,
        face_matcher=matcher,
        threshold_config=config_strict,
    )
    res_strict = checker_strict.verify("C001", "S_CONF3", "ref.jpg", "live.jpg")
    assert res_strict.identity_status == "failed"
    assert res_strict.verified is False
    assert res_strict.reason_code == "FACE_NOT_MATCHED"


def test_invalid_image_upload_rejected(api_client, candidate_c001_token):
    """F4.6: Corrupted or non-image bytes uploaded as live frame are rejected with 422."""
    headers = {"Authorization": f"Bearer {candidate_c001_token}"}
    corrupted_data = b"NOT_AN_IMAGE_RANDOM_GARBAGE_BYTES_12345"
    files = {"live_frame": ("face.jpg", corrupted_data, "image/jpeg")}

    res = api_client.post(
        "/interview/SESSION001/check",
        files=files,
        data={"candidate_id": "C001"},
        headers=headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# F4.8 & F4.9: Biometric Privacy & Model Provenance Tracking
# ---------------------------------------------------------------------------

def test_biometric_image_not_written_to_normal_logs(tmp_path):
    """F4.8: Identity audit logs must contain structured metadata only, never raw image bytes or embeddings."""
    logger = IdentityLogger(output_dir=str(tmp_path))
    result = IdentityResult(
        candidate_id="C001",
        session_id="S_PROV",
        verified=True,
        confidence=0.88,
        face_detected=True,
        face_match_score=0.88,
        liveness_status="not_implemented",
        identity_status="passed",
        matcher="sface",
        face_detector="yunet",
        model_version="2021dec",
        threshold_version="v1",
        threshold=0.70,
        review_threshold=0.50,
        checks=[
            IdentityCheck(
                timestamp="2026-09-25T11:00:00Z",
                check_type="face_match",
                face_detected=True,
                face_count=1,
                confidence=0.88,
                result="pass",
            )
        ],
    )

    log_path = logger.log(result)
    assert Path(log_path).exists()

    with open(log_path, "r", encoding="utf-8") as f:
        log_content = json.load(f)

    # Provenance fields present
    assert log_content["matcher"] == "sface"
    assert log_content["face_detector"] == "yunet"
    assert log_content["model_version"] == "2021dec"
    assert log_content["threshold_version"] == "v1"
    assert log_content["confidence"] == 0.88

    # Ensure NO binary data, base64 strings, or raw vector embeddings exist
    raw_text = Path(log_path).read_text(encoding="utf-8")
    assert "data:image" not in raw_text
    assert "embedding" not in raw_text.lower()
    assert "raw_bytes" not in raw_text


# ---------------------------------------------------------------------------
# F4.5: Repeated Checkpoints & Mid-Interview Failure
# ---------------------------------------------------------------------------

def test_repeated_checkpoint_increments_count():
    """F4.5: Repeated checkpoints during the interview increment check count and preserve state."""
    state = {
        "session_id": "S_REPEAT",
        "candidate_id": "C001",
        "identity_verified": True,
        "identity_status": "passed",
        "identity_check_count": 1,
        "interview_complete": False,
    }

    checkpoint_result = IdentityResult(
        candidate_id="C001",
        session_id="S_REPEAT",
        verified=True,
        confidence=0.91,
        identity_status="passed",
    )

    new_state = apply_identity_result(state, checkpoint_result)
    assert new_state["identity_check_count"] == 2
    assert new_state["identity_verified"] is True
    assert new_state["last_identity_confidence"] == 0.91
    assert new_state["workflow_condition"] == "identity_pass"


def test_identity_failure_during_interview_stops_progression():
    """F4.5: Mid-interview checkpoint failure immediately terminates interview progression."""
    state = {
        "session_id": "S_MID_FAIL",
        "candidate_id": "C001",
        "turn_number": 3,
        "identity_verified": True,
        "identity_status": "passed",
        "identity_check_count": 1,
        "interview_complete": False,
    }

    # Mid-interview check fails (impostor substituted)
    failure_result = IdentityResult(
        candidate_id="C001",
        session_id="S_MID_FAIL",
        verified=False,
        confidence=0.25,
        identity_status="failed",
        failure_reason="Biometric face mismatch at Turn 3 checkpoint.",
        reason_code="FACE_NOT_MATCHED",
    )

    new_state = apply_identity_result(state, failure_result)
    assert new_state["identity_verified"] is False
    assert new_state["identity_status"] == "failed"
    assert new_state["interview_complete"] is True
    assert new_state["workflow_condition"] == "identity_failure"
    assert "Biometric face mismatch" in new_state["identity_failure_reason"]


def test_identity_check_is_recorded_with_provenance(tmp_path):
    """F4.9: Identity verification via IdentityService is recorded to log with full model provenance."""
    detector = FakeDetector(reference_faces=[(0, 0, 10, 10)], live_faces=[(0, 0, 10, 10)])
    matcher = FakeMatcher(confidence=0.89)
    checker = IdentityChecker(face_detector=detector, face_matcher=matcher)
    logger = IdentityLogger(output_dir=str(tmp_path))
    service = IdentityService(logger=logger, checker=checker)

    result = service.verify(
        candidate_id="C001",
        session_id="S_REC_TEST",
        reference_image="ref.jpg",
        live_image="live.jpg",
    )

    assert result.verified is True
    log_file = tmp_path / "identity_log_S_REC_TEST.json"
    assert log_file.exists()
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["session_id"] == "S_REC_TEST"
    assert data["matcher"] == "sface"
    assert data["face_detector"] == "yunet"
    assert data["model_version"] == "2021dec"
    assert data["threshold_version"] == "v1"
    assert data["confidence"] == 0.89

