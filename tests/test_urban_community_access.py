from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig
from satn.routing import RoadGraph
from satn.urban_community import (
    SPINE_PORTAL_MAPPING_MAX_M,
    _portal_targets,
    _PortalTarget,
    _routable_portal_attachment,
)

PROJECT = Path(__file__).parents[1]


def _frame(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=27700)


def _config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")


def _urban_source() -> dict[str, gpd.GeoDataFrame]:
    places = _frame(
        [
            {
                "place_id": "direct-community",
                "name": "Direct Community",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(25, 50),
            },
            {
                "place_id": "chained-community",
                "name": "Chained Community",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(125, 50),
            },
            {
                "place_id": "gap-community",
                "name": "Gap Community",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(325, 50),
            },
            {
                "place_id": "nearby-community",
                "name": "Nearby Community",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(225, 50),
            },
            {
                "place_id": "unreachable-nearby-community",
                "name": "Unreachable Nearby Community",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(425, 400),
            },
            {
                "place_id": "community-chain",
                "name": "Community Chain",
                "kind": "community",
                "place_class": "neighbourhood",
                "source_id": "governed-places",
                "geometry": Point(2170, 50),
            },
        ]
    )
    network = _frame(
        [
            {
                "osmid": "direct-west",
                "highway": "residential",
                "geometry": LineString([(0, 50), (50, 50)]),
            },
            {
                "osmid": "direct-east",
                "highway": "residential",
                "geometry": LineString([(50, 50), (100, 50)]),
            },
            {
                "osmid": "chain-west",
                "highway": "living_street",
                "geometry": LineString([(100, 50), (150, 50)]),
            },
            {
                "osmid": "chain-east",
                "highway": "path",
                "geometry": LineString([(150, 50), (200, 50)]),
            },
            {
                "osmid": "gap-west",
                "highway": "residential",
                "geometry": LineString([(300, 50), (350, 50)]),
            },
            {
                "osmid": "gap-east",
                "highway": "path",
                "geometry": LineString([(350, 50), (400, 50)]),
            },
            {
                "osmid": "outer-chain",
                "highway": "residential",
                "geometry": LineString([(200, 50), (2200, 50)]),
            },
        ]
    )
    official = _frame(
        [
            {
                "official_feature_id": "a-road-west",
                "official_classification": "a-road",
                "source_id": "governed-open-roads",
                "effective_date": "2026-07-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "official-road-fixture",
                "geometry": LineString([(0, 0), (0, 100)]),
            }
        ]
    )
    boundaries = [
        ("south-direct-chain", [(0, 0), (200, 0)]),
        ("north-direct-chain", [(0, 100), (200, 100)]),
        ("between-direct-chain", [(100, 0), (100, 100)]),
        ("east-chain", [(200, 0), (200, 100)]),
        ("south-gap", [(300, 0), (400, 0)]),
        ("north-gap", [(300, 100), (400, 100)]),
        ("west-gap", [(300, 0), (300, 100)]),
        ("east-gap", [(400, 0), (400, 100)]),
    ]
    context = _frame(
        [
            {
                "evidence_id": boundary_id,
                "feature_type": "circulation-boundary",
                "name": boundary_id.replace("-", " ").title(),
                "category": "built-up-edge",
                "source_id": "governed-built-up-edge",
                "geometry": LineString(coordinates),
            }
            for boundary_id, coordinates in boundaries
        ]
    )
    return {
        "places": places,
        "network": network,
        "official_road_classification": official,
        "context": context,
        "boundary": gpd.GeoDataFrame(geometry=[], crs=27700),
    }


