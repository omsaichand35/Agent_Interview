from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime, timezone


class InterviewTurn(BaseModel):
    turn_id: int

    question: str

    answer: Optional[str] = None

    trigger_phrase: Optional[str] = None

    extracted_signals: List[str] = []

    reasoning: Optional[str] = None

    decision: Optional[str] = None

    competency: Optional[str] = None

    next_question: Optional[str] = None

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class InterviewSession(BaseModel):
    session_id: str
    candidate_id: str

    status: str = "created"

    current_competency: Optional[str] = None

    explored_competencies: List[str] = []

    discovered_competencies: List[str] = []

    turns: List[InterviewTurn] = []

    competency_scores: Dict[str, float] = {}

    final_score: Optional[float] = None

class InterviewReasoning(BaseModel):
    trigger_phrase: Optional[str] = None
    extracted_signals: List[str] = Field(
        default_factory=list
    )

    decision: str

    target_competency: Optional[str] = None

    rationale: str

    question_intent: str

    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )

class InterviewEvidenceEvaluation(BaseModel):
    competency: str
    score: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    technical_depth: float = Field(ge=0.0, le=1.0)
    specificity: float = Field(ge=0.0, le=1.0)
    reasoning_quality: float = Field(default=0.8, ge=0.0, le=1.0)
    reasoning: str
    evidence_quote: str


class InterviewResult(BaseModel):
    session_id: str
    candidate_id: str
    status: str
    identity_verified: bool
    interview_score: Optional[float] = None
    competency_scores: Dict[str, float] = {}
    strengths: List[str] = []
    gaps: List[str] = []
    turn_count: int = 0

    def __getitem__(self, item):
        return getattr(self, item)

    def get(self, item, default=None):
        return getattr(self, item, default)



class InterviewStartRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    candidate_id: Optional[str] = None
    application_id: Optional[str] = None
    candidate: Dict = Field(default_factory=dict)
    competencies: List[str] = Field(default_factory=list)
    first_question: Optional[str] = None


class InterviewTextAnswerRequest(BaseModel):
    answer: str = Field(min_length=1)


class InterviewResponse(BaseModel):
    session_id: str
    candidate_id: str
    transcript: Optional[str] = None
    next_question: Optional[str] = None
    decision: Optional[str] = None
    competency_scores: Dict[str, float] = {}
    interview_score: float = 0.0
    interview_complete: bool = False
    identity_verified: bool = True


class InterviewStartResponse(BaseModel):
    session_id: str
    question: str
    audio: Optional[str] = None


class InterviewAnswerResponse(BaseModel):
    transcript: str
    decision: Optional[str] = None
    competency: Optional[str] = None
    next_question: Optional[str] = None
    interview_score: Optional[float] = None


class InterviewFinishResponse(BaseModel):
    status: str
    interview_score: Optional[float] = None
    competency_scores: Dict[str, float] = {}
