"""Plugin registration and scheduling helpers."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

from app.models import Plugin
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "uploads"
MANIFEST_NAME = "manifest.json"


@dataclass(slots=True)
class PluginManifest:
    slug: str
    name: str
    version: str
    entrypoint: str
    description: str | None = None
    schedule: str | None = None
    runtime: dict[str, Any] | None = None
    source: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        required = ["slug", "name", "version", "entrypoint"]
        missing = [field for field in required if field not in data]
        if missing:
            raise ValueError(f"Manifest missing required fields: {missing}")
        return cls(
            slug=data["slug"],
            name=data["name"],
            version=data["version"],
            entrypoint=data["entrypoint"],
            description=data.get("description"),
            schedule=data.get("schedule"),
            runtime=data.get("runtime"),
            source=data.get("source"),
        )


def ensure_upload_root() -> Path:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return UPLOAD_ROOT


def extract_plugin_archive(data: bytes) -> tuple[PluginManifest, Path]:
    """Persist uploaded archive bytes, extract contents, and return manifest + path."""

    ensure_upload_root()

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)

    with ZipFile(tmp_path) as archive:
        if MANIFEST_NAME not in archive.namelist():
            raise ValueError("Plugin archive missing manifest.json")
        manifest_data = json.loads(archive.read(MANIFEST_NAME))
        manifest = PluginManifest.from_dict(manifest_data)
        target_dir = UPLOAD_ROOT / manifest.slug / manifest.version
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        archive.extractall(target_dir)

    tmp_path.unlink(missing_ok=True)
    return manifest, target_dir


def compute_next_run(
    schedule: str | None,
    reference: datetime | None = None,
    *,
    immediate: bool = False,
) -> datetime | None:
    if not schedule:
        return None
    reference = reference or datetime.now(timezone.utc)
    schedule = schedule.strip()
    if immediate:
        return reference
    try:
        interval = int(schedule)
        return reference + timedelta(seconds=interval)
    except ValueError:
        try:
            candidate = datetime.fromisoformat(schedule)
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            return candidate
        except ValueError:
            return None


def should_run(plugin: Plugin, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not plugin.is_active:
        return False
    if not plugin.schedule:
        return False
    if plugin.next_run_at is None:
        plugin.next_run_at = compute_next_run(plugin.schedule, now)
        return False
    return plugin.next_run_at <= now


def load_callable(plugin: Plugin) -> Callable[..., Any]:
    module_path, _, attr = plugin.entrypoint.partition(":")
    if not attr:
        raise ValueError("Entrypoint must be in the form 'module:callable'")

    plugin_dir = Path(plugin.upload_path)
    if plugin_dir.exists() and str(plugin_dir) not in sys.path:  # type: ignore[name-defined]
        sys.path.insert(0, str(plugin_dir))

    module = import_module(module_path)
    func = getattr(module, attr)
    if not callable(func):
        raise TypeError("Entrypoint is not callable")
    return func


__all__ = [
    "UPLOAD_ROOT",
    "PluginManifest",
    "ensure_upload_root",
    "extract_plugin_archive",
    "compute_next_run",
    "should_run",
    "load_callable",
]
