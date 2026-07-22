from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, MultiLineString, Point

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
            {
                "osmid": "minor",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            },
            {
                "osmid": "a1",
                "highway": "primary",
                "ref": "A37",
                "geometry": LineString([(0, 0), (0.05, 0.02)]),
            },
            {
                "osmid": "a2",
                "highway": "primary",
                "ref": "A37",
                "geometry": LineString([(0.05, 0.02), (0.1, 0)]),
            },
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
            {
                "osmid": "quiet-1",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.05, 0.02)]),
            },
            {
                "osmid": "quiet-2",
                "highway": "unclassified",
                "geometry": LineString([(0.05, 0.02), (0.1, 0)]),
            },
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


def test_bidirectionality_requires_reverse_edges_on_the_selected_corridor() -> None:
    network = edges(
        [
            {
                "osmid": "forward",
                "highway": "unclassified",
                "oneway": True,
                "geometry": LineString([(0, 0), (0.1, 0)]),
            },
            {
                "osmid": "return-1",
                "highway": "unclassified",
                "geometry": LineString([(0.1, 0), (0.05, 0.01)]),
            },
            {
                "osmid": "return-2",
                "highway": "unclassified",
                "geometry": LineString([(0.05, 0.01), (0, 0)]),
            },
        ]
    )
    graph = RoadGraph(network)
    start = graph.nearest_node(Point(0, 0))[0]
    end = graph.nearest_node(Point(0.1, 0))[0]

    option = graph.option(start, end, "direct")

    assert option is not None
    assert not option.bidirectional
    assert option.reverse_length_km is not None
    assert option.reverse_edge_ids == ["return-1", "return-2"]
    assert option.reverse_corridor_share < 0.5


def test_bidirectionality_records_reverse_edges_on_the_selected_corridor() -> None:
    network = edges(
        [
            {
                "osmid": "two-way",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ]
    )
    graph = RoadGraph(network)
    option = graph.option(
        graph.nearest_node(Point(0, 0))[0],
        graph.nearest_node(Point(0.1, 0))[0],
        "direct",
    )

    assert option is not None
    assert option.bidirectional
    assert option.reverse_length_km == option.length_km
    assert option.reverse_edge_ids == ["two-way"]
    assert option.reverse_corridor_share == 1


def test_nearest_nominations_collapse_and_long_connection_is_challenged() -> None:
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
                "geometry": Point(0.08, 0),
            },
            {
                "place_id": "c",
                "name": "C",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.25, 0),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {"osmid": "ab", "highway": "unclassified", "geometry": LineString([(0, 0), (0.08, 0)])},
            {
                "osmid": "bc",
                "highway": "unclassified",
                "geometry": LineString([(0.08, 0), (0.25, 0)]),
            },
        ]
    )
    boundary = gpd.GeoDataFrame(geometry=[], crs=4326)

    compiled = compile_network(
        config(),
        {"places": places, "network": network, "boundary": boundary},
        FakeAgentRuntime(),
    )

    pairs = {
        tuple(sorted((row.from_place, row.to_place))) for _, row in compiled.connections.iterrows()
    }
    assert pairs == {("a", "b"), ("b", "c"), ("a", "c")}
    assert len(compiled.connections) == len(pairs)
    assert "amber" in set(compiled.connections["criterion_distance"])
    assert set(compiled.connections["criterion_continuity"]) == {"green"}
    assert compiled.criteria["network"]["internal_termini"] == "green"


def test_missing_path_is_a_red_gap_without_an_invented_line() -> None:
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
                "geometry": Point(1, 0),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {
                "osmid": "left",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            },
            {
                "osmid": "right",
                "highway": "unclassified",
                "geometry": LineString([(0.9, 0), (1, 0)]),
            },
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


def test_disconnected_spine_evidence_cannot_become_a_validated_access() -> None:
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
                "geometry": Point(0.1, 0),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {
                "osmid": "ab",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ]
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "far-ncn",
                "feature_type": "ncn-route",
                "name": "NCN 1",
                "category": "National Cycle Network",
                "source_id": "far-ncn",
                "feature_count": 1,
                "network_scope": "rural",
                "geometry": LineString([(1, 1), (1.1, 1)]),
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {
            "places": places,
            "network": network,
            "context": context,
            "boundary": gpd.GeoDataFrame(),
        },
        FakeAgentRuntime(),
    )

    assert len(compiled.strategic_spines) == 1
    assert compiled.spine_access_connections.empty
    assert set(compiled.access_obligations["service_status"]) == {"network-gap"}
    assert len(compiled.gaps[compiled.gaps["network_role"] == "spine-access-gap"]) == 2
    assert compiled.criteria["spine_network"]["first_reachable_access"] == "red"


