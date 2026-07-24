"""Package generated Area Deployments for Pages without tracking them in Git."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from satn.deployment_catalogue import DeploymentCatalogue

GITHUB_PAGES_LIMIT_BYTES = 1_000_000_000
DEFAULT_MAXIMUM_BYTES = 900_000_000
RELEASE_ARTIFACT_NAME = "satn-pages.zip"
SCHEMA_VERSION = "satn-deployment-catalogue/v1"


@dataclass(frozen=True)
class PagesPackage:
    """Locations and sizes of one generated Pages release."""

    pages_directory: Path
    release_artifact: Path
    pages_size_bytes: int
    release_size_bytes: int


def _deployment_destination(deployment_id: str) -> Path:
    return Path("deployments") / deployment_id


def _files(directory: Path) -> list[Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"expected generated deployment directory: {directory}")
    files: list[Path] = []
    for root, directory_names, file_names in os.walk(directory, followlinks=False):
        current = Path(root)
        for name in [*directory_names, *file_names]:
            item = current / name
            if item.is_symlink():
                raise ValueError(f"generated deployment must not contain symlinks: {item}")
        for name in file_names:
            item = current / name
            if not item.is_file():
                raise ValueError(f"generated deployment must contain only regular files: {item}")
            files.append(item)
    return sorted(files, key=lambda item: item.relative_to(directory).as_posix())


def _write_zip(
    destination: Path,
    directory: Path,
    *,
    prefix: PurePosixPath | None = None,
    excluded: set[Path] | None = None,
) -> None:
    """Write a reproducible compressed archive of files below ``directory``."""

    excluded = excluded or set()
    prefix = prefix or PurePosixPath()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for item in _files(directory):
            relative = item.relative_to(directory)
            if relative in excluded:
                continue
            member = (prefix / relative.as_posix()).as_posix()
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                item.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def _directory_size(directory: Path) -> int:
    return sum(item.stat().st_size for item in _files(directory))


def _validate_budget(maximum_bytes: int) -> None:
    if maximum_bytes <= 0:
        raise ValueError("maximum_bytes must be positive")
    if maximum_bytes >= GITHUB_PAGES_LIMIT_BYTES:
        raise ValueError(
            "maximum_bytes must remain below the GitHub Pages 1 GB limit "
            f"({GITHUB_PAGES_LIMIT_BYTES} bytes)"
        )


def _json_object(path: Path, description: str) -> dict[str, Any]:
    import json

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"invalid {description}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return value


def _nonblank_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value.strip()


def _relative_file_path(value: object, field: str) -> Path:
    path = _nonblank_text(value, field)
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or ".." in parsed.parts
        or "." in parsed.parts
        or "\\" in path
        or path.endswith("/")
    ):
        raise ValueError(f"{field} must be a relative file path without traversal")
    return Path(*parsed.parts)


def _validate_publication(
    deployment: Path,
    deployment_id: str,
    *,
    expected_area_id: str,
    expected_area_definition_sha256: str,
) -> None:
    publication_path = deployment / "publication.json"
    if not publication_path.is_file():
        raise ValueError(
            f"generated deployment {deployment_id} is missing publication.json"
        )
    publication = _json_object(publication_path, "deployment publication")
    if publication.get("deployment_id") != deployment_id:
        raise ValueError(
            "deployment publication identity does not match catalogue deployment_id: "
            f"{publication_path}"
        )
    area_id = _nonblank_text(publication.get("area_id"), "publication area_id")
    if area_id != expected_area_id:
        raise ValueError(
            "deployment publication area_id does not match catalogue area_id: "
            f"{publication_path}"
        )
    if publication.get("area_definition_sha256") != expected_area_definition_sha256:
        raise ValueError(
            "deployment publication area_definition_sha256 does not match the "
            f"tracked Area Definition: {publication_path}"
        )


def _copy_deployments(
    catalogue: DeploymentCatalogue,
    deployments_root: Path,
    pages: Path,
) -> None:
    for entry in catalogue.deployments:
        expected_path = _deployment_destination(entry.deployment_id)
        declared_path = Path(entry.deployment_path.rstrip("/"))
        if declared_path != expected_path:
            raise ValueError(
                "deployment_path for "
                f"{entry.deployment_id} must be {expected_path.as_posix()}/"
            )
        source = deployments_root / entry.deployment_id
        target = pages / expected_path
        if not source.is_dir():
            raise ValueError(
                f"missing generated deployment for {entry.deployment_id}: {source}"
            )
        _files(source)
        shutil.copytree(source, target)

        _validate_publication(
            target,
            entry.deployment_id,
            expected_area_id=entry.area_id,
            expected_area_definition_sha256=entry.area_definition_sha256,
        )

        for name, artifact in entry.artifacts.items():
            if name == "review_map_zip":
                continue
            if not (target / artifact).is_file():
                raise ValueError(
                    "generated deployment "
                    f"{entry.deployment_id} is missing {name}: {artifact}"
                )

        zip_path = target / entry.artifacts["review_map_zip"]
        _write_zip(
            zip_path,
            target,
            prefix=PurePosixPath("review-map"),
            excluded={Path(entry.artifacts["review_map_zip"])},
        )


def _validate_pages_directory(pages: Path, maximum_bytes: int) -> int:
    """Validate a fully assembled Pages tree without trusting its producer."""

    pages_size = _directory_size(pages)
    if pages_size > maximum_bytes:
        raise ValueError(
            f"Pages package is {pages_size} bytes, exceeding configured budget "
            f"of {maximum_bytes} bytes"
        )

    root_index = pages / "index.html"
    catalogue_path = pages / "catalogue.json"
    if not root_index.is_file() or not catalogue_path.is_file():
        raise ValueError("Pages package must contain root index.html and catalogue.json")

    catalogue = _json_object(catalogue_path, "Pages catalogue")
    if catalogue.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Pages catalogue schema_version must be {SCHEMA_VERSION}")
    _nonblank_text(catalogue.get("title"), "catalogue title")
    entries = catalogue.get("deployments")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Pages catalogue must contain deployments")

    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each Pages catalogue deployment must be an object")
        deployment_id = _nonblank_text(entry.get("deployment_id"), "catalogue deployment_id")
        if deployment_id in seen_ids:
            raise ValueError("Pages catalogue deployment_ids must be unique")
        seen_ids.add(deployment_id)
        deployment_path = _nonblank_text(
            entry.get("deployment_path"), "catalogue deployment_path"
        )
        expected_directory = _deployment_destination(deployment_id)
        if deployment_path != f"{expected_directory.as_posix()}/":
            raise ValueError(
                "catalogue deployment_path must match deployment_id: "
                f"{deployment_path}"
            )
        _nonblank_text(entry.get("area_name"), "catalogue area_name")
        area_id = _nonblank_text(entry.get("area_id"), "catalogue area_id")
        area_definition = _nonblank_text(entry.get("area_definition"), "area_definition")
        _relative_file_path(area_definition, "area_definition")
        area_definition_sha256 = _nonblank_text(
            entry.get("area_definition_sha256"), "area_definition_sha256"
        )

        deployment = pages / expected_directory
        if deployment.is_symlink() or not deployment.is_dir():
            raise ValueError(f"Pages catalogue deployment is missing: {deployment}")
        _validate_publication(
            deployment,
            deployment_id,
            expected_area_id=area_id,
            expected_area_definition_sha256=area_definition_sha256,
        )

        artifacts = entry.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValueError("catalogue deployment artifacts must be an object")
        for name in ("review_map", "network_map_pdf", "review_map_zip"):
            artifact_path = _relative_file_path(
                artifacts.get(name), f"catalogue artifacts.{name}"
            )
            try:
                artifact_path.relative_to(expected_directory)
            except ValueError as error:
                raise ValueError(
                    f"catalogue artifacts.{name} must be rooted at {expected_directory}/"
                ) from error
            target = pages / artifact_path
            if target.is_symlink() or not target.is_file():
                raise ValueError(
                    f"Pages catalogue deployment {deployment_id} is missing {name}: "
                    f"{artifact_path}"
                )

    return pages_size


def package_pages(
    catalogue_path: str | Path,
    deployments_root: str | Path,
    destination: str | Path,
    release_artifact: str | Path,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_BYTES,
) -> PagesPackage:
    """Assemble a Pages tree and its standalone release archive from local bundles.

    The input bundles are process artifacts under an ignored build directory. This
    function deliberately never reads from or writes to a tracked ``site/`` tree.
    """

    _validate_budget(maximum_bytes)
    from satn.deployment_catalogue import load_deployment_catalogue

    catalogue = load_deployment_catalogue(catalogue_path)
    bundles_source = Path(deployments_root)
    if bundles_source.is_symlink():
        raise ValueError(f"deployments_root must not be a symlink: {bundles_source}")
    bundles = bundles_source.resolve()
    output_source = Path(destination)
    if output_source.is_symlink():
        raise ValueError(
            f"Pages destination must not be a symlink: {output_source}"
        )
    output = output_source.resolve()
    release_source = Path(release_artifact)
    if release_source.is_symlink():
        raise ValueError(f"release_artifact must not be a symlink: {release_source}")
    release = release_source.resolve()
    if release.is_relative_to(output):
        raise ValueError("release_artifact must be outside the Pages destination")
    if bundles == output or bundles.is_relative_to(output) or output.is_relative_to(bundles):
        raise ValueError("deployments_root and Pages destination must not overlap")

    output.parent.mkdir(parents=True, exist_ok=True)
    release.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".pages-package-", dir=output.parent))
    try:
        pages = temporary_root / "pages"
        pages.mkdir()
        _copy_deployments(catalogue, bundles, pages)
        from satn.deployment_catalogue import build_deployment_catalogue

        build_deployment_catalogue(catalogue_path, pages)
        pages_size = _validate_pages_directory(pages, maximum_bytes)

        temporary_release = temporary_root / RELEASE_ARTIFACT_NAME
        _write_zip(temporary_release, pages)
        release_size = temporary_release.stat().st_size

        if output.exists():
            shutil.rmtree(output)
        pages.replace(output)
        if release.exists():
            release.unlink()
        os.replace(temporary_release, release)
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)

    return PagesPackage(
        pages_directory=output,
        release_artifact=release,
        pages_size_bytes=pages_size,
        release_size_bytes=release_size,
    )
