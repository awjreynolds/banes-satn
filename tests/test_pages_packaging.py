from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from satn.pages_packaging import (
    GITHUB_PAGES_LIMIT_BYTES,
    package_pages,
)

PROJECT = Path(__file__).parents[1]
_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "validate_pages_release", PROJECT / "scripts" / "validate_pages_release.py"
)
assert _VALIDATOR_SPEC and _VALIDATOR_SPEC.loader
_VALIDATOR = importlib.util.module_from_spec(_VALIDATOR_SPEC)
sys.modules[_VALIDATOR_SPEC.name] = _VALIDATOR
_VALIDATOR_SPEC.loader.exec_module(_VALIDATOR)
validate_pages_release = _VALIDATOR.validate_pages_release


def write_catalogue(path: Path) -> None:
    definition = path.parent / "test-area" / "area.yaml"
    definition.parent.mkdir(parents=True, exist_ok=True)
    definition.write_text(
        """area_id: test-geography
area_name: Test area
deployment_id: test-area
source:
  snapshot_dir: snapshots
publication:
  output_dir: build
  title: Test area deployment
""",
        encoding="utf-8",
    )
    path.write_text(
        """schema_version: satn-deployment-catalogue/v1
title: Test deployments
deployments:
  - deployment_id: test-area
    area_id: test-geography
    area_name: Test area
    area_definition: test-area/area.yaml
    deployment_path: deployments/test-area/
    artifacts:
      review_map: index.html
      network_map_pdf: network-map.pdf
      review_map_zip: review-map.zip
""",
        encoding="utf-8",
    )


