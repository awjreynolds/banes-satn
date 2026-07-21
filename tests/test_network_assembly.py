
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import _crossing_warnings, _unresolved_rejections, compile_network
from satn.models import CouncilConfig

PROJECT = Path(__file__).parents[1]


def config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")


def test_only_rejections_that_still_block_the_network_become_gaps() -> None:
    connected = nx.Graph([("a", "b"), ("b", "c")])
    superseded = {"from_place": "a", "to_place": "c"}

    assert _unresolved_rejections(connected, [superseded], {"a", "b", "c"}, set()) == []

    disconnected = nx.Graph([("a", "b")])
    disconnected.add_node("c")
    blocking = {"from_place": "b", "to_place": "c"}
    assert _unresolved_rejections(
        disconnected, [blocking], {"a", "b", "c"}, set()
    ) == [blocking]


def test_components_and_internal_termini_are_repaired_with_unique_bounded_pairs() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "a",
                "name": "A",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "b",
                "name": "B",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.02, 0),
            },
            {
                "place_id": "c",
                "name": "C",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.20, 0),
            },
            {
                "place_id": "d",
                "name": "D",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.22, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {"osmid": "ab", "highway": "unclassified", "geometry": LineString([(0, 0), (0.02, 0)])},
            {
                "osmid": "bc",
                "highway": "unclassified",
                "geometry": LineString([(0.02, 0), (0.20, 0)]),
            },
            {
                "osmid": "cd",
                "highway": "unclassified",
                "geometry": LineString([(0.20, 0), (0.22, 0)]),
            },
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    graph = nx.Graph(
        compiled.connections[["from_place", "to_place"]].itertuples(index=False, name=None)
    )
    pairs = [tuple(sorted(edge)) for edge in graph.edges]
    assert nx.is_connected(graph)
    assert all(graph.degree(place_id) >= 2 for place_id in places["place_id"])
    assert len(pairs) == len(set(pairs))
    assert len(compiled.agent_records) <= len(places) * (len(places) - 1) // 2
    assert compiled.criteria["network"] == {
        "community_coverage": "green",
        "connected_graph": "green",
        "unique_pairs": "green",
        "internal_termini": "green",
        "intervention_coverage": "green",
    }
    assert len(compiled.network_units) == 1


def test_disconnected_source_network_emits_an_explicit_gap_and_terminates() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "a",
                "name": "A",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "b",
                "name": "B",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.02, 0),
            },
            {
                "place_id": "c",
                "name": "C",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(1, 0),
            },
            {
                "place_id": "d",
                "name": "D",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(1.02, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {"osmid": "ab", "highway": "unclassified", "geometry": LineString([(0, 0), (0.02, 0)])},
            {"osmid": "cd", "highway": "unclassified", "geometry": LineString([(1, 0), (1.02, 0)])},
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    assert not compiled.gaps.empty
    assert "No continuous OSM" in compiled.gaps.iloc[0].selection_reason
    assert compiled.criteria["network"]["connected_graph"] == "red"
    assert len(compiled.agent_records) <= len(places) * (len(places) - 1) // 2
    assert len(compiled.network_units) == 2


def test_recompilation_is_topologically_stable() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "a",
                "name": "A",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "b",
                "name": "B",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.05, 0),
            },
            {
                "place_id": "c",
                "name": "C",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.1, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "abc",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.05, 0), (0.1, 0)]),
            }
        ],
        crs=4326,
    )
    source = {"places": places, "network": network, "boundary": gpd.GeoDataFrame()}

    first = compile_network(config(), source, FakeAgentRuntime())
    second = compile_network(config(), source, FakeAgentRuntime())

    assert list(first.connections["connection_id"]) == list(second.connections["connection_id"])
    assert [geometry.wkb for geometry in first.connections.geometry] == [
        geometry.wkb for geometry in second.connections.geometry
    ]


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
