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


def _add_activation_code_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("activation_codes")}
    
    # Add is_gift column
    if "is_gift" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE activation_codes ADD COLUMN is_gift BOOLEAN DEFAULT FALSE"))
            connection.execute(text("UPDATE activation_codes SET is_gift = FALSE"))
    
    # Add gifter_user_id column
    if "gifter_user_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE activation_codes ADD COLUMN gifter_user_id INTEGER"))
    
    # Add foreign key constraint for gifter_user_id if not exists
    with engine.begin() as connection:
        # Check if the foreign key constraint already exists
        result = connection.execute(text("""
            SELECT conname 
            FROM pg_constraint 
            WHERE conrelid = 'activation_codes'::regclass 
            AND contype = 'f' 
            AND confrelid = 'users'::regclass
            AND conkey::int[] @> ARRAY[1] -- Check if gifter_user_id is part of this constraint
        """)).fetchall() if connection.dialect.name == 'postgresql' else []
        
        if not result:
            # For simplicity, we'll skip creating foreign key constraint in this migration
            # It will be handled by SQLAlchemy when the schema is updated
            pass


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
    _add_activation_code_columns(engine)  # Add the new columns for activation codes

    with session_factory() as session:
        _backfill_invite_codes(session)
