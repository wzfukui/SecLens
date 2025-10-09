"""Simple background scheduler using threading."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from app.config import get_settings
from app.database import get_session_factory
from app.logging_utils import setup_logging
from app.models import Plugin, PluginRun, PluginVersion
from app.services.plugins import compute_next_run, load_callable, should_run

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore

LOGGER = logging.getLogger(__name__)
CHECK_INTERVAL = 30  # seconds

setup_logging()


def _extract_summary(
    result: Any,
    *,
    should_proxy_post: bool,
    ingest_url: str,
    plugin_slug: str,
) -> tuple[list[Any], dict[str, Any] | None]:
    """Return normalized bulletins and ingest response for a collector run."""

    bulletins: list[Any] = []
    response_data: dict[str, Any] | None = None

    if isinstance(result, tuple):
        bulletin_payload, response_payload = result
        if bulletin_payload:
            bulletins = list(bulletin_payload)
        if isinstance(response_payload, dict):
            response_data = response_payload
    elif isinstance(result, list):
        bulletins = list(result)

    if requests and bulletins and should_proxy_post:
        payload = [item.model_dump(mode="json") for item in bulletins]
        api_response = requests.post(ingest_url, json=payload, timeout=30)
        api_response.raise_for_status()
        try:
            response_data = api_response.json()
        except ValueError:
            LOGGER.warning("Ingest response for %s is not JSON-decoded", plugin_slug)

    return bulletins, response_data


def run_plugins_once(plugin_ids: list[int] | None = None, *, force: bool = False):
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
        if plugin_ids is not None:
            versions = [v for v in versions if v.plugin_id in plugin_ids]
        for version in versions:
            if not force and not should_run(version):
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
                bulletins, response_data = _extract_summary(
                    result,
                    should_proxy_post=should_proxy_post,
                    ingest_url=ingest_url,
                    plugin_slug=plugin.slug,
                )

                collected = len(bulletins)
                accepted = response_data.get("accepted") if isinstance(response_data, dict) else None
                duplicates = response_data.get("duplicates") if isinstance(response_data, dict) else None
                if accepted is None and collected:
                    accepted = collected
                if duplicates is None and accepted is not None:
                    duplicates = max(collected - accepted, 0)

                summary_payload = {
                    "collected": collected,
                    "accepted": accepted,
                    "duplicates": duplicates,
                    "ingest_response": response_data,
                }

                run.status = "success"
                message_parts = [f"Collected {collected} items"]
                if accepted is not None:
                    message_parts.append(f"accepted={accepted}")
                if duplicates is not None:
                    message_parts.append(f"duplicates={duplicates}")
                run.message = ", ".join(message_parts)
                try:
                    run.output = json.dumps(summary_payload, ensure_ascii=False)
                except (TypeError, ValueError):
                    run.output = json.dumps(
                        {
                            "collected": collected,
                            "accepted": accepted,
                            "duplicates": duplicates,
                        },
                        ensure_ascii=False,
                    )
                LOGGER.info(
                    "Plugin %s completed: collected=%s accepted=%s duplicates=%s",
                    plugin.slug,
                    collected,
                    accepted,
                    duplicates,
                )
            except Exception as exc:  # pylint: disable=broad-except
                run.status = "failed"
                run.message = str(exc)
                LOGGER.exception("Plugin %s failed: %s", plugin.slug, exc)
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
        LOGGER.info("Starting scheduler thread with interval=%ss", CHECK_INTERVAL)
        thread.start()

    @app.on_event("shutdown")
    def _stop():  # pragma: no cover
        LOGGER.info("Stopping scheduler thread")
        stop_event.set()
        thread.join(timeout=5)

    return thread
