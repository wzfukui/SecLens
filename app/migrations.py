"""Lightweight, idempotent schema migrations for new invitation features."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import crud, models


def _add_users_invite_code_column(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "invite_code" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN invite_code VARCHAR(16)"))

    # Ensure indexes/unique constraints exist even if column existed beforehand.
    user_table = models.User.__table__
    for index in user_table.indexes:
        if any(col.name == "invite_code" for col in index.columns):
            index.create(bind=engine, checkfirst=True)


def _create_user_invitations_table(engine: Engine) -> None:
    inspector = inspect(engine)
    if "user_invitations" in inspector.get_table_names():
        return

    models.UserInvitation.__table__.create(bind=engine, checkfirst=True)


def _backfill_invite_codes(session: Session) -> None:
    pending_users = session.query(models.User).filter(models.User.invite_code.is_(None)).all()
    if not pending_users:
        return

    for user in pending_users:
        crud.ensure_invite_code(session, user)
    session.commit()


def apply_post_deployment_migrations(engine: Engine, session_factory) -> None:
    """Ensure new invitation schema exists and backfill existing users."""

    _add_users_invite_code_column(engine)
    _create_user_invitations_table(engine)

    with session_factory() as session:
        _backfill_invite_codes(session)
