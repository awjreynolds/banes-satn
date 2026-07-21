from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import geopandas as gpd

from satn import compile
from satn.constants import DISCLAIMER
from satn.models import CouncilConfig
from satn.sources import snapshot

PROJECT = Path(__file__).parents[1]


def fixture_config(tmp_path: Path) -> Path:
    fixture = tmp_path / "fixture"
    shutil.copytree(PROJECT / "examples" / "fixture", fixture)
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
        "review_map",
        "review_zip",
        "pdf",
    }
    assert all(path.exists() for path in result.artifacts.values())
    connections = gpd.read_file(result.artifacts["geopackage"], layer="connections")
    assert list(connections["status"]) == ["validated"]
    assert list(connections["classification"]) == ["low-traffic"]
    geojson = json.loads(result.artifacts["geojson"].read_text())
    assert geojson["disclaimer"] == DISCLAIMER
    assert result.artifacts["pdf"].read_bytes().startswith(b"%PDF")
    html = result.artifacts["review_map"].read_text()
    assert DISCLAIMER in html
    assert 'id="feature-details"' in html
    assert 'data-feature-id="connection-' in html
    assert "Download full typed agent records" in html
    assert (result.artifacts["review_map"].parent / "agent-records.json").exists()


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
