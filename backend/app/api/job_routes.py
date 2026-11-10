from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.auth_dependencies import get_current_user, require_roles
from app.core.exceptions import JobNotFound
from app.core.jobs import JobQueue, JobType, get_job_queue
from app.models.user import Role, UserResponse

router = APIRouter(
    prefix="/jobs",
    tags=["Jobs"],
)


class CreateJobRequest(BaseModel):
    session_id: str
    type: str = "interview_turn"
    payload: Dict[str, Any] = {}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value))],
)
@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value))],
)
async def create_job(
    request: CreateJobRequest,
    current_user: UserResponse = Depends(get_current_user),
    queue: JobQueue = Depends(get_job_queue),
) -> Dict[str, Any]:
    """Recruiter-only endpoint to enqueue background evaluation/processing jobs."""
    job_type = JobType.INTERVIEW_TURN if request.type == "interview_turn" else JobType.REPORT_GEN
    job = queue.enqueue(job_type=job_type, session_id=request.session_id, payload=request.payload)
    return {
        "job_id": job.id,
        "status": job.status.lower(),
        "session_id": job.session_id,
        "created_at": job.created_at,
    }



@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    queue: JobQueue = Depends(get_job_queue),
) -> Dict[str, Any]:
    """Retrieves current job status, results, or error details."""
    job = queue.get(job_id)
    if not job:
        raise JobNotFound(job_id)

    return {
        "job_id": job.id,
        "status": job.status.lower(),
        "type": job.type,
        "session_id": job.session_id,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "result": job.result,
        "error": job.error,
    }


@router.get("")
async def list_jobs(
    session_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    queue: JobQueue = Depends(get_job_queue),
) -> List[Dict[str, Any]]:
    """Lists jobs, optionally filtered by session_id or status."""
    jobs = queue.list_jobs(session_id=session_id, status=status)
    return [
        {
            "job_id": j.id,
            "status": j.status.lower(),
            "type": j.type,
            "session_id": j.session_id,
            "created_at": j.created_at,
            "result": j.result,
            "error": j.error,
        }
        for j in jobs
    ]
