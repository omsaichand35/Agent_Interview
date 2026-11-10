from pydantic import BaseModel, Field
from typing import List


class Competency(BaseModel):
    id: str
    name: str
    description: str
    weight: float = Field(default=1.0, ge=0.0)


class JobDescription(BaseModel):
    job_id: str
    title: str
    description: str
    competencies: List[Competency]