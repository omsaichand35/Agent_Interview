import uuid
from typing import Optional
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.database.models import UserModel


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: str) -> Optional[UserModel]:
        return self.db.query(UserModel).filter(UserModel.id == user_id).first()

    def get_by_email(self, email: str) -> Optional[UserModel]:
        return self.db.query(UserModel).filter(UserModel.email == email.lower().strip()).first()

    def create_user(
        self,
        email: str,
        password: str,
        role: str = "candidate",
        candidate_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UserModel:
        clean_email = email.lower().strip()
        existing = self.get_by_email(clean_email)
        if existing:
            raise ValueError(f"User with email '{clean_email}' already exists")

        user = UserModel(
            id=user_id or f"USR_{uuid.uuid4().hex[:8].upper()}",
            email=clean_email,
            password_hash=hash_password(password),
            role=role,
            candidate_id=candidate_id,
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> Optional[UserModel]:
        user = self.get_by_email(email)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

