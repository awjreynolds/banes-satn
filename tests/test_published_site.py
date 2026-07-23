from __future__ import annotations

import json
from pathlib import Path

from satn.constants import DISCLAIMER

PROJECT = Path(__file__).parents[1]


def test_tracked_pages_site_is_complete_and_contains_no_atm_geometry() -> None:
    site = PROJECT / "site"
    publication = json.loads((site / "publication.json").read_text(encoding="utf-8"))
    agent_records = json.loads((site / "agent-records.json").read_text(encoding="utf-8"))
    network = json.loads((site / "network.geojson").read_text(encoding="utf-8"))
    features = network["features"]
    connections = [
        feature
        for feature in features
        if feature["properties"]["feature_type"]
        in {
            "spine-access-connection",
            "school-access-connection",
            "branch-meeting-connection",
        }
    ]

    assert publication["schema_version"] == "2.0"
    assert publication["network_model"] == "backbone-outward"
    assert publication["status"] in {"complete", "reviewable"}
    assert publication["connection_count"] == len(connections)
    assert publication["gap_count"] == publication["layer_counts"]["gaps"]
    assert publication["human_intervention_request_count"] == 0
    assert publication["comparison_role"] == "superseded-reference-not-ground-truth"
    assert publication["compilation_diagnostics"]["assembly_strategy"] == "backbone-outward"
    recorded_ids = {record["connection_id"] for record in agent_records["records"]}
    assert {feature["id"] for feature in connections} <= recorded_ids
    assert recorded_ids <= {feature["id"] for feature in features}
    assert publication["disclaimer"] == DISCLAIMER
    assert len({feature["id"] for feature in connections}) == len(connections)
    assert "connection" not in {feature["properties"]["feature_type"] for feature in features}
    assert "atm-reference" not in {feature["properties"]["feature_type"] for feature in features}
    assert (site / ".nojekyll").exists()
    assert (site / "network-map.pdf").read_bytes().startswith(b"%PDF-")
    assert (site / "network.geojson").stat().st_size < 35_000_000
    assert (site / "topography.geojson").stat().st_size < 60_000_000
    assert (site / "data.js").stat().st_size < 1_000_000
    assert '"network_url":"network.geojson"' in (site / "data.js").read_text()
    assert '"topography_url":"topography.geojson"' in (site / "data.js").read_text()
    profile_index = json.loads(
        (site / "topography-profile-evidence.json").read_text(encoding="utf-8")
    )
    governed_profiles = [
        feature
        for chunk in profile_index["chunks"]
        for feature in json.loads((site / chunk["path"]).read_text(encoding="utf-8"))[
            "features"
        ]
    ]
    assert len(governed_profiles) == profile_index["profile_count"]
    available = next(
        feature
        for feature in governed_profiles
        if json.loads(feature["properties"]["micro_gradient_intervals"])
    )
    interval = json.loads(available["properties"]["micro_gradient_intervals"])[0]
    assert {
        "uphill_direction",
        "absolute_gradient_pct",
        "rolling_step_m",
        "calculation_method",
        "elevation_evidence_ids",
        "uncertainty",
    } <= set(interval)
    assert all(
        "micro_gradient_intervals" not in feature["properties"]
        for feature in connections
    )
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'id="layer-strategic-network"' in html
    assert 'id="layer-spine-access-connections"' in html
    assert 'id="layer-cross-spine-connectors"' in html
    assert 'id="layer-gaps-warnings"' in html
    assert 'id="layer-schools"' in html
    assert 'id="layer-retail-centres"' in html
    assert 'id="layer-healthcare"' in html
    assert 'id="layer-atm"' in html
    assert 'id="atm-upload"' in html
    assert 'aria-describedby="legend-strategic-network"' in html
    assert 'aria-describedby="legend-spine-access-connections"' in html
