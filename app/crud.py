"""Database helper functions for ingest API."""
from datetime import datetime, timedelta, timezone
import secrets
import string
from typing import Iterable, Optional, Sequence, Tuple

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app import models
from app.schemas import BulletinCreate


def upsert_bulletin(session: Session, payload: BulletinCreate) -> Tuple[models.Bulletin, bool]:
    """Insert a bulletin or update an existing record.

    Returns a tuple of (bulletin, created_flag).
    """

    existing = None
    if payload.source.external_id:
        stmt = select(models.Bulletin).where(
            models.Bulletin.source_slug == payload.source.source_slug,
            models.Bulletin.external_id == payload.source.external_id,
        )
        existing = session.scalars(stmt).first()
    now = datetime.now(timezone.utc)
    if existing:
        existing.title = payload.content.title
        existing.summary = payload.content.summary
        existing.body_text = payload.content.body_text
        existing.origin_url = str(payload.source.origin_url) if payload.source.origin_url else None
        existing.severity = payload.severity
        existing.labels = payload.labels
        existing.topics = payload.topics
        existing.attributes = payload.extra or existing.attributes
        existing.published_at = payload.content.published_at
        existing.fetched_at = payload.fetched_at or existing.fetched_at or now
        existing.updated_at = now
        existing.raw = payload.raw
        created = False
        bulletin = existing
    else:
        bulletin = models.Bulletin(
            source_slug=payload.source.source_slug,
            external_id=payload.source.external_id,
            title=payload.content.title,
            summary=payload.content.summary,
            body_text=payload.content.body_text,
            origin_url=str(payload.source.origin_url) if payload.source.origin_url else None,
            severity=payload.severity,
            published_at=payload.content.published_at,
            fetched_at=payload.fetched_at or now,
            created_at=now,
            updated_at=now,
            attributes=payload.extra,
            raw=payload.raw,
        )
        bulletin.labels = payload.labels
        bulletin.topics = payload.topics
        session.add(bulletin)
        created = True
    return bulletin, created


def _base_bulletin_query() -> Select:
    return select(models.Bulletin).options(
        selectinload(models.Bulletin.label_links),
        selectinload(models.Bulletin.topic_links),
    )


def list_bulletins(
    session: Session,
    *,
    source_slug: Optional[str] = None,
    label: Optional[str] = None,
    topic: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    text: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[models.Bulletin], int]:
    """Return bulletins matching filters with a total count."""

    base_query = _base_bulletin_query()

    if source_slug:
        base_query = base_query.where(models.Bulletin.source_slug == source_slug)
    if label:
        base_query = base_query.join(models.Bulletin.label_links).where(models.BulletinLabel.label == label)
    if topic:
        base_query = base_query.join(models.Bulletin.topic_links).where(models.BulletinTopic.topic == topic)
    if since:
        base_query = base_query.where(models.Bulletin.published_at >= since)
    if until:
        base_query = base_query.where(models.Bulletin.published_at <= until)
    if text:
        like_pattern = f"%{text}%"
        base_query = base_query.where(models.Bulletin.title.ilike(like_pattern))

    if label or topic:
        base_query = base_query.distinct(models.Bulletin.id)

    total_stmt = select(func.count()).select_from(base_query.subquery())
    total = session.execute(total_stmt).scalar_one()

    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    order_columns = [
        models.Bulletin.published_at.desc().nullslast(),
        models.Bulletin.id.desc(),
    ]

    if label or topic:
        query = (
            select(models.Bulletin)
            .where(models.Bulletin.id.in_(base_query.with_only_columns(models.Bulletin.id)))
            .order_by(*order_columns)
        )
    else:
        query = base_query.order_by(*order_columns)

    results = session.scalars(query.limit(safe_limit).offset(safe_offset)).all()
    return results, int(total)


def get_bulletin(session: Session, bulletin_id: int) -> Optional[models.Bulletin]:
    """Fetch a single bulletin by primary key."""

    stmt = _base_bulletin_query().where(models.Bulletin.id == bulletin_id)
    return session.scalars(stmt).first()


# --- User and VIP helpers ---


def get_user_by_id(session: Session, user_id: int) -> Optional[models.User]:
    """Return user by primary key."""

    return session.get(models.User, user_id)


