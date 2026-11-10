from app.schemas.schedule import Schedule
from app.schemas.resume import ResumeScore


class Scheduler:

    def __init__(self, slot_manager):
        self.slot_manager = slot_manager

    def schedule(
        self,
        candidates: list[ResumeScore],
    ) -> list[Schedule]:

        schedules = []

        available_slots = (
            self.slot_manager.get_available_slots()
        )

        if len(available_slots) < len(candidates):
            raise RuntimeError(
                "Not enough available interview slots."
            )

        for candidate, slot in zip(
            candidates,
            available_slots,
        ):

            reserved_slot = (
                self.slot_manager.reserve(
                    slot.slot_id
                )
            )

            cid = getattr(candidate, "candidate_id", None)
            if cid is None and isinstance(candidate, dict):
                cid = candidate.get("candidate_id")
            if cid is None:
                cid = str(candidate)

            schedules.append(
                Schedule(
                    candidate_id=cid,
                    slot_id=reserved_slot.slot_id,
                    start_time=reserved_slot.start_time,
                    end_time=reserved_slot.end_time,
                    status="scheduled",
                )
            )

        return schedules