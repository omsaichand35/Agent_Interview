"""Student applications: private resume/face enrollment and program scoring."""
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
import secrets
import uuid
from urllib.parse import urlencode
from typing import Literal
from pathlib import Path

import cv2
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_user, require_roles
from app.config import refresh_smtp_settings, settings
from app.core.upload_validators import validate_image_upload
from app.core.file_validation import validate_resume
from app.database.connection import SessionLocal, get_db
from app.database.models import ApplicationModel, CandidateModel, IdentityCheckModel, InterviewInviteModel, InterviewScheduleModel, InterviewSessionModel, JobModel, ProgramRecruiterAccessModel, ResumeModel, UserModel
from app.models.user import Role, UserResponse
from app.schemas.candidate import Candidate
from app.schemas.job import Competency
from app.schemas.job import JobDescription
from app.security.storage_manager import StorageManager
from app.core.paths import get_project_root, resolve_path
from app.stages.stage1_resume.extractor import ResumeExtractor
from app.stages.stage1_resume.parser import ResumeParser
from app.stages.stage1_resume.competency_matcher import CompetencyMatcher
from app.stages.stage1_resume.scorer import ResumeScorer
from app.stages.stage1_resume.llm_analyzer import LLMResumeAnalyzer
from app.stages.stage1_resume.llm_score_adapter import LLMScoreAdapter
from app.llm.provider import get_llm_client
from app.security.rate_limiter import rate_limit


router = APIRouter(prefix="/applications", tags=["Program applications"])
BIOMETRIC_CONSENT_VERSION = "admissions-face-consent-v1"
logger = logging.getLogger(__name__)


class InterviewCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class BulkInterviewInviteRequest(BaseModel):
    program_id: str = Field(min_length=1, max_length=64)
    selection: Literal["top_n", "min_score"]
    top_n: int | None = Field(default=None, ge=1, le=500)
    min_score: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selection == "top_n" and self.top_n is None:
            raise ValueError("top_n is required for top_n selection")
        if self.selection == "min_score" and self.min_score is None:
            raise ValueError("min_score is required for min_score selection")
        return self


def _score_payload(application: ApplicationModel) -> dict:
    return {
        "application_id": application.id,
        "program_id": application.program_id,
        "candidate_id": application.candidate_id,
        "candidate_name": application.candidate.name if application.candidate else None,
        "candidate_email": application.candidate.email if application.candidate else None,
        "status": application.status,
        "resume_score": application.resume_score,
        "interview_score": application.interview_score,
        "score_details": application.score_details or {},
        "identity_status": application.identity_status,
        "compatibility": application.resume_score,
        "scoring_method": (application.score_details or {}).get("scoring_method", "keyword_evidence"),
        "created_at": application.created_at.isoformat() if application.created_at else None,
        "interview_url": None if application.status == "interview_completed" else f"/interview-ui?application_id={application.id}",
    }


def _candidate_payload(application: ApplicationModel) -> dict:
    """Student-safe application fields; scoring and interview marks stay private."""
    resume_path = Path(application.resume.file_path) if application.resume and application.resume.file_path else None
    def utc_iso(value):
        if not value:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    return {
        "application_id": application.id,
        "program_id": application.program_id,
        "candidate_name": application.candidate.name if application.candidate else None,
        "program_title": application.program.title if application.program else None,
        "department": application.program.department if application.program else None,
        "description": application.program.description if application.program else None,
        "criteria": application.program.required_skills or [] if application.program else [],
        "resume_filename": (application.resume.original_filename if application.resume else None) or (resume_path.name if resume_path else None),
        "status": "submitted" if application.status in {"scoring", "resume_scored", "scoring_failed"} else application.status,
        "identity_status": application.identity_status,
        "biometric_consent_at": utc_iso(application.biometric_consent_at),
        "biometric_consent_version": application.biometric_consent_version,
        "created_at": utc_iso(application.created_at),
        "interview_url": None if application.status == "interview_completed" else f"/interview-ui?application_id={application.id}",
    }


