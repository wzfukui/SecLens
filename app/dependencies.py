"""Common FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db_session
from app.utils.security import TokenDecodeError, decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db_session),
) -> models.User:
    """Resolve the authenticated user from a bearer token or cookie."""

    token_value = token or request.cookies.get("access_token")
    if not token_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供访问令牌")
    try:
        payload = decode_token(token_value, expected_type="access")
    except TokenDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌无效") from exc

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌无效")

    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="访问令牌无效") from exc

    user = crud.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账户不可用或不存在")
    return user


def get_current_active_user(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Ensure the current user is active."""

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已被禁用")
    return user


def get_current_admin_user(
    user: models.User = Depends(get_current_active_user),
) -> models.User:
    """Ensure the current user holds admin privileges."""

    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


__all__ = ["oauth2_scheme", "get_current_user", "get_current_active_user", "get_current_admin_user"]
