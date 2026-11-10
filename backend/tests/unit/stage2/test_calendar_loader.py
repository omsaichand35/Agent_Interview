import json
from pathlib import Path

from app.stages.stage2_scheduling.calendar_loader import (
    CalendarLoader,
)


def test_calendar_loader(tmp_path):
    calendar_path = tmp_path / "calendar.json"
    calendar_path.write_text(json.dumps({"slots": [
        {
            "slot_id": "slot-test-1",
            "start_time": "2026-10-01T10:00:00",
            "end_time": "2026-10-01T10:30:00",
            "available": True,
        },
    ]}), encoding="utf-8")

    loader = CalendarLoader()

    slots = loader.load(
        str(calendar_path)
    )

    assert len(slots) == 1

    assert slots[0].slot_id == "slot-test-1"
    assert slots[0].available is True
