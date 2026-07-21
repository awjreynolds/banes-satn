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
        if feature["properties"]["feature_type"] == "connection"
    ]

    assert publication["status"] == "complete"
    assert publication["connection_count"] == len(connections) == 163
    assert publication["gap_count"] == 0
    assert publication["superseded_hypotheses"] == 2
    assert sum(record["decision"] == "superseded" for record in agent_records["records"]) == 2
    assert all(record["decision"] != "gap" for record in agent_records["records"])
    assert publication["disclaimer"] == DISCLAIMER
    assert len({feature["id"] for feature in connections}) == 163
    assert "atm-reference" not in {
        feature["properties"]["feature_type"] for feature in features
    }
    assert (site / ".nojekyll").exists()
    assert (site / "network-map.pdf").read_bytes().startswith(b"%PDF-")
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'id="layer-a-road-spines"' in html
    assert 'id="layer-community-connections"' in html
    assert 'id="layer-ncn-routes"' in html
    assert 'id="layer-schools"' in html
    assert 'id="layer-retail-centres"' in html
    assert 'id="layer-healthcare"' in html
    assert 'id="layer-atm"' in html
    assert 'id="atm-upload"' in html
