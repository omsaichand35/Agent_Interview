from datetime import datetime
from unittest.mock import MagicMock
from app.schemas.schedule import InterviewSlot
from app.stages.stage2_scheduling.scheduling_service import SchedulingService


def test_scheduling_requires_an_explicit_calendar(monkeypatch):
    monkeypatch.delenv("INTERVIEW_CALENDAR_PATH", raising=False)
    service = SchedulingService()

    try:
        service.schedule(shortlist=[])
    except FileNotFoundError as exc:
        assert "No interview calendar is configured" in str(exc)
    else:
        raise AssertionError("Scheduling must not silently use a bundled mock calendar")


def test_scheduling_service_schedule_contract():
    service = SchedulingService(calendar_path="test-calendar.json")

    # Mock calendar loader to return slots
    service.loader = MagicMock()
    service.loader.load.return_value = [
        InterviewSlot(
            slot_id="SLOT_01",
            start_time=datetime(2026, 10, 1, 9, 0),
            end_time=datetime(2026, 10, 1, 9, 30),
            available=True,
        ),
        InterviewSlot(
            slot_id="SLOT_02",
            start_time=datetime(2026, 10, 1, 10, 0),
            end_time=datetime(2026, 10, 1, 10, 30),
            available=True,
        ),
    ]

    # Mock confirmation generator
    service.confirmation_generator = MagicMock()
    service.confirmation_generator.generate.side_effect = [
        "data/outputs/confirmations/C001_confirmation.json",
        "data/outputs/confirmations/C002_confirmation.json",
    ]

    shortlist = [
        {"candidate_id": "C001", "name": "Alice", "resume_score": 92.0},
        {"candidate_id": "C002", "name": "Bob", "resume_score": 85.0},
    ]

    result = service.schedule(shortlist=shortlist)

    assert "schedules" in result
    assert "confirmations" in result

    schedules = result["schedules"]
    confirmations = result["confirmations"]

    assert len(schedules) == 2
    assert len(confirmations) == 2

    assert schedules[0].candidate_id == "C001"
    assert schedules[0]["candidate_id"] == "C001"
    assert schedules[0].slot_id == "SLOT_01"

    assert schedules[1].candidate_id == "C002"
    assert schedules[1]["candidate_id"] == "C002"
    assert schedules[1].slot_id == "SLOT_02"
