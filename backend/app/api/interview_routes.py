import logging
import uuid
from pathlib import Path
from typing import Literal, Optional
from datetime import datetime, timezone

import cv2
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.api.auth_dependencies import (
    get_current_user,
    verify_candidate_access,
    verify_session_candidate_access,
)
from app.api.scheduling_routes import ensure_schedule_open
from app.security.rate_limiter import rate_limit
from app.api.dependencies import (
    get_candidate_repository,
    get_identity_service,
)
from app.core.jobs import (
    Job,
    JobQueue,
    JobStatus,
    JobType,
    JobWorker,
    get_job_queue,
    get_job_worker,
)
from app.database.connection import get_db
from app.database.models import ApplicationModel, CandidateModel, IdentityCheckModel, InterviewInviteModel, InterviewScheduleModel, InterviewSessionModel
from app.models.user import UserResponse
from app.schemas.interview import (
    InterviewResponse,
    InterviewStartRequest,
    InterviewTextAnswerRequest,
)
from app.core.exceptions import (
    InterviewNotFound,
    InvalidRequestException,
    LLMUnavailableException,
    ServiceUnavailableException,
    STTUnavailableException,
)


def _enforce_scheduled_deadline(state: dict, session_id: str, db: Session) -> None:
    application_id = state.get("application_id")
    if not application_id:
        return
    placement = db.query(InterviewScheduleModel).filter(
        InterviewScheduleModel.application_id == application_id,
        InterviewScheduleModel.session_id == session_id,
    ).first()
    if placement:
        ensure_schedule_open(placement, session_id)
from app.core.upload_validators import (
    validate_audio_upload,
    validate_image_upload,
)
from app.config import settings
from app.security.storage_manager import StorageManager
from app.stages.stage4_interview.dependencies import (
    create_interview_controller,
    registry,
)
from app.stages.stage4_interview.voice.stt import get_whisper_stt
from app.stages.stage4_interview.graph.coverage import criterion_label
from app.stages.stage4_interview.questions.question_generator import generate_criterion_question
from app.stages.stage4_interview.identity_checkpoint import normalized_identity_status

router = APIRouter(
    prefix="/interview",
    tags=["Interview"],
)

controller = create_interview_controller()
stt = get_whisper_stt(settings.whisper_model)
logger = logging.getLogger(__name__)


class GazeWarningRequest(BaseModel):
    warning_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    signals: list[Literal["head_direction", "eye_direction", "face_not_visible"]] = Field(min_length=1, max_length=3)


def _transcription_prompt(state) -> str:
    """Give Whisper the current rubric context for technical vocabulary."""
    question = str(state.get("current_question") or "").strip()
    criteria = [str(item).strip() for item in (state.get("target_competencies") or []) if str(item).strip()]
    pieces = ["Graduate admissions interview answer."]
    if question:
        pieces.append(f"Current question: {question}")
    if criteria:
        pieces.append("Evaluation topics: " + ", ".join(criteria[:12]))
    return " ".join(pieces)


def _persist_application_interview_state(db: Session, session_id: str, state):
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if not session_record:
        return
    identity_status = state.get("identity_status", "pending")
    complete = bool(state.get("interview_complete", False))
    session_record.identity_verified = bool(state.get("identity_verified", False))
    session_record.identity_status = identity_status
    session_record.identity_failure_reason = state.get("identity_failure_reason")
    session_record.gaze_warning_count = int(state.get("gaze_warning_count", session_record.gaze_warning_count or 0))
    session_record.gaze_flagged = bool(state.get("gaze_flagged", session_record.gaze_flagged))
    session_record.gaze_events = state.get("gaze_events", session_record.gaze_events or [])
    session_record.turn_count = state.get("turn_number", 1)
    session_record.current_question = state.get("current_question")
    session_record.competency_scores = state.get("competency_scores", {})
    session_record.conversation_history = state.get("conversation_history", [])
    session_record.interview_score = state.get("interview_score")
    if identity_status in {"failed", "review"}:
        session_record.status = f"identity_{identity_status}"
    elif complete:
        session_record.status = "completed"
        session_record.completed_at = session_record.completed_at or datetime.now(timezone.utc)
        if session_record.interview_score is None:
            session_record.interview_score = controller.session_manager.scorer.score(
                session_record.competency_scores or {}
            )
            state["interview_score"] = session_record.interview_score

        invite_rows = db.query(InterviewInviteModel).filter(
            InterviewInviteModel.session_id == session_id,
            InterviewInviteModel.revoked_at.is_(None),
        ).all()
        deactivated_at = datetime.now(timezone.utc)
        for invite in invite_rows:
            invite.revoked_at = deactivated_at
    elif identity_status == "verified":
        session_record.status = "in_progress"

    application_id = state.get("application_id")
    application = None
    if application_id:
        application = db.query(ApplicationModel).filter(ApplicationModel.id == application_id).first()
    if not application:
        application = db.query(ApplicationModel).filter(
            ApplicationModel.candidate_id == session_record.candidate_id,
            ApplicationModel.program_id == session_record.job_id,
        ).first()
    if application:
        application.identity_status = identity_status
        if identity_status in {"failed", "review"}:
            application.status = f"identity_{identity_status}"
        elif complete:
            application.status = "interview_completed"
            application.interview_score = session_record.interview_score
            schedule = db.query(InterviewScheduleModel).filter(
                InterviewScheduleModel.session_id == session_id,
                InterviewScheduleModel.status == "joined",
            ).first()
            if schedule:
                schedule.status = "completed"
    db.commit()


