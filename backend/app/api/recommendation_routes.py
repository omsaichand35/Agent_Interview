from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException

from app.api.auth_dependencies import get_current_user, require_roles, verify_candidate_access
from app.api.dependencies import get_recommendation_service
from app.models.user import Role, UserResponse

router = APIRouter(
    prefix="/recommendations",
    tags=["recommendations"],
)


@router.get(
    "",
    dependencies=[Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value))],
)
@router.get(
    "/",
    dependencies=[Depends(require_roles(Role.RECRUITER.value, Role.ADMIN.value))],
)
async def list_recommendations(
    current_user: UserResponse = Depends(get_current_user),
    rec_service=Depends(get_recommendation_service),
) -> List[Dict[str, Any]]:
    """Recruiter-only endpoint to list all candidate hiring recommendations."""
    results = []
    for cid, rec in getattr(rec_service, "_recommendations", {}).items():
        results.append(rec.model_dump())
    return results


@router.get("/{candidate_id}")
async def get_recommendation(

    candidate_id: str,
    current_user: UserResponse = Depends(get_current_user),
    rec_service=Depends(get_recommendation_service),
):
    verify_candidate_access(candidate_id, current_user)
    recommendation = rec_service.get_recommendation(candidate_id)
    if recommendation is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recommendation for candidate {candidate_id} not available",
        )

    from app.core.audit import get_audit_service
    get_audit_service().record_event(
        actor_id=current_user.id,
        actor_role=current_user.role,
        action="RECOMMENDATION_REVIEWED",
        resource_type="RECOMMENDATION",
        resource_id=f"REC_{candidate_id}",
        candidate_id=candidate_id,
        result="SUCCESS",
    )

    result = recommendation.model_dump()
    if current_user.role == Role.CANDIDATE.value:
        for key in ("resume_score", "interview_score", "final_score", "evidence"):
            result.pop(key, None)
    return result
