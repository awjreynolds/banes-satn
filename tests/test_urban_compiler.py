# ruff: noqa: E501

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
            {"osmid": "main", "highway": "primary", "geometry": LineString([(0, -0.02), (0, 0.02)])},
            {"osmid": "minor-west", "highway": "residential", "geometry": LineString([(-0.015, 0), (0, 0)])},
            {"osmid": "minor-east", "highway": "unclassified", "geometry": LineString([(0, 0), (0.015, 0)])},
        ],
        crs=4326,
    )

    spines, areas = derive_urban_structure(places, network)

    assert len(spines) == 1
    assert set(spines["role"]) == {"urban-main-road-spine"}
    assert set(spines["intervention"]) == {"protected-cycle-infrastructure"}
    assert len(areas) == 1
    assert set(areas["role"]) == {"candidate-low-traffic-area"}
    assert areas.iloc[0].geometry.geom_type in {"Polygon", "MultiPolygon"}
    assert areas.to_crs(27700).iloc[0].geometry.intersects(
        spines.to_crs(27700).iloc[0].geometry
    )


def test_multi_portal_communities_use_the_nearest_connected_portals() -> None:
    places = gpd.GeoDataFrame(
        [
            {"place_id": "west", "name": "West", "kind": "community", "place_class": "neighbourhood", "parent_place_id": None, "geometry": Point(-0.05, 0)},
            {"place_id": "west-outer", "name": "West outer", "kind": "community_portal", "place_class": "neighbourhood", "parent_place_id": "west", "geometry": Point(-0.04, 0)},
            {"place_id": "west-inner", "name": "West inner", "kind": "community_portal", "place_class": "neighbourhood", "parent_place_id": "west", "geometry": Point(0, 0)},
            {"place_id": "east", "name": "East", "kind": "community", "place_class": "neighbourhood", "parent_place_id": None, "geometry": Point(0.15, 0)},
            {"place_id": "east-inner", "name": "East inner", "kind": "community_portal", "place_class": "neighbourhood", "parent_place_id": "east", "geometry": Point(0.1, 0)},
            {"place_id": "east-outer", "name": "East outer", "kind": "community_portal", "place_class": "neighbourhood", "parent_place_id": "east", "geometry": Point(0.14, 0)},
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [{"osmid": "urban-link", "highway": "residential", "geometry": LineString([(0, 0), (0.1, 0)])}],
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
    coordinates = list(compiled.connections.iloc[0].geometry.coords)
    assert {coordinates[0], coordinates[-1]} == {(0.0, 0.0), (0.1, 0.0)}
