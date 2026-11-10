from pydantic import BaseModel
from datetime import datetime


class InterviewSlot(BaseModel):
    slot_id: str
    start_time: datetime
    end_time: datetime
    available: bool = True


class Schedule(BaseModel):
    candidate_id: str
    slot_id: str
    start_time: datetime
    end_time: datetime
    status: str = "scheduled"

    def __getitem__(self, item):
        return getattr(self, item)