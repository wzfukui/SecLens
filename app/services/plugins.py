"""Plugin registration and scheduling helpers."""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
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


def compute_next_run(schedule: str | None, reference: datetime | None = None) -> datetime | None:
    if not schedule:
        return None
    reference = reference or datetime.now(timezone.utc)
    schedule = schedule.strip()
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


__all__ = [
    "UPLOAD_ROOT",
    "PluginManifest",
    "ensure_upload_root",
    "extract_plugin_archive",
    "compute_next_run",
    "should_run",
]
