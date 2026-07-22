from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig

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

    assert len(obligations) == 4
    assert obligations.index.is_unique
    assert set(obligations["network_scope"]) == {"urban"}
    assert obligations.loc["direct-community", "service_status"] == "served"
    assert obligations.loc["chained-community", "service_status"] == "served"
    assert obligations.loc["nearby-community", "service_status"] == "served-provisional"
    assert obligations.loc["gap-community", "service_status"] == "network-gap"
    assert obligations["access_connection_id"].isna().all()
    assert set(obligations.geometry.geom_type) == {"Point"}
    assert set(obligations["geometry_semantics"]) == {"area-permeability-no-internal-centreline"}

    chained = json.loads(obligations.loc["chained-community", "provenance"])
    assert len(chained["low_traffic_area_chain"]) == 2
    assert chained["service_via"] == "adjoining-community-area-chain"
    assert chained["urban_spine_id"]

    nearby = json.loads(obligations.loc["nearby-community", "provenance"])
    assert nearby["service_via"] == "nearby-candidate-low-traffic-area"
    assert nearby["attachment_distance_m"] == 25.0
    assert nearby["attachment_maximum_m"] == 2000.0
    assert nearby["low_traffic_area_chain"] == [
        "low-traffic-area-b4c47d281337",
        "low-traffic-area-4ed4d1a80986",
    ]
    assert nearby["urban_spine_id"]

    community_gaps = compiled.gaps[compiled.gaps["network_role"] == "urban-community-access-gap"]
    assert list(community_gaps["from_place"]) == ["gap-community"]
    assert set(community_gaps.geometry.geom_type) == {"MultiPoint"}

    coverage = compiled.compilation_diagnostics["community_coverage"]
    assert coverage == {
        "identified_rural": 0,
        "served_rural": 0,
        "gaps_rural": 0,
        "identified_urban": 4,
        "served_urban": 3,
        "gaps_urban": 1,
        "identified_total": 4,
        "served_total": 3,
        "gaps_total": 1,
    }
    assert compiled.criteria["network"]["rural_community_accounting"] == "green"
    assert compiled.criteria["network"]["urban_community_accounting"] == "green"
    assert compiled.criteria["network"]["community_accounting"] == "green"