def test_public_compile_accounts_for_every_urban_community_without_centrelines() -> None:
    compiled = compile_network(_config(), _urban_source(), FakeAgentRuntime())

    obligations = compiled.access_obligations[
        compiled.access_obligations["obligation_kind"] == "community"
    ].set_index("community_id")

    assert len(obligations) == 6
    assert obligations.index.is_unique
    assert set(obligations["network_scope"]) == {"urban"}
    assert obligations.loc["direct-community", "service_status"] == "served"
    assert obligations.loc["chained-community", "service_status"] == "served-provisional"
    assert obligations.loc["nearby-community", "service_status"] == "served-provisional"
    assert obligations.loc["community-chain", "service_status"] == "served-provisional"
    assert obligations.loc["gap-community", "service_status"] == "served-provisional"
    assert obligations.loc["unreachable-nearby-community", "service_status"] == "network-gap"
    assert obligations["access_connection_id"].isna().all()
    assert set(obligations.geometry.geom_type) == {"Point"}
    assert set(obligations["geometry_semantics"]) == {"area-permeability-no-internal-centreline"}

    chained = json.loads(obligations.loc["chained-community", "provenance"])
    assert chained["low_traffic_area_chain"]
    assert chained["service_via"] == "routable-urban-main-road-spine"
    assert chained["urban_spine_id"]

    nearby = json.loads(obligations.loc["nearby-community", "provenance"])
    assert nearby["service_via"] == "adjoining-community-graph-chain"
    assert nearby["target_community_id"] == "chained-community"
    assert 0 <= nearby["attachment_distance_m"] <= 250.0
    assert nearby["attachment_maximum_m"] == 2000.0
    assert nearby["low_traffic_area_chain"]
    assert nearby["urban_spine_id"]
    assert nearby["network_distance_m"] > 0
    assert nearby["portal_association_distance_m"] == 0.0
    assert nearby["portal_mapping_distance_m"] == 0.0
    assert nearby["total_route_cost_m"] <= 2000.0
    assert nearby["route_edge_source_ids"]

    chained_community = json.loads(obligations.loc["community-chain", "provenance"])
    assert chained_community["service_via"] == "adjoining-community-graph-chain"
    assert chained_community["target_community_id"] == "nearby-community"
    assert chained_community["target_community_name"] == "Nearby Community"
    assert chained_community["community_chain"] == ["nearby-community", "chained-community"]
    assert chained_community["portal_id"] == nearby["portal_id"]
    assert chained_community["urban_spine_id"] == nearby["urban_spine_id"]
    assert chained_community["route_edge_source_ids"]
    assert chained_community["total_route_cost_m"] <= 2000.0

    community_gaps = compiled.gaps[compiled.gaps["network_role"] == "urban-community-access-gap"]
    assert list(community_gaps["from_place"]) == ["unreachable-nearby-community"]
    assert set(community_gaps.geometry.geom_type) == {"MultiPoint"}

    coverage = compiled.compilation_diagnostics["community_coverage"]
    assert coverage == {
        "identified_rural": 0,
        "served_rural": 0,
        "gaps_rural": 0,
        "identified_urban": 6,
        "served_urban": 5,
        "gaps_urban": 1,
        "identified_total": 6,
        "served_total": 5,
        "gaps_total": 1,
    }
    assert compiled.criteria["network"]["rural_community_accounting"] == "green"
    assert compiled.criteria["network"]["urban_community_accounting"] == "green"
    assert compiled.criteria["network"]["community_accounting"] == "green"


def test_public_compile_honours_governed_urban_village_source_overrides() -> None:
    source = _urban_source()
    source["places"].loc[source["places"]["place_id"] == "direct-community", "place_class"] = (
        "village"
    )
    source["places"].loc[source["places"]["place_id"] == "direct-community", "source_id"] = (
        "governed-urban-village"
    )
    payload = _config().model_dump(mode="json")
    payload["source"]["urban_place_source_ids"] = ["governed-urban-village"]
    config = CouncilConfig.model_validate(payload)

    compiled = compile_network(config, source, FakeAgentRuntime())
    obligation = compiled.access_obligations[
        compiled.access_obligations["community_id"] == "direct-community"
    ].iloc[0]

    assert obligation["network_scope"] == "urban"
    assert obligation["service_status"] == "served"


