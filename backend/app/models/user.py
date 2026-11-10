from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Role(str, Enum):
    RECRUITER = "recruiter"
    CANDIDATE = "candidate"
    ADMIN = "admin"



class UserRegisterRequest(BaseModel):
    model_config = ConfigDict()

    email: EmailStr
    password: str = Field(..., min_length=6)
    role: Role = Role.CANDIDATE
    candidate_id: Optional[str] = None


class UserLoginRequest(BaseModel):
    model_config = ConfigDict()

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    model_config = ConfigDict()

    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    candidate_id: Optional[str] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    candidate_id: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