def get_user_by_email(session: Session, email: str) -> Optional[models.User]:
    """Return user by email (case-insensitive)."""

    normalized = email.strip().lower()
    stmt = select(models.User).where(models.User.email == normalized)
    return session.scalars(stmt).first()


INVITE_CODE_ALPHABET = string.ascii_letters + string.digits
INVITE_CODE_LENGTH = 5


def _generate_invite_code(session: Session) -> str:
    """Return a unique invitation code for a user."""

    for _ in range(64):
        code = "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))
        exists_stmt = select(models.User.id).where(models.User.invite_code == code)
        if session.execute(exists_stmt).first() is None:
            return code
    raise RuntimeError("无法生成唯一的邀请码，请重试")


def ensure_invite_code(session: Session, user: models.User) -> str:
    """Make sure a user record carries an invitation code."""

    if user.invite_code:
        return user.invite_code
    user.invite_code = _generate_invite_code(session)
    user.updated_at = datetime.now(timezone.utc)
    session.add(user)
    return user.invite_code


def get_user_by_invite_code(session: Session, invite_code: str) -> Optional[models.User]:
    """Return inviter by invitation code."""

    normalized = invite_code.strip()
    if not normalized:
        return None
    stmt = select(models.User).where(models.User.invite_code == normalized)
    return session.scalars(stmt).first()


def create_user(
    session: Session,
    *,
    email: str,
    password_hash: str,
    display_name: Optional[str] = None,
    is_admin: bool = False,
) -> models.User:
    """Persist a new user."""

    now = datetime.now(timezone.utc)
    user = models.User(
        email=email.strip().lower(),
        password_hash=password_hash,
        display_name=display_name,
        is_admin=is_admin,
        created_at=now,
        updated_at=now,
    )
    user.invite_code = _generate_invite_code(session)
    session.add(user)
    session.flush()
    return user


def touch_user_login(session: Session, user: models.User) -> None:
    """Update last login timestamp and updated_at."""

    now = datetime.now(timezone.utc)
    user.last_login_at = now
    user.updated_at = now
    session.add(user)


def _vip_extension(now: datetime, existing_expiry: Optional[datetime], days: int = 365) -> datetime:
    current_expiry = _normalize_to_utc(existing_expiry)
    term = timedelta(days=days)
    base = current_expiry if current_expiry and current_expiry > now else now
    return base + term


def create_gift_vip_activation_code(session: Session, gifter_user: models.User, invitee_user: models.User) -> models.ActivationCode:
    """Create a special activation code for gifting VIP to invitee and activate it directly."""
    import secrets
    import string
    
    # 生成一个唯一的激活码
    alphabet = string.ascii_letters + string.digits
    for _ in range(64):  # 尝试最多64次生成唯一激活码
        code = "".join(secrets.choice(alphabet) for _ in range(16))  # 16位激活码
        exists_stmt = select(models.ActivationCode).where(models.ActivationCode.code == code)
        if not session.execute(exists_stmt).first():
            break
    else:
        raise RuntimeError("无法生成唯一的激活码，请重试")
    
    # 设置30天后过期
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=30)
    
    # 创建激活码记录 - 直接激活到被邀请人账户
    activation_code = models.ActivationCode(
        code=code,
        is_used=True,  # 直接标记为已使用
        is_gift=True,  # 标识这是赠送的激活码
        gifter_user_id=gifter_user.id,  # 记录赠送者ID
        batch="gift_vip",  # 标识这是赠送VIP的激活码
        notes=f"Gift from user {gifter_user.id} to {invitee_user.id}",
        created_at=now,
        expires_at=expires_at,
        used_at=now,  # 标记使用时间为现在
        used_by_user_id=invitee_user.id  # 标记被谁使用
    )
    
    session.add(activation_code)
    session.flush()  # 获取ID
    
    # 直接为被邀请用户激活VIP（30天）
    activate_vip(session, invitee_user, days=30)
    
    return activation_code


def has_user_been_gifted_vip(session: Session, invitee_user: models.User) -> bool:
    """检查被邀请者是否已经被赠送过VIP（任何邀请人赠送的）."""
    stmt = select(models.ActivationCode).where(
        models.ActivationCode.used_by_user_id == invitee_user.id,
        models.ActivationCode.is_gift == True,
        models.ActivationCode.is_used == True
    )
    result = session.execute(stmt).first()
    return result is not None