def _score_application_in_background(application_id: str) -> None:
    """Parse and score a submitted resume without tying work to the student's browser."""
    db = SessionLocal()
    try:
        application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
        if not application or application.status != "scoring":
            return
        candidate = db.query(CandidateModel).filter(CandidateModel.id == application.candidate_id).first()
        resume_record = db.query(ResumeModel).filter(ResumeModel.id == application.resume_id).first()
        program = db.query(JobModel).filter(JobModel.id == application.program_id).first()
        if not candidate or not resume_record or not program or not resume_record.file_path:
            raise ValueError("Application scoring data is incomplete")

        resume_text = ResumeParser().parse(resume_record.file_path)
        if not resume_text.strip():
            raise ValueError("No readable text was found in the resume PDF")
        criteria = [str(item).strip() for item in (program.required_skills or []) if str(item).strip()]
        if not criteria:
            raise ValueError("Program evaluation criteria are not configured")
        competencies = [
            Competency(
                id=re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_") or f"criterion_{index}",
                name=item,
                description=item,
                weight=1.0 / len(criteria),
            )
            for index, item in enumerate(criteria, start=1)
        ]
        extracted = ResumeExtractor().extract(candidate_id=candidate.id, text=resume_text)
        scoring_candidate = Candidate(candidate_id=candidate.id, name=candidate.name, email=candidate.email, skills=extracted.skills)
        job_description = JobDescription(job_id=program.id, title=program.title, description=program.description or "", competencies=competencies)
        scoring_method = "keyword_evidence"
        try:
            analysis = LLMResumeAnalyzer(get_llm_client()).analyze(resume_text=resume_text, job=job_description)
            resume_score = LLMScoreAdapter.convert(analysis=analysis, candidate_id=candidate.id, competencies=competencies)
            scoring_method = "ai_evidence"
        except Exception:
            assessments = CompetencyMatcher().match(candidate=scoring_candidate, resume_text=resume_text, competencies=competencies)
            resume_score = ResumeScorer().score(candidate_id=candidate.id, assessments=assessments, competencies=competencies)

        score_details = resume_score.model_dump(mode="json")
        score_details["scoring_method"] = scoring_method
        score_details["extracted_keywords"] = extracted.skills
        resume_record.raw_text = resume_text
        resume_record.parsed_skills = extracted.skills
        resume_record.score = resume_score.overall_score
        resume_record.analysis = score_details
        candidate.resume_score = resume_score.overall_score
        application.resume_score = resume_score.overall_score
        application.score_details = score_details
        # Scoring is internal processing; once it finishes, the application is
        # submitted and ready for recruiter verification.
        application.status = "submitted"
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Background resume scoring failed for application %s", application_id)
        failed = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
        if failed and failed.status == "scoring":
            failed.status = "scoring_failed"
            db.commit()
    finally:
        db.close()


def _candidate_application_access(application: ApplicationModel, user: UserResponse):
    if user.role == Role.CANDIDATE.value and application.candidate_id != user.candidate_id:
        raise HTTPException(status_code=403, detail="You can only access your own applications.")


