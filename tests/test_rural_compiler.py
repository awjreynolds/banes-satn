# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig
from satn.routing import RoadGraph, choose_alignment

PROJECT = Path(__file__).parents[1]


def config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")


def edges(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)


def test_a_road_is_the_priority_strategic_spine() -> None:
    network = edges(
        [
            {"osmid": "minor", "highway": "unclassified", "geometry": LineString([(0, 0), (0.1, 0)])},
            {"osmid": "a1", "highway": "primary", "ref": "A37", "geometry": LineString([(0, 0), (0.05, 0.02)])},
            {"osmid": "a2", "highway": "primary", "ref": "A37", "geometry": LineString([(0.05, 0.02), (0.1, 0)])},
        ]
    )
    graph = RoadGraph(network)
    start = graph.nearest_node(Point(0, 0))[0]
    end = graph.nearest_node(Point(0.1, 0))[0]

    selected, options, reason = choose_alignment(graph, start, end)

    assert selected is not None
    assert selected.role == "strategic-spine"
    assert selected.a_road_share == 1
    assert {option.role for option in options} >= {"direct", "strategic-spine"}
    assert "social oversight" in reason


def test_impracticable_a_road_uses_reasoned_parallel_fallback() -> None:
    network = edges(
        [
            {
                "osmid": "a-road",
                "highway": "primary",
                "ref": "A4",
                "satn_alongside": "impracticable",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            },
            {"osmid": "quiet-1", "highway": "unclassified", "geometry": LineString([(0, 0), (0.05, 0.02)])},
            {"osmid": "quiet-2", "highway": "unclassified", "geometry": LineString([(0.05, 0.02), (0.1, 0)])},
        ]
    )
    graph = RoadGraph(network)

    selected, _, reason = choose_alignment(
        graph,
        graph.nearest_node(Point(0, 0))[0],
        graph.nearest_node(Point(0.1, 0))[0],
    )

    assert selected is not None
    assert selected.a_road_share == 0
    assert "physically impracticable" in reason


def test_nearest_nominations_collapse_and_long_connection_is_challenged() -> None:
    places = gpd.GeoDataFrame(
        [
            {"place_id": "a", "name": "A", "kind": "community", "place_class": "village", "geometry": Point(0, 0)},
            {"place_id": "b", "name": "B", "kind": "community", "place_class": "village", "geometry": Point(0.08, 0)},
            {"place_id": "c", "name": "C", "kind": "community", "place_class": "village", "geometry": Point(0.25, 0)},
        ],
        crs=4326,
    )
    network = edges(
        [
            {"osmid": "ab", "highway": "unclassified", "geometry": LineString([(0, 0), (0.08, 0)])},
            {"osmid": "bc", "highway": "unclassified", "geometry": LineString([(0.08, 0), (0.25, 0)])},
        ]
    )
    boundary = gpd.GeoDataFrame(geometry=[], crs=4326)

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": boundary},
        FakeAgentRuntime(),
    )

    pairs = {
        tuple(sorted((row.from_place, row.to_place)))
        for _, row in compiled.connections.iterrows()
    }
    assert pairs == {("a", "b"), ("b", "c")}
    assert len(compiled.connections) == len(pairs)
    assert "amber" in set(compiled.connections["criterion_distance"])
    assert set(compiled.connections["criterion_continuity"]) == {"green"}


def test_missing_path_is_a_red_gap_without_an_invented_line() -> None:
    places = gpd.GeoDataFrame(
        [
            {"place_id": "a", "name": "A", "kind": "community", "place_class": "village", "geometry": Point(0, 0)},
            {"place_id": "b", "name": "B", "kind": "community", "place_class": "village", "geometry": Point(1, 0)},
        ],
        crs=4326,
    )
    network = edges(
        [
            {"osmid": "left", "highway": "unclassified", "geometry": LineString([(0, 0), (0.1, 0)])},
            {"osmid": "right", "highway": "unclassified", "geometry": LineString([(0.9, 0), (1, 0)])},
        ]
    )

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    assert compiled.connections.empty
    assert len(compiled.gaps) == 1
    gap = compiled.gaps.iloc[0]
    assert gap.geometry.geom_type == "MultiPoint"
    assert gap.criterion_continuity == "red"
    assert gap.classification == "network-gap"
    assert json.loads(gap.alignment_options) == []
