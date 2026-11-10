from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.database.models import (
    IdentityCheckModel,
    InterviewSessionModel,
    InterviewTurnModel,
)


class InterviewRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_session(self, session_id: str) -> Optional[InterviewSessionModel]:
        return self.db.query(InterviewSessionModel).filter(
            InterviewSessionModel.id == session_id
        ).first()

    def get_by_candidate(self, candidate_id: str) -> Optional[InterviewSessionModel]:
        return self.db.query(InterviewSessionModel).filter(
            InterviewSessionModel.candidate_id == candidate_id
        ).order_by(InterviewSessionModel.started_at.desc()).first()

    def create_session(
        self,
        session_id: str,
        candidate_id: str,
        job_id: Optional[str] = None,
        status: str = "pending",
        identity_verified: bool = False,
        identity_status: str = "pending",
        current_question: Optional[str] = None,
        competency_scores: Optional[dict] = None,
    ) -> InterviewSessionModel:
        session = InterviewSessionModel(
            id=session_id,
            candidate_id=candidate_id,
            job_id=job_id,
            status=status,
            identity_verified=identity_verified,
            identity_status=identity_status,
            current_question=current_question,
            competency_scores=competency_scores or {},
            conversation_history=[],
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_session(
        self,
        session_id: str,
        **kwargs,
    ) -> Optional[InterviewSessionModel]:
        session = self.get_session(session_id)
        if not session:
            return None
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)
        self.db.commit()
        self.db.refresh(session)
        return session

    def record_turn(
        self,
        session_id: str,
        turn_number: int,
        question: str,
        answer: Optional[str] = None,
        audio_path: Optional[str] = None,
        scores: Optional[dict] = None,
    ) -> InterviewTurnModel:
        turn = InterviewTurnModel(
            session_id=session_id,
            turn_number=turn_number,
            question=question,
            answer=answer,
            audio_path=audio_path,
            scores=scores or {},
        )
        self.db.add(turn)
        session = self.get_session(session_id)
        if session:
            session.turn_count = max(session.turn_count or 0, turn_number)
            history = list(session.conversation_history or [])
            history.append({
                "turn_number": turn_number,
                "question": question,
                "answer": answer,
                "audio_path": audio_path,
            })
            session.conversation_history = history
        self.db.commit()
        self.db.refresh(turn)
        return turn

    def record_identity_check(
        self,
        candidate_id: str,
        verified: bool,
        confidence: Optional[float] = None,
        failure_reason: Optional[str] = None,
        live_frame_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> IdentityCheckModel:
        check = IdentityCheckModel(
            candidate_id=candidate_id,
            session_id=session_id,
            verified=verified,
            confidence=confidence,
            failure_reason=failure_reason,
            live_frame_path=live_frame_path,
        )
        self.db.add(check)
        if session_id:
            session = self.get_session(session_id)
            if session:
                session.identity_verified = verified
                session.identity_status = "verified" if verified else "failed"
                session.identity_failure_reason = failure_reason
        self.db.commit()
        self.db.refresh(check)
        return check
