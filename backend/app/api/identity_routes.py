from pathlib import Path
from typing import Optional
import uuid

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.auth_dependencies import (
    get_current_user,
    verify_session_candidate_access,
)
from app.api.dependencies import get_identity_service
from app.database.connection import get_db
from app.database.models import ApplicationModel, CandidateModel, IdentityCheckModel, InterviewSessionModel
from app.models.user import UserResponse
from app.core.upload_validators import validate_image_upload
from app.security.storage_manager import StorageManager
from app.stages.stage4_interview.dependencies import registry
from app.stages.stage4_interview.identity_checkpoint import normalized_identity_status


router = APIRouter(prefix="/identity", tags=["identity"])


@router.get("/{session_id}")
async def get_identity_status(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    identity_service=Depends(get_identity_service),
):
    """
    Get identity verification status and logs for a session.
    Protected by candidate ownership / recruiter role.
    """
    verify_session_candidate_access(session_id, current_user, db)

    if session_id in registry:
        state = registry.get(session_id)
        return {
            "session_id": session_id,
            "candidate_id": state.get("candidate_id"),
            "identity_verified": state.get("identity_verified", False),
            "confidence": state.get("last_identity_confidence"),
            "status": state.get("identity_status", "pending"),
            "failure_reason": state.get("identity_failure_reason"),
            "check_count": state.get("identity_check_count", 0),
        }

    from app.database.repositories.identity_check_repository import IdentityCheckRepository
    id_repo = IdentityCheckRepository(db)
    checks = id_repo.get_by_session(session_id)
    if checks:
        last = checks[-1]
        return {
            "session_id": session_id,
            "candidate_id": last.candidate_id,
            "identity_verified": last.verified,
            "confidence": last.confidence,
            "status": "verified" if last.verified else "failed",
            "failure_reason": last.failure_reason,
            "check_count": len(checks),
        }

    logs = identity_service.logger.get_logs(session_id)
    if logs:
        last = logs[-1]
        return {
            "session_id": session_id,
            "candidate_id": last.get("candidate_id"),
            "identity_verified": last.get("verified", False),
            "confidence": last.get("confidence"),
            "status": "verified" if last.get("verified") else "failed",
            "failure_reason": last.get("failure_reason"),
            "check_count": len(logs),
        }

    raise HTTPException(
        status_code=404,
        detail=f"Identity records for session '{session_id}' not found",
    )


