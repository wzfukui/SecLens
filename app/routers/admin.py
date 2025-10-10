"""Admin dashboard for managing activation codes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db_session
from app.dependencies import get_current_admin_user


router = APIRouter(prefix="/admin", tags=["admin"])


def _generate_code() -> str:
    return secrets.token_urlsafe(16)


@router.get("", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    codes = (
        db.query(models.ActivationCode)
        .order_by(models.ActivationCode.created_at.desc())
        .limit(100)
        .all()
    )
    return request.app.state.templates.TemplateResponse(  # type: ignore[attr-defined]
        request=request,
        name="admin_dashboard.html",
        context={
            "title": "SecLens 管理员中心",
            "header": "SecLens 管理员中心",
            "header_href": None,
            "page_id": "admin",
            "user": current_user,
            "codes": codes,
        },
    )


@router.post("/codes", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def create_activation_codes(
    quantity: int = Form(1, ge=1, le=100),
    expires_in_days: int | None = Form(None, ge=1, le=365),
    notes: str | None = Form(None, max_length=255),
    current_user: models.User = Depends(get_current_admin_user),
    db: Session = Depends(get_db_session),
) -> RedirectResponse:
    batch_label = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    expires_at: datetime | None = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    for _ in range(quantity):
        code = _generate_code()
        activation = models.ActivationCode(
            code=code,
            batch=batch_label,
            notes=notes,
            expires_at=expires_at,
        )
        db.add(activation)
    db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
