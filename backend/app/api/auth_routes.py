from datetime import timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_dependencies import get_current_user
from app.config import settings
from app.core.security import create_access_token
from app.database.connection import get_db
from app.database.repositories.user_repository import UserRepository
from app.models.user import Role, TokenResponse, UserLoginRequest, UserRegisterRequest, UserResponse
from app.security.rate_limiter import rate_limit
from app.services.email_service import send_welcome_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(req: UserRegisterRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Public registration creates candidate accounts only."""
    if req.role != Role.CANDIDATE:
        raise HTTPException(status_code=403, detail="Public registration is limited to candidate accounts.")
    if req.candidate_id is not None:
        raise HTTPException(status_code=422, detail="Candidate IDs are assigned by the application and cannot be set during registration.")
    try:
        user = UserRepository(db).create_user(email=req.email, password=req.password, role=req.role.value, candidate_id=None)
        background_tasks.add_task(send_welcome_email, user.email)
        return UserResponse.model_validate(user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(rate_limit(limit=5, window_seconds=60, key_prefix="login"))])
def login(req: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate an account using its email and password."""
    user = UserRepository(db).authenticate(email=req.email, password=req.password)
    from app.core.audit import get_audit_service
    audit_svc = get_audit_service(db)
    if not user:
        audit_svc.record_event(actor_id=req.email, actor_role="ANONYMOUS", action="LOGIN_FAILURE", resource_type="USER", resource_id=req.email, result="FAILED", metadata={"email": req.email})
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    audit_svc.record_event(actor_id=user.id, actor_role=user.role, action="LOGIN_SUCCESS", resource_type="USER", resource_id=user.id, candidate_id=user.candidate_id, result="SUCCESS", metadata={"email": user.email, "role": user.role})
    access_token = create_access_token(data={"sub": user.id, "email": user.email, "role": user.role, "candidate_id": user.candidate_id}, expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes))
    return TokenResponse(access_token=access_token, token_type="bearer", role=user.role, user_id=user.id, candidate_id=user.candidate_id)


@router.post("/logout")
def logout(current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.core.audit import get_audit_service
    get_audit_service(db).record_event(actor_id=current_user.id, actor_role=current_user.role, action="LOGOUT", resource_type="USER", resource_id=current_user.id, candidate_id=current_user.candidate_id, result="SUCCESS")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(current_user: UserResponse = Depends(get_current_user)):
    """Return the authenticated user's profile and assigned role."""
    return current_user
