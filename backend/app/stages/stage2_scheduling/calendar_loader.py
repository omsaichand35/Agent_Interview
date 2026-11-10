import json
from pathlib import Path

from app.schemas.schedule import InterviewSlot


class CalendarLoader:

    def load(self, path: str) -> list[InterviewSlot]:

        calendar_path = Path(path)

        if not calendar_path.exists():
            raise FileNotFoundError(
                f"Calendar not found: {path}"
            )

        with open(
            calendar_path,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return [
            InterviewSlot.model_validate(slot)
            for slot in data["slots"]
        ]