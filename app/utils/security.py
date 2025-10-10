"""Security utilities for password hashing and JWT handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings


pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


class TokenDecodeError(Exception):
    """Raised when a JWT token cannot be decoded or is invalid."""


def hash_password(password: str) -> str:
    """Return a secure hash for the provided plain-text password."""

    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify that the provided password matches the stored password hash."""

    return pwd_context.verify(plain_password, password_hash)


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": token_type,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """Generate a signed JWT access token for the given subject."""

    settings = get_settings()
    ttl = expires_minutes or settings.access_token_expires_minutes
    return _create_token(subject, timedelta(minutes=ttl), "access")


def create_refresh_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """Generate a signed JWT refresh token for the given subject."""

    settings = get_settings()
    ttl = expires_minutes or settings.refresh_token_expires_minutes
    return _create_token(subject, timedelta(minutes=ttl), "refresh")


def decode_token(token: str, expected_type: Optional[str] = None) -> dict[str, Any]:
    """Decode a JWT token and optionally validate its type."""

    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenDecodeError("Invalid token") from exc
    if expected_type and payload.get("type") != expected_type:
        raise TokenDecodeError(f"Unexpected token type: {payload.get('type')}")
    return payload


__all__ = [
    "TokenDecodeError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
]