def _recruiter_application_access(application: ApplicationModel, user: UserResponse, db: Session):
    if user.role == Role.ADMIN.value:
        return
    access = db.query(ProgramRecruiterAccessModel.id).filter(
        ProgramRecruiterAccessModel.program_id == application.program_id,
        ProgramRecruiterAccessModel.recruiter_id == user.id,
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="This application belongs to another recruiter workspace.")


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_application(
    background_tasks: BackgroundTasks,
    program_id: str = Form(...),
    full_name: str = Form(..., min_length=2, max_length=255),
    biometric_consent: bool = Form(...),
    resume: UploadFile = File(...),
    face_reference: UploadFile = File(...),
    current_user: UserResponse = Depends(require_roles(Role.CANDIDATE.value)),
    db: Session = Depends(get_db),
):
    """Apply to a program with one PDF resume and an explicitly consented face reference."""
    if biometric_consent is not True:
        raise HTTPException(status_code=422, detail="Consent to identity verification is required to submit this application.")

    program = db.query(JobModel).filter(JobModel.id == program_id, JobModel.status == "OPEN").first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found or closed.")
    if not any(str(item).strip() for item in (program.required_skills or [])):
        raise HTTPException(status_code=422, detail="This program has no evaluation criteria configured yet.")

    user_record = db.query(UserModel).filter(UserModel.id == current_user.id).first()
    if not user_record:
        raise HTTPException(status_code=401, detail="Candidate account not found.")

    candidate = None
    if current_user.candidate_id:
        candidate = db.query(CandidateModel).filter(CandidateModel.id == current_user.candidate_id).first()
    candidate_id = candidate.id if candidate else f"CAND_{uuid.uuid4().hex[:12].upper()}"
    existing_candidate_application = db.query(ApplicationModel).filter(
        ApplicationModel.candidate_id == candidate_id,
        ApplicationModel.program_id == program_id,
    ).first()
    if existing_candidate_application:
        raise HTTPException(status_code=409, detail="An application to this program already exists for this account.")

    resume_bytes = await resume.read()
    validated_resume = validate_resume(
        file_bytes=resume_bytes,
        filename=resume.filename,
        content_type=resume.content_type,
    )
    face_bytes = await face_reference.read()
    decoded_face = validate_image_upload(
        face_bytes,
        filename=face_reference.filename,
        content_type=face_reference.content_type,
    )
    success, encoded_face = cv2.imencode(".jpg", decoded_face)
    if not success:
        raise HTTPException(status_code=422, detail="Could not process the face reference image.")

    application_id = f"APP_{uuid.uuid4().hex[:12].upper()}"
    storage = StorageManager()
    # Keep every submission immutable, even when the candidate reuses a filename.
    resume_path = storage.get_resume_path(candidate_id, f"{application_id}.pdf")
    face_path = storage.get_identity_path(candidate_id, f"{application_id}_reference.jpg")

    try:
        resume_path.write_bytes(resume_bytes)
        face_path.write_bytes(encoded_face.tobytes())
        from app.api.dependencies import get_identity_service
        detected_faces = get_identity_service().checker.face_detector.detect(str(face_path))
        if len(detected_faces) != 1:
            raise HTTPException(status_code=422, detail="The face photo must show exactly one clearly visible face.")
        if candidate is None:
            candidate = CandidateModel(
                id=candidate_id,
                name=full_name.strip(),
                email=current_user.email,
                status="APPLIED",
            )
            db.add(candidate)
        else:
            candidate.name = full_name.strip()
            candidate.email = current_user.email
            candidate.status = "APPLIED"

        user_record.candidate_id = candidate_id
        resume_record = ResumeModel(
            candidate_id=candidate_id,
            file_path=str(resume_path),
            original_filename=validated_resume.sanitized_original_filename,
            raw_text=None,
            parsed_skills=[],
            score=None,
            analysis=None,
        )
        db.add(resume_record)
        db.flush()

        application = ApplicationModel(
            id=application_id,
            candidate_id=candidate_id,
            program_id=program_id,
            resume_id=resume_record.id,
            face_reference_path=str(face_path),
            biometric_consent_at=datetime.now(timezone.utc),
            biometric_consent_version=BIOMETRIC_CONSENT_VERSION,
            status="scoring",
            resume_score=None,
            score_details={},
            identity_status="pending",
        )
        db.add(application)
        db.commit()
        from app.services.email_service import send_application_received_email
        background_tasks.add_task(send_application_received_email, current_user.email, program.title)
        db.refresh(application)
        background_tasks.add_task(_score_application_in_background, application_id)
        return _candidate_payload(application)
    except HTTPException:
        db.rollback()
        resume_path.unlink(missing_ok=True)
        face_path.unlink(missing_ok=True)
        raise
    except IntegrityError as exc:
        db.rollback()
        resume_path.unlink(missing_ok=True)
        face_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="An application for this program already exists on this account. Refresh your application list.") from exc
    except Exception as exc:
        db.rollback()
        resume_path.unlink(missing_ok=True)
        face_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Application processing failed: {exc}") from exc


