from pydantic import BaseModel, Field
from typing import List


class FinalRecommendation(BaseModel):
    candidate_id: str

    resume_score: float = Field(
        ge=0.0,
        le=100.0
    )

    interview_score: float = Field(
        ge=0.0,
        le=100.0
    )

    final_score: float = Field(
        ge=0.0,
        le=100.0
    )

    strengths: List[str] = []

    gaps: List[str] = []

    evidence: List[str] = []

    identity_verified: bool

    status: str