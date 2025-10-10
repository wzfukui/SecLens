"""Subscription helpers for token generation and RSS building."""
from __future__ import annotations

import secrets
from typing import Iterable

from sqlalchemy.orm import Session

from app import crud, models
from app.schemas import BulletinOut


def generate_subscription_token(session: Session, *, max_attempts: int = 10) -> str:
    """Generate a unique subscription token."""

    for _ in range(max_attempts):
        token = secrets.token_urlsafe(24)
        if not crud.get_subscription_by_token(session, token):
            return token
    raise RuntimeError("无法生成唯一的订阅 token，请稍后再试。")


def filter_bulletins_for_subscription(
    bulletins: Iterable[models.Bulletin],
    subscription: models.UserSubscription,
) -> list[BulletinOut]:
    """Filter bulletins by subscription keyword (if provided)."""

    keyword = (subscription.keyword_filter or "").strip().lower()
    if not keyword:
        return [BulletinOut.model_validate(bulletin) for bulletin in bulletins]

    matched: list[BulletinOut] = []
    for bulletin in bulletins:
        haystacks = filter(None, [bulletin.title, bulletin.summary, bulletin.body_text])
        combined = " ".join(text.lower() for text in haystacks)
        if keyword in combined:
            matched.append(BulletinOut.model_validate(bulletin))
    return matched

