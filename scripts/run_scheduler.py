"""Lightweight scheduler for registered plugins."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import get_session_factory
from app.models import Plugin, PluginRun, PluginVersion
from app.services.plugins import (
    UPLOAD_ROOT,
    compute_next_run,
    load_callable,
    should_run,
)


def run_plugin(version: PluginVersion, ingest_override: str | None = None) -> PluginRun:
    Session = get_session_factory()
    with Session() as session:
        version = session.get(PluginVersion, version.id)
        if version is None:
            raise RuntimeError("Plugin version not found")
        plugin = version.plugin
        started_at = datetime.now(timezone.utc)
        run = PluginRun(
            plugin_id=plugin.id,
            plugin_version_id=version.id,
            started_at=started_at,
            status="running",
        )
        session.add(run)
        session.commit()

        try:
            func = load_callable(version)
            runtime_cfg = version.manifest.get("runtime", {}) if version.manifest else {}
            if ingest_override:
                runtime_cfg = dict(runtime_cfg or {})
                runtime_cfg["ingest_url"] = ingest_override
            result = func(**runtime_cfg) if runtime_cfg else func()
            output = None
            if result is not None:
                try:
                    output = json.dumps(result, ensure_ascii=False)
                except TypeError:
                    output = str(result)
            run.status = "success"
            run.message = "Completed"
            run.output = output
        except Exception as exc:  # pylint: disable=broad-except
            run.status = "failed"
            run.message = str(exc)
            run.output = traceback.format_exc()
        finally:
            finished = datetime.now(timezone.utc)
            run.finished_at = finished
            version.last_run_at = finished
            version.next_run_at = compute_next_run(version.schedule, finished)
            plugin.updated_at = finished
            session.commit()
        return run


def poll_plugins(ingest_override: str | None = None) -> None:
    Session = get_session_factory()
    with Session() as session:
        versions = (
            session.query(PluginVersion)
            .join(Plugin, PluginVersion.plugin_id == Plugin.id)
            .filter(Plugin.is_enabled.is_(True), PluginVersion.is_active.is_(True))
            .all()
        )
        due_versions = [version for version in versions if should_run(version)]
        session.commit()
        for version in due_versions:
            session.refresh(version)
            run_plugin(version, ingest_override=ingest_override)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run due plugins based on their schedules")
    parser.add_argument(
        "--ingest-url",
        dest="ingest_url",
        help="Override ingest URL when invoking plugin entrypoints",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run due plugins once and exit (default).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not UPLOAD_ROOT.exists():
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    poll_plugins(ingest_override=args.ingest_url)


if __name__ == "__main__":
    main()
