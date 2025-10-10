"""User account management routes for VIP, notifications, and subscriptions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud, models
from app.database import get_db_session
from app.dependencies import get_current_active_user
from app.schemas import (
    ActivationLogOut,
    ActivationRequest,
    NotificationSettingOut,
    NotificationSettingUpdate,
    PushRuleCreate,
    PushRuleOut,
    PushRuleUpdate,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionUpdate,
    VIPStatus,
)
from app.services.subscriptions import generate_subscription_token


router = APIRouter(prefix="/users", tags=["users"])


def _vip_status(user: models.User) -> VIPStatus:
    now = datetime.now(timezone.utc)
    expires_at = _ensure_aware(user.vip_expires_at)
    remaining_days = None
    if expires_at:
        delta = expires_at - now
        remaining_days = max(0, int(delta.total_seconds() // 86400))
    logs = sorted(
        (
            log
            for log in getattr(user, "activation_logs", []) or []
            if log.is_used and log.used_by_user_id == user.id
        ),
        key=lambda log: log.used_at or log.created_at,
        reverse=True,
    )
    history = [ActivationLogOut.model_validate(log) for log in logs]
    return VIPStatus(
        is_vip=bool(expires_at and expires_at > now),
        vip_activated_at=user.vip_activated_at,
        vip_expires_at=expires_at,
        remaining_days=remaining_days,
        history=history,
    )


def _ensure_aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ensure_valid_channels(db: Session, slugs: Iterable[str]) -> list[str]:
    unique = sorted({slug.strip() for slug in slugs if slug.strip()})
    if not unique:
        return []
    stmt = select(models.Plugin.slug).where(models.Plugin.slug.in_(unique))
    found = {row[0] for row in db.execute(stmt)}
    missing = [slug for slug in unique if slug not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"以下插件不存在: {', '.join(missing)}",
        )
    return unique


def _subscription_to_schema(
    subscription: models.UserSubscription,
    request: Request,
) -> SubscriptionOut:
    rss_url = str(request.url_for("user_subscription_feed", token=subscription.token))
    return SubscriptionOut.model_validate(
        {
            "id": subscription.id,
            "name": subscription.name,
            "channel_slugs": subscription.channel_slugs,
            "keyword_filter": subscription.keyword_filter,
            "is_active": subscription.is_active,
            "token": subscription.token,
            "created_at": subscription.created_at,
            "updated_at": subscription.updated_at,
            "rss_url": rss_url,
        }
    )


@router.get("/me/vip", response_model=VIPStatus)
def read_vip_status(current_user: models.User = Depends(get_current_active_user)) -> VIPStatus:
    """Return current VIP status for user."""

    return _vip_status(current_user)


@router.post("/me/activate", response_model=VIPStatus)
def activate_vip_code(
    payload: ActivationRequest,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> VIPStatus:
    """Consume an activation code and extend VIP."""

    activation_code = crud.get_activation_code(db, payload.code)
    if not activation_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="激活码不存在")
    if activation_code.is_used:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="激活码已被使用")
    expires_at = _ensure_aware(activation_code.expires_at)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="激活码已过期")

    crud.activate_vip(db, current_user)
    crud.mark_activation_code_used(db, activation_code, current_user)
    db.commit()
    db.refresh(current_user)
    return _vip_status(current_user)


@router.get("/me/notifications", response_model=NotificationSettingOut)
def read_notification_settings(
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> NotificationSettingOut:
    """Return stored notification settings."""

    settings = crud.ensure_notification_settings(db, current_user)
    db.commit()
    db.refresh(settings)
    return NotificationSettingOut.model_validate(settings)


@router.put("/me/notifications", response_model=NotificationSettingOut)
def update_notification_settings(
    payload: NotificationSettingUpdate,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> NotificationSettingOut:
    """Update notification settings."""

    settings = crud.ensure_notification_settings(db, current_user)
    updated = crud.update_notification_settings(
        db,
        settings,
        webhook_url=str(payload.webhook_url) if payload.webhook_url else None,
        notify_email=payload.notify_email,
        send_webhook=payload.send_webhook,
        send_email=payload.send_email,
    )
    db.commit()
    db.refresh(updated)
    return NotificationSettingOut.model_validate(updated)


@router.get("/me/push-rules", response_model=list[PushRuleOut])
def list_push_rules(
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> list[PushRuleOut]:
    """List push rules."""

    rules = crud.list_push_rules(db, current_user)
    return [PushRuleOut.model_validate(rule) for rule in rules]


@router.post("/me/push-rules", response_model=PushRuleOut, status_code=status.HTTP_201_CREATED)
def create_push_rule(
    payload: PushRuleCreate,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> PushRuleOut:
    """Create new push rule."""

    rule = crud.create_push_rule(
        db,
        current_user,
        name=payload.name,
        keyword=payload.keyword,
        is_active=payload.is_active,
        notify_via_webhook=payload.notify_via_webhook,
        notify_via_email=payload.notify_via_email,
    )
    db.commit()
    db.refresh(rule)
    return PushRuleOut.model_validate(rule)


@router.put("/me/push-rules/{rule_id}", response_model=PushRuleOut)
def update_push_rule_endpoint(
    rule_id: int,
    payload: PushRuleUpdate,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> PushRuleOut:
    """Update existing push rule."""

    rule = crud.get_push_rule(db, current_user, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="推送规则不存在")
    updated = crud.update_push_rule(
        db,
        rule,
        name=payload.name,
        keyword=payload.keyword,
        is_active=payload.is_active,
        notify_via_webhook=payload.notify_via_webhook,
        notify_via_email=payload.notify_via_email,
    )
    db.commit()
    db.refresh(updated)
    return PushRuleOut.model_validate(updated)


@router.delete("/me/push-rules/{rule_id}", status_code=status.HTTP_200_OK)
def delete_push_rule_endpoint(
    rule_id: int,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Delete push rule."""

    rule = crud.get_push_rule(db, current_user, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="推送规则不存在")
    crud.delete_push_rule(db, rule)
    db.commit()
    return {"status": "deleted"}