def _normalize_to_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def record_invitation(session: Session, inviter: models.User, invitee: models.User) -> models.UserInvitation:
    """Persist an invitation link between inviter and invitee if not already stored."""

    if inviter.id == invitee.id:
        raise ValueError("Inviter and invitee cannot be the same user")
    existing_stmt = select(models.UserInvitation).where(models.UserInvitation.invitee_id == invitee.id)
    existing = session.scalars(existing_stmt).first()
    if existing:
        return existing
    invitation = models.UserInvitation(inviter_id=inviter.id, invitee_id=invitee.id)
    session.add(invitation)
    return invitation


def list_invitations(
    session: Session,
    inviter: models.User,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[models.UserInvitation], int]:
    """Return a paginated list of invitation records for an inviter."""

    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    count_stmt = select(func.count()).select_from(models.UserInvitation).where(models.UserInvitation.inviter_id == inviter.id)
    total = session.execute(count_stmt).scalar_one()
    query = (
        select(models.UserInvitation)
        .options(selectinload(models.UserInvitation.invitee))
        .where(models.UserInvitation.inviter_id == inviter.id)
        .order_by(models.UserInvitation.created_at.desc(), models.UserInvitation.id.desc())
        .limit(safe_limit)
        .offset(safe_offset)
    )
    records = session.scalars(query).all()
    return records, int(total)


def activate_vip(session: Session, user: models.User, days: int = 365) -> None:
    """Grant or extend VIP for specified days from activation."""

    now = datetime.now(timezone.utc)
    user.vip_activated_at = user.vip_activated_at or now
    user.vip_expires_at = _vip_extension(now, user.vip_expires_at, days)
    user.updated_at = now
    session.add(user)


def get_activation_code(session: Session, code: str) -> Optional[models.ActivationCode]:
    """Return activation code instance."""

    normalized = code.strip()
    stmt = select(models.ActivationCode).where(models.ActivationCode.code == normalized)
    return session.scalars(stmt).first()


def mark_activation_code_used(
    session: Session,
    activation_code: models.ActivationCode,
    user: models.User,
) -> None:
    """Mark activation code as consumed by user."""

    now = datetime.now(timezone.utc)
    activation_code.is_used = True
    activation_code.used_at = now
    activation_code.used_by_user = user
    session.add(activation_code)


def ensure_notification_settings(session: Session, user: models.User) -> models.UserNotificationSetting:
    """Return or create notification settings for user."""

    if user.notification_settings:
        return user.notification_settings
    settings = models.UserNotificationSetting(user_id=user.id)
    session.add(settings)
    session.flush()
    return settings


def update_notification_settings(
    session: Session,
    settings: models.UserNotificationSetting,
    *,
    webhook_url: Optional[str],
    notify_email: Optional[str],
    send_webhook: bool,
    send_email: bool,
) -> models.UserNotificationSetting:
    """Persist notification settings updates."""

    settings.webhook_url = webhook_url
    settings.notify_email = notify_email
    settings.send_webhook = send_webhook
    settings.send_email = send_email
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    return settings


def list_push_rules(session: Session, user: models.User) -> Sequence[models.UserPushRule]:
    """Return push rules for user."""

    stmt = (
        select(models.UserPushRule)
        .where(models.UserPushRule.user_id == user.id)
        .order_by(models.UserPushRule.created_at.asc())
    )
    return session.scalars(stmt).all()


