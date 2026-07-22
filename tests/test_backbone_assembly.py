from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig

PROJECT = Path(__file__).parents[1]


def config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")


def frame(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)


def parallel_spine_source(*, reverse: bool = False) -> dict[str, gpd.GeoDataFrame]:
    places = [
        {
            "place_id": "left-near",
            "name": "Left Near",
            "kind": "community",
            "place_class": "village",
            "geometry": Point(0.02, 0),
        },
        {
            "place_id": "hinterland",
            "name": "Hinterland",
            "kind": "community",
            "place_class": "village",
            "geometry": Point(0.04, 0),
        },
        {
            "place_id": "right-near",
            "name": "Right Near",
            "kind": "community",
            "place_class": "village",
            "geometry": Point(0.08, 0),
        },
    ]
    network = [
        {
            "osmid": "left-spine-edge",
            "highway": "primary",
            "ref": "A1",
            "geometry": LineString([(0, 0), (0, 0.01)]),
        },
        {
            "osmid": "left-feed",
            "highway": "unclassified",
            "geometry": LineString([(0, 0), (0.02, 0)]),
        },
        {
            "osmid": "hinterland-feed",
            "highway": "unclassified",
            "geometry": LineString([(0.02, 0), (0.04, 0)]),
        },
        {
            "osmid": "middle-feed",
            "highway": "unclassified",
            "geometry": LineString([(0.04, 0), (0.08, 0)]),
        },
        {
            "osmid": "right-feed",
            "highway": "unclassified",
            "geometry": LineString([(0.08, 0), (0.1, 0)]),
        },
        {
            "osmid": "right-spine-edge",
            "highway": "primary",
            "ref": "A2",
            "geometry": LineString([(0.1, 0), (0.1, 0.01)]),
        },
    ]
    context = [
        {
            "evidence_id": "left-a1",
            "feature_type": "a-road-spine",
            "name": "A1",
            "category": "A-road strategic spine",
            "source_id": "left-spine-edge",
            "feature_count": 1,
            "network_scope": "rural",
            "geometry": LineString([(0, 0), (0, 0.01)]),
        },
        {
            "evidence_id": "right-a2",
            "feature_type": "a-road-spine",
            "name": "A2",
            "category": "A-road strategic spine",
            "source_id": "right-spine-edge",
            "feature_count": 1,
            "network_scope": "rural",
            "geometry": LineString([(0.1, 0), (0.1, 0.01)]),
        },
    ]
    if reverse:
        places.reverse()
        network.reverse()
        context.reverse()
    return {
        "places": frame(places),
        "network": frame(network),
        "context": frame(context),
        "boundary": gpd.GeoDataFrame(geometry=[], crs=4326),
    }


def topology(compiled: object) -> list[tuple[object, ...]]:
    return sorted(
        (
            row.access_connection_id,
            row.place_id,
            row.root_spine_id,
            row.branch_id,
            row.parent_role,
            row.parent_place_id,
            row.parent_access_connection_id,
            row.geometry.wkb_hex,
        )
        for row in compiled.spine_access_connections.itertuples()
    )


def test_all_spines_seed_order_independent_growth_and_hinterland_chaining() -> None:
    first = compile_network(config(), parallel_spine_source(), FakeAgentRuntime())
    reordered = compile_network(config(), parallel_spine_source(reverse=True), FakeAgentRuntime())

    assert topology(first) == topology(reordered)
    assert len(first.spine_access_connections) == 3
    assert len(first.access_obligations) == 3
    assert set(first.access_obligations["service_status"]) == {"served"}
    assert set(first.spine_access_connections["root_spine_id"]) == set(
        first.strategic_spines["spine_id"]
    )

    by_place = first.spine_access_connections.set_index("place_id")
    chained = by_place.loc["hinterland"]
    assert chained["parent_role"] == "spine-access-connection"
    assert chained["parent_place_id"] == "left-near"
    assert (
        chained["parent_access_connection_id"] == by_place.loc["left-near", "access_connection_id"]
    )
    assert chained["branch_id"] == by_place.loc["left-near", "branch_id"]
    assert chained["attachment_depth"] == 2

    for row in first.spine_access_connections.itertuples():
        provenance = json.loads(row.provenance)
        assert provenance["root_spine_id"] == row.root_spine_id
        assert provenance["branch_id"] == row.branch_id
        assert provenance["source_ids"]
        assert "cycling-network cost" in row.selection_reason

    assert len(first.spine_access_branches) == 2
    assert first.criteria["spine_network"]["all_access_obligations_resolved"] == "green"
    assert first.criteria["spine_network"]["degree_one_access_valid"] == "green"


def test_unreachable_community_becomes_a_gap_without_fabricated_linework() -> None:
    source = parallel_spine_source()
    source["places"] = frame(
        [
            *source["places"].to_dict("records"),
            {
                "place_id": "island",
                "name": "Island",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(1, 1),
            },
        ]
    )
    source["network"] = frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "island-edge",
                "highway": "unclassified",
                "geometry": LineString([(1, 1), (1.01, 1)]),
            },
        ]
    )

    compiled = compile_network(config(), source, FakeAgentRuntime())

    obligation = compiled.access_obligations.set_index("place_id").loc["island"]
    assert obligation["service_status"] == "network-gap"
    gaps = compiled.gaps[compiled.gaps["network_role"] == "spine-access-gap"]
    assert len(gaps) == 1
    gap = gaps.iloc[0]
    assert gap["from_place"] == "island"
    assert gap.geometry.geom_type == "MultiPoint"
    assert len(gap.geometry.geoms) == 1
    assert gap["criterion_continuity"] == "red"
    assert compiled.criteria["spine_network"]["all_access_obligations_resolved"] == "red"


def test_meaningful_cross_boundary_gateway_attaches_to_the_assembled_frontier() -> None:
    source = parallel_spine_source()
    source["places"] = frame(
        [
            *source["places"].to_dict("records"),
            {
                "place_id": "gateway-east",
                "name": "Towards East Town",
                "kind": "cross_boundary_gateway",
                "place_class": "road",
                "geometry": Point(0.09, 0),
            },
        ]
    )
    source["network"] = frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "gateway-link",
                "highway": "unclassified",
                "geometry": LineString([(0.08, 0), (0.09, 0)]),
            },
            {
                "osmid": "gateway-to-spine",
                "highway": "unclassified",
                "geometry": LineString([(0.09, 0), (0.1, 0)]),
            },
        ]
    )

    compiled = compile_network(config(), source, FakeAgentRuntime())

    gateway = compiled.spine_access_connections[
        compiled.spine_access_connections["place_id"] == "gateway-east"
    ].iloc[0]
    assert gateway["place_kind"] == "cross_boundary_gateway"
    assert gateway["network_role"] == "gateway-access-connection"
    assert gateway["root_spine_id"] in set(compiled.strategic_spines["spine_id"])
    assert gateway["parent_role"] in {"strategic-spine", "spine-access-connection"}
    assert "gateway-east" not in set(compiled.access_obligations["place_id"])
    assert compiled.criteria["spine_network"]["gateway_coverage"] == "green"
