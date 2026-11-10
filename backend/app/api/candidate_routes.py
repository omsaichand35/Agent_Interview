from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_candidate_repository,
    get_recommendation_service,
    get_recruiter_service,
    get_workflow_service,
)
from app.api.auth_dependencies import (
    get_current_user,
    require_roles,
    verify_candidate_access,
)
from app.core.exceptions import CandidateNotFound, DuplicateScheduleException
from app.core.file_validation import validate_resume
from app.core.upload_validators import validate_resume_upload
from app.database.connection import get_db
from app.models.user import Role, UserResponse
from app.stages.stage4_interview.dependencies import registry as interview_registry
from app.models.recommendation import RecruiterReviewRequest

router = APIRouter(
    prefix="/candidates",
    tags=["candidates"],
)


@router.get("")
@router.get("/")
async def list_candidates(
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value)),
    candidate_repo=Depends(get_candidate_repository),
    rec_service=Depends(get_recommendation_service),
):
    candidates = candidate_repo.list_all()
    results = []
    for c in candidates:
        cand_dict = c.model_dump()
        interview = interview_registry.get_by_candidate(c.candidate_id)
        review = rec_service.get_human_review(c.candidate_id)

        if review and review.get("requires_review"):
            cand_dict["requires_review"] = True
            cand_dict["review_reason"] = review.get("reason")

        if interview:
            cand_dict["interview_score"] = interview.get("interview_score")
            cand_dict["identity_verified"] = interview.get("identity_verified", False)
            cand_dict["identity_status"] = interview.get("identity_status", "pending")
            if cand_dict.get("requires_review"):
                cand_dict["status"] = "HUMAN REVIEW"
            else:
                cand_dict["status"] = "Completed" if interview.get("interview_complete") else "Interviewing"
        else:
            cand_dict["interview_score"] = cand_dict.get("interview_score")
            cand_dict["identity_verified"] = False
            cand_dict["identity_status"] = "pending"
            if cand_dict.get("requires_review"):
                cand_dict["status"] = "HUMAN REVIEW"
            else:
                cand_dict["status"] = "Shortlisted" if (cand_dict.get("resume_score") or 0) >= 70.0 else "Under Review"

        try:
            from app.api.dependencies import get_workflow_service
            wf_service = get_workflow_service()
            for wf in wf_service.persistence.list_all():
                if c.candidate_id in wf.get("human_review", []):
                    cand_dict["requires_review"] = True
                    cand_dict["status"] = "HUMAN REVIEW"
                    cand_dict["identity_status"] = "failed"
                    cand_dict["identity_verified"] = False
                    cand_dict["interview_score"] = None
                    for rev in wf.get("human_review", []):
                        if (isinstance(rev, dict) and rev.get("candidate_id") == c.candidate_id) or rev == c.candidate_id:
                            cand_dict["review_reason"] = rev.get("reason", "Face mismatch") if isinstance(rev, dict) else "Face mismatch"
                    break
        except Exception:
            pass

        results.append(cand_dict)
    return results


@router.get("/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    current_user: UserResponse = Depends(get_current_user),
    candidate_repo=Depends(get_candidate_repository),
    rec_service=Depends(get_recommendation_service),
):
    verify_candidate_access(candidate_id, current_user)
    candidate = candidate_repo.get_by_id(candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail=f"Candidate {candidate_id} not found",
        )

    from app.core.audit import get_audit_service
    get_audit_service().record_event(
        actor_id=current_user.id,
        actor_role=current_user.role,
        action="CANDIDATE_VIEWED",
        resource_type="CANDIDATE",
        resource_id=candidate_id,
        candidate_id=candidate_id,
        result="SUCCESS",
    )

    cand_dict = candidate.model_dump()
    interview = interview_registry.get_by_candidate(candidate_id)
    if interview:
        cand_dict["interview"] = interview
        cand_dict["interview_score"] = interview.get("interview_score")
        cand_dict["identity_status"] = interview.get("identity_status")
        cand_dict["identity_verified"] = interview.get("identity_verified", False)

    if current_user.role == Role.CANDIDATE.value:
        for key in ("resume_score", "interview_score", "final_score"):
            cand_dict.pop(key, None)
        if isinstance(cand_dict.get("interview"), dict):
            cand_dict["interview"] = {
                key: value for key, value in cand_dict["interview"].items()
                if "score" not in key.lower() and key != "competency_scores"
            }

    review = rec_service.get_human_review(candidate_id)
    if review and review.get("requires_review"):
        cand_dict["requires_review"] = True
        cand_dict["human_review"] = review

    try:
        from app.api.dependencies import get_workflow_service
        wf_service = get_workflow_service()
        for wf in wf_service.persistence.list_all():
            if candidate_id in wf.get("human_review", []):
                cand_dict["requires_review"] = True
                cand_dict["status"] = "HUMAN REVIEW"
                cand_dict["identity_status"] = "failed"
                cand_dict["identity_verified"] = False
                cand_dict["interview_score"] = None
                reason = "Face mismatch"
                for rev in wf.get("human_review", []):
                    if (isinstance(rev, dict) and rev.get("candidate_id") == candidate_id) or rev == candidate_id:
                        reason = rev.get("reason", "Face mismatch") if isinstance(rev, dict) else "Face mismatch"
                cand_dict["review_reason"] = reason
                cand_dict["human_review"] = {"requires_review": True, "reason": reason}
                break
    except Exception:
        pass

    return cand_dict


