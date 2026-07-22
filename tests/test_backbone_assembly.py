from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

import satn.backbone as backbone_module
from satn.agents import AgentRole, FakeAgentRuntime
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
    access_ids = set(first.spine_access_connections["access_connection_id"])
    assert access_ids <= {record.connection_id for record in first.agent_records}
    assert first.criteria["spine_network"]["all_access_obligations_resolved"] == "green"
    assert first.criteria["spine_network"]["degree_one_access_valid"] == "green"


def test_reachable_attachment_can_bypass_a_nearer_disconnected_fragment() -> None:
    source = parallel_spine_source()
    source["places"] = frame(
        [
            *source["places"].to_dict("records"),
            {
                "place_id": "near-island",
                "name": "Near Island",
                "kind": "community",
                "place_class": "village",
                "geometry": Point(0.05, 0.001),
            },
        ]
    )
    source["network"] = frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "near-island-fragment",
                "highway": "unclassified",
                "geometry": LineString([(0.05, 0.001), (0.051, 0.001)]),
            },
        ]
    )

    compiled = compile_network(config(), source, FakeAgentRuntime())

    obligation = compiled.access_obligations.set_index("place_id").loc["near-island"]
    assert obligation["service_status"] == "served"
    access = compiled.spine_access_connections.set_index("place_id").loc["near-island"]
    assert access["community_attachment_node"] != "xy:0.0500000:0.0010000"


def test_equidistant_attachment_tie_is_stable_when_source_rows_reverse() -> None:
    places = [
        {
            "place_id": "tie",
            "name": "Tie",
            "kind": "community",
            "place_class": "village",
            "geometry": Point(0, 0),
        },
        {
            "place_id": "left-anchor",
            "name": "Left Anchor",
            "kind": "community",
            "place_class": "village",
            "geometry": Point(-0.01, 0),
        },
    ]
    network = [
        {
            "osmid": "left",
            "highway": "primary",
            "ref": "A1",
            "geometry": LineString([(-0.01, 0), (-0.001, 0)]),
        },
        {
            "osmid": "right",
            "highway": "primary",
            "ref": "A2",
            "geometry": LineString([(0.001, 0), (0.01, 0)]),
        },
    ]
    context = [
        {
            "evidence_id": "left-spine",
            "feature_type": "a-road-spine",
            "name": "A1",
            "category": "A-road strategic spine",
            "source_id": "left",
            "feature_count": 1,
            "network_scope": "rural",
            "geometry": network[0]["geometry"],
        },
        {
            "evidence_id": "right-spine",
            "feature_type": "a-road-spine",
            "name": "A2",
            "category": "A-road strategic spine",
            "source_id": "right",
            "feature_count": 1,
            "network_scope": "rural",
            "geometry": network[1]["geometry"],
        },
    ]

    def compile_rows(reverse: bool) -> object:
        return compile_network(
            config(),
            {
                "places": frame(list(reversed(places)) if reverse else places),
                "network": frame(list(reversed(network)) if reverse else network),
                "context": frame(list(reversed(context)) if reverse else context),
                "boundary": gpd.GeoDataFrame(geometry=[], crs=4326),
            },
            FakeAgentRuntime(),
        )

    assert topology(compile_rows(False)) == topology(compile_rows(True))


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


def test_agent_gate_rejection_cannot_enter_validated_backbone_state() -> None:
    rejected = {
        "decision": "gap",
        "selected_role": None,
        "rationale": "Evidence review rejected this candidate.",
    }
    runtime = FakeAgentRuntime(
        {AgentRole.SYNTHESISER: [rejected.copy() for _ in range(6)]}
    )

    compiled = compile_network(config(), parallel_spine_source(), runtime)

    assert compiled.spine_access_connections.empty
    assert set(compiled.access_obligations["service_status"]) == {"network-gap"}
    access_records = [
        record
        for record in compiled.agent_records
        if record.connection_id.startswith("spine-access-")
    ]
    assert len(access_records) == 6
    assert {record.decision for record in access_records} == {"gap"}


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
    branch_place_ids = {
        place_id
        for value in compiled.spine_access_branches["place_ids"]
        for place_id in json.loads(value)
    }
    assert "gateway-east" not in branch_place_ids
    assert compiled.criteria["spine_network"]["gateway_coverage"] == "green"


def test_colocated_gateway_is_already_connected_without_zero_length_linework() -> None:
    source = parallel_spine_source()
    source["places"] = frame(
        [
            *source["places"].to_dict("records"),
            {
                "place_id": "gateway-colocated",
                "name": "Towards Nearby Town",
                "kind": "cross_boundary_gateway",
                "place_class": "road",
                "geometry": Point(0.08, 0),
            },
        ]
    )

    compiled = compile_network(config(), source, FakeAgentRuntime())

    gateway_rows = compiled.spine_access_connections[
        compiled.spine_access_connections["place_id"] == "gateway-colocated"
    ]
    assert gateway_rows.empty
    assert compiled.criteria["spine_network"]["gateway_coverage"] == "green"


def test_growth_evaluates_each_new_frontier_once_at_representative_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    community_count = 24
    places = [
        {
            "place_id": f"community-{index:02d}",
            "name": f"Community {index:02d}",
            "kind": "community",
            "place_class": "village",
            "geometry": Point((index + 1) * 3000, 0),
        }
        for index in range(community_count)
    ]
    network = [
        {
            "osmid": f"edge-{index:02d}",
            "highway": "primary" if index == 0 else "unclassified",
            "ref": "A1" if index == 0 else None,
            "geometry": LineString([(index * 3000, 0), ((index + 1) * 3000, 0)]),
        }
        for index in range(community_count)
    ]
    context = [
        {
            "evidence_id": "scale-spine",
            "feature_type": "a-road-spine",
            "name": "A1",
            "category": "A-road strategic spine",
            "source_id": "edge-00",
            "feature_count": 1,
            "network_scope": "rural",
            "geometry": network[0]["geometry"],
        }
    ]
    calls = 0
    original = backbone_module._candidate

    def counted_candidate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(backbone_module, "_candidate", counted_candidate)
    compiled = compile_network(
        config(),
        {
            "places": gpd.GeoDataFrame(places, geometry="geometry", crs=27700),
            "network": gpd.GeoDataFrame(network, geometry="geometry", crs=27700),
            "context": gpd.GeoDataFrame(context, geometry="geometry", crs=27700),
            "boundary": gpd.GeoDataFrame(geometry=[], crs=27700),
        },
        FakeAgentRuntime(),
    )

    assert len(compiled.spine_access_connections) == community_count
    assert calls == community_count + community_count * (community_count - 1) // 2
