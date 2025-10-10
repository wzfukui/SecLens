"""Utility to package resources plugins and optionally upload them."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Iterable, Iterator
from zipfile import ZIP_DEFLATED, ZipFile

import requests


RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "dist" / "plugins"

SKIP_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


class PackagingError(Exception):
    """Raised when packaging fails due to invalid plugin structure."""


def iter_plugin_dirs(resources_dir: Path) -> Iterator[Path]:
    if (resources_dir / "manifest.json").exists():
        yield resources_dir
        return

    for entry in sorted(resources_dir.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "manifest.json").exists():
            yield entry


def load_manifest(plugin_dir: Path) -> dict[str, object]:
    manifest_path = plugin_dir / "manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PackagingError(f"Invalid manifest in {plugin_dir.name}: {exc}") from exc


def package_plugin(plugin_dir: Path, output_dir: Path) -> tuple[Path, dict[str, object]]:
    manifest = load_manifest(plugin_dir)
    slug = manifest.get("slug")
    version = manifest.get("version")
    if not slug or not version:
        raise PackagingError(f"Manifest for {plugin_dir.name} missing slug/version")

    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{slug}-{version}.zip"

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for file_path in sorted(plugin_dir.rglob("*")):
            if file_path.name in SKIP_NAMES:
                continue
            if file_path.suffix in SKIP_SUFFIXES:
                continue
            if file_path.is_dir():
                continue
            archive.write(file_path, arcname=str(file_path.relative_to(plugin_dir)))
    return zip_path, manifest


def package_all(resources_dir: Path, output_dir: Path) -> list[tuple[str, Path, dict[str, object]]]:
    results: list[tuple[str, Path, dict[str, object]]] = []
    for plugin_dir in iter_plugin_dirs(resources_dir):
        zip_path, manifest = package_plugin(plugin_dir, output_dir)
        results.append((plugin_dir.name, zip_path, manifest))
    return results


def upload_zip(zip_path: Path, upload_url: str, token: str | None = None) -> requests.Response:
    payload = {
        "filename": zip_path.name,
        "content": base64.b64encode(zip_path.read_bytes()).decode("utf-8"),
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.post(upload_url, json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package resources plugins for upload.")
    parser.add_argument(
        "--resources-dir",
        default=str(RESOURCES_DIR),
        help="Root directory containing plugin resources (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to store generated plugin archives (default: %(default)s)",
    )
    parser.add_argument(
        "--upload-url",
        help="Optional API endpoint to upload packaged plugins (POST /v1/plugins/upload)",
    )
    parser.add_argument(
        "--token",
        help="Optional bearer token when uploading via --upload-url",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    resources_dir = Path(args.resources_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not resources_dir.exists():
        print(f"[ERROR] resources directory not found: {resources_dir}", file=sys.stderr)
        return 1

    try:
        packages = package_all(resources_dir, output_dir)
    except PackagingError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    if not packages:
        print("[INFO] No plugins found to package.")
        return 0

    print(f"[INFO] Packaged {len(packages)} plugins into {output_dir}")
    for _, zip_path, manifest in packages:
        print(f" - {zip_path.name} ({manifest.get('name')} {manifest.get('version')})")

    if args.upload_url:
        print(f"[INFO] Uploading archives to {args.upload_url}")
        for _, zip_path, manifest in packages:
            try:
                response = upload_zip(zip_path, args.upload_url, token=args.token)
                print(f"   ✓ {zip_path.name} uploaded ({response.status_code})")
            except requests.HTTPError as exc:
                print(f"   ✗ {zip_path.name} upload failed: {exc}", file=sys.stderr)
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
