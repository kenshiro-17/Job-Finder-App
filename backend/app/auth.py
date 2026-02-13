from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User


security = HTTPBearer(auto_error=False)
DEFAULT_ITERATIONS = 210_000
TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(60 * 60 * 24 * 14)))
AUTH_SECRET = os.getenv("AUTH_SECRET", "match-pilot-dev-secret")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        DEFAULT_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${DEFAULT_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _, iterations_str, salt, digest = password_hash.split("$", 3)
        iterations = int(iterations_str)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(expected, digest)


def create_access_token(user_id: int) -> str:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    nonce = secrets.token_hex(6)
    payload = f"{user_id}:{exp}:{nonce}"
    signature = hmac.new(AUTH_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token_raw = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(token_raw).decode("utf-8").rstrip("=")


def decode_access_token(token: str) -> int | None:
    if not token:
        return None
    padding = "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode((token + padding).encode("utf-8")).decode("utf-8")
        user_id_str, exp_str, nonce, signature = decoded.split(":", 3)
        payload = f"{user_id_str}:{exp_str}:{nonce}"
    except Exception:
        return None

    expected_signature = hmac.new(
        AUTH_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        return None

    try:
        exp = int(exp_str)
        user_id = int(user_id_str)
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    return user_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user
