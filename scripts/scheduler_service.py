"""Simple background scheduler using threading."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI

from app.database import get_session_factory
from app.models import Plugin, PluginRun
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
        plugins = session.query(Plugin).all()
        for plugin in plugins:
            if not should_run(plugin):
                continue
            LOGGER.info("Running plugin %s", plugin.slug)
            started = datetime.now(timezone.utc)
            run = PluginRun(plugin_id=plugin.id, started_at=started, status="running")
            session.add(run)
            session.commit()

            try:
                func = load_callable(plugin)
                runtime_args = {}
                if plugin.manifest and isinstance(plugin.manifest, dict):
                    runtime_args.update(plugin.manifest.get("runtime", {}))

                if "ingest_url" not in runtime_args:
                    runtime_args["ingest_url"] = ingest_url

                result = func(**runtime_args)

                if requests and isinstance(result, tuple):
                    bulletins, _response = result
                    if bulletins and "ingest_url" not in runtime_args:
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
                plugin.last_run_at = finished
                plugin.next_run_at = compute_next_run(plugin.schedule, finished)
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
