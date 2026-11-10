from datetime import datetime

import pytest

from app.schemas.schedule import InterviewSlot
from app.schemas.resume import ResumeScore

from app.stages.stage2_scheduling.slot_manager import (
    SlotManager,
)

from app.stages.stage2_scheduling.scheduler import (
    Scheduler,
)


def make_slot(slot_id, hour):

    return InterviewSlot(
        slot_id=slot_id,
        start_time=datetime(
            2026,
            10,
            1,
            hour,
            0,
        ),
        end_time=datetime(
            2026,
            10,
            1,
            hour,
            30,
        ),
        available=True,
    )


def make_candidate(candidate_id, score):

    return ResumeScore(
        candidate_id=candidate_id,
        overall_score=score,
        competency_scores=[],
        strengths=[],
        gaps=[],
    )


def test_candidates_are_assigned_unique_slots():

    slots = [
        make_slot("S001", 10),
        make_slot("S002", 11),
    ]

    manager = SlotManager(slots)

    scheduler = Scheduler(manager)

    candidates = [
        make_candidate("C001", 80),
        make_candidate("C002", 70),
    ]

    schedules = scheduler.schedule(
        candidates
    )

    assert len(schedules) == 2

    assert schedules[0].candidate_id == "C001"
    assert schedules[0].slot_id == "S001"

    assert schedules[1].candidate_id == "C002"
    assert schedules[1].slot_id == "S002"

    assert (
        schedules[0].slot_id
        != schedules[1].slot_id
    )


def test_scheduler_rejects_insufficient_slots():

    slots = [
        make_slot("S001", 10),
    ]

    manager = SlotManager(slots)

    scheduler = Scheduler(manager)

    candidates = [
        make_candidate("C001", 80),
        make_candidate("C002", 70),
    ]

    with pytest.raises(RuntimeError):

        scheduler.schedule(
            candidates
        )