def _restore_stale_identity_completion_flag(db: Session, session_id: str, state):
    """Clear legacy identity-failure flags when the saved interview is still untouched."""
    if not state.get("interview_complete"):
        return state
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if not session_record:
        return state
    application = db.query(ApplicationModel).filter(ApplicationModel.id == state.get("application_id")).first()
    identity_status = state.get("identity_status", session_record.identity_status)
    if identity_status in {"failed", "review"}:
        if session_record.status != "completed" and not (application and application.status == "interview_completed"):
            state["interview_complete"] = False
            state["next_question"] = state.get("current_question") or state.get("next_question")
            session_record.completed_at = None
            session_record.status = f"identity_{identity_status}"
            if application and application.status == "interviewing":
                application.status = f"identity_{identity_status}"
            registry.update(session_id, state)
            db.commit()
            logger.warning("Cleared a legacy identity failure flag that prematurely completed interview %s", session_id)
        return state
    if identity_status != "verified":
        return state
    history = state.get("conversation_history") or session_record.conversation_history or []
    if (
        session_record.status == "completed"
        or int(session_record.turn_count or 0) > 0
        or history
        or (application and application.status == "interview_completed")
    ):
        return state
    state["interview_complete"] = False
    state["next_question"] = state.get("current_question") or state.get("next_question")
    registry.update(session_id, state)
    logger.warning("Cleared a premature identity-failure completion flag for interview %s", session_id)
    return state


def _reject_completed_candidate_session(session_id: str, current_user: UserResponse, db: Session):
    if current_user.role != "candidate":
        return
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    invite = db.query(InterviewInviteModel).filter(InterviewInviteModel.session_id == session_id).first()
    application = db.query(ApplicationModel).filter(
        ApplicationModel.id == invite.application_id
    ).first() if invite else None
    if (
        (session_record and session_record.status == "completed")
        or (application and application.status == "interview_completed")
    ):
        raise HTTPException(status_code=410, detail="This interview is complete. Return to your application page.")


