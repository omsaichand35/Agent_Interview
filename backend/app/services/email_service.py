"""Small SMTP sender for transactional admissions notifications."""
import logging
import smtplib
from email.message import EmailMessage

from app.config import refresh_smtp_settings, settings

logger = logging.getLogger(__name__)


def send_email(to_email: str | None, subject: str, body: str) -> bool:
    """Deliver an email when SMTP is configured; failures never affect app flows."""
    refresh_smtp_settings()
    if not to_email or not settings.smtp_host or not settings.smtp_from_email:
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = to_email
    message.set_content(body)
    try:
        smtp_cls = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
        with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls and not settings.smtp_use_ssl:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True
    except Exception:
        logger.exception("Transactional email delivery failed")
        return False


def send_welcome_email(to_email: str) -> None:
    send_email(to_email, "Welcome to Graduate Admissions", "Your account is ready. Sign in to continue your admissions journey at the Graduate Admissions portal.")


def send_application_received_email(to_email: str, program_title: str) -> None:
    send_email(to_email, "Application received", f"We received your application to {program_title}. You can track its progress in your student portal.")


def send_interview_invite_email(to_email: str, student_name: str, program_title: str, code: str, expires_at: str) -> None:
    send_email(to_email, "Interview invitation", f"Hello {student_name or 'student'},\n\nYou have been invited to interview for {program_title}. Redeem this single-use code in your student portal: {code}\n\nThe code expires at {expires_at}.")


def send_scheduled_interview_batch_emails(
    messages: list[tuple[str, str, str, str, str, int, str | None]],
    recruiter_report: dict | None = None,
) -> int:
    """Send schedule emails in bounded authenticated SMTP sessions."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    import csv
    from io import StringIO
    import smtplib

    refresh_smtp_settings()
    if not settings.smtp_host or not settings.smtp_from_email or (not messages and not recruiter_report):
        return 0
    prepared = []
    for to_email, student_name, program_title, scheduled_at, timezone_name, slot_number, code in messages:
        local_time = datetime.fromisoformat(scheduled_at).astimezone(ZoneInfo(timezone_name))
        body = (
            f"Hello {student_name or 'student'},\n\n"
            f"Your interview for {program_title} is scheduled for {local_time.strftime('%A, %B %d, %Y at %I:%M %p')} ({timezone_name}).\n"
            f"Your place is in slot {slot_number}. Open the student portal before your slot: "
            f"{settings.public_base_url.rstrip('/')}/student\n"
        )
        if code:
            body += f"\nRedeem this single-use interview code in the student portal: {code}\n"
        body += "\nThe portal will show a countdown and enable the interview join button when your slot opens."
        message = EmailMessage()
        message["Subject"] = "Your interview schedule"
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to_email
        message.set_content(body)
        prepared.append((to_email, message))

    if recruiter_report and recruiter_report.get("to_email"):
        report_message = EmailMessage()
        report_message["Subject"] = f"Interview schedule roster — {recruiter_report['program_title']}"
        report_message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        report_message["To"] = recruiter_report["to_email"]
        rule = recruiter_report.get("selection_rule") or {}
        rule_text = (
            f"Top {rule.get('top_n')} by resume score"
            if rule.get("selection") == "top_n"
            else f"Resume score at least {rule.get('min_score')}"
        )
        report_message.set_content(
            f"The interview schedule for {recruiter_report['program_title']} is ready.\n\n"
            f"Batch: {recruiter_report['batch_id']}\n"
            f"Students scheduled: {len(recruiter_report.get('roster', []))}\n"
            f"Selection rule: {rule_text}\n"
            f"Timezone: {recruiter_report['timezone']}\n\n"
            f"The complete roster is attached as a CSV. It is also available in the recruiter portal: "
            f"{settings.public_base_url.rstrip('/')}/recruiter"
        )
        csv_buffer = StringIO(newline="")
        writer = csv.writer(csv_buffer)
        writer.writerow(["Student", "Email", "Resume score", "Slot", "Start", "End", "Timezone"])
        for row in recruiter_report.get("roster", []):
            writer.writerow([
                row.get("candidate_name"),
                row.get("candidate_email"),
                row.get("resume_score"),
                row.get("slot_number"),
                row.get("scheduled_start"),
                row.get("scheduled_end"),
                row.get("timezone"),
            ])
        report_message.add_attachment(
            csv_buffer.getvalue().encode("utf-8"),
            maintype="text",
            subtype="csv",
            filename=f"interview-roster-{recruiter_report['batch_id']}.csv",
        )
        prepared.append((recruiter_report["to_email"], report_message))

    smtp_cls = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    sent = 0
    for offset in range(0, len(prepared), 50):
        try:
            with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_starttls and not settings.smtp_use_ssl:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                for to_email, message in prepared[offset:offset + 50]:
                    try:
                        smtp.send_message(message)
                        sent += 1
                    except Exception:
                        logger.exception("Scheduled interview email failed for recipient %s", to_email)
        except Exception:
            logger.exception("Could not connect to SMTP for schedule email chunk starting at %s", offset)
            break
    if sent != len(prepared):
        logger.warning(
            "Schedule email batch delivered %s of %s messages (batch %s)",
            sent,
            len(prepared),
            (recruiter_report or {}).get("batch_id", "unknown"),
        )
    return sent


def send_schedule_reminder_email(
    to_email: str,
    student_name: str,
    program_title: str,
    scheduled_at: str,
    timezone_name: str,
) -> bool:
    from zoneinfo import ZoneInfo
    from datetime import datetime

    local_time = datetime.fromisoformat(scheduled_at).astimezone(ZoneInfo(timezone_name))
    body = (
        f"Hello {student_name or 'student'},\n\n"
        f"Your interview for {program_title} starts in about 10 minutes, at "
        f"{local_time.strftime('%I:%M %p')} ({timezone_name}).\n"
        f"Open the student portal to join when the countdown reaches zero: "
        f"{settings.public_base_url.rstrip('/')}/student"
    )
    return send_email(to_email, "Interview starts in 10 minutes", body)
