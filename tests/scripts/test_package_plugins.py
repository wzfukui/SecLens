from pathlib import Path
from zipfile import ZipFile

from scripts.package_plugins import package_all


def test_package_all_plugins(tmp_path):
    resources_dir = Path(__file__).resolve().parents[2] / "resources"
    packages = package_all(resources_dir, tmp_path)
    assert packages
    for _, zip_path, manifest in packages:
        assert zip_path.exists()
        assert manifest.get("slug")
        with ZipFile(zip_path) as archive:
            assert "manifest.json" in archive.namelist()
