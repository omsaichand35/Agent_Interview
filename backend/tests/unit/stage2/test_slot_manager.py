import pytest

from datetime import datetime

from app.schemas.schedule import InterviewSlot

from app.stages.stage2_scheduling.slot_manager import (
    SlotManager,
)


def create_slot():

    return InterviewSlot(
        slot_id="S001",
        start_time=datetime(
            2026,
            10,
            1,
            10,
            0,
        ),
        end_time=datetime(
            2026,
            10,
            1,
            10,
            30,
        ),
        available=True,
    )


def test_slot_can_be_reserved():

    manager = SlotManager(
        [create_slot()]
    )

    slot = manager.reserve("S001")

    assert slot.slot_id == "S001"
    assert slot.available is False


def test_same_slot_cannot_be_reserved_twice():

    manager = SlotManager(
        [create_slot()]
    )

    manager.reserve("S001")

    with pytest.raises(ValueError):

        manager.reserve("S001")