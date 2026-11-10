from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class IdentityCheck(BaseModel):
    timestamp: datetime
    check_type: str

    face_detected: bool
    face_count: int

    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    result: str  # "pass", "fail", "review"
    reason: Optional[str] = None
    reason_code: Optional[str] = None  # e.g. NO_FACE, MULTIPLE_FACES, LOW_CONFIDENCE, etc.
    liveness_status: str = "not_implemented"


class IdentityResult(BaseModel):
    candidate_id: str
    session_id: str

    verified: bool
    confidence: Optional[float] = None

    # F4.1 & F4.7: Separation of face detection, face matching, liveness, and decision
    face_detected: bool = True
    face_match_score: Optional[float] = None
    liveness_status: str = "not_implemented"
    # Do not imply a pass when `verified` is false or omitted.
    identity_status: Optional[str] = None  # "passed", "review", "failed", "pending"

    # F4.6: Suspicious conditions
    reason_code: Optional[str] = None

    # F4.9: Model provenance and threshold configuration
    matcher: str = "sface"
    face_detector: str = "yunet"
    model_version: str = "2021dec"
    threshold_version: str = "v1"
    threshold: float = 0.70
    review_threshold: float = 0.50

    checks: List[IdentityCheck] = []
    failure_reason: Optional[str] = None
