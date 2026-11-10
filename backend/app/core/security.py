from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import settings


def hash_password(password: str) -> str:
    """
    Hashes a plaintext password using bcrypt.
    Never stores plaintext passwords.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verifies a plaintext password against a stored bcrypt hash.
    """
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    data: Optional[Dict[str, Any]] = None,
    expires_delta: Optional[timedelta] = None,
    user_id: Optional[str] = None,
    role: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> str:
    """
    Creates a signed JWT access token containing claims.
    Accepts a claims dictionary and/or explicit user_id and role arguments.
    """
    to_encode = data.copy() if data else {}
    if user_id:
        to_encode["sub"] = user_id
    if role:
        to_encode["role"] = role
    if candidate_id:
        to_encode["candidate_id"] = candidate_id

    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and validates a JWT access token.
    Raises ValueError on token expiration, signature mismatch, or malformed JWT.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid or expired token: {str(e)}") from e