@router.post(
    "/{session_id}/gaze-warning",
    dependencies=[Depends(rate_limit(limit=20, window_seconds=60, key_prefix="gaze_warning"))],
)
def record_gaze_warning(
    session_id: str,
    payload: GazeWarningRequest,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store a candidate-visible, client-side gaze warning for recruiter review."""
    if current_user.role != "candidate":
        raise HTTPException(status_code=403, detail="Only the interview candidate can submit gaze warnings.")
    verify_session_candidate_access(session_id, current_user, db)
    try:
        state = registry.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found.") from exc
    if state.get("identity_status") != "verified":
        raise HTTPException(status_code=403, detail="Complete identity verification before reporting interview monitoring events.")

    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if not session_record:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    events = list(session_record.gaze_events or [])
    if any(event.get("warning_id") == payload.warning_id for event in events):
        return {
            "warning_count": int(session_record.gaze_warning_count or 0),
            "flagged_for_review": bool(session_record.gaze_flagged),
        }

    warning_count = int(session_record.gaze_warning_count or 0) + 1
    flagged = warning_count >= 3
    event = {
        "warning_id": payload.warning_id,
        "signals": list(dict.fromkeys(payload.signals)),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "warning_number": warning_count,
    }
    events.append(event)
    session_record.gaze_warning_count = warning_count
    session_record.gaze_flagged = flagged
    session_record.gaze_events = events[-100:]
    if flagged and not session_record.gaze_flagged_at:
        session_record.gaze_flagged_at = datetime.now(timezone.utc)

    state["gaze_warning_count"] = warning_count
    state["gaze_flagged"] = flagged
    state["gaze_events"] = events[-100:]
    registry.update(session_id, state)
    db.commit()
    return {"warning_count": warning_count, "flagged_for_review": flagged}


@router.post(
    "/start",
    response_model=InterviewResponse,
)
def start_interview(
    request: InterviewStartRequest,
    current_user: UserResponse = Depends(get_current_user),
    candidate_repo=Depends(get_candidate_repository),
    db: Session = Depends(get_db),
):
    application = None
    candidate_id = request.candidate_id
    candidate_data = request.candidate
    competencies = request.competencies
    program_id = None
    if request.application_id:
        if current_user.role != "candidate":
            raise HTTPException(status_code=403, detail="Application interviews can only be started by the applying student.")
        application = db.query(ApplicationModel).filter(ApplicationModel.id == request.application_id).first()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found.")
        verify_candidate_access(application.candidate_id, current_user)
        if current_user.role == "candidate" and application.candidate_id != current_user.candidate_id:
            raise HTTPException(status_code=403, detail="This application does not belong to your account.")
        if application.status == "interview_completed":
            raise HTTPException(status_code=410, detail="This interview is already complete. Return to your application page.")
        invite = db.query(InterviewInviteModel).filter(
            InterviewInviteModel.application_id == application.id,
            InterviewInviteModel.session_id == request.session_id,
            InterviewInviteModel.redeemed_at.is_not(None),
            InterviewInviteModel.revoked_at.is_(None),
        ).first()
        if not invite:
            raise HTTPException(status_code=403, detail="Redeem the interview code from your student portal before starting.")
        invite_expiry = invite.expires_at
        if invite_expiry.tzinfo is None:
            invite_expiry = invite_expiry.replace(tzinfo=timezone.utc)
        if invite_expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="This interview authorization has expired. Ask your recruiter for a new code.")
        existing_session = db.query(InterviewSessionModel).filter(
            InterviewSessionModel.id == request.session_id,
        ).first()
        if (existing_session and existing_session.status == "completed") or application.status == "interview_completed":
            raise HTTPException(status_code=410, detail="This interview is already complete. Return to your application page.")
        if application.status not in {"interview_authorized", "interviewing", "identity_failed"}:
            raise HTTPException(status_code=403, detail="The recruiter has not authorized this application for interview.")
        scheduled_interview = db.query(InterviewScheduleModel).filter(
            InterviewScheduleModel.application_id == application.id,
        ).order_by(InterviewScheduleModel.created_at.desc()).first()
        if scheduled_interview:
            ensure_schedule_open(scheduled_interview, request.session_id)
        if not Path(application.face_reference_path).is_file():
            raise HTTPException(status_code=409, detail="This application has no available face reference. Reapply with a face photo.")
        candidate_id = application.candidate_id
        candidate_record = db.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
        candidate_data = {
            "candidate_id": candidate_id,
            "name": candidate_record.name if candidate_record else "Student",
            "email": candidate_record.email if candidate_record else current_user.email,
            "photo_path": application.face_reference_path,
            "application_id": application.id,
            "program_title": application.program.title if application.program else None,
        }
        competencies = application.program.required_skills or []
        program_id = application.program_id
        if not competencies:
            raise HTTPException(status_code=409, detail="This program has no interview criteria configured.")
    if not candidate_id:
        raise HTTPException(status_code=422, detail="candidate_id or application_id is required.")
    verify_candidate_access(candidate_id, current_user)
    try:

        state = controller.start(
            session_id=request.session_id,
            candidate_id=candidate_id,
            candidate=candidate_data,
            competencies=competencies,
            first_question=None if application else request.first_question,
        )
        if application:
            state["application_id"] = application.id
            state["job_id"] = application.program_id

        registry.create(
            request.session_id,
            state,
        )

        if application:
            session_record = db.query(InterviewSessionModel).filter(
                InterviewSessionModel.id == request.session_id
            ).first()
            if not session_record:
                session_record = InterviewSessionModel(
                    id=request.session_id,
                    candidate_id=candidate_id,
                    job_id=program_id,
                    status="identity_pending",
                    identity_verified=False,
                    identity_status="pending",
                    current_question=state.get("current_question"),
                    competency_scores={},
                    conversation_history=[],
                )
                db.add(session_record)
            if application.status != "interview_completed":
                application.status = "interviewing"
            if scheduled_interview and scheduled_interview.status == "scheduled":
                scheduled_interview.status = "joined"
            db.commit()

        if request.candidate:
            cand_dict = request.candidate if isinstance(request.candidate, dict) else {}
            candidate_repo.create_or_update(
                candidate_id=request.candidate_id,
                name=cand_dict.get("name", ""),
                email=cand_dict.get("email", ""),
                photo_path=cand_dict.get("photo_path"),
            )

        from app.core.audit import get_audit_service
        get_audit_service().record_event(
            actor_id=current_user.id,
            actor_role=current_user.role,
            action="INTERVIEW_STARTED",
            resource_type="INTERVIEW_SESSION",
            resource_id=request.session_id,
            candidate_id=candidate_id,
            result="SUCCESS",
        )

        return InterviewResponse(
            session_id=request.session_id,
            candidate_id=candidate_id,
            next_question=(
                state["next_question"]
            ),
            identity_verified=(
                state["identity_verified"]
            ),
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


@router.post(
    "/{session_id}/check",
    dependencies=[Depends(rate_limit(limit=30, window_seconds=60, key_prefix="identity_check"))],
)
async def check_identity(
    session_id: str,
    request: Request,
    candidate_id: Optional[str] = Form(None),
    live_frame: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    identity_service=Depends(get_identity_service),
    candidate_repo=Depends(get_candidate_repository),
):
    # Enforce session ownership (Requirement F3.2)
    verify_session_candidate_access(session_id, current_user, db)
    _reject_completed_candidate_session(session_id, current_user, db)
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if current_user.role == "candidate" and session_record and (
        session_record.status == "completed" or session_record.completed_at is not None
    ):
        raise HTTPException(status_code=410, detail="This interview is complete. Return to your application page.")

    # Server-authoritative candidate ID derivation - ignore conflicting client query/form (Requirement F3.2)
    if session_id in registry:
        server_cand_id = registry.get(session_id).get("candidate_id")
        if server_cand_id:
            candidate_id = server_cand_id
    elif not candidate_id:
        from app.stages.stage4_interview.persistence import InterviewPersistence
        pers = InterviewPersistence()
        if pers.exists(session_id):
            candidate_id = pers.load(session_id).get("candidate_id")

    if not candidate_id:
        raise HTTPException(
            status_code=422,
            detail="candidate_id is required",
        )

    # 1. Resolve application-scoped reference first; do not substitute a
    # different candidate's static demo image for a real application.
    reference_image = None
    state = registry.get(session_id) if session_id in registry else None
    cand_data = (state or {}).get("candidate", {})
    if isinstance(cand_data, dict):
        reference_image = cand_data.get("photo_path")
    elif hasattr(cand_data, "photo_path"):
        reference_image = cand_data.photo_path
    if not reference_image:
        candidate = candidate_repo.get_by_id(candidate_id)
        if candidate and candidate.photo_path:
            reference_image = candidate.photo_path

    # 2. Validate and encode the live frame. Keep it in the private identity
    # store only when an automated borderline result needs human review.
    contents = await live_frame.read()
    live_image = validate_image_upload(contents, filename=live_frame.filename, content_type=live_frame.content_type)
    if live_image is None:
        raise HTTPException(status_code=422, detail="Could not process the live camera image.")
    ok, encoded = cv2.imencode(".jpg", live_image)
    if not ok:
        raise HTTPException(status_code=422, detail="Could not process the live camera image.")
    storage = StorageManager()
    temp_path = storage.get_identity_path(candidate_id, f"check_{session_id}_{uuid.uuid4().hex}.jpg")
    temp_path.write_bytes(encoded.tobytes())

    # 3. Verify identity via identity_service
    try:
        result = identity_service.verify(
            candidate_id=candidate_id,
            session_id=session_id,
            reference_image=reference_image or "",
            live_image=str(temp_path),
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    normalized_status = normalized_identity_status(result)
    verified = normalized_status == "passed"
    stored_status = "verified" if verified else normalized_status

    output_path = None
    if stored_status == "review" and reference_image:
        output_path = storage.get_identity_path(candidate_id, f"review_{session_id}_{uuid.uuid4().hex}.jpg")
        temp_path.replace(output_path)
    else:
        temp_path.unlink(missing_ok=True)

    # 4. Update session registry state if session exists
    if session_id in registry:
        state = registry.get(session_id)
        state["identity_verified"] = verified
        state["last_identity_confidence"] = result.confidence
        state["face_match_score"] = getattr(result, "face_match_score", result.confidence)
        state["liveness_status"] = getattr(result, "liveness_status", "not_implemented")
        state["identity_reason_code"] = getattr(result, "reason_code", None)

        state["identity_status"] = stored_status
        state["identity_check_count"] = state.get("identity_check_count", 0) + 1
        state["current_live_frame"] = str(output_path) if output_path else None
        if not verified:
            state["identity_failure_reason"] = result.failure_reason
        else:
            state["identity_failure_reason"] = None
        registry.update(session_id, state)

    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
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
        if state and state.get("application_id"):
            application = db.query(ApplicationModel).filter(ApplicationModel.id == state["application_id"]).first()
            if application:
                application.identity_status = session_record.identity_status
        db.commit()
        if verified and state:
            _restore_stale_identity_completion_flag(db, session_id, state)

    from app.core.audit import get_audit_service
    action_name = (
        "IDENTITY_PASSED"
        if verified
        else ("IDENTITY_REVIEW_REQUIRED" if normalized_status == "review" else "IDENTITY_FAILED")
    )
    get_audit_service().record_event(
        actor_id=current_user.id,
        actor_role=current_user.role,
        action=action_name,
        resource_type="INTERVIEW_SESSION",
        resource_id=session_id,
        candidate_id=candidate_id,
        result="PASSED" if verified else normalized_status.upper(),
        metadata={"confidence": result.confidence, "reason": result.failure_reason},
    )

    response_payload = result.model_dump()
    response_payload["identity_status"] = normalized_status
    return response_payload



@router.post(
    "/{session_id}/answer",
    response_model=InterviewResponse,
    dependencies=[Depends(rate_limit(limit=20, window_seconds=60, key_prefix="interview_answer"))],
)
async def submit_answer(
    session_id: str,
    request: Request,
    answer: Optional[str] = Form(None),
    live_frame: Optional[UploadFile] = File(None),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    try:
        state = registry.get(
            session_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    # Enforce session ownership (Requirement F3.2)
    verify_session_candidate_access(session_id, current_user, db)
    _reject_completed_candidate_session(session_id, current_user, db)
    _enforce_scheduled_deadline(state, session_id, db)
    state = _restore_stale_identity_completion_flag(db, session_id, state)

    if state.get("interview_complete", False):
        raise HTTPException(
            status_code=409,
            detail="Interview is already complete.",
        )

    # Enforce identity gate (Requirement F4.4)
    ident_status = state.get("identity_status")
    if ident_status == "review":
        raise HTTPException(
            status_code=403,
            detail="Identity verification is under review. Interview progression held.",
        )
    elif ident_status == "failed":
        raise HTTPException(
            status_code=403,
            detail="Identity verification failed. Interview blocked.",
        )
    elif ident_status == "pending" and current_user.role == "candidate":
        raise HTTPException(
            status_code=403,
            detail="Identity verification pending. Must complete identity verification first.",
        )

    # Replay protection & Idempotency (Requirement F3.4)
    idem_key = (
        request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
    )
    if idem_key and "_idempotency_cache" in state and idem_key in state["_idempotency_cache"]:
        cached = state["_idempotency_cache"][idem_key]
        return InterviewResponse(**cached) if isinstance(cached, dict) else cached

    ct = request.headers.get("content-type", "")
    answer_text = answer
    frame_path = None

    if "application/json" in ct:
        body = await request.json()
        # Strictly extract only candidate answer string, discarding any client turn_number, score, decision (Requirement F3.5)
        answer_text = body.get("answer")
    if answer_text is None or not str(answer_text).strip():
        raise InvalidRequestException("Answer cannot be empty.")

    if "application/json" not in ct and live_frame is not None:
        contents = await live_frame.read()
        decoded_frame = validate_image_upload(contents, filename=live_frame.filename, content_type=live_frame.content_type)
        ok, encoded_frame = cv2.imencode(".jpg", decoded_frame)
        if not ok:
            raise HTTPException(status_code=422, detail="Could not process the live camera frame.")
        private_frame_path = StorageManager().get_identity_path(
            state.get("candidate_id", "unknown"), f"live_{uuid.uuid4().hex}.jpg"
        )
        private_frame_path.write_bytes(encoded_frame.tobytes())
        frame_path = str(private_frame_path)

    if current_user.role == "candidate" and not frame_path:
        raise HTTPException(status_code=422, detail="A live camera frame is required with each interview answer.")

    try:
        result = controller.submit_text(
            state,
            answer_text,
            live_image=frame_path,
        )
    except (LLMUnavailableException, STTUnavailableException):
        if frame_path:
            Path(frame_path).unlink(missing_ok=True)
        raise
    except Exception as exc:
        if frame_path:
            Path(frame_path).unlink(missing_ok=True)
        err_msg = str(exc).lower()
        if "llm" in err_msg or "rate limit" in err_msg or "timeout" in err_msg or "connection error" in err_msg or "unavailable" in err_msg:
            raise LLMUnavailableException(f"LLM service is currently unavailable: {exc}")
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    resp = InterviewResponse(
        session_id=session_id,
        candidate_id=result["candidate_id"],
        transcript=answer_text,
        next_question=result.get(
            "next_question"
        ),
        decision=result.get(
            "decision"
        ),
        competency_scores=result.get(
            "competency_scores",
            {},
        ),
        interview_score=result.get(
            "interview_score",
            0.0,
        ),
        interview_complete=result.get(
            "interview_complete",
            False,
        ),
        identity_verified=result.get(
            "identity_verified",
            False,
        ),
    )

    if idem_key:
        if "_idempotency_cache" not in result:
            result["_idempotency_cache"] = {}
        result["_idempotency_cache"][idem_key] = resp.model_dump()

    if frame_path:
        result["current_live_frame"] = None
    registry.update(
        session_id,
        result,
    )

    _persist_application_interview_state(db, session_id, result)
    if frame_path:
        Path(frame_path).unlink(missing_ok=True)

    if current_user.role == "candidate" and not result.get("identity_verified", False):
        raise HTTPException(
            status_code=403,
            detail=result.get("identity_failure_reason") or "Identity verification did not pass.",
        )

    from app.core.audit import get_audit_service
    get_audit_service().record_event(
        actor_id=current_user.id,
        actor_role=current_user.role,
        action="ANSWER_SUBMITTED",
        resource_type="INTERVIEW_SESSION",
        resource_id=session_id,
        candidate_id=result.get("candidate_id"),
        result="SUCCESS",
        metadata={"turn_number": result.get("turn_number")},
    )
    if result.get("interview_complete", False):
        get_audit_service().record_event(
            actor_id=current_user.id,
            actor_role=current_user.role,
            action="INTERVIEW_COMPLETED",
            resource_type="INTERVIEW_SESSION",
            resource_id=session_id,
            candidate_id=result.get("candidate_id"),
            result="SUCCESS",
            metadata={"final_score": result.get("interview_score")},
        )

    return resp



@router.post(
    "/{session_id}/audio",
    dependencies=[Depends(rate_limit(limit=20, window_seconds=60, key_prefix="interview_audio"))],
)
async def submit_audio_answer(
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    live_frame: Optional[UploadFile] = File(None),
    sync: bool = Query(False),
    idempotency_key: Optional[str] = Query(None),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    job_queue: JobQueue = Depends(get_job_queue),
    job_worker: JobWorker = Depends(get_job_worker),
):
    try:
        state = registry.get(session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Interview session not found: {session_id}",
        )

    # Enforce session ownership (Requirement F3.2)
    verify_session_candidate_access(session_id, current_user, db)
    _enforce_scheduled_deadline(state, session_id, db)

    if state.get("interview_complete", False):
        raise HTTPException(
            status_code=409,
            detail="Interview is already complete.",
        )

    # Enforce identity gate (Requirement F4.4)
    ident_status = state.get("identity_status")
    if ident_status == "review":
        raise HTTPException(
            status_code=403,
            detail="Identity verification is under review. Interview progression held.",
        )
    elif ident_status == "failed":
        raise HTTPException(
            status_code=403,
            detail="Identity verification failed. Interview blocked.",
        )
    elif ident_status == "pending" and current_user.role == "candidate":
        raise HTTPException(
            status_code=403,
            detail="Identity verification pending. Must complete identity verification first.",
        )
    if current_user.role == "candidate" and not live_frame:
        raise HTTPException(status_code=422, detail="A live camera frame is required with each interview answer.")

    # 1. Validate audio upload bytes before storage
    content = await audio.read()
    audio_validation = validate_audio_upload(content, filename=audio.filename, content_type=audio.content_type)

    # 2. Check Idempotency (prevent duplicate turns)
    idem_key = (
        idempotency_key
        or request.headers.get("Idempotency-Key")
        or request.headers.get("X-Idempotency-Key")
    )
    if idem_key:
        existing_job = job_queue.find_by_idempotency_key(session_id, idem_key)
        if existing_job:
            return JSONResponse(
                status_code=200 if existing_job.status == JobStatus.COMPLETED.value else 202,
                content={
                    "job_id": existing_job.id,
                    "status": existing_job.status.lower(),
                    "result": existing_job.result,
                },
            )

    # 3. Save audio file
    turn_num = state.get("turn_number", 1)
    storage = StorageManager()
    audio_save_path = storage.get_audio_path(session_id, f"turn_{turn_num}_{uuid.uuid4().hex}.{audio_validation.audio_format}")
    audio_save_path.write_bytes(content)
    live_image_path = None
    if live_frame:
        try:
            frame_bytes = await live_frame.read()
            decoded_frame = validate_image_upload(frame_bytes, filename=live_frame.filename, content_type=live_frame.content_type)
            frame_ok, encoded_frame = cv2.imencode(".jpg", decoded_frame)
            if not frame_ok:
                raise HTTPException(status_code=422, detail="Could not process the live camera frame.")
            live_image_path = storage.get_identity_path(state.get("candidate_id", "unknown"), f"live_{uuid.uuid4().hex}.jpg")
            live_image_path.write_bytes(encoded_frame.tobytes())
        except Exception:
            audio_save_path.unlink(missing_ok=True)
            if live_image_path:
                live_image_path.unlink(missing_ok=True)
            raise

    # 4. Synchronous fallback mode if requested
    is_sync = sync or request.headers.get("X-Sync", "").lower() == "true"
    if is_sync:
        try:
            res = controller.submit_audio(state, str(audio_save_path), live_image=str(live_image_path) if live_image_path else None)
        except (STTUnavailableException, LLMUnavailableException, ServiceUnavailableException):
            audio_save_path.unlink(missing_ok=True)
            if live_image_path:
                live_image_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            audio_save_path.unlink(missing_ok=True)
            if live_image_path:
                live_image_path.unlink(missing_ok=True)
            err = str(exc).lower()
            if "stt" in err or "whisper" in err or "audio" in err:
                raise STTUnavailableException(f"STT speech recognition error: {exc}")
            if "llm" in err or "timeout" in err:
                raise LLMUnavailableException(f"LLM service error: {exc}")
            raise

        if live_image_path:
            res["state"]["current_live_frame"] = None
        registry.update(session_id, res["state"])
        _persist_application_interview_state(db, session_id, res["state"])
        audio_save_path.unlink(missing_ok=True)
        if live_image_path:
            live_image_path.unlink(missing_ok=True)

        return InterviewResponse(
            session_id=res["state"]["session_id"],
            candidate_id=res["state"]["candidate_id"],
            transcript=res["transcript"],
            next_question=res.get("next_question"),
            decision=res["state"].get("decision"),
            competency_scores=res["state"].get("competency_scores", {}),
            interview_score=res["state"].get("interview_score", 0.0),
            interview_complete=res["state"].get("interview_complete", False),
            identity_verified=res["state"].get("identity_verified", True),
        )

    # 5. Default Async Background Job Creation (D4)
    job_id = f"JOB_{uuid.uuid4().hex[:8]}"
    job = Job(
        id=job_id,
        type=JobType.INTERVIEW_AUDIO.value,
        status=JobStatus.QUEUED.value,
        session_id=session_id,
        candidate_id=state.get("candidate_id"),
        idempotency_key=idem_key,
        payload={
            "audio_path": str(audio_save_path),
            "live_image": str(live_image_path) if live_image_path else None,
            "session_id": session_id,
            "turn_number": turn_num,
        },
    )
    job_queue.enqueue(job)

    # Dispatch to background task runner
    background_tasks.add_task(job_worker.process_job, job.id)

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.id,
            "status": "queued",
        },
    )


@router.post("/{session_id}/finish", response_model=InterviewResponse)
def finish_interview(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        state = registry.get(session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Interview session not found: {session_id}",
        )

    verify_session_candidate_access(session_id, current_user, db)
    _enforce_scheduled_deadline(state, session_id, db)

    state["interview_complete"] = True

    final_result = controller.session_manager.build_result(state)

    state["interview_score"] = final_result.get("interview_score", 0.0)
    registry.update(session_id, state)
    _persist_application_interview_state(db, session_id, state)

    return InterviewResponse(
        session_id=final_result["session_id"],
        candidate_id=final_result["candidate_id"],
        next_question=None,
        decision=state.get("decision"),
        competency_scores=final_result.get("competency_scores", {}),
        interview_score=final_result.get("interview_score", 0.0),
        interview_complete=True,
        identity_verified=final_result.get("identity_verified", True),
    )


@router.get(
    "/{session_id}",
)
def get_interview(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_session_candidate_access(session_id, current_user, db)
    _reject_completed_candidate_session(session_id, current_user, db)

    try:

        state = registry.get(
            session_id
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    state = _restore_stale_identity_completion_flag(db, session_id, state)
    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if current_user.role == "candidate" and (
        state.get("interview_complete")
        or (session_record and session_record.status == "completed")
    ):
        raise HTTPException(status_code=410, detail="This interview is complete. Return to your application page.")

    # Replace known legacy résumé-style prompts for the pending turn so an
    # in-progress interview benefits from the improved technical question style.
    current_question = str(state.get("current_question") or "")
    legacy_resume_prompt = any(
        marker in current_question.casefold()
        for marker in (
            "can you describe one specific example from your experience",
            "walk me through a problem you solved with code",
            "a problem you solved with code that you're particularly proud",
            "tell me about your experience",
            "what experience do you have",
        )
    )
    if legacy_resume_prompt and not state.get("interview_complete"):
        competency = criterion_label(str(state.get("current_competency") or ""))
        replacement = generate_criterion_question(
            competency,
            state.get("coverage_phase", "horizontal"),
            state.get("candidate_answer", ""),
        )
        state["current_question"] = replacement
        state["next_question"] = replacement
        current_question = replacement
        registry._get_persistence().save(session_id, state)
        _persist_application_interview_state(db, session_id, state)

    return {
        "session_id": session_id,
        "candidate_id": state.get("candidate_id"),
        "current_question": current_question,
        "competency": state.get("current_competency"),
        "decision": state.get("decision"),
        "competency_scores": state.get("competency_scores", {}),
        "interview_complete": state.get("interview_complete", False),
        "identity_verified": state.get("identity_verified", False),
        "turn_number": state.get("turn_number", 1),
    }



@router.get(
    "/{session_id}/result",
)
def get_interview_result(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_session_candidate_access(session_id, current_user, db)

    session_record = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
    if current_user.role == "candidate" and session_record and session_record.status == "completed":
        raise HTTPException(status_code=403, detail="Interview results are available to the recruiter.")

    try:

        state = registry.get(
            session_id
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    if not state["interview_complete"]:

        raise HTTPException(
            status_code=409,
            detail="Interview is not complete.",
        )

    return controller.session_manager.build_result(
        state
    )


@router.get("/{session_id}/trace")
def get_interview_trace(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns AI decision traces for each turn of the interview."""
    verify_session_candidate_access(session_id, current_user, db)

    try:
        state = registry.get(session_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Interview session {session_id} not found",
        )

    traces = list(state.get("decision_traces", []))
    if not traces:
        for turn in state.get("conversation_history", []):
            if "trace" in turn:
                traces.append(turn["trace"])

    return {
        "session_id": session_id,
        "candidate_id": state.get("candidate_id"),
        "traces": traces,
        "turn_count": len(traces),
    }


@router.post(
    "/{session_id}/complete",
)
def complete_interview(
    session_id: str,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        state = registry.get(
            session_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    verify_session_candidate_access(session_id, current_user, db)

    if not state["interview_complete"]:

        raise HTTPException(
            status_code=409,
            detail="Interview is not complete.",
        )

    result = (
        controller.session_manager.build_result(
            state
        )
    )

    state["interview_score"] = result.get("interview_score")
    registry.update(session_id, state)
    _persist_application_interview_state(db, session_id, state)

    if getattr(controller, "workflow_resumer", None) is not None:
        resumer = controller.workflow_resumer
        job_id = state.get("job_id") or (
            state.get("candidate", {}).get("job_id")
            if isinstance(state.get("candidate"), dict)
            else None
        )
        if hasattr(resumer, "resume_interview") and job_id:
            try:
                resumer.resume_interview(job_id, result)
            except Exception:
                pass
        elif hasattr(resumer, "resume_after_interview") and hasattr(resumer, "persistence"):
            if job_id:
                try:
                    wf_state = resumer.persistence.load(job_id)
                    resumer.resume_after_interview(wf_state, result)
                except Exception:
                    pass
            else:
                try:
                    resumer.resume_after_interview(state, result)
                except Exception:
                    pass
        elif hasattr(resumer, "resume"):
            resumer.resume(session_id=session_id, result=result)
        elif callable(resumer):
            resumer(session_id, result)

    return result

@router.post("/{session_id}/answer/audio")
async def submit_audio_answer(
    session_id: str,
    audio: UploadFile = File(...),
    live_frame: Optional[UploadFile] = File(None),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        state = registry.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Interview session not found")
    verify_session_candidate_access(session_id, current_user, db)
    _reject_completed_candidate_session(session_id, current_user, db)
    _enforce_scheduled_deadline(state, session_id, db)
    state = _restore_stale_identity_completion_flag(db, session_id, state)
    if state.get("interview_complete", False):
        raise HTTPException(status_code=409, detail="Interview is already complete.")
    if current_user.role == "candidate" and state.get("identity_status") != "verified":
        raise HTTPException(status_code=403, detail="Complete face verification before submitting an answer.")
    if current_user.role == "candidate" and not live_frame:
        raise HTTPException(status_code=422, detail="A live camera frame is required with each interview answer.")

    audio_bytes = await audio.read()
    audio_validation = validate_audio_upload(audio_bytes, filename=audio.filename, content_type=audio.content_type)
    storage = StorageManager()
    audio_path = storage.get_audio_path(session_id, f"{uuid.uuid4().hex}.{audio_validation.audio_format}")
    audio_path.write_bytes(audio_bytes)
    frame_path = None
    if live_frame:
        try:
            frame_bytes = await live_frame.read()
            decoded_frame = validate_image_upload(frame_bytes, filename=live_frame.filename, content_type=live_frame.content_type)
            ok, encoded_frame = cv2.imencode(".jpg", decoded_frame)
            if not ok:
                raise HTTPException(status_code=422, detail="Could not process the live camera frame.")
            frame_path = storage.get_identity_path(state.get("candidate_id", "unknown"), f"live_{uuid.uuid4().hex}.jpg")
            frame_path.write_bytes(encoded_frame.tobytes())
        except Exception:
            audio_path.unlink(missing_ok=True)
            if frame_path:
                frame_path.unlink(missing_ok=True)
            raise

    # 1. Speech → text
    try:
        transcript = await run_in_threadpool(
            stt.transcribe,
            str(audio_path),
            _transcription_prompt(state),
        )
    except ValueError as exc:
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        if "empty transcription" in str(exc).lower():
            raise HTTPException(status_code=422, detail="No speech detected in audio. Please speak clearly into your microphone and try again.")
        logger.exception("Speech transcription failed for interview session %s", session_id)
        raise STTUnavailableException("Speech recognition failed. Please retry; if it continues, check that the speech model is installed and available.") from exc
    except ServiceUnavailableException:
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        logger.exception("Speech transcription failed for interview session %s", session_id)
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        raise STTUnavailableException("Speech recognition failed. Please retry; if it continues, check that the speech model is installed and available.") from exc

    # 2. Whisper transcript → interview agent
    try:
        updated_state = controller.submit_text(
            state=state,
            answer=transcript,
            live_image=str(frame_path) if frame_path else None,
        )
    except LLMUnavailableException:
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        logger.exception("AI evaluation failed after Whisper transcription for interview session %s", session_id)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Whisper captured your answer, but AI evaluation is temporarily unavailable. Your transcript is ready below so you can retry it as text.",
                "transcript": transcript,
                "stage": "ai_evaluation",
            },
        )
    except STTUnavailableException:
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        audio_path.unlink(missing_ok=True)
        if frame_path:
            frame_path.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        logger.exception("AI evaluation failed after Whisper transcription for interview session %s", session_id)
        err = str(exc).lower()
        if getattr(exc, "status_code", None) == 404 and "function" in err and "not found for account" in err:
            detail = (
                "Whisper transcribed your answer, but NVIDIA rejected the model request with "
                "404 Function not found for account. Check NVIDIA Build access for Public API "
                "Endpoints or generate a fresh API key from the Nemotron model page. Your "
                "transcript is available below; retry it as text after NVIDIA access is fixed."
            )
        else:
            detail = (
                "Whisper transcribed your answer, but the AI evaluation service failed. "
                "Your transcript is available below so you can retry it as text."
            )
        return JSONResponse(
            status_code=503,
            content={
                "detail": detail,
                "transcript": transcript,
                "stage": "ai_evaluation",
            },
        )

    # 3. Save updated session
    if frame_path:
        updated_state["current_live_frame"] = None
    registry.update(
        session_id,
        updated_state,
    )
    _persist_application_interview_state(db, session_id, updated_state)
    audio_path.unlink(missing_ok=True)
    if frame_path:
        frame_path.unlink(missing_ok=True)
    if current_user.role == "candidate" and not updated_state.get("identity_verified", False):
        raise HTTPException(status_code=403, detail=updated_state.get("identity_failure_reason") or "Identity verification did not pass.")

    if isinstance(updated_state, dict):
        question = updated_state.get("next_question") or updated_state.get("current_question")
        decision = updated_state.get("decision")
        complete = updated_state.get("interview_complete", False)
        turn_number = updated_state.get("turn_number", 1)
        competency_scores = updated_state.get("competency_scores", {})
    else:
        question = getattr(updated_state, "next_question", None) or getattr(updated_state, "current_question", None)
        decision = getattr(updated_state, "decision", None)
        complete = getattr(updated_state, "interview_complete", False)
        turn_number = getattr(updated_state, "turn_number", 1)
        competency_scores = getattr(updated_state, "competency_scores", {})

    return {
        "session_id": session_id,
        "transcript": transcript,
        "question": question,
        "next_question": question,
        "turn_number": turn_number,
        "competency_scores": competency_scores,
        "decision": decision,
        "complete": complete,
        "interview_complete": complete,
    }


@router.post("/{session_id}/answer/transcribe")
async def transcribe_answer(
    session_id: str,
    audio: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_session_candidate_access(session_id, current_user, db)
    audio_bytes = await audio.read()
    audio_validation = validate_audio_upload(audio_bytes, filename=audio.filename, content_type=audio.content_type)
    audio_path = StorageManager().get_audio_path(session_id, f"transcribe_{uuid.uuid4().hex}.{audio_validation.audio_format}")
    audio_path.write_bytes(audio_bytes)

    try:
        transcript = await run_in_threadpool(stt.transcribe, str(audio_path))
    except ValueError as exc:
        audio_path.unlink(missing_ok=True)
        if "empty transcription" in str(exc).lower():
            raise HTTPException(status_code=422, detail="No speech detected in audio. Please speak clearly into your microphone and try again.")
        logger.exception("Speech transcription failed for interview session %s", session_id)
        raise STTUnavailableException("Speech recognition failed. Please retry; if it continues, check that the speech model is installed and available.") from exc
    except ServiceUnavailableException:
        audio_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        logger.exception("Speech transcription failed for interview session %s", session_id)
        audio_path.unlink(missing_ok=True)
        raise STTUnavailableException("Speech recognition failed. Please retry; if it continues, check that the speech model is installed and available.") from exc

    audio_path.unlink(missing_ok=True)
    return {
        "session_id": session_id,
        "transcript": transcript,
    }
