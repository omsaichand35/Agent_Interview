from typing import List, Optional
from sqlalchemy.orm import Session

from app.database.models import CandidateModel, ResumeModel


class CandidateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, candidate_id: str) -> Optional[CandidateModel]:
        return self.db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()

    def list_all(self, job_id: Optional[str] = None) -> List[CandidateModel]:
        query = self.db.query(CandidateModel)
        if job_id:
            query = query.filter(CandidateModel.job_id == job_id)
        return query.all()

    def create(
        self,
        candidate_id: str,
        name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        photo_path: Optional[str] = None,
        job_id: Optional[str] = None,
        resume_score: Optional[float] = None,
        status: str = "APPLIED",
    ) -> CandidateModel:
        candidate = CandidateModel(
            id=candidate_id,
            name=name,
            email=email,
            phone=phone,
            photo_path=photo_path,
            job_id=job_id,
            resume_score=resume_score,
            status=status,
        )
        self.db.add(candidate)
        self.db.commit()
        self.db.refresh(candidate)
        return candidate

    def create_or_update(
        self,
        candidate_id: str,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        photo_path: Optional[str] = None,
        job_id: Optional[str] = None,
        resume_score: Optional[float] = None,
        status: Optional[str] = None,
    ) -> CandidateModel:
        cand = self.get_by_id(candidate_id)
        if cand is None:
            return self.create(
                candidate_id=candidate_id,
                name=name or f"Candidate {candidate_id}",
                email=email,
                phone=phone,
                photo_path=photo_path,
                job_id=job_id,
                resume_score=resume_score,
                status=status or "APPLIED",
            )
        if name is not None:
            cand.name = name
        if email is not None:
            cand.email = email
        if phone is not None:
            cand.phone = phone
        if photo_path is not None:
            cand.photo_path = photo_path
        if job_id is not None:
            cand.job_id = job_id
        if resume_score is not None:
            cand.resume_score = resume_score
        if status is not None:
            cand.status = status
        self.db.commit()
        self.db.refresh(cand)
        return cand

    def save_resume(
        self,
        candidate_id: str,
        raw_text: Optional[str] = None,
        parsed_skills: Optional[list] = None,
        experience_years: Optional[float] = None,
        score: Optional[float] = None,
        analysis: Optional[dict] = None,
        file_path: Optional[str] = None,
    ) -> ResumeModel:
        resume = ResumeModel(
            candidate_id=candidate_id,
            raw_text=raw_text,
            parsed_skills=parsed_skills or [],
            experience_years=experience_years,
            score=score,
            analysis=analysis or {},
            file_path=file_path,
        )
        self.db.add(resume)
        self.db.commit()
        self.db.refresh(resume)
        return resume
