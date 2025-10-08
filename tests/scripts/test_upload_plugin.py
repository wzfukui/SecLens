from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.upload_plugin import UploadError, build_plugin_archive


def test_build_plugin_archive_from_directory(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "exploit_db"
    shutil.copytree(Path("resources/exploit_db"), plugin_dir)

    pycache_dir = plugin_dir / "__pycache__"
    pycache_dir.mkdir(exist_ok=True)
    (pycache_dir / "ignored.pyc").write_bytes(b"ignored")

    filename, archive_bytes, manifest = build_plugin_archive(plugin_dir)

    assert filename == "exploit_db-1.0.0.zip"
    assert manifest["slug"] == "exploit_db"
    assert manifest["version"] == "1.0.0"

    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "collector.py" in names
        assert "__pycache__/ignored.pyc" not in names


def test_build_plugin_archive_requires_manifest(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "collector.py").write_text("x = 1", encoding="utf-8")

    with pytest.raises(UploadError):
        build_plugin_archive(plugin_dir)


def test_build_plugin_archive_from_zip(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    shutil.copytree(Path("resources/exploit_db"), plugin_dir)

    zip_path = tmp_path / "archive.zip"
    with ZipFile(zip_path, "w") as archive:
        for path in plugin_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(plugin_dir).as_posix())

    filename, archive_bytes, manifest = build_plugin_archive(zip_path)

    assert filename == "archive.zip"
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest_in_zip = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert manifest_in_zip["slug"] == manifest["slug"]