def test_distant_community_snap_cannot_become_a_served_access_obligation() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "a",
                "name": "A",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0, 0.03),
            },
            {
                "place_id": "b",
                "name": "B",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.1, 0.03),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {
                "osmid": "a1",
                "highway": "primary",
                "ref": "A1",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ]
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "rural-a1",
                "feature_type": "a-road-spine",
                "name": "A1",
                "category": "A-road strategic spine",
                "source_id": "a1",
                "feature_count": 1,
                "network_scope": "rural",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {
            "places": places,
            "network": network,
            "context": context,
            "boundary": gpd.GeoDataFrame(),
        },
        FakeAgentRuntime(),
    )

    assert len(compiled.strategic_spines) == 1
    assert compiled.spine_access_connections.empty
    assert set(compiled.access_obligations["service_status"]) == {"network-gap"}
    assert len(compiled.gaps[compiled.gaps["network_role"] == "spine-access-gap"]) == 2


def test_bounded_off_network_community_uses_a_canonical_attachment_without_inventing_a_path() -> (
    None
):
    community_point = Point(0, 0.005)
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "a",
                "name": "A",
                "kind": "community",
                "place_class": "village",
                "geometry": community_point,
            },
            {
                "place_id": "b",
                "name": "B",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.1, 0.03),
            },
        ],
        crs=4326,
    )
    spine_geometry = LineString([(0, 0), (0.1, 0)])
    network = edges(
        [
            {
                "osmid": "a1",
                "highway": "primary",
                "ref": "A1",
                "geometry": spine_geometry,
            }
        ]
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "rural-a1",
                "feature_type": "a-road-spine",
                "name": "A1",
                "category": "A-road strategic spine",
                "source_id": "a1",
                "feature_count": 1,
                "network_scope": "rural",
                "geometry": spine_geometry,
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {
            "places": places,
            "network": network,
            "context": context,
            "boundary": gpd.GeoDataFrame(),
        },
        FakeAgentRuntime(),
    )

    access = compiled.spine_access_connections.iloc[0]
    assert not access.geometry.intersects(community_point)
    assert 0 < access["community_attachment_distance_m"] < 2000
    assert access["community_attachment_point"].startswith("POINT")
    assert access["spine_attachment_distance_m"] == 0
    assert access["spine_attachment_point"].startswith("POINT")
    assert "canonical graph attachment points" in access["geometry_semantics"]
    assert "not claimed paths" in access["geometry_semantics"]


def test_invalid_network_scope_is_rejected_at_the_compiler_boundary() -> None:
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
                "geometry": Point(0.1, 0),
            },
        ],
        crs=4326,
    )
    network = edges([{"osmid": "a1", "geometry": LineString([(0, 0), (0.1, 0)])}])
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "a1",
                "feature_type": "a-road-spine",
                "source_id": "a1",
                "network_scope": "rurla",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ],
        crs=4326,
    )

    with pytest.raises(ValueError, match="invalid governed network_scope"):
        compile_network(
            config(),
            {
                "places": places,
                "network": network,
                "context": context,
                "boundary": gpd.GeoDataFrame(),
            },
            FakeAgentRuntime(),
        )


def test_urban_a_road_evidence_is_not_promoted_to_a_rural_strategic_spine() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "west",
                "name": "West",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "east",
                "name": "East",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0.01, 0),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {
                "osmid": "a1",
                "highway": "primary",
                "ref": "A1",
                "geometry": LineString([(0, 0), (0.01, 0)]),
            }
        ]
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "urban-a1",
                "feature_type": "a-road-spine",
                "name": "A1",
                "category": "A-road strategic spine",
                "source_id": "a1",
                "feature_count": 1,
                "network_scope": "urban",
                "geometry": LineString([(0, 0), (0.01, 0)]),
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {
            "places": places,
            "network": network,
            "context": context,
            "boundary": gpd.GeoDataFrame(),
        },
        FakeAgentRuntime(),
    )

    assert compiled.strategic_spines.empty


def test_disconnected_rural_evidence_becomes_separately_identified_continuous_spines() -> None:
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
                "geometry": Point(0.3, 0),
            },
        ],
        crs=4326,
    )
    network = edges(
        [
            {
                "osmid": "whole-route",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.3, 0)]),
            }
        ]
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "split-ncn",
                "feature_type": "ncn-route",
                "name": "NCN 1",
                "category": "National Cycle Network",
                "source_id": "split-ncn",
                "feature_count": 2,
                "network_scope": "rural",
                "geometry": MultiLineString([[(0, 0), (0.1, 0)], [(0.2, 0), (0.3, 0)]]),
            }
        ],
        crs=4326,
    )

    compiled = compile_network(
        config(),
        {
            "places": places,
            "network": network,
            "context": context,
            "boundary": gpd.GeoDataFrame(),
        },
        FakeAgentRuntime(),
    )

    assert len(compiled.strategic_spines) == 2
    assert len(set(compiled.strategic_spines["spine_id"])) == 2
    assert set(compiled.strategic_spines.geometry.geom_type) == {"LineString"}
