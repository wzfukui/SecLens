"""Authentication and account management routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import crud
from app.config import get_settings
from app.database import get_db_session
from app.dependencies import get_current_active_user
from app.schemas import (
    TokenPair,
    TokenRefreshRequest,
    UserCreate,
    UserLoginRequest,
    UserOut,
)
from app.utils.security import (
    TokenDecodeError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(payload: UserCreate, db: Session = Depends(get_db_session)) -> UserOut:
    """Register a new user account."""

    existing = crud.get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已注册")
    inviter = None
    invite_code = (payload.invitation_code or "").strip()
    if invite_code:
        inviter = crud.get_user_by_invite_code(db, invite_code)
        if not inviter:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码无效")
    password_hash = hash_password(payload.password)
    user = crud.create_user(
        db,
        email=payload.email,
        password_hash=password_hash,
        display_name=payload.display_name,
    )
    if inviter:
        crud.record_invitation(db, inviter, user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


def _set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        "access_token",
        access_token,
        max_age=settings.access_token_expires_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        max_age=settings.refresh_token_expires_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=TokenPair)
def login(payload: UserLoginRequest, db: Session = Depends(get_db_session)) -> JSONResponse:
    """Authenticate with email/password and issue tokens."""

    user = crud.get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已被禁用")
    crud.touch_user_login(db, user)
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    db.commit()
    token_pair = TokenPair(access_token=access_token, refresh_token=refresh_token)
    response = JSONResponse(token_pair.model_dump())
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(payload: TokenRefreshRequest, db: Session = Depends(get_db_session)) -> JSONResponse:
    """Exchange a refresh token for a new token pair."""

    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效") from exc
    subject = token_payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效")
    user = crud.get_user_by_id(db, int(subject))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    token_pair = TokenPair(access_token=access_token, refresh_token=refresh_token)
    response = JSONResponse(token_pair.model_dump())
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.get("/me", response_model=UserOut)
def read_current_user(current_user=Depends(get_current_active_user)) -> UserOut:
    """Return current authenticated user's profile."""

    return UserOut.model_validate(current_user)


@router.post("/logout")
def logout() -> JSONResponse:
    """Clear auth cookies on logout."""

    response = JSONResponse({"detail": "logged_out"})
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response