def test_public_compile_uses_settlement_form_to_scope_substantial_villages() -> None:
    source = _urban_source()
    direct = source["places"]["place_id"] == "direct-community"
    sparse = source["places"]["place_id"] == "unreachable-nearby-community"
    source["places"].loc[direct, "place_class"] = "village"
    source["places"].loc[sparse, "place_class"] = "village"
    source["places"].loc[sparse, "geometry"] = Point(5000, 5000)
    source["network"] = _frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "direct-north",
                "highway": "residential",
                "geometry": LineString([(50, 50), (50, 150)]),
            },
        ]
    )
    source["context"] = _frame(
        [
            *source["context"].to_dict("records"),
            {
                "evidence_id": "dense-village-school",
                "feature_type": "school",
                "name": "Dense Village School",
                "category": "school",
                "source_id": "dense-village-school",
                "school_kind": "primary",
                "school_obligation_eligible": True,
                "access_point_status": "unresolved",
                "network_scope": "rural",
                "geometry": Point(25, 50),
            },
            {
                "evidence_id": "sparse-village-school",
                "feature_type": "school",
                "name": "Sparse Village School",
                "category": "school",
                "source_id": "sparse-village-school",
                "school_kind": "primary",
                "school_obligation_eligible": True,
                "access_point_status": "unresolved",
                "network_scope": "urban",
                "geometry": Point(5000, 5000),
            },
        ]
    )
    payload = _config().model_dump(mode="json")
    payload["source"]["urban_settlement_form"] = {
        "assessment_radius_km": 0.15,
        "minimum_minor_street_length_km": 0.15,
        "minimum_junction_count": 1,
    }
    config = CouncilConfig.model_validate(payload)

    compiled = compile_network(config, source, FakeAgentRuntime())
    obligations = compiled.access_obligations.set_index("community_id")

    assert obligations.loc["direct-community", "network_scope"] == "urban"
    assert obligations.loc["unreachable-nearby-community", "network_scope"] == "rural"
    schools = compiled.schools.set_index("source_id")
    assert schools.loc["dense-village-school", "network_scope"] == "urban"
    assert schools.loc["sparse-village-school", "network_scope"] == "rural"
    profiles = {
        profile["community_id"]: profile
        for profile in compiled.compilation_diagnostics["urban_settlement_form_profiles"]
    }
    assert profiles["direct-community"]["eligibility_basis"] == "settlement-form"
    assert profiles["direct-community"]["minor_street_length_km"] >= 0.15
    assert profiles["direct-community"]["junction_count"] >= 1
    assert profiles["unreachable-nearby-community"]["eligibility_basis"] == (
        "insufficient-settlement-form"
    )
    assert profiles["unreachable-nearby-community"]["minor_street_component_id"] is None
    assert profiles["unreachable-nearby-community"]["component_association_distance_m"] is None
    assert profiles["unreachable-nearby-community"]["minor_street_length_km"] == 0
    assert profiles["unreachable-nearby-community"]["junction_count"] == 0
    assert (
        "No minor-street component is reachable"
        in profiles["unreachable-nearby-community"]["urban_eligibility_rationale"]
    )


def test_public_compile_ignores_dense_streets_disconnected_from_a_sparse_village() -> None:
    source = _urban_source()
    sparse_id = "unreachable-nearby-community"
    sparse = source["places"]["place_id"] == sparse_id
    source["places"].loc[sparse, "place_class"] = "village"
    source["places"].loc[sparse, "geometry"] = Point(5000, 5000)
    disconnected_dense_cluster = [
        LineString([(5100, 5000), (5050, 5000)]),
        LineString([(5100, 5000), (5150, 5000)]),
        LineString([(5100, 5000), (5100, 4950)]),
        LineString([(5100, 5000), (5100, 5050)]),
    ]
    source["network"] = _frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "sparse-village-stub",
                "highway": "residential",
                "geometry": LineString([(5000, 5000), (5005, 5000)]),
            },
            *[
                {
                    "osmid": f"disconnected-dense-{index}",
                    "highway": "residential",
                    "geometry": geometry,
                }
                for index, geometry in enumerate(disconnected_dense_cluster)
            ],
        ]
    )
    payload = _config().model_dump(mode="json")
    payload["source"]["urban_settlement_form"] = {
        "assessment_radius_km": 0.2,
        "maximum_component_association_m": 20,
        "minimum_minor_street_length_km": 0.15,
        "minimum_junction_count": 1,
    }
    config = CouncilConfig.model_validate(payload)

    compiled = compile_network(config, source, FakeAgentRuntime())
    obligation = compiled.access_obligations[
        compiled.access_obligations["community_id"] == sparse_id
    ].iloc[0]
    profile = next(
        profile
        for profile in compiled.compilation_diagnostics["urban_settlement_form_profiles"]
        if profile["community_id"] == sparse_id
    )

    assert obligation["network_scope"] == "rural"
    assert profile["eligibility_basis"] == "insufficient-settlement-form"
    assert profile["component_association_distance_m"] == 0
    assert profile["minor_street_length_km"] == 0.005
    assert profile["junction_count"] == 0


