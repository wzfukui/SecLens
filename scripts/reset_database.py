"""Development helper to rebuild SecLens tables from scratch.

This script drops the bulletin/plugin tables and recreates them using the
current SQLAlchemy models. Existing data will be lost.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from sqlalchemy import inspect
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, get_engine
from app import models


def drop_tables(tables: Sequence[str]) -> None:
    engine = get_engine()
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    to_drop = [name for name in tables if name in existing]
    if not to_drop:
        print("No matching tables to drop.")
        return

    with engine.begin() as conn:
        for name in to_drop:
            print(f"Dropping table '{name}'")
            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{name}" CASCADE')


def reset_database() -> None:
    tables_to_reset = [
        "plugin_runs",
        "plugin_versions",
        "plugins",
        "bulletin_topics",
        "bulletin_labels",
        "bulletins",
    ]
    drop_tables(tables_to_reset)
    engine = get_engine()
    print("Recreating tables …")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            models.Bulletin.__table__,
            models.BulletinLabel.__table__,
            models.BulletinTopic.__table__,
            models.Plugin.__table__,
            models.PluginVersion.__table__,
            models.PluginRun.__table__,
        ],
    )
    print("Database reset complete.")


LINUXSECURITY_SOURCES = ("linuxsecurity_hybrid",)


def clear_linuxsecurity_data() -> None:
    engine = get_engine()
    with Session(engine) as session:
        bulletins = (
            session.query(models.Bulletin)
            .filter(models.Bulletin.source_slug.in_(LINUXSECURITY_SOURCES))
            .all()
        )
        if not bulletins:
            print("No LinuxSecurity bulletins found.")
            return
        total = len(bulletins)
        print(f"Deleting {total} LinuxSecurity bulletins …")
        for bulletin in bulletins:
            session.delete(bulletin)
        session.commit()
        print("LinuxSecurity data cleanup complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset SecLens development database (drops data).")
    parser.add_argument(
        "--source",
        choices=["all", "linuxsecurity"],
        default="all",
        help="Target dataset to reset. Defaults to 'all'.",
    )
    args = parser.parse_args()
    if args.source == "all":
        reset_database()
    elif args.source == "linuxsecurity":
        clear_linuxsecurity_data()
    else:
        parser.error(f"Unsupported source: {args.source!r}")


if __name__ == "__main__":
    main()
