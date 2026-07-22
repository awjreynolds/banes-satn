from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import geopandas as gpd
import pyogrio

from satn import compile
from satn.constants import DISCLAIMER
from satn.models import CouncilConfig
from satn.sources import snapshot

PROJECT = Path(__file__).parents[1]


def fixture_config(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    return fixture / "council.yaml"


def test_public_api_runs_complete_fixture(tmp_path: Path) -> None:
    config_path = fixture_config(tmp_path)
    config = CouncilConfig.from_yaml(config_path)
    snapshot_path = snapshot(config)

    assert snapshot_path.name == "fixture-001"
    manifest = json.loads((snapshot_path / "snapshot.json").read_text())
    assert manifest["source_kind"] == "fixture"
    assert manifest["disclaimer"] == DISCLAIMER

    result = compile(config)

    assert result.status == "complete"
    assert result.connections == 1
    assert result.gaps == 0
    assert result.criteria["connections"]["mandatory_checks"] == "green"
    assert result.agent_records[0].decision == "accept"
    assert set(result.artifacts) == {
        "geopackage",
        "geojson",
        "run",
        "agents",
        "divergences",
        "review_map",
        "review_zip",
        "pdf",
    }
    assert all(path.exists() for path in result.artifacts.values())
    connections = gpd.read_file(result.artifacts["geopackage"], layer="connections")
    assert list(connections["status"]) == ["validated"]
    assert list(connections["classification"]) == ["low-traffic"]
    assert {
        "strategic_spines",
        "access_obligations",
        "spine_access_connections",
        "a_road_spines",
        "ncn_routes",
        "schools",
        "retail_centres",
        "healthcare",
    } <= set(pyogrio.list_layers(result.artifacts["geopackage"])[:, 0])
    strategic_spines = gpd.read_file(result.artifacts["geopackage"], layer="strategic_spines")
    assert set(strategic_spines["spine_kind"]) == {"a-road", "ncn"}
    assert set(strategic_spines["network_role"]) == {"strategic-spine"}
    assert "b2" not in set(strategic_spines["source_id"])
    a_road = strategic_spines[strategic_spines["spine_kind"] == "a-road"].iloc[0]
    assert a_road["intervention_assumption"] == (
        "Major engineering required to provide high-quality protected or shared provision"
    )
    assert a_road["design_status"] == "strategic assumption; not a carriageway or final design"
    spine_access = gpd.read_file(result.artifacts["geopackage"], layer="spine_access_connections")
    assert len(spine_access) == 1
    assert spine_access.iloc[0]["access_connection_id"].startswith("spine-access-")
    assert spine_access.iloc[0]["community_id"] in {"westfield", "eastfield"}
    assert spine_access.iloc[0]["spine_id"] in set(strategic_spines["spine_id"])
    assert spine_access.iloc[0]["network_role"] == "spine-access-connection"
    assert spine_access.iloc[0]["community_attachment_node"]
    assert spine_access.iloc[0]["community_attachment_distance_m"] >= 0
    assert spine_access.iloc[0]["spine_attachment_node"]
    assert spine_access.iloc[0]["spine_attachment_distance_m"] <= 20
    assert json.loads(spine_access.iloc[0]["source_ids"])
    target_spine = strategic_spines[
        strategic_spines["spine_id"] == spine_access.iloc[0]["spine_id"]
    ].iloc[0]
    assert spine_access.iloc[0].geometry.intersects(target_spine.geometry)
    assert result.metadata["strategic_spines"] == 2
    assert result.metadata["access_obligations"] == 1
    assert result.metadata["spine_access_connections"] == 1
    obligation = gpd.read_file(result.artifacts["geopackage"], layer="access_obligations")
    assert list(obligation["network_role"]) == ["community-access-obligation"]
    assert (
        obligation.iloc[0]["access_connection_id"] == spine_access.iloc[0]["access_connection_id"]
    )
    assert spine_access.iloc[0].geometry.intersects(obligation.iloc[0].geometry)
    assert result.metadata["strategic_spine_records"][0]["spine_id"] in set(
        strategic_spines["spine_id"]
    )
    assert json.loads(result.metadata["strategic_spine_records"][0]["provenance"])["evidence_id"]
    assert result.metadata["spine_access_connection_records"][0]["access_connection_id"] in set(
        spine_access["access_connection_id"]
    )
    assert json.loads(result.metadata["spine_access_connection_records"][0]["source_ids"])
    assert (
        result.metadata["spine_access_connection_records"][0]["community_attachment_node"]
        == spine_access.iloc[0]["community_attachment_node"]
    )
    assert (
        result.metadata["access_obligation_records"][0]["obligation_id"]
        == obligation.iloc[0]["obligation_id"]
    )
    assert (
        json.loads(result.metadata["access_obligation_records"][0]["provenance"])["community_id"]
        == obligation.iloc[0]["community_id"]
    )
    geojson = json.loads(result.artifacts["geojson"].read_text())
    assert geojson["disclaimer"] == DISCLAIMER
    geojson_ids = {feature["id"] for feature in geojson["features"]}
    assert set(strategic_spines["spine_id"]) <= geojson_ids
    assert set(spine_access["access_connection_id"]) <= geojson_ids
    assert set(obligation["obligation_id"]) <= geojson_ids
    assert result.artifacts["pdf"].read_bytes().startswith(b"%PDF")
    html = result.artifacts["review_map"].read_text()
    assert DISCLAIMER in html
    assert 'id="feature-details"' in html
    assert 'id="layer-a-road-spines"' in html
    assert 'id="layer-community-connections"' in html
    assert 'id="layer-ncn-routes"' in html
    assert 'id="layer-strategic-spines"' in html
    assert 'id="layer-spine-access-connections"' in html
    assert "A-road Strategic Spine — major engineering required" in html
    assert "Established NCN Strategic Spine" in html
    assert "Spine Access Connection" in html
    assert 'id="legend-strategic-spines"' in html
    assert 'id="legend-spine-access-connections"' in html
    assert 'id="layer-schools"' in html
    assert 'id="layer-retail-centres"' in html
    assert 'id="layer-healthcare"' in html
    data = (result.artifacts["review_map"].parent / "data.js").read_text()
    assert '"id": "connection-' in data
    app = (result.artifacts["review_map"].parent / "assets" / "review-map.js").read_text()
    assert "button.dataset.featureId = feature.id" in app
    assert "Typed agent records" in html
    assert (result.artifacts["review_map"].parent / "agent-records.json").exists()
    assert '"from_place_name": "Eastfield"' in data
    assert '"to_place_name": "Westfield"' in data


def test_external_cli_snapshot_and_compile(tmp_path: Path) -> None:
    config_path = fixture_config(tmp_path)
    snapshot_run = subprocess.run(
        [str(PROJECT / ".venv" / "bin" / "satn"), "snapshot", str(config_path)],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "fixture-001" in snapshot_run.stdout

    compile_run = subprocess.run(
        [str(PROJECT / ".venv" / "bin" / "satn"), "compile", str(config_path)],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "complete: 1 connections, 0 gaps" in compile_run.stdout
    assert (config_path.parent / "work" / "output" / "review-map.zip").exists()


def test_compile_replaces_the_previous_run(tmp_path: Path) -> None:
    config_path = fixture_config(tmp_path)
    config = CouncilConfig.from_yaml(config_path)
    snapshot(config)
    first = compile(config)
    stale = first.output_dir / "stale.txt"
    stale.write_text("must disappear")

    second = compile(config)

    assert first.run_id == second.run_id
    assert not stale.exists()
