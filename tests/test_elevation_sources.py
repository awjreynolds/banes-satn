from __future__ import annotations

import json
import os
import shutil
import urllib.parse
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from satn import compile
from satn.models import CouncilConfig, NationalElevationConfig
from satn.sources import _osm_elevation_corroboration, load_snapshot, snapshot

PROJECT = Path(__file__).parents[1]


def copied_config(tmp_path: Path) -> CouncilConfig:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    return CouncilConfig.from_yaml(fixture / "council.yaml")


def test_local_national_elevation_is_clipped_and_snapshotted_with_provenance(
    tmp_path: Path,
) -> None:
    config = copied_config(tmp_path)
    terrain = tmp_path / "national-terrain.geojson"
    gpd.GeoDataFrame(
        [
            {"sample": "inside-1", "height": 10, "geometry": Point(-2.50, 51.40)},
            {"sample": "inside-2", "height": 20, "geometry": Point(-2.48, 51.41)},
            {"sample": "outside", "height": 30, "geometry": Point(-1.0, 52.0)},
        ],
        geometry="geometry",
        crs=4326,
    ).to_file(terrain, driver="GeoJSON")
    config.source.external_buffer_km = 0.1
    config.source.national_elevation = NationalElevationConfig(
        provider="local-geojson",
        path=terrain,
        source_id="national-dtm-2026",
        effective_date="2026-01-15",
        licence="Open Government Licence v3.0",
        attribution="National terrain test source",
        elevation_field="height",
        identifier_field="sample",
    )

    path = snapshot(config)
    loaded = load_snapshot(config)["elevation_evidence"]
    manifest = json.loads((path / "snapshot.json").read_text())

    assert set(loaded["evidence_id"]) == {"inside-1", "inside-2"}
    assert set(loaded["source_id"]) == {"national-dtm-2026"}
    assert list(loaded["elevation_m"]) == [10.0, 20.0]
    assert manifest["evidence_sources"]["elevation"] | {
        "content_fingerprint": "ignored",
        "retrieved_at": "ignored",
    } == {
        "provider": "local-geojson",
        "source_id": "national-dtm-2026",
        "effective_date": "2026-01-15",
        "date_kind": "effective",
        "licence": "Open Government Licence v3.0",
        "attribution": "National terrain test source",
        "bounded_to_compilation_area": True,
        "coverage_status": "available",
        "sample_count": 2,
        "content_fingerprint": "ignored",
        "retrieved_at": "ignored",
    }


def test_remote_national_elevation_request_uses_governed_bbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = copied_config(tmp_path)
    config.source.external_buffer_km = 0.1
    config.source.national_elevation = NationalElevationConfig(
        provider="remote-geojson",
        url="https://terrain.example.test/samples",
        source_id="national-remote-dtm",
        licence="Open Government Licence v3.0",
        attribution="Remote national terrain",
        elevation_field="height",
        identifier_field="sample",
    )
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"sample": "remote-1", "height": 15},
                "geometry": {"type": "Point", "coordinates": [-2.49, 51.40]},
            }
        ],
    }
    seen: dict[str, str] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode()

    def fake_urlopen(request: object, timeout: int) -> Response:
        seen["url"] = request.full_url  # type: ignore[attr-defined]
        assert timeout == 90
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    path = snapshot(config)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert "bbox" in query
    assert len(query["bbox"][0].split(",")) == 4
    manifest = json.loads((path / "snapshot.json").read_text())
    assert manifest["evidence_sources"]["elevation"]["date_kind"] == "retrieved"
    assert manifest["evidence_sources"]["elevation"]["sample_count"] == 1


