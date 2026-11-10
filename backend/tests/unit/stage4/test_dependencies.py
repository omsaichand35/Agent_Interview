from unittest.mock import patch, MagicMock
from app.stages.stage4_interview.dependencies import (
    create_interview_controller,
    registry,
)
from app.stages.stage4_interview.registry import InterviewSessionRegistry
from app.stages.stage4_interview.controller import InterviewController


def test_registry_instance():
    assert isinstance(registry, InterviewSessionRegistry)


@patch("app.stages.stage4_interview.dependencies.get_llm_client")
def test_create_interview_controller(mock_get_llm):
    mock_get_llm.return_value = MagicMock()

    controller = create_interview_controller()
    assert isinstance(controller, InterviewController)
    assert controller.session_manager is not None
    assert controller.session_manager.graph is not None
    assert controller.session_manager.persistence is not None
