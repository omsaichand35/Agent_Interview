from typing import List, Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.connection import get_db
from app.database.repositories.user_repository import UserRepository
from app.models.user import Role, UserResponse

security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Extracts Bearer token from Authorization header and decodes JWT.
    Raises HTTP 401 if missing, expired, or invalid.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token: missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if user:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive",
            )
        return UserResponse.model_validate(user)

    role = payload.get("role")
    if role:
        from datetime import datetime, timezone
        return UserResponse(
            id=user_id,
            email=payload.get("email", f"{user_id}@example.com"),
            role=role,
            candidate_id=payload.get("candidate_id"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="User not found",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*allowed_roles: str):
    """
    Dependency factory to restrict endpoint access by role (e.g. 'recruiter').
    """
    def role_checker(
        current_user: UserResponse = Depends(get_current_user),
    ) -> UserResponse:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: role '{current_user.role}' is not authorized for this resource",
            )
        return current_user

    return role_checker


def verify_candidate_access(
    candidate_id: str,
    current_user: UserResponse,
) -> None:
    """
    Enforces the critical security boundary:
    Candidate users can ONLY access resources belonging to their own candidate_id.
    Recruiters have access to all candidates.
    """
    if current_user.role == Role.CANDIDATE.value:
        if not current_user.candidate_id or current_user.candidate_id != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You are not authorized to access candidate '{candidate_id}'",
            )


def verify_session_candidate_access(
    session_id: str,
    current_user: UserResponse,
    db: Session,
) -> None:
    """
    Verifies that a candidate only accesses interview sessions belonging to them.
    Recruiters are permitted access.
    """
    if current_user.role == Role.CANDIDATE.value or current_user.role == "candidate":
        from app.database.repositories.interview_repository import InterviewRepository
        from app.stages.stage4_interview.dependencies import registry
        from app.stages.stage4_interview.persistence import InterviewPersistence

        candidate_id = None
        # Check DB first
        interview_repo = InterviewRepository(db)
        sess = interview_repo.get_session(session_id)
        if sess:
            candidate_id = sess.candidate_id
        elif session_id in registry:
            state = registry.get(session_id)
            candidate_id = state.get("candidate_id")
        else:
            persistence = InterviewPersistence()
            if persistence.exists(session_id):
                persisted = persistence.load(session_id)
                candidate_id = persisted.get("candidate_id")

        if candidate_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Interview session '{session_id}' not found",
            )

        if current_user.candidate_id != candidate_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: You cannot access interview session '{session_id}'",
            )
