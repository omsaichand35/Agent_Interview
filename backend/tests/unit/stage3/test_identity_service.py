from unittest.mock import MagicMock
from app.schemas.identity import IdentityResult
from app.stages.stage3_identity.identity_service import IdentityService


def test_identity_service_verify_success():
    service = IdentityService()
    service.checker = MagicMock()
    service.logger = MagicMock()

    mock_result = IdentityResult(
        candidate_id="C001",
        session_id="SESSION001",
        verified=True,
        confidence=0.88,
        checks=[],
    )
    service.checker.verify.return_value = mock_result

    result = service.verify(
        candidate_id="C001",
        session_id="SESSION001",
        reference_image="ref.jpg",
        live_image="live.jpg",
    )

    assert isinstance(result, IdentityResult)
    assert result.verified is True
    assert result.candidate_id == "C001"
    assert result.session_id == "SESSION001"
    service.checker.verify.assert_called_once_with(
        candidate_id="C001",
        session_id="SESSION001",
        reference_path="ref.jpg",
        live_path="live.jpg",
    )
    service.logger.log.assert_called_once()


def test_identity_service_verify_failure_gates_interview():
    service = IdentityService()
    service.checker = MagicMock()
    service.logger = MagicMock()

    mock_result = IdentityResult(
        candidate_id="C002",
        session_id="SESSION002",
        verified=False,
        confidence=0.42,
        failure_reason="Face mismatch between reference and live feed.",
        checks=[],
    )
    service.checker.verify.return_value = mock_result

    result = service.verify(
        candidate_id="C002",
        session_id="SESSION002",
        reference_image="ref.jpg",
        live_image="live.jpg",
    )

    assert isinstance(result, IdentityResult)
    assert result.verified is False
    assert result.failure_reason == "Face mismatch between reference and live feed."
    # The workflow checks result.verified directly:
    workflow_action = "interview" if result.verified else "human_review"
    assert workflow_action == "human_review"
