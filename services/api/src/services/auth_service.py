"""JWT authentication helpers and FastAPI dependencies."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, ExpiredSignatureError, jwt

from src.models.user import TinyDBId, User
from src.services.user_service import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def _get_secret_key() -> str:
    secret_key = os.getenv("SECRET_KEY")
    if secret_key:
        return secret_key
    raise RuntimeError("SECRET_KEY must be configured; refusing to use an insecure fallback.")


def _get_algorithm() -> str:
    value = os.getenv("ALGORITHM", "HS256").strip()
    if value:
        return value
    return "HS256"


def _get_access_token_expire_minutes() -> int:
    raw_value = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be an integer.") from exc

    if value <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero.")
    return value


def create_access_token(user_id: TinyDBId) -> str:
    """Generate a signed JWT access token including the TinyDB user id."""

    expire_minutes = _get_access_token_expire_minutes()
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "exp": expire_at,
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_get_algorithm())


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Resolve and return current user from Authorization Bearer token."""

    unauthorized_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        return get_user_from_token(token)
    except ValueError as exc:
        raise unauthorized_exception from exc


def get_user_from_token(token: str) -> User:
    """Validate an API JWT and resolve its active user (HTTP or WebSocket)."""
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
    except (ExpiredSignatureError, JWTError) as exc:
        raise ValueError("Invalid or expired access token") from exc

    subject = payload.get("sub")
    if subject is None:
        raise ValueError("Access token has no subject")
    user = get_user_by_id(subject)
    if user is None or not user.is_active:
        raise ValueError("Access token user is unavailable")
    return user
