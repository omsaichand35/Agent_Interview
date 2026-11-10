import pytest
from app.stages.stage4_interview.registry import InterviewSessionRegistry


def test_registry_lifecycle():
    registry = InterviewSessionRegistry()

    # create
    state = {"session_id": "S1", "turn_number": 1}
    registry.create("S1", state)

    # get
    retrieved = registry.get("S1")
    assert retrieved == state

    # update
    updated_state = {"session_id": "S1", "turn_number": 2}
    registry.update("S1", updated_state)
    assert registry.get("S1")["turn_number"] == 2

    # delete
    registry.delete("S1")
    with pytest.raises(KeyError, match="Interview session not found: S1"):
        registry.get("S1")


def test_registry_get_nonexistent():
    registry = InterviewSessionRegistry()
    with pytest.raises(KeyError, match="Interview session not found: MISSING"):
        registry.get("MISSING")