def test_configured_source_without_local_coverage_is_explicit_unknown(
    tmp_path: Path,
) -> None:
    config = copied_config(tmp_path)
    terrain = tmp_path / "outside-terrain.geojson"
    gpd.GeoDataFrame(
        [{"height": 30, "geometry": Point(-1.0, 52.0)}],
        geometry="geometry",
        crs=4326,
    ).to_file(terrain, driver="GeoJSON")
    config.source.external_buffer_km = 0.1
    config.source.national_elevation = NationalElevationConfig(
        provider="local-geojson",
        path=terrain,
        source_id="national-dtm-no-local-coverage",
        effective_date="2026-01-15",
        licence="Open Government Licence v3.0",
        attribution="National terrain test source",
        elevation_field="height",
    )

    path = snapshot(config)
    result = compile(config)
    manifest = json.loads((path / "snapshot.json").read_text())
    profiles = gpd.read_file(result.artifacts["geopackage"], layer="topography_profiles")

    assert manifest["evidence_sources"]["elevation"]["coverage_status"] == ("explicit-unknown")
    assert manifest["evidence_sources"]["elevation"]["sample_count"] == 0
    assert result.metadata["elevation_evidence_status"] == "explicit-unknown"
    assert set(profiles["evidence_status"]) == {"evidence-unavailable"}


def test_empty_remote_coverage_is_snapshotted_as_explicit_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = copied_config(tmp_path)
    config.source.national_elevation = NationalElevationConfig(
        provider="remote-geojson",
        url="https://terrain.example.test/empty",
        source_id="national-empty-remote",
        licence="Open Government Licence v3.0",
        attribution="Empty remote terrain fixture",
    )

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"type":"FeatureCollection","features":[]}'

    def fake_urlopen(_request: object, timeout: int) -> Response:
        assert timeout == 90
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    path = snapshot(config)
    result = compile(config)
    manifest = json.loads((path / "snapshot.json").read_text())

    assert manifest["evidence_sources"]["elevation"]["coverage_status"] == ("explicit-unknown")
    assert result.metadata["elevation_evidence_status"] == "explicit-unknown"


def test_duplicate_governed_terrain_identifiers_are_rejected(tmp_path: Path) -> None:
    config = copied_config(tmp_path)
    terrain = tmp_path / "duplicate-terrain.geojson"
    gpd.GeoDataFrame(
        [
            {"sample": "duplicate", "height": 10, "geometry": Point(-2.50, 51.40)},
            {"sample": "duplicate", "height": 20, "geometry": Point(-2.48, 51.41)},
        ],
        geometry="geometry",
        crs=4326,
    ).to_file(terrain, driver="GeoJSON")
    config.source.national_elevation = NationalElevationConfig(
        provider="local-geojson",
        path=terrain,
        source_id="duplicate-terrain",
        effective_date="2026-01-15",
        licence="Synthetic fixture",
        attribution="Duplicate identifier fixture",
        elevation_field="height",
        identifier_field="sample",
    )

    with pytest.raises(ValueError, match="duplicate sample identifiers"):
        snapshot(config)


