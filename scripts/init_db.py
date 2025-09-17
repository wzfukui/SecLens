"""Utility script to create database tables for the SecLens MVP."""
from sqlalchemy import inspect, text

from app.database import Base, get_engine
from app.models import Plugin, PluginRun


def main() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    columns = {col.get("name") for col in inspector.get_columns("bulletins")}
    if "attributes" not in columns:
        with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                connection.execute(text("ALTER TABLE bulletins ADD COLUMN attributes JSONB"))
            else:
                connection.execute(text("ALTER TABLE bulletins ADD COLUMN attributes JSON"))
        print("Added attributes column to bulletins table.")

    if "plugins" not in inspector.get_table_names():
        Plugin.__table__.create(bind=engine)
        print("Created plugins table.")
    if "plugin_runs" not in inspector.get_table_names():
        PluginRun.__table__.create(bind=engine)
        print("Created plugin_runs table.")
    print("Database tables ensured.")


if __name__ == "__main__":
    main()
