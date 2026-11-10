import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.jobs.job import Job, JobStatus

logger = logging.getLogger(__name__)


class JobQueue:
    """Persistent Job Queue that survives server restarts.
    
    Guarantees:
    1. Persistence: Jobs are stored to disk (and optionally Redis).
    2. Idempotency: Multiple requests with the same idempotency key return the existing job.
    3. Concurrency-safe: Thread locks guard state mutations.
    """

    def __init__(
        self,
        storage_dir: str = "data/outputs/jobs",
        redis_client: Optional[Any] = None,
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.redis_client = redis_client
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._idempotency_map: Dict[str, str] = {}  # key -> job_id

        # Load existing jobs on startup for crash recovery
        self._load_from_disk()

    def _make_idempotency_lookup_key(self, session_id: Optional[str], idempotency_key: str) -> str:
        sess = session_id or "__global__"
        return f"{sess}:{idempotency_key}"

    def _load_from_disk(self) -> None:
        """Restores persisted jobs from disk on backend startup."""
        with self._lock:
            for job_file in self.storage_dir.glob("*.json"):
                try:
                    with job_file.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                        job = Job(**data)
                        if job.status == JobStatus.RUNNING.value:
                            logger.warning("Job %s was RUNNING during process crash/restart; resetting to QUEUED for recovery.", job.id)
                            job.status = JobStatus.QUEUED.value
                            job.started_at = None
                            job.error = "Recovered after worker process interruption"
                        self._jobs[job.id] = job
                        if job.idempotency_key:
                            lookup = self._make_idempotency_lookup_key(job.session_id, job.idempotency_key)
                            self._idempotency_map[lookup] = job.id
                except Exception as e:
                    logger.warning("Failed to load job from %s: %s", job_file, e)

    def _persist(self, job: Job) -> None:
        """Atomically saves job to disk."""
        filepath = self.storage_dir / f"{job.id}.json"
        temp_path = self.storage_dir / f"{job.id}.tmp"
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                f.write(job.model_dump_json(indent=2))
            temp_path.replace(filepath)
        except Exception as e:
            logger.error("Failed to persist job %s: %s", job.id, e)

    def enqueue(
        self,
        job: Optional[Job] = None,
        *,
        job_type: Optional[str] = None,
        session_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Job:
        """Enqueues a job, registering idempotency and persisting immediately."""
        if job is None:
            import uuid
            job = Job(
                id=f"job_{uuid.uuid4().hex[:10]}",
                type=job_type or JobType.INTERVIEW_AUDIO.value,
                session_id=session_id,
                candidate_id=candidate_id,
                payload=payload or {},
                idempotency_key=idempotency_key,
            )

        with self._lock:
            # Check idempotency first
            if job.idempotency_key:
                lookup = self._make_idempotency_lookup_key(job.session_id, job.idempotency_key)
                if lookup in self._idempotency_map:
                    existing_id = self._idempotency_map[lookup]
                    if existing_id in self._jobs:
                        return self._jobs[existing_id]

            self._jobs[job.id] = job
            if job.idempotency_key:
                lookup = self._make_idempotency_lookup_key(job.session_id, job.idempotency_key)
                self._idempotency_map[lookup] = job.id

            self._persist(job)

            # Optional Redis integration
            if self.redis_client:
                try:
                    self.redis_client.lpush("interview:jobs:queued", job.id)
                except Exception as e:
                    logger.warning("Redis lpush failed for job %s: %s", job.id, e)

            return job

    def get(self, job_id: str) -> Optional[Job]:
        """Retrieves a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: Job) -> Job:
        """Updates job state in memory and persists to disk."""
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
            return job

    def find_by_idempotency_key(
        self,
        session_id: Optional[str],
        idempotency_key: str,
    ) -> Optional[Job]:
        """Finds an existing job by session and idempotency key."""
        with self._lock:
            lookup = self._make_idempotency_lookup_key(session_id, idempotency_key)
            job_id = self._idempotency_map.get(lookup)
            if job_id:
                return self._jobs.get(job_id)
            return None

    def get_next_queued_job(self) -> Optional[Job]:
        """Pops the oldest queued job in FIFO order."""
        with self._lock:
            queued_jobs = [
                j for j in self._jobs.values()
                if j.status == JobStatus.QUEUED.value
            ]
            if not queued_jobs:
                return None
            queued_jobs.sort(key=lambda j: j.created_at)
            return queued_jobs[0]

    def list_jobs(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Job]:
        """Lists jobs filtered by session or status."""
        with self._lock:
            results = list(self._jobs.values())
            if session_id:
                results = [j for j in results if j.session_id == session_id]
            if status:
                results = [j for j in results if j.status.upper() == status.upper()]
            return results
