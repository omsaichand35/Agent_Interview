"""Recruiter-created interview batches, persistent rosters, and student schedules."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.auth_dependencies import require_roles
from app.config import refresh_smtp_settings, settings
from app.database.connection import get_db
from app.database.models import (
    ApplicationModel,
    InterviewInviteModel,
    InterviewScheduleBatchModel,
    InterviewScheduleModel,
    ProgramRecruiterAccessModel,
)
from app.models.user import Role, UserResponse

router = APIRouter(prefix="/schedules", tags=["Schedules"])


class ScheduleBatchRequest(BaseModel):
    program_id: str = Field(min_length=1, max_length=64)
    selection: Literal["top_n", "min_score"]
    top_n: int | None = Field(default=None, ge=1, le=10_000)
    min_score: float | None = Field(default=None, ge=0, le=100)
    first_slot_start: AwareDatetime
    timezone: str = Field(min_length=1, max_length=64)
    slot_duration_minutes: int = Field(ge=5, le=480)
    people_per_slot: int = Field(ge=1, le=500)
    number_of_slots: int = Field(ge=1, le=500)

    @model_validator(mode="after")
    def validate_rule(self):
        if self.selection == "top_n" and self.top_n is None:
            raise ValueError("top_n is required for top_n selection")
        if self.selection == "min_score" and self.min_score is None:
            raise ValueError("min_score is required for min_score selection")
        if self.people_per_slot * self.number_of_slots > 20_000:
            raise ValueError("A schedule batch cannot exceed 20,000 seats")
        return self


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ensure_schedule_open(placement: InterviewScheduleModel, session_id: str, now: datetime | None = None) -> None:
    if placement.session_id != session_id:
        raise HTTPException(status_code=403, detail="This interview code does not match the scheduled interview.")
    if placement.status not in {"scheduled", "joined", "completed"}:
        raise HTTPException(status_code=409, detail="This interview schedule is no longer active. Contact your recruiter.")
    start = _aware_utc(placement.scheduled_start)
    current = _aware_utc(now or datetime.now(timezone.utc))
    if current < start:
        raise HTTPException(status_code=403, detail="Your interview slot has not opened yet. Return when the countdown reaches zero.")
    if current >= _aware_utc(placement.scheduled_end):
        raise HTTPException(status_code=410, detail="Your interview slot has ended. Contact your recruiter if you need more time.")


def _program_access(program_id: str, user: UserResponse, db: Session) -> None:
    if user.role == Role.ADMIN.value:
        return
    access = db.query(ProgramRecruiterAccessModel.id).filter(
        ProgramRecruiterAccessModel.program_id == program_id,
        ProgramRecruiterAccessModel.recruiter_id == user.id,
    ).first()
    if not access:
        raise HTTPException(status_code=403, detail="This program belongs to another recruiter workspace.")


def _schedule_payload(schedule: InterviewScheduleModel) -> dict:
    app = schedule.application
    batch = schedule.batch
    candidate = app.candidate if app else None
    return {
        "schedule_id": schedule.id,
        "application_id": schedule.application_id,
        "candidate_id": app.candidate_id if app else None,
        "candidate_name": candidate.name if candidate else None,
        "candidate_email": candidate.email if candidate else None,
        "resume_score": app.resume_score if app else None,
        "program_id": app.program_id if app else batch.program_id,
        "program_title": batch.program.title if batch and batch.program else None,
        "batch_id": batch.id if batch else None,
        "slot_number": schedule.slot_number,
        "scheduled_start": _aware_utc(schedule.scheduled_start).isoformat(),
        "scheduled_end": _aware_utc(schedule.scheduled_end).isoformat(),
        "timezone": batch.timezone if batch else "UTC",
        "status": schedule.status,
        "reminder_sent_at": _aware_utc(schedule.reminder_sent_at).isoformat() if schedule.reminder_sent_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_schedule_batch(
    payload: ScheduleBatchRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    """Rank eligible applications, fill capacity-limited slots, and email each student."""
    refresh_smtp_settings()
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="Use a valid IANA timezone, such as Asia/Kolkata.") from exc

    first_start = _aware_utc(payload.first_slot_start)
    now = datetime.now(timezone.utc)
    if first_start <= now + timedelta(minutes=1):
        raise HTTPException(status_code=422, detail="The first slot must start at least one minute in the future.")

    _program_access(payload.program_id, current_user, db)
    applications_query = db.query(ApplicationModel).filter(
        ApplicationModel.program_id == payload.program_id,
        ApplicationModel.status.in_(["submitted", "resume_scored", "shortlisted", "interview_authorized"]),
        ApplicationModel.resume_score.is_not(None),
    )
    if payload.selection == "min_score":
        applications_query = applications_query.filter(ApplicationModel.resume_score >= payload.min_score)
    applications = applications_query.order_by(
        ApplicationModel.resume_score.desc(),
        ApplicationModel.created_at.asc(),
        ApplicationModel.id.asc(),
    ).all()

    if not applications:
        raise HTTPException(status_code=409, detail="No scored applications match this scheduling rule.")

    existing_schedule_ids = {
        row[0] for row in db.query(InterviewScheduleModel.application_id).filter(
            InterviewScheduleModel.application_id.in_([app.id for app in applications]),
            InterviewScheduleModel.status.in_(["scheduled", "joined"]),
        ).all()
    }
    applications = [app for app in applications if app.id not in existing_schedule_ids]
    if payload.selection == "top_n":
        applications = applications[:payload.top_n]
    capacity = payload.people_per_slot * payload.number_of_slots
    eligible_count = len(applications)
    applications = applications[:capacity]
    if not applications:
        raise HTTPException(status_code=409, detail="All matching students already have an active interview schedule.")

    batch_id = f"SCHB_{uuid4().hex[:16].upper()}"
    batch = InterviewScheduleBatchModel(
        id=batch_id,
        program_id=payload.program_id,
        created_by=current_user.id,
        first_slot_start=first_start,
        timezone=payload.timezone,
        slot_duration_minutes=payload.slot_duration_minutes,
        people_per_slot=payload.people_per_slot,
        number_of_slots=payload.number_of_slots,
        selection_rule={
            "selection": payload.selection,
            "top_n": payload.top_n,
            "min_score": payload.min_score,
        },
    )
    db.add(batch)
    db.flush()

    invite_rows = db.query(InterviewInviteModel).filter(
        InterviewInviteModel.application_id.in_([app.id for app in applications]),
        InterviewInviteModel.revoked_at.is_(None),
    ).order_by(InterviewInviteModel.created_at.desc()).all()
    invites_by_application: dict[str, list[InterviewInviteModel]] = {}
    for invite in invite_rows:
        invites_by_application.setdefault(invite.application_id, []).append(invite)

    from app.services.email_service import send_scheduled_interview_batch_emails

    roster = []
    scheduled_emails = []
    for index, application in enumerate(applications):
        candidate = application.candidate
        email_ready = bool(settings.smtp_host and settings.smtp_from_email)
        if not candidate or (email_ready and not candidate.email):
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Application {application.id} has no student email address.")

        slot_number = index // payload.people_per_slot + 1
        slot_start = first_start + timedelta(minutes=(slot_number - 1) * payload.slot_duration_minutes)
        slot_end = slot_start + timedelta(minutes=payload.slot_duration_minutes)
        existing_invites = invites_by_application.get(application.id, [])
        redeemed_invite = next((invite for invite in existing_invites if invite.redeemed_at is not None), None)
        code = None
        if redeemed_invite:
            session_id = redeemed_invite.session_id
        else:
            for old_invite in existing_invites:
                old_invite.revoked_at = now
            code = secrets.token_hex(8).upper()
            session_id = f"INT_{uuid4().hex[:16].upper()}"
            invite_expiry = max(now + timedelta(days=7), slot_end + timedelta(days=1))
            db.add(InterviewInviteModel(
                application_id=application.id,
                code_hash=hashlib.sha256(code.encode("ascii")).hexdigest(),
                session_id=session_id,
                created_by=current_user.id,
                expires_at=invite_expiry,
            ))
            application.status = "shortlisted"

        placement = InterviewScheduleModel(
            id=f"SCH_{uuid4().hex[:16].upper()}",
            batch_id=batch_id,
            application_id=application.id,
            session_id=session_id,
            slot_number=slot_number,
            scheduled_start=slot_start,
            scheduled_end=slot_end,
            status="scheduled",
        )
        db.add(placement)
        roster.append({
            "application_id": application.id,
            "candidate_name": candidate.name,
            "candidate_email": candidate.email,
            "resume_score": application.resume_score,
            "slot_number": slot_number,
            "scheduled_start": slot_start.isoformat(),
            "scheduled_end": slot_end.isoformat(),
            "timezone": payload.timezone,
        })
        if candidate.email:
            scheduled_emails.append((
                candidate.email,
                candidate.name,
                batch.program.title,
                slot_start.isoformat(),
                payload.timezone,
                slot_number,
                code,
            ))

    email_ready = bool(settings.smtp_host and settings.smtp_from_email)
    if email_ready:
        background_tasks.add_task(
            send_scheduled_interview_batch_emails,
            scheduled_emails,
            {
                "to_email": current_user.email,
                "program_title": batch.program.title,
                "batch_id": batch_id,
                "timezone": payload.timezone,
                "selection_rule": batch.selection_rule,
                "roster": roster,
            },
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "batch_id": batch_id,
        "program_id": payload.program_id,
        "program_title": batch.program.title,
        "candidate_count": len(roster),
        "eligible_count": eligible_count,
        "capacity_skipped_count": eligible_count - len(roster),
        "requested_slots": payload.number_of_slots,
        "slots_used": max(item["slot_number"] for item in roster),
        "people_per_slot": payload.people_per_slot,
        "slot_duration_minutes": payload.slot_duration_minutes,
        "timezone": payload.timezone,
        "selection_rule": batch.selection_rule,
        "roster": roster,
        "message": f"Schedule created for {len(roster)} student(s) across {max(item['slot_number'] for item in roster)} slot(s).",
    }


@router.get("")
def list_schedules(
    program_id: str | None = None,
    current_user: UserResponse = Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value)),
    db: Session = Depends(get_db),
):
    query = db.query(InterviewScheduleBatchModel).order_by(InterviewScheduleBatchModel.created_at.desc())
    if program_id:
        _program_access(program_id, current_user, db)
        query = query.filter(InterviewScheduleBatchModel.program_id == program_id)
    elif current_user.role != Role.ADMIN.value:
        managed = db.query(ProgramRecruiterAccessModel.program_id).filter(
            ProgramRecruiterAccessModel.recruiter_id == current_user.id
        )
        query = query.filter(InterviewScheduleBatchModel.program_id.in_(managed))

    batches = query.all()
    return [{
        "batch_id": batch.id,
        "program_id": batch.program_id,
        "program_title": batch.program.title if batch.program else None,
        "created_at": _aware_utc(batch.created_at).isoformat(),
        "first_slot_start": _aware_utc(batch.first_slot_start).isoformat(),
        "timezone": batch.timezone,
        "slot_duration_minutes": batch.slot_duration_minutes,
        "people_per_slot": batch.people_per_slot,
        "number_of_slots": batch.number_of_slots,
        "selection_rule": batch.selection_rule,
        "roster": [_schedule_payload(item) for item in sorted(batch.placements, key=lambda x: (x.slot_number, x.scheduled_start))],
    } for batch in batches]


def list_candidate_schedules(candidate_id: str, db: Session) -> dict[str, dict]:
    schedules = db.query(InterviewScheduleModel).join(ApplicationModel).filter(
        ApplicationModel.candidate_id == candidate_id,
        InterviewScheduleModel.status.in_(["scheduled", "joined"]),
    ).order_by(InterviewScheduleModel.scheduled_start.asc()).all()
    return {item.application_id: {
        "schedule_id": item.id,
        "batch_id": item.batch_id,
        "slot_number": item.slot_number,
        "scheduled_start": _aware_utc(item.scheduled_start).isoformat(),
        "scheduled_end": _aware_utc(item.scheduled_end).isoformat(),
        "timezone": item.batch.timezone if item.batch else "UTC",
        "status": item.status,
    } for item in schedules}


async def scheduling_reminder_loop():
    """Send each scheduled student's reminder when their start time is within 10 minutes."""
    import asyncio
    import logging

    from app.services.email_service import send_schedule_reminder_email

    logger = logging.getLogger("scheduling.reminders")
    while True:
        try:
            refresh_smtp_settings()
            if settings.smtp_host and settings.smtp_from_email:
                await asyncio.to_thread(_send_due_schedule_reminders, send_schedule_reminder_email, logger)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Schedule reminder run failed")
        await asyncio.sleep(30)


