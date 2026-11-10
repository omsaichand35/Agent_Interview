from typing import List, Optional
from sqlalchemy.orm import Session

from app.database.models import JobModel


class JobRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, job_id: str) -> Optional[JobModel]:
        return self.db.query(JobModel).filter(JobModel.id == job_id).first()

    def list_all(self) -> List[JobModel]:
        return self.db.query(JobModel).all()

    def create(
        self,
        job_id: str,
        title: str,
        department: str = "Engineering",
        description: Optional[str] = None,
        required_skills: Optional[list] = None,
        status: str = "OPEN",
    ) -> JobModel:
        job = JobModel(
            id=job_id,
            title=title,
            department=department,
            description=description,
            required_skills=required_skills or [],
            status=status,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def create_or_update(
        self,
        job_id: str,
        title: Optional[str] = None,
        department: Optional[str] = None,
        description: Optional[str] = None,
        required_skills: Optional[list] = None,
        status: Optional[str] = None,
    ) -> JobModel:
        job = self.get_by_id(job_id)
        if job is None:
            return self.create(
                job_id=job_id,
                title=title or f"Job {job_id}",
                department=department or "Engineering",
                description=description,
                required_skills=required_skills,
                status=status or "OPEN",
            )
        if title is not None:
            job.title = title
        if department is not None:
            job.department = department
        if description is not None:
            job.description = description
        if required_skills is not None:
            job.required_skills = required_skills
        if status is not None:
            job.status = status
        self.db.commit()
        self.db.refresh(job)
        return job