def create_push_rule(
    session: Session,
    user: models.User,
    *,
    name: str,
    keyword: str,
    is_active: bool,
    notify_via_webhook: bool,
    notify_via_email: bool,
) -> models.UserPushRule:
    """Create push rule."""

    now = datetime.now(timezone.utc)
    rule = models.UserPushRule(
        user_id=user.id,
        name=name,
        keyword=keyword,
        is_active=is_active,
        notify_via_webhook=notify_via_webhook,
        notify_via_email=notify_via_email,
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    return rule


def get_push_rule(session: Session, user: models.User, rule_id: int) -> Optional[models.UserPushRule]:
    """Fetch single push rule by id ensuring ownership."""

    stmt = select(models.UserPushRule).where(
        models.UserPushRule.id == rule_id,
        models.UserPushRule.user_id == user.id,
    )
    return session.scalars(stmt).first()


def update_push_rule(
    session: Session,
    rule: models.UserPushRule,
    *,
    name: Optional[str] = None,
    keyword: Optional[str] = None,
    is_active: Optional[bool] = None,
    notify_via_webhook: Optional[bool] = None,
    notify_via_email: Optional[bool] = None,
) -> models.UserPushRule:
    """Apply updates to push rule."""

    if name is not None:
        rule.name = name
    if keyword is not None:
        rule.keyword = keyword
    if is_active is not None:
        rule.is_active = is_active
    if notify_via_webhook is not None:
        rule.notify_via_webhook = notify_via_webhook
    if notify_via_email is not None:
        rule.notify_via_email = notify_via_email
    rule.updated_at = datetime.now(timezone.utc)
    session.add(rule)
    return rule


def delete_push_rule(session: Session, rule: models.UserPushRule) -> None:
    """Delete rule."""

    session.delete(rule)


def list_subscriptions(
    session: Session,
    user: models.User,
) -> Sequence[models.UserSubscription]:
    """Return subscriptions for user."""

    stmt = (
        select(models.UserSubscription)
        .options(selectinload(models.UserSubscription.channel_links))
        .where(models.UserSubscription.user_id == user.id)
        .order_by(models.UserSubscription.created_at.asc())
    )
    return session.scalars(stmt).all()


def get_subscription(
    session: Session,
    user: models.User,
    subscription_id: int,
) -> Optional[models.UserSubscription]:
    """Return single subscription ensuring ownership."""

    stmt = (
        select(models.UserSubscription)
        .options(selectinload(models.UserSubscription.channel_links))
        .where(
            models.UserSubscription.id == subscription_id,
            models.UserSubscription.user_id == user.id,
        )
    )
    return session.scalars(stmt).first()


def create_subscription(
    session: Session,
    user: models.User,
    *,
    name: str,
    token: str,
    keyword_filter: Optional[str],
    is_active: bool,
    channel_slugs: Iterable[str],
) -> models.UserSubscription:
    """Create subscription entry and channel links."""

    now = datetime.now(timezone.utc)
    subscription = models.UserSubscription(
        user_id=user.id,
        name=name,
        token=token,
        keyword_filter=keyword_filter,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    subscription.channel_links = [
        models.UserSubscriptionChannel(subscription=subscription, plugin_slug=slug)
        for slug in _normalize_channel_slugs(channel_slugs)
    ]
    session.add(subscription)
    return subscription


def update_subscription(
    session: Session,
    subscription: models.UserSubscription,
    *,
    name: Optional[str] = None,
    keyword_filter: Optional[str] = None,
    is_active: Optional[bool] = None,
    channel_slugs: Optional[Iterable[str]] = None,
) -> models.UserSubscription:
    """Update subscription record."""

    if name is not None:
        subscription.name = name
    if keyword_filter is not None:
        subscription.keyword_filter = keyword_filter
    if is_active is not None:
        subscription.is_active = is_active
    if channel_slugs is not None:
        subscription.channel_links = [
            models.UserSubscriptionChannel(subscription=subscription, plugin_slug=slug)
            for slug in _normalize_channel_slugs(channel_slugs)
        ]
    subscription.updated_at = datetime.now(timezone.utc)
    session.add(subscription)
    return subscription


def delete_subscription(session: Session, subscription: models.UserSubscription) -> None:
    """Delete subscription entry."""

    session.delete(subscription)


def _normalize_channel_slugs(channel_slugs: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for slug in channel_slugs:
        normalized = slug.strip()
        if not normalized or normalized in seen:
            continue
        seen.append(normalized)
    return seen


def get_subscription_by_token(session: Session, token: str) -> Optional[models.UserSubscription]:
    """Fetch subscription via token."""

    stmt = (
        select(models.UserSubscription)
        .options(
            selectinload(models.UserSubscription.channel_links),
            selectinload(models.UserSubscription.user),
        )
        .where(models.UserSubscription.token == token)
    )
    return session.scalars(stmt).first()


def get_bulletins_by_ids(session: Session, bulletin_ids: Sequence[int]) -> list[models.Bulletin]:
    """Fetch bulletins by ids preserving requested order."""

    if not bulletin_ids:
        return []
    stmt = select(models.Bulletin).where(models.Bulletin.id.in_(bulletin_ids))
    rows = session.scalars(stmt).all()
    order_map = {bulletin_id: index for index, bulletin_id in enumerate(bulletin_ids)}
    return sorted(rows, key=lambda bulletin: order_map.get(bulletin.id, len(order_map)))