def _send_due_schedule_reminders(send_email, logger=None) -> int:
    from app.database.connection import SessionLocal

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    sent = 0
    try:
        due = db.query(InterviewScheduleModel).filter(
            InterviewScheduleModel.status == "scheduled",
            InterviewScheduleModel.scheduled_start > now,
            InterviewScheduleModel.scheduled_start <= now + timedelta(minutes=10),
            InterviewScheduleModel.reminder_sent_at.is_(None),
            (InterviewScheduleModel.reminder_claimed_at.is_(None)) | (
                InterviewScheduleModel.reminder_claimed_at < now - timedelta(minutes=2)
            ),
        ).all()
        for placement in due:
            claimed = db.query(InterviewScheduleModel).filter(
                InterviewScheduleModel.id == placement.id,
                InterviewScheduleModel.reminder_sent_at.is_(None),
                (InterviewScheduleModel.reminder_claimed_at.is_(None)) | (
                    InterviewScheduleModel.reminder_claimed_at < now - timedelta(minutes=2)
                ),
            ).update({InterviewScheduleModel.reminder_claimed_at: now}, synchronize_session=False)
            db.commit()
            if claimed != 1:
                continue
            application = db.query(ApplicationModel).filter(ApplicationModel.id == placement.application_id).first()
            candidate = application.candidate if application else None
            batch = db.query(InterviewScheduleBatchModel).filter(InterviewScheduleBatchModel.id == placement.batch_id).first()
            delivered = bool(candidate and candidate.email and batch and send_email(
                candidate.email,
                candidate.name,
                batch.program.title if batch.program else "your interview",
                _aware_utc(placement.scheduled_start).isoformat(),
                batch.timezone,
            ))
            if delivered:
                db.query(InterviewScheduleModel).filter(InterviewScheduleModel.id == placement.id).update(
                    {InterviewScheduleModel.reminder_sent_at: now}, synchronize_session=False
                )
                sent += 1
            else:
                db.query(InterviewScheduleModel).filter(InterviewScheduleModel.id == placement.id).update(
                    {InterviewScheduleModel.reminder_claimed_at: None}, synchronize_session=False
                )
            db.commit()
        return sent
    finally:
        db.close()
