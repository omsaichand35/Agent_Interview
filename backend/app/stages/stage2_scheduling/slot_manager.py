from app.schemas.schedule import InterviewSlot


class SlotManager:

    def __init__(self, slots: list[InterviewSlot]):
        self.slots = {
            slot.slot_id: slot
            for slot in slots
        }

    def get_available_slots(self) -> list[InterviewSlot]:

        return [
            slot
            for slot in self.slots.values()
            if slot.available
        ]

    def reserve(self, slot_id: str) -> InterviewSlot:

        if slot_id not in self.slots:
            raise ValueError(
                f"Unknown slot: {slot_id}"
            )

        slot = self.slots[slot_id]

        if not slot.available:
            raise ValueError(
                f"Slot {slot_id} is already booked."
            )

        slot.available = False

        return slot