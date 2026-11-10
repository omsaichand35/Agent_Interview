from datetime import datetime, timedelta, timezone
import smtplib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.scheduling_routes import _send_due_schedule_reminders, ensure_schedule_open
from app.config import settings
from app.core.security import create_access_token
from app.database.connection import get_db_context
from app.database.models import (
    ApplicationModel,
    CandidateModel,
    InterviewSessionModel,
    InterviewScheduleBatchModel,
    InterviewScheduleModel,
    JobModel,
    ProgramRecruiterAccessModel,
    UserModel,
)
from app.main import app
from app.services import email_service


def _seed_recruiter_program_and_apps(count=5):
    suffix = uuid4().hex[:10].upper()
    recruiter_id = f"USR_{suffix}"
    program_id = f"JOB_{suffix}"
    with get_db_context() as db:
        db.add(UserModel(
            id=recruiter_id,
            email=f"recruiter-{suffix.lower()}@example.test",
            password_hash="unused",
            role="recruiter",
        ))
        program = JobModel(
            id=program_id,
            title="Scheduling sample",
            department="Engineering",
            description="Sample scheduling test program",
            required_skills=["Python"],
            status="OPEN",
        )
        db.add(program)
        db.add(ProgramRecruiterAccessModel(program_id=program_id, recruiter_id=recruiter_id))
        for index in range(count):
            candidate_id = f"C_{suffix}_{index}"
            db.add(UserModel(
                id=f"USR_{suffix}_{index}",
                email=f"student{index + 1}-{suffix.lower()}@example.test",
                password_hash="unused",
                role="candidate",
                candidate_id=candidate_id,
            ))
            candidate = CandidateModel(
                id=candidate_id,
                name=f"Student {index + 1}",
                email=f"student{index + 1}-{suffix.lower()}@example.test",
                status="APPLIED",
            )
            db.add(candidate)
            db.add(ApplicationModel(
                id=f"APP_{suffix}_{index}",
                candidate_id=candidate_id,
                program_id=program_id,
                face_reference_path="unused.jpg",
                biometric_consent_at=datetime.now(timezone.utc),
                biometric_consent_version="test-consent",
                status="submitted",
                resume_score=max(0, 100 - index),
            ))
    token = create_access_token(user_id=recruiter_id, role="recruiter")
    candidate_token = create_access_token(
        user_id=f"USR_{suffix}_0",
        role="candidate",
        candidate_id=f"C_{suffix}_0",
    )
    return recruiter_id, program_id, token, candidate_token


