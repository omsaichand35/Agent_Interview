from pydantic import BaseModel
from typing import List, Optional


class Experience(BaseModel):
    company: str
    role: str
    years: float = 0.0
    description: Optional[str] = None


class Education(BaseModel):
    institution: str
    degree: str
    field: Optional[str] = None
    year: Optional[int] = None


class Candidate(BaseModel):
    candidate_id: str
    name: str
    email: str

    resume_path: Optional[str] = None
    photo_path: Optional[str] = None

    skills: List[str] = []
    experience: List[Experience] = []
    education: List[Education] = []

    resume_score: Optional[float] = None
    interview_score: Optional[float] = None
    final_score: Optional[float] = None