"""Validate a Pages release using only the Python standard library.

This is deliberately a standalone script: the deployment runner checks out the
release tag, but does not install SATN's geospatial/compiler dependencies.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

GITHUB_PAGES_LIMIT_BYTES = 1_000_000_000
DEFAULT_MAXIMUM_BYTES = 900_000_000
SCHEMA_VERSION = "satn-deployment-catalogue/v1"
_ARTIFACTS = ("review_map", "network_map_pdf", "review_map_zip")


@dataclass(frozen=True)
class PagesPackage:
    pages_directory: Path
    release_artifact: Path
    pages_size_bytes: int
    release_size_bytes: int


def _strip_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote:
            if character == quote and not escaped:
                quote = None
            escaped = character == "\\" and not escaped
        elif character in "'\"":
            quote = character
        elif character == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    return line.rstrip()


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("YAML scalar must not be blank")
    if value[0] in "'\"":
        try:
            decoded = ast.literal_eval(value)
        except (SyntaxError, ValueError) as error:
            raise ValueError(f"invalid quoted YAML scalar: {value}") from error
        if not isinstance(decoded, str):
            raise ValueError("YAML scalar must be a string")
        return decoded
    return value


def _yaml_lines(path: Path) -> list[tuple[int, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"cannot read tracked YAML: {path}") from error
    lines: list[tuple[int, str]] = []
    for raw in content.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line[:indent]:
            raise ValueError(f"tracked YAML must use spaces for indentation: {path}")
        lines.append((indent, line[indent:]))
    return lines


def _yaml_mapping_item(content: str) -> tuple[str, str]:
    if ":" not in content:
        raise ValueError(f"expected YAML mapping item: {content}")
    key, value = content.split(":", 1)
    if not key or key.strip() != key:
        raise ValueError(f"invalid YAML mapping key: {content}")
    return key, value.strip()


def _parse_yaml_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[object, int]:
    if index >= len(lines) or lines[index][0] != indent:
        raise ValueError("invalid YAML indentation")
    is_list = lines[index][1].startswith("- ")
    result: list[object] | dict[str, object] = [] if is_list else {}
    while index < len(lines) and lines[index][0] == indent:
        _, content = lines[index]
        if content.startswith("- ") != is_list:
            raise ValueError("YAML must not mix lists and mappings at one indentation")
        if is_list:
            item = content[2:].strip()
            if not item:
                index += 1
                if index >= len(lines) or lines[index][0] <= indent:
                    raise ValueError("YAML list item must have a value")
                value, index = _parse_yaml_block(lines, index, lines[index][0])
            elif ":" not in item:
                value = _yaml_scalar(item)
                index += 1
            else:
                key, raw_value = _yaml_mapping_item(item)
                value = {key: _yaml_scalar(raw_value)} if raw_value else {key: None}
                index += 1
                if index < len(lines) and lines[index][0] > indent:
                    remainder, index = _parse_yaml_block(lines, index, lines[index][0])
                    if not isinstance(remainder, dict):
                        raise ValueError("YAML list mapping continuation must be a mapping")
                    value.update(remainder)
                if value[key] is None:
                    raise ValueError(f"YAML mapping value is required: {key}")
            result.append(value)
        else:
            key, raw_value = _yaml_mapping_item(content)
            index += 1
            if raw_value:
                result[key] = _yaml_scalar(raw_value)
            else:
                if index >= len(lines) or lines[index][0] <= indent:
                    raise ValueError(f"YAML mapping value is required: {key}")
                result[key], index = _parse_yaml_block(lines, index, lines[index][0])
    return result, index


def _load_simple_yaml(path: Path) -> dict[str, object]:
    lines = _yaml_lines(path)
    if not lines or lines[0][0] != 0:
        raise ValueError(f"tracked YAML must start with a mapping: {path}")
    parsed, index = _parse_yaml_block(lines, 0, 0)
    if index != len(lines) or not isinstance(parsed, dict):
        raise ValueError(f"tracked YAML must be a mapping: {path}")
    return parsed


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value.strip()


def _relative_path(value: object, field: str, *, directory: bool = False) -> str:
    path = _text(value, field)
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts or "\\" in path:
        raise ValueError(f"{field} must be a relative path without traversal")
    normalized = parsed.as_posix()
    if directory:
        if not path.endswith("/"):
            raise ValueError(f"{field} must end with /")
        return f"{normalized}/"
    if path.endswith("/"):
        raise ValueError(f"{field} must name a file")
    return normalized


def _tracked_file(path: Path, root: Path, field: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{field} must not be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{field} does not exist: {path}") from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"{field} must be a file below the tracked deployments directory")
    return resolved


def _load_expected_catalogue(catalogue_path: str | Path) -> dict[str, object]:
    catalogue_source = Path(catalogue_path)
    if catalogue_source.is_symlink():
        raise ValueError(f"deployment catalogue must not be a symlink: {catalogue_source}")
    catalogue = catalogue_source.resolve()
    deployments_root = catalogue.parent
    _tracked_file(catalogue_source, deployments_root, "deployment catalogue")
    tracked = _load_simple_yaml(catalogue)
    if tracked.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"deployment catalogue schema_version must be {SCHEMA_VERSION}")
    title = _text(tracked.get("title"), "deployment catalogue title")
    entries = tracked.get("deployments")
    if not isinstance(entries, list) or not entries:
        raise ValueError("deployment catalogue must contain deployments")

    expected: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise ValueError("each deployment catalogue entry must be a mapping")
        deployment_id = _text(raw_entry.get("deployment_id"), "deployment_id")
        if deployment_id in seen_ids:
            raise ValueError("deployment catalogue deployment_ids must be unique")
        seen_ids.add(deployment_id)
        area_id = _text(raw_entry.get("area_id"), "area_id")
        area_name = _text(raw_entry.get("area_name"), "area_name")
        area_definition = _relative_path(
            raw_entry.get("area_definition"), "area_definition"
        )
        deployment_path = _relative_path(
            raw_entry.get("deployment_path"), "deployment_path", directory=True
        )
        if deployment_path != f"deployments/{deployment_id}/":
            raise ValueError("deployment_path must exactly match deployment_id")
        definition_path = _tracked_file(
            deployments_root / area_definition, deployments_root, "area_definition"
        )
        area_definition_sha256 = hashlib.sha256(definition_path.read_bytes()).hexdigest()
        definition = _load_simple_yaml(definition_path)
        if (
            definition.get("deployment_id") != deployment_id
            or definition.get("area_id") != area_id
            or definition.get("area_name") != area_name
        ):
            raise ValueError("area_definition identity must exactly match its catalogue entry")
        raw_artifacts = raw_entry.get("artifacts")
        if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != set(_ARTIFACTS):
            raise ValueError(f"artifacts must contain exactly: {', '.join(_ARTIFACTS)}")
        artifacts = {
            name: f"{deployment_path}{_relative_path(raw_artifacts[name], f'artifacts.{name}')}"
            for name in _ARTIFACTS
        }
        expected.append(
            {
                "deployment_id": deployment_id,
                "area_id": area_id,
                "area_name": area_name,
                "area_definition": area_definition,
                "area_definition_sha256": area_definition_sha256,
                "deployment_path": deployment_path,
                "artifacts": artifacts,
            }
        )
    return {"schema_version": SCHEMA_VERSION, "title": title, "deployments": expected}


def _files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for root, directory_names, file_names in os.walk(directory, followlinks=False):
        current = Path(root)
        for name in [*directory_names, *file_names]:
            item = current / name
            if item.is_symlink():
                raise ValueError(f"Pages package must not contain symlinks: {item}")
        for name in file_names:
            item = current / name
            if not item.is_file():
                raise ValueError(f"Pages package must contain only regular files: {item}")
            files.append(item)
    return files


def _json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"invalid {description}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return value


def _validate_pages_directory(
    pages: Path, expected_catalogue: dict[str, object], maximum_bytes: int
) -> int:
    pages_size = sum(item.stat().st_size for item in _files(pages))
    if pages_size > maximum_bytes:
        raise ValueError(
            "Pages package is "
            f"{pages_size} bytes, exceeding configured budget of {maximum_bytes} bytes"
        )
    if not (pages / "index.html").is_file():
        raise ValueError("Pages package must contain root index.html")
    actual_catalogue = _json_object(pages / "catalogue.json", "Pages catalogue")
    if actual_catalogue != expected_catalogue:
        raise ValueError("Pages catalogue does not exactly match the tracked deployment catalogue")
    for entry in expected_catalogue["deployments"]:
        assert isinstance(entry, dict)  # Constructed above; narrows for type checkers.
        deployment_id = entry["deployment_id"]
        area_id = entry["area_id"]
        area_definition_sha256 = entry["area_definition_sha256"]
        assert (
            isinstance(deployment_id, str)
            and isinstance(area_id, str)
            and isinstance(area_definition_sha256, str)
        )
        deployment = pages / f"deployments/{deployment_id}"
        if deployment.is_symlink() or not deployment.is_dir():
            raise ValueError(f"Pages catalogue deployment is missing: {deployment}")
        publication = _json_object(deployment / "publication.json", "deployment publication")
        if (
            publication.get("deployment_id") != deployment_id
            or publication.get("area_id") != area_id
        ):
            raise ValueError(f"deployment publication identity does not match {deployment_id}")
        if publication.get("area_definition_sha256") != area_definition_sha256:
            raise ValueError(
                "deployment publication area_definition_sha256 does not match the "
                f"tracked Area Definition: {deployment_id}"
            )
        artifacts = entry["artifacts"]
        assert isinstance(artifacts, dict)
        for name, artifact in artifacts.items():
            assert isinstance(artifact, str)
            target = pages / artifact
            if target.is_symlink() or not target.is_file():
                raise ValueError(
                    f"Pages catalogue deployment {deployment_id} is missing {name}: {artifact}"
                )
    return pages_size


def _safe_zip_member(info: zipfile.ZipInfo) -> Path:
    name = info.filename
    parsed = PurePosixPath(name)
    mode = info.external_attr >> 16
    if (
        not name
        or "\\" in name
        or parsed.is_absolute()
        or ".." in parsed.parts
        or "." in parsed.parts
    ):
        raise ValueError(f"release archive contains unsafe path: {name!r}")
    if stat.S_ISLNK(mode):
        raise ValueError(f"release archive contains symlink: {name}")
    if not info.is_dir() and stat.S_IFMT(mode) and not stat.S_ISREG(mode):
        raise ValueError(f"release archive contains non-regular file: {name}")
    return Path(*parsed.parts)


def validate_pages_release(
    release_artifact: str | Path,
    destination: str | Path,
    catalogue_path: str | Path,
    *,
    maximum_bytes: int = DEFAULT_MAXIMUM_BYTES,
) -> PagesPackage:
    """Safely extract and validate a release against the checked-out release tag."""

    if maximum_bytes <= 0 or maximum_bytes >= GITHUB_PAGES_LIMIT_BYTES:
        raise ValueError("maximum_bytes must be positive and below the GitHub Pages 1 GB limit")
    release_source = Path(release_artifact)
    output_source = Path(destination)
    if release_source.is_symlink():
        raise ValueError(f"Pages release archive must not be a symlink: {release_source}")
    if output_source.is_symlink():
        raise ValueError(
            f"Pages validation destination must not be a symlink: {output_source}"
        )
    release = release_source.resolve()
    output = output_source.resolve()
    if not release.is_file():
        raise ValueError(f"expected Pages release archive: {release}")
    if output.exists():
        raise ValueError(f"Pages validation destination must not already exist: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    temporary_root = Path(tempfile.mkdtemp(prefix=".pages-validate-", dir=output.parent))
    try:
        pages = temporary_root / "pages"
        pages.mkdir()
        with zipfile.ZipFile(release) as archive:
            members = archive.infolist()
            member_paths: set[Path] = set()
            declared_size = 0
            for info in members:
                member_path = _safe_zip_member(info)
                if member_path in member_paths:
                    raise ValueError(f"release archive contains duplicate path: {info.filename}")
                member_paths.add(member_path)
                if not info.is_dir():
                    declared_size += info.file_size
            if declared_size > maximum_bytes:
                raise ValueError(
                    "release archive extracted size exceeds configured budget: "
                    f"{declared_size} bytes"
                )
            expected_catalogue = _load_expected_catalogue(catalogue_path)
            for info in members:
                member_path = _safe_zip_member(info)
                target = pages / member_path
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as extracted:
                        shutil.copyfileobj(source, extracted)
        pages_size = _validate_pages_directory(pages, expected_catalogue, maximum_bytes)
        pages.replace(output)
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
    return PagesPackage(output, release, pages_size, release.stat().st_size)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release_artifact", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--catalogue", type=Path, required=True, help="Tracked deployments/catalogue.yaml"
    )
    parser.add_argument(
        "--maximum-bytes",
        type=int,
        default=int(os.environ.get("SATN_PAGES_MAX_BYTES", DEFAULT_MAXIMUM_BYTES)),
    )
    args = parser.parse_args()
    result = validate_pages_release(
        args.release_artifact,
        args.destination,
        args.catalogue,
        maximum_bytes=args.maximum_bytes,
    )
    print(f"{result.pages_directory} ({result.pages_size_bytes} extracted bytes)")


if __name__ == "__main__":
    main()