def test_schedule_batch_ranks_assigns_and_emails_students(monkeypatch):
    recruiter_id, program_id, token, candidate_token = _seed_recruiter_program_and_apps()
    calls = []
    recruiter_reports = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
    def capture_schedule_emails(messages, recruiter_report=None):
        calls.extend(messages)
        recruiter_reports.append(recruiter_report)
        return len(messages) + bool(recruiter_report)

    monkeypatch.setattr(email_service, "send_scheduled_interview_batch_emails", capture_schedule_emails)
    payload = {
        "program_id": program_id,
        "selection": "top_n",
        "top_n": 5,
        "first_slot_start": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "timezone": "Asia/Kolkata",
        "slot_duration_minutes": 30,
        "people_per_slot": 2,
        "number_of_slots": 3,
    }

    with TestClient(app) as client:
        response = client.post("/schedules", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["candidate_count"] == 5
        assert body["slots_used"] == 3
        assert [item["slot_number"] for item in body["roster"]] == [1, 1, 2, 2, 3]
        assert [item["resume_score"] for item in body["roster"]] == [100, 99, 98, 97, 96]

        roster_response = client.get(f"/schedules?program_id={program_id}", headers={"Authorization": f"Bearer {token}"})
        assert roster_response.status_code == 200
        assert len(roster_response.json()[0]["roster"]) == 5
        student_headers = {"Authorization": f"Bearer {candidate_token}"}
        student_apps = client.get("/applications/mine", headers=student_headers).json()
        student_app = next(item for item in student_apps if item["application_id"] == body["roster"][0]["application_id"])
        assert student_app["schedule"]["slot_number"] == 1
        assert student_app["interview_url"] is None
        code = calls[0][6]
        redeemed = client.post("/applications/redeem-interview-code", json={"code": code}, headers=student_headers)
        assert redeemed.status_code == 200
        assert redeemed.json()["interview_url"] == "/student"
        refreshed = client.get("/applications/mine", headers=student_headers).json()
        student_app = next(item for item in refreshed if item["application_id"] == student_app["application_id"])
        session_id = student_app["interview_url"].split("session_id=")[1]
        early_join = client.post("/interview/start", json={
            "application_id": student_app["application_id"],
            "session_id": session_id,
        }, headers=student_headers)
        assert early_join.status_code == 403
        assert "countdown reaches zero" in early_join.json()["detail"]

    assert len(calls) == 5
    assert recruiter_reports[0]["to_email"].startswith("recruiter-")
    assert len(recruiter_reports[0]["roster"]) == 5


def test_schedule_is_created_even_when_smtp_is_not_configured(monkeypatch):
    from fastapi import BackgroundTasks
    from app.api.scheduling_routes import ScheduleBatchRequest, create_schedule_batch
    from app.models.user import UserResponse

    recruiter_id, program_id, _, _ = _seed_recruiter_program_and_apps(count=1)
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from_email", "")
    payload = ScheduleBatchRequest(
        program_id=program_id,
        selection="top_n",
        top_n=1,
        first_slot_start=datetime.now(timezone.utc) + timedelta(hours=2),
        timezone="Asia/Kolkata",
        slot_duration_minutes=30,
        people_per_slot=1,
        number_of_slots=1,
    )
    background_tasks = BackgroundTasks()
    recruiter = UserResponse(
        id=recruiter_id,
        email=f"recruiter-{recruiter_id.removeprefix('USR_').lower()}@example.test",
        role="recruiter",
    )

    with get_db_context() as db:
        result = create_schedule_batch(payload, background_tasks, recruiter, db)
        roster = db.query(InterviewScheduleModel).filter_by(batch_id=result["batch_id"]).all()
        assert result["candidate_count"] == 1
        assert result["message"].startswith("Schedule created")
        assert len(roster) == 1
        assert background_tasks.tasks == []


def test_schedule_batch_assigns_hundreds_with_capacity_limit(monkeypatch):
    _, program_id, token, _ = _seed_recruiter_program_and_apps(count=101)
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
    sent = []

    def capture(messages, recruiter_report=None):
        sent.extend(messages)
        assert recruiter_report is not None
        assert len(recruiter_report["roster"]) == 100
        return len(messages) + 1

    monkeypatch.setattr(email_service, "send_scheduled_interview_batch_emails", capture)
    payload = {
        "program_id": program_id,
        "selection": "top_n",
        "top_n": 101,
        "first_slot_start": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "timezone": "Asia/Kolkata",
        "slot_duration_minutes": 30,
        "people_per_slot": 10,
        "number_of_slots": 10,
    }
    with TestClient(app) as client:
        response = client.post("/schedules", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["candidate_count"] == 100
    assert result["eligible_count"] == 101
    assert result["capacity_skipped_count"] == 1
    assert result["slots_used"] == 10
    assert [sum(row["slot_number"] == slot for row in result["roster"]) for slot in range(1, 11)] == [10] * 10
    assert len(sent) == 100


def test_min_score_batch_caps_at_capacity_in_score_order(monkeypatch):
    _, program_id, token, _ = _seed_recruiter_program_and_apps()
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
    monkeypatch.setattr(email_service, "send_scheduled_interview_batch_emails", lambda messages, recruiter_report=None: len(messages))
    payload = {
        "program_id": program_id,
        "selection": "min_score",
        "min_score": 96,
        "first_slot_start": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "timezone": "UTC",
        "slot_duration_minutes": 30,
        "people_per_slot": 1,
        "number_of_slots": 2,
    }
    with TestClient(app) as client:
        response = client.post("/schedules", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 201, response.text
    assert response.json()["candidate_count"] == 2
    assert response.json()["eligible_count"] == 5
    assert response.json()["capacity_skipped_count"] == 3
    assert [item["resume_score"] for item in response.json()["roster"]] == [100, 99]


def test_scheduled_interview_cannot_be_joined_before_its_slot():
    placement = SimpleNamespace(
        session_id="INT_SAMPLE",
        status="scheduled",
        scheduled_start=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    with pytest.raises(HTTPException) as exc_info:
        ensure_schedule_open(placement, "INT_SAMPLE")
    assert exc_info.value.status_code == 403
    assert "countdown reaches zero" in exc_info.value.detail


def test_completed_scheduled_interview_can_be_reviewed_after_slot():
    placement = SimpleNamespace(
        session_id="INT_SAMPLE",
        status="completed",
        scheduled_start=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    ensure_schedule_open(placement, "INT_SAMPLE")


def test_schedule_reminder_is_sent_once_for_due_placement():
    suffix = uuid4().hex[:10].upper()
    recruiter_id = f"USR_{suffix}"
    program_id = f"JOB_{suffix}"
    candidate_id = f"C_{suffix}"
    application_id = f"APP_{suffix}"
    batch_id = f"SCHB_{suffix}"
    schedule_id = f"SCH_{suffix}"
    with get_db_context() as db:
        db.add(UserModel(id=recruiter_id, email=f"r-{suffix}@example.test", password_hash="x", role="recruiter"))
        db.add(JobModel(id=program_id, title="Reminder sample", department="Engineering", required_skills=["Python"]))
        db.add(CandidateModel(id=candidate_id, name="Reminder Student", email=f"s-{suffix}@example.test"))
        db.add(ApplicationModel(
            id=application_id,
            candidate_id=candidate_id,
            program_id=program_id,
            face_reference_path="unused.jpg",
            biometric_consent_at=datetime.now(timezone.utc),
            biometric_consent_version="test-consent",
            status="interview_authorized",
            resume_score=90,
        ))
        db.add(InterviewScheduleBatchModel(
            id=batch_id,
            program_id=program_id,
            created_by=recruiter_id,
            first_slot_start=datetime.now(timezone.utc) + timedelta(minutes=5),
            timezone="UTC",
            slot_duration_minutes=30,
            people_per_slot=1,
            number_of_slots=1,
            selection_rule={"selection": "top_n", "top_n": 1},
        ))
        db.add(InterviewScheduleModel(
            id=schedule_id,
            batch_id=batch_id,
            application_id=application_id,
            session_id="INT_REMINDER_SAMPLE",
            slot_number=1,
            scheduled_start=datetime.now(timezone.utc) + timedelta(minutes=5),
            scheduled_end=datetime.now(timezone.utc) + timedelta(minutes=35),
            status="scheduled",
        ))
    calls = []
    send = lambda *args: calls.append(args) or True
    assert _send_due_schedule_reminders(send) == 1
    assert _send_due_schedule_reminders(send) == 0
    assert len(calls) == 1


def test_schedule_email_batch_contains_student_codes_and_recruiter_csv(monkeypatch):
    captured = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            captured.append(message)

    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    messages = [(
        "student@example.test",
        "Sample Student",
        "Sample Program",
        (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "Asia/Kolkata",
        1,
        "ABCDEF0123456789",
    )]
    report = {
        "to_email": "recruiter@example.test",
        "program_title": "Sample Program",
        "batch_id": "SCHB_SAMPLE",
        "timezone": "Asia/Kolkata",
        "selection_rule": {"selection": "top_n", "top_n": 1},
        "roster": [{
            "candidate_name": "Sample Student",
            "candidate_email": "student@example.test",
            "resume_score": 91,
            "slot_number": 1,
            "scheduled_start": messages[0][3],
            "scheduled_end": messages[0][3],
            "timezone": "Asia/Kolkata",
        }],
    }

    sent = email_service.send_scheduled_interview_batch_emails(messages, report)
    assert sent == 2
    assert captured[0]["To"] == "student@example.test"
    assert "ABCDEF0123456789" in captured[0].get_content()
    assert captured[1]["To"] == "recruiter@example.test"
    attachment = next(captured[1].iter_attachments())
    assert attachment.get_filename() == "interview-roster-SCHB_SAMPLE.csv"
    assert "Sample Student" in attachment.get_payload(decode=True).decode("utf-8")


def test_schedule_email_batch_reconnects_for_large_audience(monkeypatch):
    class FakeSMTP:
        connections = 0
        sent = 0

        def __init__(self, *args, **kwargs):
            type(self).connections += 1

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send_message(self, message):
            type(self).sent += 1

    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    start = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    messages = [
        (f"student{index}@example.test", f"Student {index}", "Sample Program", start, "UTC", 1, None)
        for index in range(101)
    ]

    assert email_service.send_scheduled_interview_batch_emails(messages) == 101
    assert FakeSMTP.connections == 3
    assert FakeSMTP.sent == 101


def test_completed_interview_report_stays_in_recruiter_table_and_is_per_application(monkeypatch):
    from app.api.application_routes import get_application_interview
    from app.api.interview_routes import _persist_application_interview_state
    from app.models.user import UserResponse

    class FakeSMTP:
        sent = []

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def send_message(self, message):
            self.sent.append(message)

    suffix = uuid4().hex[:10].upper()
    recruiter_id = f"USR_REPORT_{suffix}"
    program_id = f"JOB_REPORT_{suffix}"
    applicants = []
    with get_db_context() as db:
        db.add(UserModel(id=recruiter_id, email=f"recruiter-{suffix.lower()}@example.test", password_hash="unused", role="recruiter"))
        db.add(JobModel(id=program_id, title="Report program", department="Engineering", description="Report test program"))
        db.add(ProgramRecruiterAccessModel(program_id=program_id, recruiter_id=recruiter_id))
        for index in range(2):
            candidate_id = f"C_REPORT_{suffix}_{index}"
            application_id = f"APP_REPORT_{suffix}_{index}"
            session_id = f"SESSION_REPORT_{suffix}_{index}"
            applicants.append((candidate_id, application_id, session_id))
            db.add(CandidateModel(id=candidate_id, name=f"Report student {index + 1}", email=f"student{index}@example.test"))
            db.add(ApplicationModel(
                id=application_id, candidate_id=candidate_id, program_id=program_id,
                face_reference_path="unused.jpg", biometric_consent_at=datetime.now(timezone.utc),
                biometric_consent_version="test-consent", status="interviewing",
            ))
            db.add(InterviewSessionModel(
                id=session_id, candidate_id=candidate_id, job_id=program_id,
                status="in_progress", started_at=datetime.now(timezone.utc),
            ))
        db.commit()

        monkeypatch.setattr(settings, "smtp_host", "smtp.test")
        monkeypatch.setattr(settings, "smtp_from_email", "admissions@example.test")
        monkeypatch.setattr(settings, "smtp_starttls", False)
        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        for index, (_, application_id, session_id) in enumerate(applicants):
            _persist_application_interview_state(db, session_id, {
                "application_id": application_id,
                "identity_status": "verified",
                "identity_verified": True,
                "interview_complete": True,
                "interview_score": 80 + index,
                "turn_number": 1,
                "competency_scores": {"research": 80 + index},
                "conversation_history": [{"question": f"Question {index + 1}", "answer": f"Answer {index + 1}"}],
            })

        recruiter = UserResponse(id=recruiter_id, email=f"recruiter-{suffix.lower()}@example.test", role="recruiter")
        first = get_application_interview(applicants[0][1], recruiter, db)
        second = get_application_interview(applicants[1][1], recruiter, db)
        assert first["application_id"] != second["application_id"]
        assert first["interview"]["conversation_history"][0]["answer"] == "Answer 1"
        assert second["interview"]["conversation_history"][0]["answer"] == "Answer 2"
        assert db.query(ApplicationModel).filter_by(id=applicants[0][1]).one().status == "interview_completed"

    assert FakeSMTP.sent == []