def write_bundle(root: Path) -> None:
    bundle = root / "test-area"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<h1>Test area</h1>", encoding="utf-8")
    (bundle / "network-map.pdf").write_bytes(b"%PDF-test")
    (bundle / "assets" / "map.js").write_text("window.map = true;", encoding="utf-8")
    (bundle / "publication.json").write_text(
        json.dumps(
            {
                "deployment_id": "test-area",
                "area_id": "test-geography",
                "area_definition_sha256": hashlib.sha256(
                    (root.parent / "test-area" / "area.yaml").read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


def write_release_from_tree(root: Path, release: Path) -> None:
    with zipfile.ZipFile(release, "w") as archive:
        for item in sorted(root.rglob("*")):
            if item.is_file():
                archive.write(item, item.relative_to(root).as_posix())


def test_package_pages_generates_stable_links_deployment_zip_and_release_archive(
    tmp_path: Path,
) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    destination = tmp_path / "pages"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)

    result = package_pages(catalogue, deployments, destination, release, maximum_bytes=1_000_000)

    assert result.pages_directory == destination.resolve()
    assert result.release_artifact == release.resolve()
    assert result.pages_size_bytes < 1_000_000
    publication = json.loads((destination / "catalogue.json").read_text(encoding="utf-8"))
    assert publication["deployments"][0]["artifacts"] == {
        "review_map": "deployments/test-area/index.html",
        "network_map_pdf": "deployments/test-area/network-map.pdf",
        "review_map_zip": "deployments/test-area/review-map.zip",
    }
    assert publication["deployments"][0]["area_id"] == "test-geography"
    area_definition_sha256 = hashlib.sha256(
        (catalogue.parent / "test-area" / "area.yaml").read_bytes()
    ).hexdigest()
    assert publication["deployments"][0]["area_definition_sha256"] == area_definition_sha256
    assert json.loads(
        (destination / "deployments" / "test-area" / "publication.json").read_text()
    )["area_definition_sha256"] == area_definition_sha256
    assert (destination / "deployments" / "test-area" / "network-map.pdf").exists()
    with zipfile.ZipFile(destination / "deployments" / "test-area" / "review-map.zip") as archive:
        assert set(archive.namelist()) == {
            "review-map/assets/map.js",
            "review-map/index.html",
            "review-map/network-map.pdf",
            "review-map/publication.json",
        }
    with zipfile.ZipFile(release) as archive:
        assert "index.html" in archive.namelist()
        assert "catalogue.json" in archive.namelist()
        assert "deployments/test-area/review-map.zip" in archive.namelist()


def test_validate_pages_release_independently_checks_extracted_content(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, tmp_path / "packaged-pages", release)

    result = validate_pages_release(release, tmp_path / "validated-pages", catalogue)

    assert result.pages_size_bytes < 900_000_000
    assert (result.pages_directory / "catalogue.json").is_file()
    assert (
        result.pages_directory / "deployments" / "test-area" / "publication.json"
    ).is_file()


def test_validate_pages_release_rejects_mismatched_deployment_content(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    packaged_pages = tmp_path / "packaged-pages"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, packaged_pages, tmp_path / "original-release.zip")
    (packaged_pages / "deployments" / "test-area" / "publication.json").write_text(
        json.dumps({"deployment_id": "wrong", "area_id": "test-geography"}),
        encoding="utf-8",
    )
    write_release_from_tree(packaged_pages, release)

    with pytest.raises(ValueError, match="publication identity does not match"):
        validate_pages_release(release, tmp_path / "validated-pages", catalogue)


def test_validate_pages_release_rejects_mismatched_publication_area_id(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    packaged_pages = tmp_path / "packaged-pages"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, packaged_pages, tmp_path / "original-release.zip")
    (packaged_pages / "deployments" / "test-area" / "publication.json").write_text(
        json.dumps({"deployment_id": "test-area", "area_id": "other-area"}),
        encoding="utf-8",
    )
    write_release_from_tree(packaged_pages, release)

    with pytest.raises(ValueError, match="publication identity does not match"):
        validate_pages_release(release, tmp_path / "validated-pages", catalogue)


def test_validate_pages_release_binds_archive_catalogue_to_tracked_identities(
    tmp_path: Path,
) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    packaged_pages = tmp_path / "packaged-pages"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, packaged_pages, tmp_path / "original-release.zip")
    archived_catalogue = json.loads((packaged_pages / "catalogue.json").read_text())
    archived_catalogue["deployments"][0]["area_name"] = "Untracked area name"
    (packaged_pages / "catalogue.json").write_text(
        json.dumps(archived_catalogue), encoding="utf-8"
    )
    write_release_from_tree(packaged_pages, release)

    with pytest.raises(ValueError, match="does not exactly match"):
        validate_pages_release(release, tmp_path / "validated-pages", catalogue)


def test_validate_pages_release_runs_in_an_isolated_stdlib_subprocess(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, tmp_path / "packaged-pages", release)

    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(PROJECT / "scripts" / "validate_pages_release.py"),
            str(release),
            str(tmp_path / "validated-pages"),
            "--catalogue",
            str(catalogue),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "validated-pages" / "catalogue.json").is_file()


def test_validate_pages_release_rejects_stale_area_definition_in_isolated_subprocess(
    tmp_path: Path,
) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    release = tmp_path / "satn-pages.zip"
    write_catalogue(catalogue)
    write_bundle(deployments)
    package_pages(catalogue, deployments, tmp_path / "packaged-pages", release)
    definition = tmp_path / "test-area" / "area.yaml"
    definition.write_text(
        definition.read_text(encoding="utf-8").replace(
            "title: Test area deployment", "title: Changed area deployment title"
        ),
        encoding="utf-8",
    )
    archived_catalogue_path = tmp_path / "packaged-pages" / "catalogue.json"
    archived_catalogue = json.loads(archived_catalogue_path.read_text(encoding="utf-8"))
    archived_catalogue["deployments"][0]["area_definition_sha256"] = hashlib.sha256(
        definition.read_bytes()
    ).hexdigest()
    archived_catalogue_path.write_text(json.dumps(archived_catalogue), encoding="utf-8")
    write_release_from_tree(tmp_path / "packaged-pages", release)

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(PROJECT / "scripts" / "validate_pages_release.py"),
            str(release),
            str(tmp_path / "validated-pages"),
            "--catalogue",
            str(catalogue),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "area_definition_sha256 does not match" in completed.stderr


def test_package_pages_rejects_missing_or_mismatched_deployment_publication(
    tmp_path: Path,
) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    write_catalogue(catalogue)
    write_bundle(deployments)
    publication = deployments / "test-area" / "publication.json"
    publication.unlink()

    with pytest.raises(ValueError, match=r"missing publication\.json"):
        package_pages(catalogue, deployments, tmp_path / "pages", tmp_path / "release.zip")

    publication.write_text(
        json.dumps({"deployment_id": "wrong", "area_id": "test-geography"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity does not match catalogue deployment_id"):
        package_pages(catalogue, deployments, tmp_path / "pages", tmp_path / "release.zip")


def test_package_pages_rejects_stale_area_definition_with_stable_identity(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    write_catalogue(catalogue)
    write_bundle(deployments)
    definition = tmp_path / "test-area" / "area.yaml"
    definition.write_text(
        definition.read_text(encoding="utf-8").replace(
            "title: Test area deployment", "title: Changed area deployment title"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="area_definition_sha256 does not match"):
        package_pages(catalogue, deployments, tmp_path / "pages", tmp_path / "release.zip")


def test_package_pages_rejects_file_and_directory_symlinks_before_copying(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    write_catalogue(catalogue)
    write_bundle(deployments)
    bundle = deployments / "test-area"
    (bundle / "file-link").symlink_to(bundle / "index.html")

    with pytest.raises(ValueError, match="must not contain symlinks"):
        package_pages(catalogue, deployments, tmp_path / "pages", tmp_path / "release.zip")

    (bundle / "file-link").unlink()
    (bundle / "directory-link").symlink_to(bundle / "assets", target_is_directory=True)
    with pytest.raises(ValueError, match="must not contain symlinks"):
        package_pages(catalogue, deployments, tmp_path / "pages", tmp_path / "release.zip")


def test_package_pages_rejects_symlinked_input_roots_before_resolving(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    write_catalogue(catalogue)
    write_bundle(deployments)
    deployments_link = tmp_path / "deployments-link"
    deployments_link.symlink_to(deployments, target_is_directory=True)

    with pytest.raises(ValueError, match="deployments_root must not be a symlink"):
        package_pages(catalogue, deployments_link, tmp_path / "pages", tmp_path / "release.zip")

    release_target = tmp_path / "release-target.zip"
    release_target.write_bytes(b"keep")
    release_link = tmp_path / "release-link.zip"
    release_link.symlink_to(release_target)
    with pytest.raises(ValueError, match="release_artifact must not be a symlink"):
        package_pages(catalogue, deployments, tmp_path / "pages", release_link)
    assert release_target.read_bytes() == b"keep"


def test_validate_pages_release_rejects_traversal_symlinks_and_oversized_payload(
    tmp_path: Path,
) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside", "no")
    with pytest.raises(ValueError, match="unsafe path"):
        validate_pages_release(traversal, tmp_path / "traversal-pages", tmp_path / "catalogue.yaml")

    symlink = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr(info, "target")
    with pytest.raises(ValueError, match="contains symlink"):
        validate_pages_release(symlink, tmp_path / "symlink-pages", tmp_path / "catalogue.yaml")

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("large", "xx")
    with pytest.raises(ValueError, match="extracted size exceeds"):
        validate_pages_release(
            oversized,
            tmp_path / "oversized-pages",
            tmp_path / "catalogue.yaml",
            maximum_bytes=1,
        )


def test_validate_pages_release_rejects_symlinked_archive_before_resolving(tmp_path: Path) -> None:
    release = tmp_path / "release.zip"
    with zipfile.ZipFile(release, "w") as archive:
        archive.writestr("index.html", "test")
    link = tmp_path / "release-link.zip"
    link.symlink_to(release)

    with pytest.raises(ValueError, match="release archive must not be a symlink"):
        validate_pages_release(link, tmp_path / "validated-pages", tmp_path / "catalogue.yaml")


def test_validate_pages_release_rejects_symlinked_destination_before_resolving(
    tmp_path: Path,
) -> None:
    destination_target = tmp_path / "destination-target"
    destination = tmp_path / "validated-pages"
    destination.symlink_to(destination_target, target_is_directory=True)

    with pytest.raises(ValueError, match="destination must not be a symlink"):
        validate_pages_release(
            tmp_path / "missing.zip", destination, tmp_path / "catalogue.yaml"
        )


def test_package_pages_rejects_symlinked_destination_before_removal(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    destination_target = tmp_path / "destination-target"
    destination = tmp_path / "pages"
    write_catalogue(catalogue)
    write_bundle(deployments)
    destination.symlink_to(destination_target, target_is_directory=True)

    with pytest.raises(ValueError, match="Pages destination must not be a symlink"):
        package_pages(catalogue, deployments, destination, tmp_path / "release.zip")


def test_package_pages_rejects_budget_at_or_above_pages_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="below the GitHub Pages"):
        package_pages(
            tmp_path / "catalogue.yaml",
            tmp_path / "deployments",
            tmp_path / "pages",
            tmp_path / "satn-pages.zip",
            maximum_bytes=GITHUB_PAGES_LIMIT_BYTES,
        )


def test_package_pages_fails_before_publishing_when_the_budget_is_exceeded(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.yaml"
    deployments = tmp_path / "deployments"
    write_catalogue(catalogue)
    write_bundle(deployments)

    with pytest.raises(ValueError, match="exceeding configured budget"):
        package_pages(
            catalogue,
            deployments,
            tmp_path / "pages",
            tmp_path / "satn-pages.zip",
            maximum_bytes=1,
        )
