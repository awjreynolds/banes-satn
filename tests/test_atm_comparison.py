# ruff: noqa: E501

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString

from satn import compile
from satn.agents import FakeAgentRuntime
from satn.atm import compare_atm
from satn.compiler import compile_network
from satn.models import CouncilConfig
from satn.sources import load_snapshot, snapshot

PROJECT = Path(__file__).parents[1]


def prepared(tmp_path: Path) -> tuple[CouncilConfig, Path]:
    fixture = tmp_path / "fixture"
    shutil.copytree(PROJECT / "examples" / "fixture", fixture)
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    atm_path = fixture / "atm.geojson"
    gpd.GeoDataFrame(
        [
            {"portal_feature_id": "atm-match", "geometry": LineString([(-2.5, 51.4), (-2.482, 51.412), (-2.46, 51.42)])},
            {"portal_feature_id": "atm-omission", "geometry": LineString([(-2.6, 51.3), (-2.59, 51.31)])},
        ],
        crs=4326,
    ).to_file(atm_path, driver="GeoJSON")
    config.atm.enabled = True
    config.atm.path = atm_path
    config.atm.mode = "blind"
    snapshot(config)
    return config, atm_path


def test_blind_comparison_is_independent_and_publication_is_lawful(tmp_path: Path) -> None:
    config, _ = prepared(tmp_path)
    config.publication.audience = "public"
    config.atm.redistribution_permitted = False

    result = compile(config)

    assert result.metadata["atm_mode"] == "blind"
    assert result.metadata["atm_geometry_included"] is False
    assert result.metadata["divergence_counts"] == {"match": 1, "omission": 1}
    network = json.loads(result.artifacts["geojson"].read_text())
    assert "atm-reference" not in {f["properties"]["feature_type"] for f in network["features"]}
    assert "atm_reference" not in set(pyogrio.list_layers(result.artifacts["geopackage"])[:, 0])
    divergence = json.loads(result.artifacts["divergences"].read_text())
    assert {record["status"] for record in divergence["records"]} == {"match", "omission"}
    connection = gpd.read_file(result.artifacts["geopackage"], layer="connections").iloc[0]
    assert not connection.selection_reason.startswith("ATM-seeded")


def test_seeded_mode_isolated_from_blind_cache_and_records_its_hypothesis(tmp_path: Path) -> None:
    config, _ = prepared(tmp_path)
    blind = compile(config)
    config.atm.mode = "seeded"

    seeded = compile(config)

    assert blind.metadata["cache"] == {"hits": 0, "misses": 1}
    assert seeded.metadata["cache"] == {"hits": 0, "misses": 1}
    connection = gpd.read_file(seeded.artifacts["geopackage"], layer="connections").iloc[0]
    assert connection.selection_reason.startswith("ATM-seeded")


def test_local_or_permitted_output_can_include_the_atm_overlay(tmp_path: Path) -> None:
    config, atm_path = prepared(tmp_path)
    config.publication.audience = "local"
    atm = gpd.read_file(atm_path)
    atm["fid"] = [101, 102]
    atm.loc[len(atm)] = {
        "portal_feature_id": "atm-null",
        "fid": 103,
        "geometry": None,
    }
    atm = atm.set_crs(4326, allow_override=True)
    atm.to_file(atm_path, driver="GeoJSON")

    local = compile(config)

    assert local.metadata["atm_geometry_included"] is True
    assert "atm_reference" in set(pyogrio.list_layers(local.artifacts["geopackage"])[:, 0])
    published_atm = gpd.read_file(
        local.artifacts["geopackage"], layer="atm_reference"
    )
    assert list(published_atm["source_fid"]) == [101, 102, 103]
    network = json.loads(local.artifacts["geojson"].read_text())
    assert "atm-reference" in {f["properties"]["feature_type"] for f in network["features"]}


def test_divergence_statuses_cover_deviation_and_addition(tmp_path: Path) -> None:
    config, _ = prepared(tmp_path)
    source = load_snapshot(config)
    compiled = compile_network(config, source, FakeAgentRuntime())
    route = compiled.connections.to_crs(27700).iloc[0].geometry
    midpoint = route.interpolate(0.5, normalized=True)
    partial = LineString([route.coords[0], (midpoint.x, midpoint.y)])
    partial_atm = gpd.GeoDataFrame(
        [{"portal_feature_id": "partial", "geometry": partial}], crs=27700
    )

    deviation = compare_atm(compiled, partial_atm, FakeAgentRuntime(), config)
    far_atm = gpd.GeoDataFrame(
        [{"portal_feature_id": "far", "geometry": LineString([(500000, 100000), (501000, 100000)])}],
        crs=27700,
    )
    addition = compare_atm(compiled, far_atm, FakeAgentRuntime(), config)

    assert "deviation" in {record.status for record in deviation}
    assert {record.status for record in addition} == {"addition", "omission"}
    assert all(record.resolution_attempts for record in [*deviation, *addition])