def test_public_compile_uses_near_equivalent_residential_component_not_service_stub() -> None:
    source = _urban_source()
    village_id = "unreachable-nearby-community"
    village = source["places"]["place_id"] == village_id
    source["places"].loc[village, "place_class"] = "village"
    source["places"].loc[village, "geometry"] = Point(5000, 5000)
    dense_component = [
        LineString([(5061, 5000), (5111, 5000)]),
        LineString([(5061, 5000), (5061, 5050)]),
        LineString([(5061, 5000), (5061, 4950)]),
        LineString([(5061, 5000), (5091, 5040)]),
    ]
    source["network"] = _frame(
        [
            *source["network"].to_dict("records"),
            {
                "osmid": "nearest-service-stub",
                "highway": "service",
                "geometry": LineString([(5000, 5000), (5005, 5000)]),
            },
            {
                "osmid": "nearest-residential-stub",
                "highway": "residential",
                "geometry": LineString([(5054, 5000), (5055, 5000)]),
            },
            *[
                {
                    "osmid": f"dense-residential-{index}",
                    "highway": "residential",
                    "geometry": geometry,
                }
                for index, geometry in enumerate(dense_component)
            ],
        ]
    )
    payload = _config().model_dump(mode="json")
    payload["source"]["urban_settlement_form"] = {
        "assessment_radius_km": 0.2,
        "maximum_component_association_m": 100,
        "component_association_tolerance_m": 10,
        "minimum_minor_street_length_km": 0.15,
        "minimum_junction_count": 1,
    }
    config = CouncilConfig.model_validate(payload)

    compiled = compile_network(config, source, FakeAgentRuntime())
    obligation = compiled.access_obligations[
        compiled.access_obligations["community_id"] == village_id
    ].iloc[0]
    profile = next(
        profile
        for profile in compiled.compilation_diagnostics["urban_settlement_form_profiles"]
        if profile["community_id"] == village_id
    )

    assert obligation["network_scope"] == "urban"
    assert profile["component_association_distance_m"] == 61
    assert profile["minor_street_length_km"] == 0.2
    assert profile["junction_count"] == 1


def test_spine_targets_require_a_bounded_mapping_to_their_rooted_portal() -> None:
    network = _frame(
        [
            {
                "osmid": "long-spine",
                "highway": "primary",
                "geometry": LineString([(0, 0), (5000, 0)]),
            }
        ]
    )
    graph = RoadGraph(network)
    portal = pd.Series(
        {
            "portal_id": "portal-west",
            "area_id": "area-west",
            "boundary_id": "spine-west-east",
            "geometry": Point(0, 0),
        }
    )
    spines = _frame(
        [
            {
                "structure_id": "spine-west-east",
                "geometry": LineString([(0, 0), (5000, 0)]),
            }
        ]
    )

    targets = _portal_targets(graph, {"area-west": [(portal, ("fabric",))]}, spines)

    assert targets
    assert max(target.portal_mapping_distance_m for target in targets) <= (
        SPINE_PORTAL_MAPPING_MAX_M
    )
    assert all(graph.node_points[target.node_id].x < 5000 for target in targets)


def test_routable_spine_attachment_accepts_an_edge_interior_start() -> None:
    network = _frame(
        [
            {
                "osmid": "long-bidirectional-edge",
                "highway": "residential",
                "geometry": LineString([(0, 0), (1000, 0)]),
            }
        ]
    )
    graph = RoadGraph(network)
    assert graph.nodes_near(Point(500, 0), 250.0) == []
    target_node, _ = graph.nodes_on_geometry(Point(0, 0), tolerance_m=1.0)[0]
    portal = pd.Series(
        {
            "portal_id": "portal-west",
            "area_id": "area-west",
            "boundary_id": "spine-west",
            "geometry": Point(0, 0),
        }
    )
    target = _PortalTarget(
        node_id=target_node,
        association_m=0.0,
        portal=portal,
        fabric_source_ids=("fabric",),
        portal_mapping_distance_m=0.0,
    )

    routed = _routable_portal_attachment(
        pd.Series({"geometry": Point(500, 0)}),
        graph,
        [target],
        attachment_maximum_m=2000.0,
    )

    assert routed is not None
    route, selected = routed
    assert selected.portal["portal_id"] == "portal-west"
    assert route.start_snap_m == 0.0
    assert route.option.edge_ids
    assert route.option.bidirectional
