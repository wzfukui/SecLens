"""Notification dispatching for user push rules."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from html import escape
from typing import Sequence
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import crud, models
from app.services.email import EmailNotConfiguredWarning, send_email

logger = logging.getLogger(__name__)


def handle_new_bulletins(session: Session, bulletin_ids: Sequence[int]) -> None:
    """Check bulletins against push rules and dispatch notifications."""

    if not bulletin_ids:
        return

    bulletins = crud.get_bulletins_by_ids(session, bulletin_ids)
    if not bulletins:
        return

    rules = session.scalars(
        select(models.UserPushRule)
        .options(
            selectinload(models.UserPushRule.user).selectinload(models.User.notification_settings),
        )
        .where(models.UserPushRule.is_active.is_(True))
    ).all()

    if not rules:
        return

    for bulletin in bulletins:
        for rule in rules:
            user = rule.user
            if not user or not user.is_active:
                continue
            if not _keyword_match(bulletin, rule.keyword):
                continue
            _dispatch_notifications(user, rule, bulletin)


def _keyword_match(bulletin: models.Bulletin, keyword: str) -> bool:
    normalized = (keyword or "").strip().lower()
    if not normalized:
        return False
    candidates = filter(
        None,
        [
            bulletin.title,
            bulletin.summary,
            bulletin.body_text,
        ],
    )
    combined = " ".join(text.lower() for text in candidates)
    return normalized in combined


def _dispatch_notifications(user: models.User, rule: models.UserPushRule, bulletin: models.Bulletin) -> None:
    settings = user.notification_settings
    if not settings:
        return

    title = bulletin.title or "SecLens 情报更新"
    payload = {
        "user_id": user.id,
        "rule_id": rule.id,
        "rule_name": rule.name,
        "keyword": rule.keyword,
        "bulletin": {
            "id": bulletin.id,
            "title": title,
            "summary": bulletin.summary,
            "origin_url": bulletin.origin_url,
            "source_slug": bulletin.source_slug,
            "published_at": bulletin.published_at.isoformat() if bulletin.published_at else None,
        },
    }
    payload["message"] = f"[SecLens] 关键词「{rule.keyword}」命中新情报：{title}"

    if rule.notify_via_webhook and settings.send_webhook and settings.webhook_url:
        _send_to_webhook(settings.webhook_url, payload, is_test=False, suppress_errors=True)

    if rule.notify_via_email and settings.send_email:
        recipient = settings.notify_email or user.email
        if recipient:
            _send_email_notification(recipient, payload)


def _send_to_webhook(url: str, payload: dict, *, is_test: bool, suppress_errors: bool) -> None:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    body = payload
    if hostname.endswith("oapi.dingtalk.com"):
        body = _build_dingtalk_body(payload, is_test=is_test)
    try:
        response = httpx.post(url, json=body, timeout=5.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - best effort with logging
        logger.warning("Webhook 通知失败 %s: %s", url, exc)
        if not suppress_errors:
            raise


def _send_email_notification(recipient: str, payload: dict) -> None:
    bulletin = payload.get("bulletin", {})
    title = bulletin.get("title") or "SecLens 情报更新"
    summary = bulletin.get("summary") or ""
    origin_url = bulletin.get("origin_url")

    safe_title = escape(title)
    safe_summary = escape(summary) if summary else "暂无摘要"
    safe_keyword = escape(payload.get("keyword", ""))

    html_parts = [
        f"<p>关键词 <strong>{safe_keyword}</strong> 命中了新的情报。</p>",
        f"<p><strong>{safe_title}</strong></p>",
        f"<p>{safe_summary}</p>",
    ]
    if origin_url:
        html_parts.append(f'<p><a href="{escape(origin_url)}" target="_blank" rel="noopener">查看详情</a></p>')
    html_body = "\n".join(html_parts)

    text_parts = [
        f"关键词 {payload.get('keyword')} 命中了新的情报。",
        title,
        summary or "",
    ]
    if origin_url:
        text_parts.append(f"详情链接: {origin_url}")
    text_body = "\n".join(part for part in text_parts if part)

    subject = f"[SecLens] 关键词命中：{payload.get('keyword')}"
    try:
        send_email(to=[recipient], subject=subject, html=html_body, text=text_body or None)
    except EmailNotConfiguredWarning:
        logger.warning("Resend 未配置，无法发送邮件到 %s", recipient)


def send_webhook_test(url: str, user: models.User) -> None:
    """Send a test payload to ensure webhook connectivity."""

    payload = {
        "message": "[SecLens] Webhook 测试消息：配置验证。",
        "user_id": user.id,
        "rule_id": None,
        "rule_name": "Webhook 测试",
        "keyword": "SecLens",
        "is_test": True,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "bulletin": None,
    }
    _send_to_webhook(url, payload, is_test=True, suppress_errors=False)


def _build_dingtalk_body(payload: dict, *, is_test: bool) -> dict:
    """Return a DingTalk-compatible payload."""

    title = payload.get("message") or "SecLens 情报更新"
    lines: list[str] = [title]
    if is_test:
        lines.append("> 这是一次 SecLens Webhook 测试，请确认收到后再启用推送规则。")
    else:
        rule_name = payload.get("rule_name")
        keyword = payload.get("keyword")
        bulletin = payload.get("bulletin") or {}
        if rule_name:
            lines.append(f"> 规则：{rule_name}")
        if keyword:
            lines.append(f"> 关键词：{keyword}")
        if bulletin:
            if bulletin.get("title"):
                lines.append(f"> 标题：{bulletin['title']}")
            if bulletin.get("source_slug"):
                lines.append(f"> 来源：{bulletin['source_slug']}")
            if bulletin.get("summary"):
                lines.append("")
                lines.append(bulletin["summary"])
            if bulletin.get("origin_url"):
                lines.append("")
                lines.append(f"[查看详情]({bulletin['origin_url']})")
    markdown_text = "\n".join(lines)
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": "SecLens 通知",
            "text": markdown_text,
        },
    }


__all__ = ["handle_new_bulletins", "send_webhook_test"]
