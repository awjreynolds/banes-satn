
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig
from satn.urban import derive_urban_structure


def test_urban_spines_and_low_traffic_fabrics_share_one_representation() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "neighbourhood",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "portal-west",
                "name": "West portal",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "urban-centre",
                "geometry": Point(-0.01, 0),
            },
            {
                "place_id": "portal-east",
                "name": "East portal",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "urban-centre",
                "geometry": Point(0.01, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "main",
                "highway": "primary",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            },
            {
                "osmid": "minor-west",
                "highway": "residential",
                "geometry": LineString([(-0.015, 0), (0, 0)]),
            },
            {
                "osmid": "minor-west-2",
                "highway": "residential",
                "geometry": LineString([(-0.015, 0), (-0.015, 0.01)]),
            },
            {
                "osmid": "minor-east",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.015, 0)]),
            },
            {
                "osmid": "minor-east-2",
                "highway": "residential",
                "geometry": LineString([(0.015, 0), (0.015, 0.01)]),
            },
        ],
        crs=4326,
    )
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": "official-a",
                "official_classification": "a-road",
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "Open Government Licence v3.0",
                "content_fingerprint": "abc123",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            }
        ],
        crs=4326,
    )

    spines, unknowns, areas = derive_urban_structure(places, network, official)

    assert len(spines) == 1
    assert set(spines["role"]) == {"urban-main-road-spine"}
    assert set(spines["intervention"]) == {"protected-cycle-infrastructure"}
    assert set(spines["official_classification"]) == {"a-road"}
    assert set(spines["classification_status"]) == {"governed-official"}
    assert unknowns.empty
    assert "Major engineering" in spines.iloc[0]["intervention_assumption"]
    assert len(areas) == 2
    assert set(areas["role"]) == {"candidate-low-traffic-area"}
    assert areas.iloc[0].geometry.geom_type in {"Polygon", "MultiPolygon"}
    projected_spine = spines.to_crs(27700).iloc[0].geometry
    assert all(
        not geometry.intersects(projected_spine) for geometry in areas.to_crs(27700).geometry
    )


def test_osm_tags_do_not_override_missing_or_unclassified_official_evidence() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "osm-primary",
                "highway": "primary",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            }
        ],
        crs=4326,
    )
    unclassified = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": "official-u",
                "official_classification": "unclassified",
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "abc123",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            }
        ],
        crs=4326,
    )

    missing_spines, missing_unknowns, _ = derive_urban_structure(places, network)
    unclassified_spines, unclassified_unknowns, _ = derive_urban_structure(
        places, network, unclassified
    )

    assert missing_spines.empty
    assert missing_unknowns.empty
    assert unclassified_spines.empty
    assert unclassified_unknowns.empty

    unknown = unclassified.copy()
    unknown["official_classification"] = "unknown"
    _, unknowns, _ = derive_urban_structure(places, network, unknown)
    assert len(unknowns) == 1
    assert unknowns.iloc[0]["classification_status"] == "explicit-unknown"
    assert unknowns.iloc[0]["role"] == "urban-road-classification-unknown"


def test_official_a_b_and_classified_unnumbered_are_stable_urban_spines() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "minor",
                "highway": "residential",
                "geometry": LineString([(-0.02, 0), (0.02, 0)]),
            }
        ],
        crs=4326,
    )
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": f"official-{classification}",
                "official_classification": classification,
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "abc123",
                "geometry": LineString([(offset, -0.01), (offset, 0.01)]),
            }
            for classification, offset in (
                ("a-road", -0.005),
                ("b-road", 0.0),
                ("classified-unnumbered", 0.005),
            )
        ],
        crs=4326,
    )

    first, first_unknowns, _ = derive_urban_structure(places, network, official)
    second, second_unknowns, _ = derive_urban_structure(places, network, official)

    assert set(first["official_classification"]) == {
        "a-road",
        "b-road",
        "classified-unnumbered",
    }
    assert list(first["structure_id"]) == list(second["structure_id"])
    assert set(first["source_id"]) == {"council-highways"}
    assert first_unknowns.empty
    assert second_unknowns.empty


def test_multi_portal_communities_use_the_nearest_connected_portals() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "west",
                "name": "West",
                "kind": "community",
                "place_class": "neighbourhood",
                "parent_place_id": None,
                "geometry": Point(-0.05, 0),
            },
            {
                "place_id": "west-outer",
                "name": "West outer",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "west",
                "geometry": Point(-0.04, 0),
            },
            {
                "place_id": "west-inner",
                "name": "West inner",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "west",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "east",
                "name": "East",
                "kind": "community",
                "place_class": "neighbourhood",
                "parent_place_id": None,
                "geometry": Point(0.15, 0),
            },
            {
                "place_id": "east-inner",
                "name": "East inner",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "east",
                "geometry": Point(0.1, 0),
            },
            {
                "place_id": "east-outer",
                "name": "East outer",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "east",
                "geometry": Point(0.14, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "urban-link",
                "highway": "residential",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ],
        crs=4326,
    )
    config = CouncilConfig.from_yaml(
        Path(__file__).parents[1] / "examples" / "fixture" / "council.yaml"
    )

    compiled = compile_network(
        config,
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    assert len(compiled.connections) == 1
    assert compiled.urban_spines.empty
    assert compiled.urban_classification_unknowns.empty
    assert compiled.urban_classification_status == "explicit-unknown"
    assert compiled.criteria["urban_network"]["official_road_classification"] == "grey"
    coordinates = list(compiled.connections.iloc[0].geometry.coords)
    assert {coordinates[0], coordinates[-1]} == {(0.0, 0.0), (0.1, 0.0)}
