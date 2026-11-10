import os
from typing import Optional
from app.core.jobs.job import Job, JobStatus, JobType
from app.core.jobs.queue import JobQueue
from app.core.jobs.worker import JobWorker

_job_queue_instance: Optional[JobQueue] = None
_job_worker_instance: Optional[JobWorker] = None


def get_job_queue() -> JobQueue:
    """Returns singleton JobQueue instance."""
    global _job_queue_instance
    if _job_queue_instance is None:
        storage_dir = os.environ.get("JOBS_STORAGE_DIR", "data/outputs/jobs")
        _job_queue_instance = JobQueue(storage_dir=storage_dir)
    return _job_queue_instance


def get_job_worker() -> JobWorker:
    """Returns singleton JobWorker instance."""
    global _job_worker_instance
    if _job_worker_instance is None:
        queue = get_job_queue()
        _job_worker_instance = JobWorker(queue=queue)
    return _job_worker_instance


def reset_job_system() -> None:
    """Resets singleton instances for isolated tests."""
    global _job_queue_instance, _job_worker_instance
    if _job_worker_instance:
        _job_worker_instance.stop_background()
    _job_queue_instance = None
    _job_worker_instance = None


__all__ = [
    "Job",
    "JobStatus",
    "JobType",
    "JobQueue",
    "JobWorker",
    "get_job_queue",
    "get_job_worker",
    "reset_job_system",
]
