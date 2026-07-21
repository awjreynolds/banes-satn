from __future__ import annotations

import json
from pathlib import Path

from satn.constants import DISCLAIMER

PROJECT = Path(__file__).parents[1]


def test_tracked_pages_site_is_complete_and_contains_no_atm_geometry() -> None:
    site = PROJECT / "site"
    publication = json.loads((site / "publication.json").read_text(encoding="utf-8"))
    network = json.loads((site / "network.geojson").read_text(encoding="utf-8"))
    features = network["features"]
    connections = [
        feature
        for feature in features
        if feature["properties"]["feature_type"] == "connection"
    ]

    assert publication["status"] == "complete"
    assert publication["connection_count"] == len(connections) == 150
    assert publication["gap_count"] == 0
    assert publication["disclaimer"] == DISCLAIMER
    assert len({feature["id"] for feature in connections}) == 150
    assert "atm-reference" not in {
        feature["properties"]["feature_type"] for feature in features
    }
    assert (site / ".nojekyll").exists()