@router.get("/me/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions_endpoint(
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> list[SubscriptionOut]:
    """Return all subscriptions for the user."""

    subscriptions = crud.list_subscriptions(db, current_user)
    return [_subscription_to_schema(sub, request) for sub in subscriptions]


@router.post("/me/subscriptions", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
def create_subscription_endpoint(
    payload: SubscriptionCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> SubscriptionOut:
    """Create a subscription."""

    channels = _ensure_valid_channels(db, payload.channel_slugs)
    token = generate_subscription_token(db)
    subscription = crud.create_subscription(
        db,
        current_user,
        name=payload.name,
        token=token,
        keyword_filter=payload.keyword_filter,
        is_active=payload.is_active,
        channel_slugs=channels,
    )
    db.commit()
    db.refresh(subscription)
    return _subscription_to_schema(subscription, request)


@router.put("/me/subscriptions/{subscription_id}", response_model=SubscriptionOut)
def update_subscription_endpoint(
    subscription_id: int,
    payload: SubscriptionUpdate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> SubscriptionOut:
    """Update subscription configuration."""

    subscription = crud.get_subscription(db, current_user, subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在")
    channels = None
    if payload.channel_slugs is not None:
        channels = _ensure_valid_channels(db, payload.channel_slugs)
    updated = crud.update_subscription(
        db,
        subscription,
        name=payload.name,
        keyword_filter=payload.keyword_filter,
        is_active=payload.is_active,
        channel_slugs=channels,
    )
    db.commit()
    db.refresh(updated)
    return _subscription_to_schema(updated, request)


@router.delete("/me/subscriptions/{subscription_id}", status_code=status.HTTP_200_OK)
def delete_subscription_endpoint(
    subscription_id: int,
    db: Session = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
) -> dict[str, str]:
    """Remove a subscription."""

    subscription = crud.get_subscription(db, current_user, subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在")
    crud.delete_subscription(db, subscription)
    db.commit()
    return {"status": "deleted"}