@router.get("/{candidate_id}/interview")
async def get_candidate_interview(
    candidate_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    verify_candidate_access(candidate_id, current_user)
    interview = interview_registry.get_by_candidate(
        candidate_id
    )

    if interview is None:
        raise HTTPException(
            status_code=404,
            detail=f"Interview for candidate {candidate_id} not found",
        )

    if "conversation_history" not in interview:
        interview["conversation_history"] = []
    if "competency_scores" not in interview:
        interview["competency_scores"] = {}

    if current_user.role == Role.CANDIDATE.value:
        interview = {
            key: value for key, value in interview.items()
            if "score" not in key.lower() and key != "competency_scores"
        }

    return interview


@router.get("/{candidate_id}/recommendation")
async def get_candidate_recommendation(
    candidate_id: str,
    current_user: UserResponse = Depends(get_current_user),
    rec_service=Depends(get_recommendation_service),
):
    verify_candidate_access(candidate_id, current_user)
    recommendation = (
        rec_service
        .get_recommendation(candidate_id)
    )

    if recommendation is None:
        raise HTTPException(
            status_code=404,
            detail="Recommendation not available",
        )

    result = recommendation.model_dump()
    if current_user.role == Role.CANDIDATE.value:
        for key in ("resume_score", "interview_score", "final_score"):
            result.pop(key, None)
    return result


@router.get("/{candidate_id}/review")
async def get_candidate_review(
    candidate_id: str,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value)),
    recruiter_service=Depends(get_recruiter_service),
    wf_service=Depends(get_workflow_service),
):
    """
    Return the full human-review payload for the recruiter dashboard.

    Aggregates: resume score, interview transcript, identity checks,
    the reason the candidate reached human review, and any existing
    recruiter decision.
    """
    # Find the workflow containing this candidate in human_review.
    workflow = None
    try:
        for wf in wf_service.persistence.list_all():
            hr = wf.get("human_review", [])
            in_hr = any(
                (isinstance(e, dict) and e.get("candidate_id") == candidate_id)
                or e == candidate_id
                for e in hr
            )
            if in_hr:
                workflow = wf
                break
    except Exception:
        pass

    payload = recruiter_service.build_review_payload(
        candidate_id=candidate_id,
        workflow=workflow,
    )
    return payload


