"""Immutable source snapshot acquisition and loading."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd

from satn.constants import DISCLAIMER, SCHEMA_VERSION
from satn.models import CouncilConfig

SOURCE_FILES = ("boundary.geojson", "places.geojson", "network.geojson")


def snapshot(config: CouncilConfig, *, replace: bool = False) -> Path:
    """Materialise an immutable, attributable source snapshot."""
    destination = config.source.snapshot_dir / config.source.snapshot_id
    if destination.exists() and not replace:
        _validate_snapshot(destination)
        return destination
    if config.source.kind != "fixture":
        raise NotImplementedError("OSM acquisition is introduced by the B&NES source slice")
    if config.source.fixture_dir is None:
        raise ValueError("fixture sources require source.fixture_dir")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for filename in SOURCE_FILES:
            shutil.copy2(config.source.fixture_dir / filename, temporary / filename)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": config.source.snapshot_id,
            "council_id": config.council_id,
            "source_kind": config.source.kind,
            "source_identifier": str(config.source.fixture_dir),
            "retrieved_at": datetime.now(UTC).isoformat(),
            "files": list(SOURCE_FILES),
            "disclaimer": DISCLAIMER,
        }
        (temporary / "snapshot.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        _validate_snapshot(temporary)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def _validate_snapshot(path: Path) -> None:
    manifest_path = path / "snapshot.json"
    if not manifest_path.exists():
        raise ValueError(f"invalid snapshot: missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for filename in manifest["files"]:
        file_path = path / filename
        if not file_path.exists():
            raise ValueError(f"invalid snapshot: missing {file_path}")
        frame = gpd.read_file(file_path)
        if frame.crs is None:
            raise ValueError(f"invalid snapshot: {filename} has no CRS")


def load_snapshot(config: CouncilConfig) -> dict[str, gpd.GeoDataFrame]:
    path = config.source.snapshot_dir / config.source.snapshot_id
    _validate_snapshot(path)
    return {
        "boundary": gpd.read_file(path / "boundary.geojson"),
        "places": gpd.read_file(path / "places.geojson"),
        "network": gpd.read_file(path / "network.geojson"),
    }

