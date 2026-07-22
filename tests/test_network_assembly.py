from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import _crossing_warnings, compile_network
from satn.models import CouncilConfig

PROJECT = Path(__file__).parents[1]


def config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")


def test_missing_spine_evidence_exposes_every_rural_obligation_as_a_gap() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": place_id,
                "name": place_id.upper(),
                "kind": "community",
                "place_class": "village",
                "geometry": Point(position, 0),
            }
            for place_id, position in (("a", 0), ("b", 0.02), ("c", 0.04))
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "abc",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.02, 0), (0.04, 0)]),
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    assert compiled.spine_access_connections.empty
    assert len(compiled.access_obligations) == len(places)
    assert set(compiled.access_obligations["service_status"]) == {"network-gap"}
    assert len(compiled.gaps) == len(places)
    assert compiled.criteria["network"]["legacy_pairwise_absent"] == "green"


def test_unjoined_route_crossing_is_an_amber_warning() -> None:
    connections = gpd.GeoDataFrame(
        [
            {"connection_id": "one", "geometry": LineString([(-1, 0), (1, 0)])},
            {"connection_id": "two", "geometry": LineString([(0, -1), (0, 1)])},
        ],
        crs=4326,
    )

    warnings = _crossing_warnings(connections)

    assert len(warnings) == 1
    assert warnings.iloc[0].status == "amber"
    assert warnings.iloc[0].geometry.equals(Point(0, 0))
