"""Lightweight scheduler for registered plugins."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from app.database import get_session_factory
from app.models import Plugin, PluginRun
from app.services.plugins import UPLOAD_ROOT, compute_next_run, should_run


def load_callable(plugin: Plugin):
    module_path, _, attr = plugin.entrypoint.partition(":")
    if not attr:
        raise ValueError("Entrypoint must be in the form 'module:callable'")

    plugin_dir = Path(plugin.upload_path)
    if plugin_dir.exists() and str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))

    module = importlib.import_module(module_path)
    func = getattr(module, attr)
    if not callable(func):
        raise TypeError("Entrypoint is not callable")
    return func


def run_plugin(plugin: Plugin, ingest_override: str | None = None) -> PluginRun:
    Session = get_session_factory()
    with Session() as session:
        plugin = session.get(Plugin, plugin.id)
        started_at = datetime.now(timezone.utc)
        run = PluginRun(plugin_id=plugin.id, started_at=started_at, status="running")
        session.add(run)
        session.commit()

        try:
            func = load_callable(plugin)
            runtime_cfg = plugin.manifest.get("runtime", {}) if plugin.manifest else {}
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
            plugin.last_run_at = finished
            plugin.next_run_at = compute_next_run(plugin.schedule, finished)
            session.commit()
        return run


def poll_plugins(ingest_override: str | None = None) -> None:
    Session = get_session_factory()
    with Session() as session:
        plugins = session.query(Plugin).all()
        due_plugins = [plugin for plugin in plugins if should_run(plugin)]
        session.commit()
        for plugin in due_plugins:
            session.refresh(plugin)
            run_plugin(plugin, ingest_override=ingest_override)


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
