from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

from app.database.models import RecommendationModel, RecruiterReviewModel


class RecommendationRepository:
    def __init__(self, db: Session):
        self.db = db

    def save_recommendation(
        self,
        candidate_id: str,
        resume_score: Optional[float] = None,
        interview_score: Optional[float] = None,
        final_score: Optional[float] = None,
        strengths: Optional[list] = None,
        gaps: Optional[list] = None,
        evidence: Optional[list] = None,
        status: str = "completed",
        job_id: Optional[str] = None,
    ) -> RecommendationModel:
        existing = (
            self.db.query(RecommendationModel)
            .filter(RecommendationModel.candidate_id == candidate_id)
            .first()
        )
        if existing:
            existing.resume_score = resume_score
            existing.interview_score = interview_score
            existing.final_score = final_score
            existing.strengths = strengths or []
            existing.gaps = gaps or []
            existing.evidence = evidence or []
            existing.status = status
            if job_id:
                existing.job_id = job_id
            self.db.commit()
            self.db.refresh(existing)
            return existing

        rec = RecommendationModel(
            candidate_id=candidate_id,
            job_id=job_id,
            resume_score=resume_score,
            interview_score=interview_score,
            final_score=final_score,
            strengths=strengths or [],
            gaps=gaps or [],
            evidence=evidence or [],
            status=status,
        )
        self.db.add(rec)
        self.db.commit()
        self.db.refresh(rec)
        return rec

    def get_recommendation(self, candidate_id: str) -> Optional[RecommendationModel]:
        return (
            self.db.query(RecommendationModel)
            .filter(RecommendationModel.candidate_id == candidate_id)
            .order_by(RecommendationModel.created_at.desc())
            .first()
        )

    def save_review(
        self,
        candidate_id: str,
        reviewer_id: str,
        decision: str,
        status: str = "completed",
        notes: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> RecruiterReviewModel:
        review = RecruiterReviewModel(
            candidate_id=candidate_id,
            job_id=job_id,
            reviewer_id=reviewer_id,
            decision=decision,
            status=status,
            notes=notes,
            reviewed_at=datetime.now(timezone.utc),
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def get_review(self, candidate_id: str) -> Optional[RecruiterReviewModel]:
        return (
            self.db.query(RecruiterReviewModel)
            .filter(RecruiterReviewModel.candidate_id == candidate_id)
            .order_by(RecruiterReviewModel.reviewed_at.desc())
            .first()
        )
