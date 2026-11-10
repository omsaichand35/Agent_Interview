"""Authentication Attacks Security Test Suite (Requirement F6.2).

Verifies the security and robustness of the authentication boundary against hostile vectors:
[x] missing token -> 401
[x] empty token -> 401
[x] malformed token -> 401
[x] expired token -> 401
[x] invalid signature (forged secret key) -> 401
[x] token with 'none' algorithm or unsupported algorithm -> 401
[x] token for inactive/disabled user -> 401
[x] wrong password login -> 401
[x] ensures protected routes NEVER treat malformed credentials as anonymous access
"""

from datetime import datetime, timedelta, timezone
from jose import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import create_access_token
from app.database.connection import SessionLocal
from app.database.repositories.user_repository import UserRepository
from app.main import app
from app.models.user import Role
from app.security.rate_limiter import rate_limiter_instance


@pytest.fixture(autouse=True)
def reset_rate_limits():
    rate_limiter_instance.reset()
    yield
    rate_limiter_instance.reset()


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# F6.2: Authentication Boundary Attacks
# ---------------------------------------------------------------------------

def test_missing_token_returns_401(api_client):
    """F6.2: Protected endpoints without Authorization header yield 401."""
    res = api_client.get("/auth/me")
    assert res.status_code == 401
    assert "not authenticated" in res.text.lower() or "missing" in res.text.lower() or "unauthorized" in res.text.lower()


def test_empty_token_returns_401(api_client):
    """F6.2: Empty Bearer token yields 401."""
    res = api_client.get("/auth/me", headers={"Authorization": "Bearer "})
    assert res.status_code == 401


def test_malformed_token_returns_401(api_client):
    """F6.2: Random garbage string passed as Bearer token yields 401."""
    res = api_client.get("/auth/me", headers={"Authorization": "Bearer garbage.payload.tokens"})
    assert res.status_code == 401


def test_expired_token_returns_401(api_client):
    """F6.2: Expired JWT access token yields 401."""
    expired_token = create_access_token(
        data={"sub": "U_EXPIRED", "role": "candidate"},
        expires_delta=timedelta(seconds=-3600),
    )
    res = api_client.get("/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "expired" in res.text.lower()


def test_invalid_signature_forged_secret_returns_401(api_client):
    """F6.2: Token signed with unauthorized/attacker secret key yields 401."""
    forged_payload = {
        "sub": "U_ATTACKER",
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    forged_token = jwt.encode(forged_payload, "ATTACKER_UNAUTHORIZED_KEY_12345", algorithm="HS256")
    res = api_client.get("/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert res.status_code == 401
    assert "signature" in res.text.lower() or "invalid" in res.text.lower()


def test_none_algorithm_attack_rejected(api_client):
    """F6.2: Tokens with 'none' algorithm or unsigned attacks are firmly rejected."""
    # Attempt CVE-style algorithm: none attack
    header = {"alg": "none", "typ": "JWT"}
    payload = {
        "sub": "U_ATTACKER",
        "role": "admin",
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
    }
    # Raw token without signature
    import base64
    import json
    b64_h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b64_p = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    none_token = f"{b64_h}.{b64_p}."

    res = api_client.get("/auth/me", headers={"Authorization": f"Bearer {none_token}"})
    assert res.status_code == 401


def test_token_for_disabled_user_returns_401(api_client, db_session):
    """F6.2: Validly signed token for an inactive/disabled user account is rejected with 401."""
    import uuid
    email = f"disabled_{uuid.uuid4().hex[:6]}@example.com"
    user_repo = UserRepository(db_session)
    user = user_repo.create_user(
        email=email,
        password="ValidPassword123!",
        role="candidate",
    )
    # Disable user account
    user.is_active = False
    db_session.commit()

    token = create_access_token(
        data={"sub": user.id, "email": user.email, "role": user.role}
    )
    res = api_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code in (401, 403)
    assert "inactive" in res.text.lower() or "disabled" in res.text.lower() or "invalid" in res.text.lower()


def test_wrong_password_login_returns_401(api_client, db_session):
    """F6.2: Invalid password yields 401 Unauthorized, never 200 or 500."""
    import uuid
    email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    user_repo = UserRepository(db_session)
    user_repo.create_user(email=email, password="CorrectPassword123!", role="candidate")

    res = api_client.post("/auth/login", json={"email": email, "password": "WrongPassword!"})
    assert res.status_code == 401
    assert "incorrect" in res.text.lower()


def test_malformed_token_never_treated_as_anonymous(api_client):
    """F6.2: Ensure malformed or invalid auth headers are NOT silently treated as anonymous."""
    protected_urls = [
        ("GET", "/auth/me"),
        ("GET", "/candidates"),
        ("GET", "/recommendations"),
        ("POST", "/interview/SESSION001/answer"),
    ]
    for method, url in protected_urls:
        res = api_client.request(
            method,
            url,
            headers={"Authorization": "Bearer bad.token.here"},
            json={"answer": "hello"} if method == "POST" else None,
        )
        assert res.status_code == 401, f"{method} {url} allowed malformed token"
