import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from app.core.jobs.job import Job, JobStatus, JobType
from app.core.jobs.queue import JobQueue
from app.core.jobs.tasks import process_interview_audio, process_resume_extraction

logger = logging.getLogger(__name__)


class JobWorker:
    """Worker that executes background jobs from the JobQueue."""

    def __init__(
        self,
        queue: JobQueue,
        registry: Optional[Any] = None,
        controller: Optional[Any] = None,
        stt: Optional[Any] = None,
    ):
        self.queue = queue
        self.registry = registry
        self.controller = controller
        self.stt = stt
        self._running = False
        self._thread: Optional[threading.Thread] = None

        self._handlers: Dict[str, Callable[..., Job]] = {
            JobType.INTERVIEW_AUDIO.value: self._handle_interview_audio,
            JobType.RESUME_EXTRACTION.value: self._handle_resume_extraction,
        }

    def register_handler(self, job_type: str, handler: Callable[..., Job]) -> None:
        self._handlers[job_type] = handler

    def _handle_interview_audio(self, job_id: str) -> Job:
        return process_interview_audio(
            job_id=job_id,
            queue=self.queue,
            registry=self.registry,
            controller=self.controller,
            stt=self.stt,
        )

    def _handle_resume_extraction(self, job_id: str) -> Job:
        return process_resume_extraction(
            job_id=job_id,
            queue=self.queue,
        )

    def process_job(self, job_id: str) -> Optional[Job]:
        """Synchronously processes a specific job by ID."""
        job = self.queue.get(job_id)
        if not job:
            logger.warning("Worker could not find job %s", job_id)
            return None

        # Idempotency guard: do not re-process completed or failed jobs
        if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
            logger.info("Job %s is already %s, skipping re-execution", job.id, job.status)
            return job

        handler = self._handlers.get(job.type)
        if not handler:
            error_msg = f"No handler registered for job type: {job.type}"
            logger.error(error_msg)
            job.mark_failed(error_msg)
            return self.queue.update(job)

        start_time = time.perf_counter()
        try:
            result = handler(job_id)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info("Job %s (%s) finished in %0.2fms", job.id, job.type, duration_ms)
            return result
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception("Error executing job %s after %0.2fms: %s", job_id, duration_ms, exc)
            if job.should_retry(exc):
                job.record_retry(str(exc))
                logger.warning(
                    "Job %s scheduled for retry (attempt %d/%d)",
                    job.id,
                    job.retry_count,
                    job.max_retries,
                )
            else:
                job.mark_failed(str(exc))
            return self.queue.update(job)

    def process_next(self) -> Optional[Job]:
        """Picks up and executes the next available queued job."""
        job = self.queue.get_next_queued_job()
        if not job:
            return None
        return self.process_job(job.id)

    def run_until_idle(self) -> int:
        """Processes all pending queued jobs until the queue is empty.
        
        Returns the number of jobs processed.
        """
        count = 0
        while True:
            job = self.process_next()
            if job is None:
                break
            count += 1
        return count

    def start_background(self, poll_interval: float = 0.5) -> None:
        """Starts worker polling in a daemon thread."""
        if self._running:
            return

        self._running = True

        def _worker_loop():
            logger.info("Background JobWorker started")
            while self._running:
                processed = self.process_next()
                if not processed:
                    time.sleep(poll_interval)
            logger.info("Background JobWorker stopped")

        self._thread = threading.Thread(target=_worker_loop, daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        """Stops the background worker thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