@router.post("/{session_id}/check")
async def check_identity(
    session_id: str,
    request: Request,
    candidate_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    live_frame: Optional[UploadFile] = File(None),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    identity_service=Depends(get_identity_service),
):
    """
    Receive a browser webcam frame and perform identity verification.
    """
    if not candidate_id:
        candidate_id = request.query_params.get("candidate_id")

    state = registry.get(session_id) if session_id in registry else None
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    authoritative_candidate_id = (state or {}).get("candidate_id") or (session_record.candidate_id if session_record else None)
    if authoritative_candidate_id:
        candidate_id = authoritative_candidate_id

    if not candidate_id:
        raise HTTPException(
            status_code=400,
            detail="candidate_id is required",
        )

    verify_session_candidate_access(session_id, current_user, db)
    if current_user.role == "candidate" and session_record and (
        session_record.status == "completed" or session_record.completed_at is not None
    ):
        raise HTTPException(status_code=410, detail="This interview is complete. Return to your application page.")

    uploaded_file = image or live_frame
    if not uploaded_file:
        raise HTTPException(
            status_code=400,
            detail="Uploaded image file must be provided",
        )

    if not uploaded_file.content_type or not uploaded_file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be an image",
        )

    image_bytes = await uploaded_file.read()
    live_image = validate_image_upload(
        image_bytes,
        filename=uploaded_file.filename,
        content_type=uploaded_file.content_type,
    )
    if live_image is None:
        raise HTTPException(status_code=422, detail="Could not process the live camera image.")

    storage = StorageManager()
    encoded_ok, encoded_image = cv2.imencode(".jpg", live_image)
    if not encoded_ok:
        raise HTTPException(status_code=422, detail="Could not process the live camera image.")
    temp_path = storage.get_identity_path(candidate_id, f"check_{session_id}_{uuid.uuid4().hex}.jpg")
    temp_path.write_bytes(encoded_image.tobytes())

    # Use only an application, session, or database enrollment reference.
    # Bundled sample faces are never valid identity references.
    reference_path = None
    state_candidate = (state or {}).get("candidate", {})
    if isinstance(state_candidate, dict):
        reference_path = state_candidate.get("photo_path")
    if not reference_path and session_record:
        application = db.query(ApplicationModel).filter(
            ApplicationModel.candidate_id == candidate_id,
            ApplicationModel.program_id == session_record.job_id,
        ).order_by(ApplicationModel.created_at.desc()).first()
        if application:
            reference_path = application.face_reference_path
    candidate_record = db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
    if not reference_path and candidate_record:
        reference_path = candidate_record.photo_path
    if not reference_path and state and state.get("application_id"):
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="The application face reference is unavailable.")
    if not reference_path or not Path(reference_path).is_file():
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail="No enrolled face reference is available for this interview.")

    reference_image = cv2.imread(str(reference_path))

    if reference_image is None:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Could not load candidate reference image",
        )

    from app.core.logging import log_event
    from app.core.metrics import get_metrics_collector

    log_event("identity_check_started", session_id=session_id, candidate_id=candidate_id)

    try:
        result = identity_service.verify(
            reference_image=str(reference_path),
            live_image=str(temp_path),
            candidate_id=candidate_id,
            session_id=session_id,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    normalized_status = normalized_identity_status(result)
    verified = normalized_status == "passed"
    stored_status = "verified" if verified else normalized_status
    output_path = None
    if stored_status == "review":
        output_path = storage.get_identity_path(candidate_id, f"review_{session_id}_{uuid.uuid4().hex}.jpg")
        temp_path.replace(output_path)
    else:
        temp_path.unlink(missing_ok=True)
    get_metrics_collector().record_identity_check(verified)
    event_name = "identity_check_passed" if verified else f"identity_check_{normalized_status}"
    log_event(
        event_name,
        session_id=session_id,
        candidate_id=candidate_id,
        confidence=result.confidence,
        reason=result.failure_reason,
    )

    if session_id in registry:
        state = registry.get(session_id)
        if isinstance(state.get("candidate"), dict) and not state["candidate"].get("photo_path"):
            state["candidate"]["photo_path"] = str(reference_path)
        state["identity_verified"] = verified
        state["last_identity_confidence"] = result.confidence
        state["face_match_score"] = getattr(result, "face_match_score", result.confidence)
        state["liveness_status"] = getattr(result, "liveness_status", "not_implemented")
        state["identity_reason_code"] = getattr(result, "reason_code", None)

        state["identity_status"] = stored_status
        state["identity_check_count"] = state.get("identity_check_count", 0) + 1
        state["current_live_frame"] = str(output_path) if output_path else None
        if not verified:
            state["identity_failure_reason"] = result.failure_reason or "face_mismatch"
        else:
            state["identity_failure_reason"] = None
        registry.update(session_id, state)

    db.add(IdentityCheckModel(
        candidate_id=candidate_id,
        session_id=session_id,
        verified=verified,
        confidence=getattr(result, "face_match_score", result.confidence),
        failure_reason=result.failure_reason,
        live_frame_path=str(output_path) if output_path else None,
    ))
    if session_record:
        session_record.identity_verified = verified
        session_record.identity_status = stored_status
        session_record.identity_failure_reason = result.failure_reason
        session_record.status = "in_progress" if verified else f"identity_{session_record.identity_status}"
        if state and state.get("application_id"):
            application = db.query(ApplicationModel).filter(ApplicationModel.id == state["application_id"]).first()
            if application:
                application.identity_status = session_record.identity_status
                application.status = "interviewing" if verified else f"identity_{session_record.identity_status}"
        db.commit()

    try:
        from app.api.dependencies import get_workflow_service
        wf_service = get_workflow_service()
        for wf_dict in wf_service.persistence.list_all():
            cand_ids = wf_dict.get("candidate_ids", []) or [c.get("candidate_id") for c in wf_dict.get("candidates", [])]
            if candidate_id in cand_ids:
                if verified:
                    wf_service.identity_passed(wf_dict, candidate_id, result)
                else:
                    wf_service.identity_failed(wf_dict, candidate_id, result)
                break
    except Exception:
        pass

    res_dict = result.model_dump()
    res_dict["identity_status"] = normalized_status
    res_dict["status"] = "verified" if verified else normalized_status
    res_dict["reason"] = result.failure_reason or ("face_mismatch" if not verified else None)
    return res_dict