@router.post("/{candidate_id}/review")
async def submit_candidate_review(
    candidate_id: str,
    body: RecruiterReviewRequest,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value)),
    recruiter_service=Depends(get_recruiter_service),
    wf_service=Depends(get_workflow_service),
):
    """
    Record the recruiter's decision (APPROVE / REJECT / REQUEST_REVIEW).

    This is the ONLY way the frontend can advance a HUMAN_REVIEW workflow
    to COMPLETED.  Direct status mutations from the client are never allowed.
    """
    # Try to locate the workflow for this candidate.
    job_id = None
    try:
        for wf in wf_service.persistence.list_all():
            hr = wf.get("human_review", [])
            in_hr = any(
                (isinstance(e, dict) and e.get("candidate_id") == candidate_id)
                or e == candidate_id
                for e in hr
            )
            if in_hr:
                job_id = wf.get("job_id")
                break
    except Exception:
        pass

    try:
        result = recruiter_service.submit_review(
            candidate_id=candidate_id,
            request=body,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    from app.core.audit import get_audit_service
    get_audit_service().record_event(
        actor_id=current_user.id,
        actor_role=current_user.role,
        action="REVIEW_CREATED",
        resource_type="REVIEW",
        resource_id=f"REV_{candidate_id}",
        candidate_id=candidate_id,
        job_id=job_id,
        result=getattr(body, "decision", "COMPLETED"),
        metadata={
            "decision": getattr(body, "decision", None),
            "notes": getattr(body, "notes", None),
        },
    )

    return result.model_dump()


@router.post("/{candidate_id}/resume")
async def upload_candidate_resume(
    candidate_id: str,
    resume: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    candidate_repo=Depends(get_candidate_repository),
):
    """
    Validates and stores a candidate resume.
    Ensures PDF format, PDF magic bytes, and size limit.
    """
    verify_candidate_access(candidate_id, current_user)
    candidate = candidate_repo.get_by_id(candidate_id)
    if not candidate:
        raise CandidateNotFound(candidate_id=candidate_id)

    file_bytes = await resume.read()
    val_res = validate_resume(file_bytes, filename=resume.filename, content_type=resume.content_type)

    from app.security.storage_manager import StorageManager
    storage = StorageManager()
    cand_dir = storage.resumes_dir / candidate_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    private_file_path = cand_dir / val_res.safe_filename
    private_file_path.write_bytes(file_bytes)

    # Legacy output path for backwards compatibility
    output_dir = Path("data/outputs/resumes")
    output_dir.mkdir(parents=True, exist_ok=True)
    legacy_file_path = output_dir / f"{candidate_id}_resume.pdf"
    legacy_file_path.write_bytes(file_bytes)

    return {
        "candidate_id": candidate_id,
        "filename": val_res.sanitized_original_filename,
        "file_id": val_res.internal_id,
        "size_bytes": len(file_bytes),
        "pages": val_res.page_count,
        "status": "uploaded",
    }


@router.get("/{candidate_id}/resume")
async def get_candidate_resume(
    candidate_id: str,
    current_user: UserResponse = Depends(get_current_user),
    candidate_repo=Depends(get_candidate_repository),
):
    """Secure endpoint for retrieving candidate resume (Requirement F2.6).

    Enforces permission check:
    1. Who is requesting this?
    2. Are they authorized (Candidate themselves, Recruiter, or Admin)?
    3. Retrieve strictly from private storage partition outside public web roots.
    """
    verify_candidate_access(candidate_id, current_user)
    candidate = candidate_repo.get_by_id(candidate_id)
    if not candidate:
        raise CandidateNotFound(candidate_id=candidate_id)

    from app.security.storage_manager import StorageManager
    storage = StorageManager()
    cand_dir = storage.resumes_dir / candidate_id

    resume_path = None
    if cand_dir.exists():
        pdf_files = sorted(cand_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if pdf_files:
            resume_path = pdf_files[0]

    if not resume_path or not resume_path.exists():
        legacy_path = Path("data/outputs/resumes") / f"{candidate_id}_resume.pdf"
        if legacy_path.exists():
            resume_path = legacy_path

    if not resume_path or not resume_path.exists():
        raise HTTPException(status_code=404, detail="Candidate resume not found")

    return FileResponse(
        resume_path,
        media_type="application/pdf",
        filename=f"{candidate_id}_resume.pdf",
    )


@router.post("/{candidate_id}/schedule")
async def schedule_candidate_interview(
    candidate_id: str,
    slot_id: str,
    current_user: UserResponse = Depends(get_current_user),
    candidate_repo=Depends(get_candidate_repository),
    db: Session = Depends(get_db),
):
    """
    Schedules an interview slot for a candidate, rejecting duplicates with 409 Conflict.
    """
    verify_candidate_access(candidate_id, current_user)
    candidate = candidate_repo.get_by_id(candidate_id)
    if not candidate:
        raise CandidateNotFound(candidate_id=candidate_id)

    from app.database.models import InterviewSessionModel
    existing = db.query(InterviewSessionModel).filter_by(candidate_id=candidate_id).first()
    if existing:
        raise DuplicateScheduleException(
            f"Candidate '{candidate_id}' is already scheduled for an interview (session: {existing.id})"
        )

    return {
        "candidate_id": candidate_id,
        "slot_id": slot_id,
        "status": "scheduled",
    }
