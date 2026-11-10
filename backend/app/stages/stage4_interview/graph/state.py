from typing import Dict, List, Optional, TypedDict


class InterviewState(TypedDict):
    session_id: str
    candidate_id: str
    candidate: Dict

    target_competencies: List[str]
    current_competency: Optional[str]
    coverage_phase: Optional[str]
    answered_competency: Optional[str]
    answered_coverage_phase: Optional[str]

    explored_competencies: List[str]
    discovered_competencies: List[str]

    conversation_history: List[Dict]

    current_question: Optional[str]
    candidate_answer: Optional[str]

    trigger_phrase: Optional[str]
    extracted_signals: List[str]

    reasoning: Optional[str]
    reasoning_confidence: float

    decision: Optional[str]
    next_question: Optional[str]

    evidence: Dict
    evaluation: Optional[Dict]
    competency_scores: Dict[str, float]

    identity_verified: bool
    identity_status: Optional[str]
    identity_failure_reason: str | None
    last_identity_confidence: float | None
    identity_check_count: int
    identity_checks: list
    _identity_checkpoint_passed_for_turn: bool

    gaze_warning_count: int
    gaze_flagged: bool
    gaze_events: list

    current_live_frame: Optional[str]

    turn_number: int
    interview_complete: bool
    workflow_condition: Optional[str]

    bad_answer_count: int
    recovery_attempted: bool