"""Plugin registration and scheduling helpers."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from typing import Any, Callable
from zipfile import ZipFile

from app.models import PluginVersion
UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "uploads"
MANIFEST_NAME = "manifest.json"


@dataclass
class PluginManifest:
    slug: str
    name: str
    version: str
    entrypoint: str
    description: str | None = None
    schedule: str | None = None
    runtime: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None

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
            ui=data.get("ui"),
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


def should_run(version: PluginVersion, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not version.is_active:
        return False
    if not version.schedule:
        return False
    if version.next_run_at is None:
        version.next_run_at = compute_next_run(version.schedule, now)
        return False
    return version.next_run_at <= now


def load_callable(version: PluginVersion) -> Callable[..., Any]:
    module_path, _, attr = version.entrypoint.partition(":")
    if not attr:
        raise ValueError("Entrypoint must be in the form 'module:callable'")

    plugin_dir = Path(version.upload_path)
    if not plugin_dir.exists():
        raise FileNotFoundError(f"Plugin files for {version.plugin.slug} not found at {plugin_dir}")
    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))

    # Build a unique module name per plugin version to avoid collisions between
    # different plugins all exposing `collector.py`.
    unique_module_name = f"_seclens.plugins.{version.plugin.slug}.{version.version.replace('.', '_')}.{module_path}"
    module_rel_path = Path(*module_path.split("."))

    def _load_from_file(file_path: Path, *, is_package: bool = False):
        spec = importlib.util.spec_from_file_location(
            unique_module_name,
            file_path,
            submodule_search_locations=[str(file_path.parent)] if is_package else None,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module '{module_path}' from '{file_path}'")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_module_name] = module
        # Ensure we don't accidentally reuse a stale bare module name if another plugin registered it.
        sys.modules.pop(module_path, None)
        spec.loader.exec_module(module)
        # Expose the bare module name for runtime code that might import it directly,
        # while keeping a unique canonical name to avoid cross-plugin collisions.
        sys.modules[module_path] = module
        return module

    if module_rel_path.suffix:
        # Prevent inputs like "collector.py"
        raise ValueError("Entrypoint module should be a dotted path without file suffix")

    candidate = plugin_dir / module_rel_path
    if candidate.with_suffix(".py").is_file():
        module = _load_from_file(candidate.with_suffix(".py"))
    elif candidate.is_dir() and (candidate / "__init__.py").is_file():
        module = _load_from_file(candidate / "__init__.py", is_package=True)
    else:
        raise FileNotFoundError(f"Module '{module_path}' not found for plugin {version.plugin.slug}")

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
