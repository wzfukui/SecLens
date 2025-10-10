"""Thin wrapper around the Resend email API."""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailNotConfiguredWarning(RuntimeError):
    """Raised when attempting to send email without configuration."""


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def send_email(
    *,
    to: Iterable[str],
    subject: str,
    html: str,
    text: str | None = None,
) -> None:
    """Send an email via Resend, logging failures."""

    settings = get_settings()
    api_key = settings.resend_api_key
    from_email = settings.resend_from_email
    if not api_key or not from_email:
        logger.warning("Resend 邮件未配置，跳过发送")
        raise EmailNotConfiguredWarning("Resend credentials missing")

    payload: dict[str, object] = {
        "from": from_email,
        "to": list(to),
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    try:
        response = httpx.post(
            f"{settings.resend_api_base_url.rstrip('/')}/emails",
            json=payload,
            timeout=10.0,
            headers=_build_headers(api_key),
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failure logging
        logger.warning("发送邮件失败: %s", exc)


__all__ = ["send_email", "EmailNotConfiguredWarning"]
