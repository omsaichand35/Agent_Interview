from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_workflow_service

router = APIRouter(
    prefix="/workflow",
    tags=["workflow"],
)


class CreateJobRequest(BaseModel):
    job_id: str
    job_title: str
    department: str
    candidates: Optional[List[Dict[str, Any]]] = None


@router.get("")
@router.get("/")
async def list_workflows(
    workflow_service=Depends(get_workflow_service),
):
    return workflow_service.list_jobs()


@router.get("/{job_id}")
async def get_workflow(
    job_id: str,
    workflow_service=Depends(get_workflow_service),
):
    workflow = workflow_service.get(job_id)

    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found",
        )

    return workflow


@router.post("/create")
async def create_workflow_job(
    request: CreateJobRequest,
    workflow_service=Depends(get_workflow_service),
):
    job_state = workflow_service.create_job(
        job_id=request.job_id,
        title=request.job_title,
        department=request.department,
        candidates=request.candidates,
    )
    return job_state


@router.post("/{job_id}/start")
async def start_workflow(
    job_id: str,
    workflow_service=Depends(get_workflow_service),
):
    workflow = workflow_service.get(job_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Progress to scheduled and interview ready
    workflow["status"] = "INTERVIEW_IN_PROGRESS"
    workflow_service.persistence.save(workflow)
    return workflow
