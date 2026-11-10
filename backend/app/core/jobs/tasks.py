import logging
import time
from pathlib import Path
from typing import Any, Optional

from app.core.jobs.job import Job, JobStatus
from app.core.jobs.queue import JobQueue
from app.core.logging import log_event
from app.core.metrics import get_metrics_collector
from app.config import settings

logger = logging.getLogger(__name__)


def process_interview_audio(
    job_id: str,
    queue: JobQueue,
    registry: Optional[Any] = None,
    controller: Optional[Any] = None,
    stt: Optional[Any] = None,
) -> Job:
    """Processes candidate interview audio asynchronously.
    
    Pipeline:
    1. Update job to RUNNING.
    2. Transcribe audio via STT (Whisper).
       - On failure: job -> FAILED with friendly retry message. State NOT advanced.
    3. Evaluate via LLM reasoning.
       - On failure: job -> FAILED with retry message. State NOT advanced.
    4. On success: advance state exactly once, update registry, job -> COMPLETED.
    """
    job = queue.get(job_id)
    if not job:
        logger.error("Job %s not found in queue", job_id)
        return None

    if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
        logger.info("Job %s is already %s, returning existing job", job_id, job.status)
        return job

    job.mark_running()
    queue.update(job)

    # Lazy-load dependencies if not injected
    if registry is None:
        from app.stages.stage4_interview.dependencies import registry as global_registry
        registry = global_registry

    if controller is None:
        from app.stages.stage4_interview.dependencies import create_interview_controller
        controller = create_interview_controller()

    if stt is None:
        from app.stages.stage4_interview.voice.stt import get_whisper_stt
        stt = get_whisper_stt(settings.whisper_model)

    session_id = job.session_id
    if not session_id:
        job.mark_failed("Missing session_id on interview audio job.")
        queue.update(job)
        return job

    try:
        state = registry.get(session_id)
    except KeyError:
        job.mark_failed(f"Interview session {session_id} not found.")
        queue.update(job)
        return job
    except Exception as exc:
        job.mark_failed(f"Error accessing session {session_id}: {exc}")
        queue.update(job)
        return job

    audio_path = job.payload.get("audio_path")
    live_image = job.payload.get("live_image")

    def cleanup_media():
        for media_path in (audio_path, live_image):
            if media_path:
                Path(media_path).unlink(missing_ok=True)

    if not audio_path:
        cleanup_media()
        job.mark_failed("Missing audio_path in job payload.")
        queue.update(job)
        return job

    # Step 1: STT Transcription
    t_stt = time.time()
    try:
        question = str(state.get("current_question") or "").strip()
        criteria = [str(item).strip() for item in (state.get("target_competencies") or []) if str(item).strip()]
        prompt_parts = ["Graduate admissions interview answer."]
        if question:
            prompt_parts.append(f"Current question: {question}")
        if criteria:
            prompt_parts.append("Evaluation topics: " + ", ".join(criteria[:12]))
        try:
            transcript = stt.transcribe(audio_path, prompt=" ".join(prompt_parts))
        except TypeError:
            # Keep injected/legacy STT adapters with the original one-argument API working.
            transcript = stt.transcribe(audio_path)
        stt_duration_ms = round((time.time() - t_stt) * 1000, 2)
        if not transcript or not transcript.strip():
            logger.warning("Empty speech transcription for job %s", job_id)
            get_metrics_collector().record_stt(success=False, latency_ms=stt_duration_ms)
            log_event(
                "interview_processing_failed",
                level="ERROR",
                session_id=session_id,
                job_id=job_id,
                candidate_id=state.get("candidate_id"),
                error_code="EMPTY_TRANSCRIPT",
            )
            job.mark_failed("We couldn't process your recording. Please try recording your answer again.")
            queue.update(job)
            cleanup_media()
            return job

        get_metrics_collector().record_stt(success=True, latency_ms=stt_duration_ms)
        log_event(
            "stt_completed",
            session_id=session_id,
            job_id=job_id,
            candidate_id=state.get("candidate_id"),
            latency_ms=stt_duration_ms,
        )
    except Exception as exc:
        stt_duration_ms = round((time.time() - t_stt) * 1000, 2)
        get_metrics_collector().record_stt(success=False, latency_ms=stt_duration_ms)
        log_event(
            "interview_processing_failed",
            level="ERROR",
            session_id=session_id,
            job_id=job_id,
            candidate_id=state.get("candidate_id"),
            error_code="STT_FAILED",
            error=str(exc),
        )
        logger.exception("STT failure for job %s: %s", job_id, exc)
        job.mark_failed("We couldn't process your recording. Please try recording your answer again.")
        queue.update(job)
        cleanup_media()
        return job

    # Step 2: LLM Reasoning & Competency Assessment
    t_llm = time.time()
    try:
        result = controller.submit_text(
            state,
            transcript,
            live_image=live_image,
        )
        # Identity failures can return a state normally without raising. Do not
        # report the transcription job as completed unless the turn was accepted.
        if result.get("identity_status") in {"failed", "review"} or not result.get("identity_verified", True):
            reason = result.get("identity_failure_reason") or "Identity verification did not pass."
            job.mark_failed(f"Interview answer was not accepted: {reason}")
            queue.update(job)
            cleanup_media()
            return job
        llm_duration_ms = round((time.time() - t_llm) * 1000, 2)
        get_metrics_collector().record_llm(success=True, latency_ms=llm_duration_ms)
    except Exception as exc:
        llm_duration_ms = round((time.time() - t_llm) * 1000, 2)
        get_metrics_collector().record_llm(success=False, latency_ms=llm_duration_ms)
        log_event(
            "interview_processing_failed",
            level="ERROR",
            session_id=session_id,
            job_id=job_id,
            candidate_id=state.get("candidate_id"),
            error_code="LLM_FAILED",
            error=str(exc),
        )
        logger.exception("LLM reasoning failure for job %s: %s", job_id, exc)
        job.mark_failed("LLM reasoning service is currently unavailable. Please try again.")
        queue.update(job)
        cleanup_media()
        return job

    # Step 3: Success - advance state and persist
    try:
        result["current_live_frame"] = None
        registry.update(session_id, result)
    except Exception as exc:
        logger.exception("Failed to update registry for session %s: %s", session_id, exc)
        job.mark_failed(f"Failed to persist interview state: {exc}")
        queue.update(job)
        cleanup_media()
        return job

    try:
        from app.api.interview_routes import _persist_application_interview_state
        from app.database.connection import SessionLocal
        db = SessionLocal()
        try:
            _persist_application_interview_state(db, session_id, result)
        finally:
            db.close()
    except Exception:
        logger.exception("Could not sync application interview status for session %s", session_id)
    cleanup_media()

    # Build standard job result envelope
    result_data = {
        "session_id": session_id,
        "candidate_id": result.get("candidate_id"),
        "transcript": transcript,
        "next_question": result.get("next_question"),
        "decision": result.get("decision"),
        "competency_scores": result.get("competency_scores", {}),
        "interview_score": result.get("interview_score"),
        "interview_complete": result.get("interview_complete", False),
        "identity_verified": result.get("identity_verified", True),
    }

    job.mark_completed(result=result_data)
    queue.update(job)
    return job


def process_resume_extraction(
    job_id: str,
    queue: JobQueue,
    candidate_repo: Optional[Any] = None,
) -> Job:
    """Asynchronously extracts resume text and computes competency match."""
    job = queue.get(job_id)
    if not job:
        return None

    job.mark_running()
    queue.update(job)

    candidate_id = job.candidate_id or job.payload.get("candidate_id")
    resume_path = job.payload.get("resume_path")

    try:
        import pypdf
        reader = pypdf.PdfReader(resume_path)
        extracted_text = " ".join([page.extract_text() or "" for page in reader.pages])

        result_data = {
            "candidate_id": candidate_id,
            "resume_path": resume_path,
            "text_length": len(extracted_text),
            "status": "extracted",
        }
        job.mark_completed(result=result_data)
    except Exception as exc:
        logger.exception("Resume extraction failed for job %s: %s", job_id, exc)
        job.mark_failed(f"Resume extraction failed: {exc}")

    queue.update(job)
    return job