@router.get("")
def list_applications(
    program_id: str | None = None,
    response: Response = None,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    if response is not None:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    query = db.query(ApplicationModel)
    if current_user.role != Role.ADMIN.value:
        managed_programs = db.query(ProgramRecruiterAccessModel.program_id).filter(
            ProgramRecruiterAccessModel.recruiter_id == current_user.id
        )
        query = query.filter(ApplicationModel.program_id.in_(managed_programs))
    if program_id:
        query = query.filter(ApplicationModel.program_id == program_id)
    applications = query.order_by(
        ApplicationModel.resume_score.desc(), ApplicationModel.created_at.desc()
    ).all()
    results = []
    now = datetime.now(timezone.utc)
    for application in applications:
        # Recruiter/admin-only listing needs names, scores, and scoring status.
        # Student endpoints continue to use the score-free candidate payload.
        item = _score_payload(application)
        invite = db.query(InterviewInviteModel).filter(
            InterviewInviteModel.application_id == application.id,
            InterviewInviteModel.revoked_at.is_(None),
        ).order_by(InterviewInviteModel.created_at.desc()).first()
        expires_at = invite.expires_at if invite else None
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        item["invite_status"] = (
            "redeemed" if invite and invite.redeemed_at
            else "issued" if invite and expires_at > now
            else None
        )
        item["invite_expires_at"] = invite.expires_at.isoformat() if invite else None
        interview_query = db.query(InterviewSessionModel).filter(
            InterviewSessionModel.candidate_id == application.candidate_id,
            InterviewSessionModel.job_id == application.program_id,
        )
        if invite:
            interview_query = interview_query.filter(InterviewSessionModel.id == invite.session_id)
        interview_session = interview_query.order_by(InterviewSessionModel.started_at.desc()).first()
        item["gaze_warning_count"] = int(interview_session.gaze_warning_count or 0) if interview_session else 0
        item["gaze_flagged"] = bool(interview_session.gaze_flagged) if interview_session else False
        item["interview_turn_count"] = int(interview_session.turn_count or 0) if interview_session else 0
        item["interview_report_available"] = bool(interview_session and interview_session.conversation_history)
        results.append(item)
    return results


@router.post("/{application_id}/shortlist")
def shortlist_application(
    application_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    if application.status == "shortlisted":
        return _score_payload(application)
    if application.status not in {"resume_scored", "submitted"}:
        raise HTTPException(status_code=409, detail=f"Application cannot be shortlisted from status '{application.status}'.")
    application.status = "shortlisted"
    db.commit()
    db.refresh(application)
    return _score_payload(application)


@router.post("/bulk-interview-invites")
def bulk_interview_invites(
    payload: BulkInterviewInviteRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Invite the top applicants or everyone meeting a score threshold for one program."""
    refresh_smtp_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        raise HTTPException(
            status_code=503,
            detail="Email delivery is not configured. Set SMTP_HOST and SMTP_FROM_EMAIL before sending interview invitations.",
        )

    program = db.query(JobModel).filter(JobModel.id == payload.program_id).first()
    if not program:
        raise HTTPException(status_code=404, detail="Program not found.")
    if current_user.role != Role.ADMIN.value:
        access = db.query(ProgramRecruiterAccessModel.id).filter(
            ProgramRecruiterAccessModel.program_id == program.id,
            ProgramRecruiterAccessModel.recruiter_id == current_user.id,
        ).first()
        if not access:
            raise HTTPException(status_code=403, detail="This program belongs to another recruiter workspace.")

    query = db.query(ApplicationModel).filter(
        ApplicationModel.program_id == program.id,
        ApplicationModel.status.in_(["submitted", "resume_scored", "shortlisted"]),
        ApplicationModel.resume_score.is_not(None),
    )
    if payload.selection == "min_score":
        query = query.filter(ApplicationModel.resume_score >= payload.min_score)
    applications = query.order_by(
        ApplicationModel.resume_score.desc(),
        ApplicationModel.created_at.asc(),
        ApplicationModel.id.asc(),
    ).all()
    if not applications:
        return {"selected": 0, "emails_queued": 0, "skipped": 0, "message": "No scored applications match this threshold."}

    scheduled_application_ids = {
        row[0] for row in db.query(InterviewScheduleModel.application_id).filter(
            InterviewScheduleModel.application_id.in_([application.id for application in applications]),
            InterviewScheduleModel.status.in_(["scheduled", "joined"]),
        ).all()
    }
    applications = [application for application in applications if application.id not in scheduled_application_ids]

    invite_rows = db.query(InterviewInviteModel).filter(
        InterviewInviteModel.application_id.in_([application.id for application in applications]),
        InterviewInviteModel.revoked_at.is_(None),
    ).all()
    invites_by_application: dict[str, list[InterviewInviteModel]] = {}
    for invite in invite_rows:
        invites_by_application.setdefault(invite.application_id, []).append(invite)

    now = datetime.now(timezone.utc)
    eligible = []
    for application in applications:
        candidate = application.candidate
        if not candidate or not candidate.email:
            continue
        existing_invites = invites_by_application.get(application.id, [])
        if any(invite.redeemed_at is not None for invite in existing_invites):
            continue
        has_unexpired_invite = False
        for invite in existing_invites:
            expires_at = invite.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > now:
                has_unexpired_invite = True
            else:
                invite.revoked_at = now
        if not has_unexpired_invite:
            eligible.append(application)
    applications = eligible[:payload.top_n] if payload.selection == "top_n" else eligible

    if not applications:
        db.commit()
        return {"selected": 0, "emails_queued": 0, "skipped": 0, "message": "No new eligible students match this threshold."}

    from app.services.email_service import send_interview_invite_email

    queued = 0
    skipped = 0
    for application in applications:
        candidate = application.candidate
        code = secrets.token_hex(8).upper()
        expires_at = now + timedelta(days=7)
        invite = InterviewInviteModel(
            application_id=application.id,
            code_hash=hashlib.sha256(code.encode("ascii")).hexdigest(),
            session_id=f"INT_{uuid.uuid4().hex[:16].upper()}",
            created_by=current_user.id,
            expires_at=expires_at,
        )
        application.status = "shortlisted"
        db.add(invite)
        background_tasks.add_task(
            send_interview_invite_email,
            candidate.email,
            candidate.name or "student",
            program.title,
            code,
            expires_at.isoformat(),
        )
        queued += 1

    db.commit()
    return {
        "selected": len(applications),
        "emails_queued": queued,
        "skipped": skipped,
        "message": f"Queued interview invitation emails for {queued} student(s).",
    }


@router.post("/{application_id}/interview-invite")
def issue_interview_invite(
    application_id: str,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Shortlist an application and issue a one-time code for its interview."""
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    if db.query(InterviewScheduleModel.id).filter(
        InterviewScheduleModel.application_id == application.id,
        InterviewScheduleModel.status.in_(["scheduled", "joined"]),
    ).first():
        raise HTTPException(status_code=409, detail="This application already has an active interview schedule. Use the schedule roster to manage it.")
    if application.status not in {"resume_scored", "submitted", "shortlisted"}:
        raise HTTPException(status_code=409, detail=f"An interview code cannot be issued for status '{application.status}'.")

    invites = db.query(InterviewInviteModel).filter(
        InterviewInviteModel.application_id == application.id,
        InterviewInviteModel.revoked_at.is_(None),
    ).all()
    if any(invite.redeemed_at is not None for invite in invites):
        raise HTTPException(status_code=409, detail="This interview code has already been used. The interview is available in the student's portal.")

    now = datetime.now(timezone.utc)
    for invite in invites:
        invite.revoked_at = now

    code = secrets.token_hex(8).upper()
    session_id = f"INT_{uuid.uuid4().hex[:16].upper()}"
    invite = InterviewInviteModel(
        application_id=application.id,
        code_hash=hashlib.sha256(code.encode("ascii")).hexdigest(),
        session_id=session_id,
        created_by=current_user.id,
        expires_at=now + timedelta(days=7),
    )
    application.status = "shortlisted"
    db.add(invite)
    db.commit()
    db.refresh(invite)
    from app.services.email_service import send_interview_invite_email
    background_tasks.add_task(
        send_interview_invite_email,
        application.candidate.email if application.candidate else None,
        application.candidate.name if application.candidate else "student",
        application.program.title if application.program else "your program",
        code,
        invite.expires_at.isoformat(),
    )
    return {
        "application_id": application.id,
        "student_name": application.candidate.name if application.candidate else None,
        "student_email": application.candidate.email if application.candidate else None,
        "program_title": application.program.title if application.program else None,
        "code": code,
        "expires_at": invite.expires_at.isoformat(),
        "message": "Share this code with the student. It can be redeemed once and expires in 7 days.",
    }


@router.post(
    "/redeem-interview-code",
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60, key_prefix="interview_code"))],
)
def redeem_interview_code(
    payload: InterviewCodeRequest,
    current_user: UserResponse = Depends(require_roles(Role.CANDIDATE.value)),
    db: Session = Depends(get_db),
):
    if not current_user.candidate_id:
        raise HTTPException(status_code=403, detail="Your student account is not linked to an application.")
    code = payload.code.strip().upper()
    if not re.fullmatch(r"[0-9A-F]{16}", code):
        raise HTTPException(status_code=400, detail="Enter the 16-character interview code from your recruiter.")

    invite = db.query(InterviewInviteModel).filter(
        InterviewInviteModel.code_hash == hashlib.sha256(code.encode("ascii")).hexdigest(),
        InterviewInviteModel.revoked_at.is_(None),
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Interview code is invalid or no longer active.")
    now = datetime.now(timezone.utc)
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        invite.revoked_at = now
        db.commit()
        raise HTTPException(status_code=410, detail="Interview code has expired. Ask your recruiter for a new code.")
    if invite.redeemed_at is not None:
        raise HTTPException(status_code=409, detail="Interview code has already been used.")

    application = db.query(ApplicationModel).filter(ApplicationModel.id == invite.application_id).first()
    if not application or application.candidate_id != current_user.candidate_id:
        raise HTTPException(status_code=403, detail="This interview code was issued to a different student.")
    if application.status != "shortlisted":
        raise HTTPException(status_code=409, detail="This application is not currently approved for interview.")

    # Conditional update makes redemption single-use even if two requests race.
    redeemed = db.execute(
        update(InterviewInviteModel)
        .where(
            InterviewInviteModel.id == invite.id,
            InterviewInviteModel.redeemed_at.is_(None),
            InterviewInviteModel.revoked_at.is_(None),
        )
        .values(redeemed_at=now)
    )
    if redeemed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Interview code has already been used.")
    application.status = "interview_authorized"
    db.commit()
    query = urlencode({"application_id": application.id, "session_id": invite.session_id})
    scheduled = db.query(InterviewScheduleModel).filter(
        InterviewScheduleModel.application_id == application.id,
        InterviewScheduleModel.session_id == invite.session_id,
        InterviewScheduleModel.status.in_(["scheduled", "joined"]),
    ).first()
    return {
        "application_id": application.id,
        "program_title": application.program.title if application.program else None,
        "status": application.status,
        "scheduled_start": (
            scheduled.scheduled_start.replace(tzinfo=timezone.utc).isoformat()
            if scheduled and scheduled.scheduled_start.tzinfo is None
            else scheduled.scheduled_start.isoformat() if scheduled else None
        ),
        "interview_url": "/student" if scheduled else f"/interview-ui?{query}",
    }


@router.get("/mine")
def list_my_applications(
    current_user: UserResponse = Depends(require_roles(Role.CANDIDATE.value)),
    db: Session = Depends(get_db),
):
    if not current_user.candidate_id:
        return []
    applications = db.query(ApplicationModel).filter(
        ApplicationModel.candidate_id == current_user.candidate_id
    ).order_by(ApplicationModel.created_at.desc()).all()
    results = []
    from app.api.scheduling_routes import list_candidate_schedules
    schedules = list_candidate_schedules(current_user.candidate_id, db)
    for application in applications:
        # Students can see application progress, never resume/interview scores
        # or evaluator evidence. Recruiter routes use _score_payload instead.
        item = _candidate_payload(application)
        invite = db.query(InterviewInviteModel).filter(
            InterviewInviteModel.application_id == application.id,
            InterviewInviteModel.revoked_at.is_(None),
            InterviewInviteModel.redeemed_at.is_not(None),
        ).order_by(InterviewInviteModel.created_at.desc()).first()
        if invite and application.status != "interview_completed":
            item["interview_url"] = f"/interview-ui?{urlencode({'application_id': application.id, 'session_id': invite.session_id})}"
        else:
            item["interview_url"] = None
        item["schedule"] = None if application.status == "interview_completed" else schedules.get(application.id)
        results.append(item)
    return results


@router.get("/{application_id}/interview")
def get_application_interview(
    application_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Return recruiter-safe summary and transcript for an application's interview."""
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    session = db.query(InterviewSessionModel).filter(
        InterviewSessionModel.candidate_id == application.candidate_id,
        InterviewSessionModel.job_id == application.program_id,
    ).order_by(InterviewSessionModel.started_at.desc()).first()
    if not session:
        return {
            "application_id": application.id,
            "candidate_name": application.candidate.name if application.candidate else None,
            "program_title": application.program.title if application.program else None,
            "status": "not_started",
            "interview": None,
        }
    return {
        "application_id": application.id,
        "candidate_name": application.candidate.name if application.candidate else None,
        "candidate_email": application.candidate.email if application.candidate else None,
        "program_title": application.program.title if application.program else None,
        "status": session.status,
        "interview": {
            "session_id": session.id,
            "status": session.status,
            "identity_status": session.identity_status,
            "identity_verified": bool(session.identity_verified),
            "gaze_warning_count": int(session.gaze_warning_count or 0),
            "gaze_flagged": bool(session.gaze_flagged),
            "gaze_flagged_at": session.gaze_flagged_at.isoformat() if session.gaze_flagged_at else None,
            "gaze_events": session.gaze_events or [],
            "interview_score": session.interview_score if session.status == "completed" else None,
            "turn_count": session.turn_count,
            "competency_scores": session.competency_scores or {},
            "conversation_history": session.conversation_history or [],
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
    }


@router.get("/{application_id}")
def get_application(
    application_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _candidate_application_access(application, current_user)
    if current_user.role in {Role.RECRUITER.value, Role.ADMIN.value}:
        _recruiter_application_access(application, current_user, db)
    payload = _candidate_payload(application) if current_user.role == Role.CANDIDATE.value else _score_payload(application)
    payload["program"] = {
        "title": application.program.title,
        "department": application.program.department,
        "criteria": application.program.required_skills or [],
    }
    return payload


@router.get("/{application_id}/overview")
def get_application_overview(
    application_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Recruiter-friendly candidate and resume summary for the overview dialog."""
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    resume = application.resume
    candidate = application.candidate
    details = application.score_details or {}
    return {
        "application_id": application.id,
        "candidate_id": candidate.id,
        "candidate_name": candidate.name,
        "candidate_email": candidate.email,
        "candidate_phone": candidate.phone,
        "program_title": application.program.title,
        "department": application.program.department,
        "status": application.status,
        "resume_score": application.resume_score,
        "scoring_method": details.get("scoring_method", "keyword_evidence"),
        "identity_status": application.identity_status,
        "resume": {
            "skills": (resume.parsed_skills or []) if resume else [],
            "experience_years": resume.experience_years if resume else None,
            "text": resume.raw_text if resume else None,
        },
        "score_details": details,
    }


def _identity_evidence_path(application: ApplicationModel, kind: str, db: Session) -> Path | None:
    storage = StorageManager()
    if kind == "reference":
        candidate_path = Path(application.face_reference_path).resolve()
        root = storage.identity_dir.resolve()
        return candidate_path if root in candidate_path.parents and candidate_path.is_file() else None

    session = db.query(InterviewSessionModel).filter(
        InterviewSessionModel.candidate_id == application.candidate_id,
        InterviewSessionModel.job_id == application.program_id,
    ).order_by(InterviewSessionModel.started_at.desc()).first()
    if not session:
        return None
    check = db.query(IdentityCheckModel).filter(
        IdentityCheckModel.session_id == session.id,
        IdentityCheckModel.live_frame_path.is_not(None),
    ).order_by(IdentityCheckModel.created_at.desc()).first()
    if check and check.live_frame_path:
        path = Path(check.live_frame_path).resolve()
        root = storage.identity_dir.resolve()
        if root in path.parents and path.is_file():
            return path
    # Compatibility for borderline checks saved by older app versions.
    legacy_root = resolve_path("data/outputs/interviews").resolve()
    legacy = (legacy_root / f"{session.id}_identity.jpg").resolve()
    return legacy if legacy_root in legacy.parents and legacy.is_file() else None


@router.get("/{application_id}/identity-review")
def get_application_identity_review(
    application_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Provide recruiter-authorized evidence for a borderline identity check."""
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    from app.stages.stage3_identity.threshold_config import get_threshold_config
    session = db.query(InterviewSessionModel).filter(
        InterviewSessionModel.candidate_id == application.candidate_id,
        InterviewSessionModel.job_id == application.program_id,
    ).order_by(InterviewSessionModel.started_at.desc()).first()
    check = db.query(IdentityCheckModel).filter(
        IdentityCheckModel.session_id == session.id,
    ).order_by(IdentityCheckModel.created_at.desc()).first() if session else None
    confidence = check.confidence if check else None
    if confidence is None and session:
        from app.stages.stage4_interview.dependencies import registry
        state = registry.get(session.id) if session.id in registry else None
        confidence = (state or {}).get("face_match_score", (state or {}).get("last_identity_confidence"))
    reference = _identity_evidence_path(application, "reference", db)
    live = _identity_evidence_path(application, "live", db)
    return {
        "status": session.identity_status if session else application.identity_status,
        "confidence": confidence,
        "pass_threshold": get_threshold_config().pass_threshold,
        "review_threshold": get_threshold_config().review_threshold,
        "reason": (check.failure_reason if check else (session.identity_failure_reason if session else None)),
        "checked_at": check.created_at.isoformat() if check and check.created_at else None,
        "has_reference": reference is not None,
        "has_live_frame": live is not None,
        "reference_url": f"/applications/{application_id}/identity-review/image/reference" if reference else None,
        "live_frame_url": f"/applications/{application_id}/identity-review/image/live" if live else None,
    }


@router.get("/{application_id}/identity-review/image/{kind}")
def get_application_identity_image(
    application_id: str,
    kind: Literal["reference", "live"],
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    _recruiter_application_access(application, current_user, db)
    image_path = _identity_evidence_path(application, kind, db)
    if not image_path:
        raise HTTPException(status_code=404, detail="Identity review image is unavailable.")
    return FileResponse(image_path, media_type="image/jpeg", headers={"Cache-Control": "private, no-store, max-age=0"})


def _authorized_resume_path(application_id: str, current_user: UserResponse, db: Session) -> Path:
    application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found.")
    if current_user.role == Role.CANDIDATE.value:
        _candidate_application_access(application, current_user)
    elif current_user.role in {Role.RECRUITER.value, Role.ADMIN.value}:
        _recruiter_application_access(application, current_user, db)
    else:
        raise HTTPException(status_code=403, detail="This account cannot access application resumes.")
    if not application.resume or not application.resume.file_path:
        raise HTTPException(status_code=404, detail="Resume not found.")
    from app.security.storage_manager import StorageManager
    resume_root = StorageManager().resumes_dir.resolve()
    resume_path = Path(application.resume.file_path).resolve()
    if resume_root not in resume_path.parents or not resume_path.is_file():
        raise HTTPException(status_code=404, detail="Resume not found.")
    return resume_path


@router.get("/{application_id}/resume")
def get_application_resume(
    application_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Serve a resume PDF to its candidate or an authorized recruiter."""
    resume_path = _authorized_resume_path(application_id, current_user, db)
    return FileResponse(
        resume_path,
        media_type="application/pdf",
        filename=f"{Path(resume_path).stem}_resume.pdf",
        headers={"Cache-Control": "private, no-store, max-age=0"},
    )


@router.get("/{application_id}/resume/preview")
def get_application_resume_preview(
    application_id: str,
    page: int = Query(default=1, ge=1),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render one authorized resume page as a PNG for reliable browser preview."""
    resume_path = _authorized_resume_path(application_id, current_user, db)
    try:
        import fitz
        document = fitz.open(resume_path)
        if page > document.page_count:
            document.close()
            raise HTTPException(status_code=404, detail="Resume page not found.")
        page_count = document.page_count
        rendered = document.load_page(page - 1).get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
        image = rendered.tobytes("png")
        document.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Resume preview rendering failed for application %s", application_id)
        raise HTTPException(status_code=422, detail="Could not render this resume preview.") from exc
    return Response(
        content=image,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Resume-Page-Count": str(page_count),
        },
    )
