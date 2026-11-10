from pydantic import BaseModel, Field
from typing import List


class Evidence(BaseModel):
    text: str
    source: str
    relevance: float = Field(default=0.0, ge=0.0, le=1.0)


class CompetencyAssessment(BaseModel):
    competency: str
    score: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence] = []
    reasoning: str


class ResumeScore(BaseModel):
    candidate_id: str
    overall_score: float = Field(ge=0.0, le=100.0)
    competency_scores: List[CompetencyAssessment]
    strengths: List[str] = []
    gaps: List[str] = []

class LLMEvidence(BaseModel):
    quote: str
    relevance: float = Field(ge=0.0, le=1.0)


class LLMCompetencyAssessment(BaseModel):
    competency_id: str
    competency_name: str
    score: float = Field(ge=0.0, le=1.0)
    evidence: List[LLMEvidence] = Field(default_factory=list)
    reasoning: str


class LLMResumeAnalysis(BaseModel):
    candidate_name: str
    candidate_email: str
    assessments: List[LLMCompetencyAssessment]
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)

