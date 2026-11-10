import os
from pathlib import Path
from typing import Optional

from app.stages.stage2_scheduling.calendar_loader import (
    CalendarLoader,
)
from app.stages.stage2_scheduling.slot_manager import (
    SlotManager,
)
from app.stages.stage2_scheduling.scheduler import (
    Scheduler,
)
from app.stages.stage2_scheduling.confirmation import (
    ConfirmationGenerator,
)


class SchedulingService:

    def __init__(
        self,
        calendar_path: Optional[str] = None,
        confirmation_dir: Optional[str] = None,
    ):
        calendar_path = calendar_path or os.environ.get("INTERVIEW_CALENDAR_PATH")

        if confirmation_dir is None:
            candidate_dirs = [
                Path("data/outputs/confirmations"),
                Path("../data/outputs/confirmations"),
                Path(__file__).resolve().parents[4]
                / "data"
                / "outputs"
                / "confirmations",
            ]
            for cd in candidate_dirs:
                if cd.parent.exists():
                    confirmation_dir = str(cd)
                    break
            if confirmation_dir is None:
                confirmation_dir = str(candidate_dirs[0])

        self.calendar_path = str(calendar_path) if calendar_path else None
        self.confirmation_dir = str(confirmation_dir)
        self.loader = CalendarLoader()
        self.confirmation_generator = ConfirmationGenerator()

    def schedule(
        self,
        shortlist,
        calendar_path: Optional[str] = None,
        confirmation_dir: Optional[str] = None,
    ):

        cal_path = calendar_path or self.calendar_path
        if not cal_path:
            raise FileNotFoundError(
                "No interview calendar is configured. Set INTERVIEW_CALENDAR_PATH "
                "or pass calendar_path explicitly."
            )
        conf_dir = confirmation_dir or self.confirmation_dir

        return self.schedule_candidates(
            shortlist=shortlist,
            calendar_path=cal_path,
            confirmation_dir=conf_dir,
        )

    def schedule_candidates(
        self,
        shortlist,
        calendar_path: str,
        confirmation_dir: str,
    ):

        slots = self.loader.load(
            calendar_path
        )

        slot_manager = SlotManager(
            slots
        )

        scheduler = Scheduler(
            slot_manager
        )

        schedules = scheduler.schedule(
            shortlist
        )

        confirmations = []

        for schedule in schedules:

            confirmation_path = (
                self.confirmation_generator.generate(
                    schedule,
                    confirmation_dir,
                )
            )

            confirmations.append(
                confirmation_path
            )

        return {
            "schedules": schedules,
            "confirmations": confirmations,
        }
