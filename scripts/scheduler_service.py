"""Simple background scheduler using threading."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from app.database import get_session_factory
from app.models import Plugin, PluginRun, PluginVersion
from app.services.plugins import load_callable, should_run, compute_next_run
from app.config import get_settings

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

LOGGER = logging.getLogger(__name__)
CHECK_INTERVAL = 30  # seconds


def run_plugins_once():
    Session = get_session_factory()
    settings = get_settings()
    ingest_url = settings.ingest_base_url.rstrip("/") + "/v1/ingest/bulletins"
    with Session() as session:
        versions = (
            session.query(PluginVersion)
            .join(Plugin, PluginVersion.plugin_id == Plugin.id)
            .filter(Plugin.is_enabled.is_(True), PluginVersion.is_active.is_(True))
            .all()
        )
        for version in versions:
            if not should_run(version):
                continue
            plugin = version.plugin
            LOGGER.info("Running plugin %s@%s", plugin.slug, version.version)
            started = datetime.now(timezone.utc)
            run = PluginRun(
                plugin_id=plugin.id,
                plugin_version_id=version.id,
                started_at=started,
                status="running",
            )
            session.add(run)
            session.commit()

            try:
                func = load_callable(version)
                runtime_args: dict[str, Any] = {}
                should_proxy_post = True
                if version.manifest and isinstance(version.manifest, dict):
                    runtime_args.update(version.manifest.get("runtime", {}))
                if "ingest_url" not in runtime_args:
                    runtime_args["ingest_url"] = ingest_url
                else:
                    should_proxy_post = False

                result = func(**runtime_args)

                if requests and isinstance(result, tuple):
                    bulletins, _response = result
                    if bulletins and should_proxy_post:
                        payload = [item.model_dump(mode="json") for item in bulletins]
                        requests.post(ingest_url, json=payload, timeout=30)
                run.status = "success"
                run.message = "Completed"
            except Exception as exc:  # pylint: disable=broad-except
                run.status = "failed"
                run.message = str(exc)
            finally:
                finished = datetime.now(timezone.utc)
                run.finished_at = finished
                version.last_run_at = finished
                version.next_run_at = compute_next_run(version.schedule, finished)
                version.updated_at = finished
                plugin.updated_at = finished
                session.commit()


def start_scheduler(app: FastAPI):
    stop_event = threading.Event()

    def loop():
        while not stop_event.is_set():
            try:
                run_plugins_once()
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception("Scheduler error: %s", exc)
            stop_event.wait(CHECK_INTERVAL)

    thread = threading.Thread(target=loop, daemon=True)

    @app.on_event("startup")
    def _start():  # pragma: no cover
        thread.start()

    @app.on_event("shutdown")
    def _stop():  # pragma: no cover
        stop_event.set()
        thread.join(timeout=5)

    return thread
