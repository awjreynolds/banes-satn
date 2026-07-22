from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import geopandas as gpd

from satn import compile
from satn.models import CouncilConfig
from satn.sources import snapshot

PROJECT = Path(__file__).parents[1]


def prepared_config(tmp_path: Path) -> CouncilConfig:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    snapshot(config)
    return config


def test_validated_connection_is_reused_when_governed_inputs_match(tmp_path: Path) -> None:
    config = prepared_config(tmp_path)

    first = compile(config)
    second = compile(config)

    assert first.metadata["cache"] == {"hits": 0, "misses": 1}
    assert second.metadata["cache"] == {"hits": 1, "misses": 0}
    frame = gpd.read_file(second.artifacts["geopackage"], layer="connections")
    assert set(frame["cache_status"]) == {"reused"}
    assert first.agent_records[0].created_at == second.agent_records[0].created_at


def test_full_directive_ignores_reusable_connections(tmp_path: Path) -> None:
    config = prepared_config(tmp_path)
    compile(config)
    config.compilation.full = True

    forced = compile(config)

    assert forced.metadata["cache"] == {"hits": 0, "misses": 1}
    frame = gpd.read_file(forced.artifacts["geopackage"], layer="connections")
    assert set(frame["cache_status"]) == {"compiled"}


def test_criteria_change_invalidates_all_reuse(tmp_path: Path) -> None:
    config = prepared_config(tmp_path)
    compile(config)
    config.compilation.criteria_version = "2-new-criterion"

    changed = compile(config)

    assert changed.metadata["cache"] == {"hits": 0, "misses": 1}


def test_changed_elevation_evidence_invalidates_cache_and_run_fingerprint(
    tmp_path: Path,
) -> None:
    config = prepared_config(tmp_path)
    first = compile(config)
    terrain_path = config.source.national_elevation.path
    assert terrain_path is not None
    terrain = gpd.read_file(terrain_path)
    terrain.loc[0, "elevation_m"] = float(terrain.loc[0, "elevation_m"]) + 1
    terrain.to_file(terrain_path, driver="GeoJSON")
    snapshot(config, replace=True)

    changed = compile(config)

    assert changed.metadata["cache"] == {"hits": 0, "misses": 1}
    assert changed.run_id != first.run_id


def test_cli_full_directive_forces_recompilation(tmp_path: Path) -> None:
    config = prepared_config(tmp_path)
    compile(config)

    subprocess.run(
        [
            str(PROJECT / ".venv" / "bin" / "satn"),
            "compile",
            str(config.config_path),
            "--full",
        ],
        cwd=PROJECT,
        check=True,
        capture_output=True,
        text=True,
    )

    run = json.loads((config.publication.output_dir / "run.json").read_text())
    assert run["cache"] == {"hits": 0, "misses": 1}