@pytest.mark.parametrize("height", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_governed_terrain_heights_are_rejected(
    tmp_path: Path, height: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = copied_config(tmp_path)
    terrain = tmp_path / "non-finite-terrain.geojson"
    source = gpd.GeoDataFrame(
        [{"sample": "invalid-height", "height": height, "geometry": Point(-2.50, 51.40)}],
        geometry="geometry",
        crs=4326,
    )
    terrain.touch()
    original_read_file = gpd.read_file

    def read_file_with_non_finite_source(
        path: object, *args: object, **kwargs: object
    ) -> gpd.GeoDataFrame:
        if Path(path) == terrain:
            return source.copy()
        return original_read_file(path, *args, **kwargs)

    monkeypatch.setattr("satn.sources.gpd.read_file", read_file_with_non_finite_source)
    config.source.national_elevation = NationalElevationConfig(
        provider="local-geojson",
        path=terrain,
        source_id="non-finite-terrain",
        effective_date="2026-01-15",
        licence="Synthetic fixture",
        attribution="Non-finite height fixture",
        elevation_field="height",
        identifier_field="sample",
    )

    with pytest.raises(ValueError, match="unusable heights"):
        snapshot(config)


def test_null_governed_terrain_identifier_uses_geometry_fallback(tmp_path: Path) -> None:
    config = copied_config(tmp_path)
    terrain = tmp_path / "null-identifier-terrain.geojson"
    gpd.GeoDataFrame(
        [
            {"sample": 101, "height": 10, "geometry": Point(-2.50, 51.40)},
            {"sample": None, "height": 20, "geometry": Point(-2.48, 51.41)},
        ],
        geometry="geometry",
        crs=4326,
    ).to_file(terrain, driver="GeoJSON")
    config.source.national_elevation = NationalElevationConfig(
        provider="local-geojson",
        path=terrain,
        source_id="null-identifier-terrain",
        effective_date="2026-01-15",
        licence="Synthetic fixture",
        attribution="Null identifier fixture",
        elevation_field="height",
        identifier_field="sample",
    )

    snapshot(config)
    loaded = load_snapshot(config)["elevation_evidence"]

    assert "nan" not in set(loaded["evidence_id"])
    assert "<NA>" not in set(loaded["evidence_id"])
    assert len(set(loaded["evidence_id"])) == 2


def test_segmented_osm_way_corroboration_ids_are_unique_and_stable() -> None:
    rows = [
        {
            "osmid": "shared-way",
            "ele": "100",
            "incline": "5%",
            "geometry": LineString([(0, 0), (1, 0)]),
        },
        {
            "osmid": "shared-way",
            "ele": "110",
            "incline": "6%",
            "geometry": LineString([(1, 0), (2, 0)]),
        },
    ]
    network = gpd.GeoDataFrame(rows, geometry="geometry", crs=27700)

    first = _osm_elevation_corroboration(network)
    reversed_result = _osm_elevation_corroboration(network.iloc[::-1])

    assert first["corroboration_id"].is_unique
    assert set(first["corroboration_id"]) == set(reversed_result["corroboration_id"])
    assert set(first["source_id"]) == {"shared-way"}


def test_sparse_osm_height_tags_never_replace_missing_national_elevation(
    tmp_path: Path,
) -> None:
    config = copied_config(tmp_path)
    config.source.national_elevation = None
    evidence_path = config.source.fixture_dir / "elevation-evidence.geojson"
    evidence_path.unlink()
    network_path = config.source.fixture_dir / "network.geojson"
    network = gpd.read_file(network_path)
    network["ele"] = "150"
    network["incline"] = "12%"
    network.to_file(network_path, driver="GeoJSON")
    snapshot(config)

    result = compile(config)
    profiles = gpd.read_file(result.artifacts["geopackage"], layer="topography_profiles")
    corroboration = gpd.read_file(result.artifacts["geopackage"], layer="elevation_corroboration")

    assert set(profiles["evidence_status"]) == {"evidence-unavailable"}
    assert result.metadata["elevation_evidence_status"] == "explicit-unknown"
    assert result.metadata["elevation_corroboration_count"] == len(network)
    assert set(corroboration["evidence_role"]) == {"corroborating-only"}


@pytest.mark.live_terrain
def test_live_national_elevation_acquisition_is_explicitly_opt_in(tmp_path: Path) -> None:
    url = os.environ.get("SATN_TEST_TERRAIN_GEOJSON_URL")
    if not url:
        pytest.skip("set SATN_TEST_TERRAIN_GEOJSON_URL for the opt-in live terrain test")
    config = copied_config(tmp_path)
    config.source.national_elevation = NationalElevationConfig(
        provider="remote-geojson",
        url=url,
        source_id="live-national-terrain",
        licence="Configured by SATN_TEST_TERRAIN_GEOJSON_URL",
        attribution="Configured live terrain test source",
    )

    path = snapshot(config)

    assert (path / "elevation-evidence.geojson").exists()
