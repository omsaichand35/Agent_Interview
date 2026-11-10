"""Academic program definitions and publication endpoints."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_user, require_roles
from app.database.connection import get_db
from app.database.models import JobModel, ProgramRecruiterAccessModel
from app.models.user import Role, UserResponse


router = APIRouter(prefix="/programs", tags=["Academic programs"])


class ProgramCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    department: str = Field(min_length=2, max_length=128)
    description: str = Field(min_length=30, max_length=20000)
    criteria: List[str] = Field(min_length=1, max_length=20)


def program_payload(program: JobModel) -> dict:
    return {
        "id": program.id,
        "title": program.title,
        "department": program.department,
        "description": program.description or "",
        "criteria": program.required_skills or [],
        "status": program.status,
        "created_at": program.created_at.isoformat() if program.created_at else None,
    }


def require_program_access(db: Session, program_id: str, current_user: UserResponse):
    if current_user.role == Role.ADMIN.value:
        return
    access = db.query(ProgramRecruiterAccessModel.id).filter(
        ProgramRecruiterAccessModel.program_id == program_id,
        ProgramRecruiterAccessModel.recruiter_id == current_user.id,
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="This opportunity is not assigned to your recruiter workspace.")


@router.get("")
def list_programs(db: Session = Depends(get_db)):
    """Public catalogue of open programs available to applicants."""
    programs = db.query(JobModel).filter(JobModel.status == "OPEN").order_by(JobModel.created_at.desc()).all()
    return [program_payload(program) for program in programs]


@router.get("/manage")
def list_programs_for_recruiter(
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """List owned programs plus legacy programs no recruiter has claimed yet."""
    if current_user.role == Role.ADMIN.value:
        programs = db.query(JobModel).order_by(JobModel.created_at.desc()).all()
        return [{**program_payload(program), "can_manage": True, "can_claim": False} for program in programs]
    owned_rows = db.query(ProgramRecruiterAccessModel.program_id).filter(
        ProgramRecruiterAccessModel.recruiter_id == current_user.id
    ).all()
    owned_ids = [row[0] for row in owned_rows]
    all_assigned = db.query(ProgramRecruiterAccessModel.program_id)
    programs = db.query(JobModel).filter(
        or_(JobModel.id.in_(owned_ids), ~JobModel.id.in_(all_assigned))
    ).order_by(JobModel.created_at.desc()).all()
    owned = set(owned_ids)
    return [{
        **program_payload(program),
        "can_manage": program.id in owned,
        "can_claim": program.id not in owned,
    } for program in programs]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_program(
    request: ProgramCreateRequest,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    criteria = list(dict.fromkeys(item.strip() for item in request.criteria if item.strip()))
    if not criteria:
        raise HTTPException(status_code=422, detail="At least one non-empty evaluation criterion is required.")
    program = JobModel(
        id=f"PRG_{uuid.uuid4().hex[:10].upper()}",
        title=request.title.strip(),
        department=request.department.strip(),
        description=request.description.strip(),
        required_skills=criteria,
        status="OPEN",
    )
    db.add(program)
    db.flush()
    if current_user.role == Role.RECRUITER.value:
        db.add(ProgramRecruiterAccessModel(program_id=program.id, recruiter_id=current_user.id))
    db.commit()
    db.refresh(program)
    return program_payload(program)


@router.post("/{program_id}/claim")
def claim_program(
    program_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value)),
    db: Session = Depends(get_db),
):
    program = db.query(JobModel).filter(JobModel.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Opportunity not found.")
    existing = db.query(ProgramRecruiterAccessModel).filter(
        ProgramRecruiterAccessModel.program_id == program_id
    ).first()
    if existing:
        if existing.recruiter_id == current_user.id:
            return {"id": program_id, "claimed": True, "message": "You already manage this opportunity."}
        raise HTTPException(status_code=409, detail="Another recruiter already manages this opportunity.")
    db.add(ProgramRecruiterAccessModel(program_id=program_id, recruiter_id=current_user.id))
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another recruiter claimed this opportunity first.") from exc
    return {"id": program_id, "claimed": True, "message": "Opportunity and its application history are now assigned to your workspace."}


@router.get("/{program_id}")
def get_program(program_id: str, db: Session = Depends(get_db)):
    program = db.query(JobModel).filter(JobModel.id == program_id).first()
    if not program or program.status != "OPEN":
        raise HTTPException(status_code=404, detail="Program not found or closed.")
    return program_payload(program)


@router.delete("/{program_id}")
def delete_or_close_program(
    program_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Delete an unused job, or close it while retaining its application history."""
    program = db.query(JobModel).filter(JobModel.id == program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Job not found.")
    require_program_access(db, program_id, current_user)

    from app.database.models import ApplicationModel, CandidateModel, InterviewSessionModel
    has_applications = db.query(ApplicationModel.id).filter(
        ApplicationModel.program_id == program_id
    ).first() is not None
    has_legacy_candidates = db.query(CandidateModel.id).filter(
        CandidateModel.job_id == program_id
    ).first() is not None
    has_interviews = db.query(InterviewSessionModel.id).filter(
        InterviewSessionModel.job_id == program_id
    ).first() is not None

    if has_applications or has_legacy_candidates or has_interviews:
        program.status = "CLOSED"
        db.commit()
        return {"id": program_id, "status": "CLOSED", "deleted": False,
                "message": "Job closed. Existing applications and interview history were retained."}

    db.query(ProgramRecruiterAccessModel).filter(
        ProgramRecruiterAccessModel.program_id == program_id
    ).delete(synchronize_session=False)
    db.delete(program)
    db.commit()
    return {"id": program_id, "status": "DELETED", "deleted": True,
            "message": "Empty job deleted."}
