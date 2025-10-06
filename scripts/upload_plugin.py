"""CLI utility to upload a plugin archive and verify it via the SecLens API."""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from pathlib import Path
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

import requests

DEFAULT_BASE_URL = "http://localhost:8000"
IGNORED_SUFFIXES = {".pyc", ".pyo", ".pyd"}
IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".DS_Store"}


class UploadError(RuntimeError):
    """Raised when the upload or verification workflow fails."""


def _iter_content_files(base_path: Path) -> Iterable[Path]:
    for candidate in sorted(base_path.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.suffix in IGNORED_SUFFIXES:
            continue
        if any(part in IGNORED_NAMES for part in candidate.parts):
            continue
        yield candidate


def build_plugin_archive(source_path: Path) -> tuple[str, bytes, dict[str, str]]:
    if source_path.is_file():
        if source_path.suffix != ".zip":
            raise UploadError("Archive mode requires a .zip file")
        manifest = _load_manifest_from_archive(source_path)
        return source_path.name, source_path.read_bytes(), manifest

    manifest_path = source_path / "manifest.json"
    if not manifest_path.is_file():
        raise UploadError("Plugin directory missing manifest.json")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    slug = manifest_data.get("slug")
    version = manifest_data.get("version")
    if not slug or not version:
        raise UploadError("Manifest must define 'slug' and 'version'")

    filename = f"{slug}-{version}.zip"

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in _iter_content_files(source_path):
            archive.write(file_path, file_path.relative_to(source_path).as_posix())
    return filename, buffer.getvalue(), manifest_data


def _load_manifest_from_archive(archive_path: Path) -> dict[str, str]:
    with ZipFile(archive_path, "r") as archive:
        try:
            with archive.open("manifest.json") as manifest_file:
                return json.load(manifest_file)
        except KeyError as exc:
            raise UploadError("Archive does not contain manifest.json") from exc


def upload_plugin(base_url: str, *, filename: str, archive_bytes: bytes) -> dict[str, object]:
    encoded = base64.b64encode(archive_bytes).decode("ascii")
    response = requests.post(
        f"{base_url.rstrip('/')}/v1/plugins/upload",
        json={"filename": filename, "content": encoded},
        timeout=30,
    )
    if response.status_code >= 400:
        raise UploadError(f"Upload failed with status {response.status_code}: {response.text}")
    return response.json()


def verify_plugin(base_url: str, *, slug: str, version: str) -> dict[str, object]:
    response = requests.get(
        f"{base_url.rstrip('/')}/v1/plugins",
        timeout=30,
    )
    if response.status_code >= 400:
        raise UploadError(f"Verification failed with status {response.status_code}: {response.text}")

    payload = response.json()
    items = payload.get("items", [])
    for item in items:
        if item.get("slug") == slug and item.get("version") == version:
            return item
    raise UploadError(f"Uploaded plugin {slug} v{version} not found in listing")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a plugin to the SecLens ingest platform.")
    parser.add_argument("source", help="Path to the plugin directory or pre-built .zip archive")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="SecLens API base URL")
    parser.add_argument("--skip-verify", action="store_true", help="Skip verification step")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_path = Path(args.source).expanduser().resolve()

    try:
        filename, archive_bytes, manifest = build_plugin_archive(source_path)
        upload_info = upload_plugin(args.base_url, filename=filename, archive_bytes=archive_bytes)
        slug = manifest.get("slug", "<unknown>")
        version = manifest.get("version", "<unknown>")

        print(f"Uploaded {slug} v{version} as {filename}")
        if args.skip_verify:
            print(json.dumps(upload_info, indent=2, ensure_ascii=False))
            return 0

        verified = verify_plugin(args.base_url, slug=slug, version=version)
        print("Verification succeeded:")
        print(json.dumps(verified, indent=2, ensure_ascii=False))
        return 0
    except (UploadError, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
