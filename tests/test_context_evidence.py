from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.evidence import derive_context_layers, mark_ncn_edges
from satn.routing import RoadGraph, choose_alignment


def test_derives_a_road_ncn_and_quiet_optional_destination_layers() -> None:
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "a37",
                "ref": "A37",
                "highway": "primary",
                "geometry": LineString([(0, 0), (0.02, 0)]),
            }
        ],
        crs=4326,
    )
    ncn = gpd.GeoDataFrame(
        [
            {
                "osmid": "relation-24",
                "network": "ncn",
                "route": "bicycle",
                "ref": "24",
                "geometry": LineString([(0, 0), (0.02, 0)]),
            }
        ],
        crs=4326,
    )
    facilities = gpd.GeoDataFrame(
        [
            {
                "osmid": "school",
                "amenity": "school",
                "name": "Test School",
                "geometry": Point(0.005, 0.001),
            },
            {
                "osmid": "pharmacy",
                "amenity": "pharmacy",
                "name": "Test Pharmacy",
                "geometry": Point(0.006, 0.001),
            },
            {
                "osmid": "shop-1",
                "shop": "bakery",
                "addr:street": "High Street",
                "geometry": Point(0.0100, 0.001),
            },
            {
                "osmid": "shop-2",
                "shop": "convenience",
                "addr:street": "High Street",
                "geometry": Point(0.0104, 0.001),
            },
            {
                "osmid": "shop-3",
                "shop": "books",
                "addr:street": "High Street",
                "geometry": Point(0.0108, 0.001),
            },
        ],
        crs=4326,
    )

    context = derive_context_layers(network, ncn, facilities)

    counts = context.groupby("feature_type").size().to_dict()
    assert counts == {
        "a-road-spine": 1,
        "healthcare": 1,
        "ncn-route": 1,
        "retail-centre": 1,
        "school": 1,
    }
    retail = context[context["feature_type"] == "retail-centre"].iloc[0]
    assert retail["name"] == "High Street retail centre"
    assert retail["feature_count"] == 3


def test_ncn_evidence_informs_alignment_without_overriding_an_a_road_spine() -> None:
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "direct",
                "highway": "unclassified",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            },
            {
                "osmid": "ncn-1",
                "highway": "cycleway",
                "geometry": LineString([(0, 0), (0.05, 0.01)]),
            },
            {
                "osmid": "ncn-2",
                "highway": "cycleway",
                "geometry": LineString([(0.05, 0.01), (0.1, 0)]),
            },
        ],
        crs=4326,
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "ncn",
                "feature_type": "ncn-route",
                "name": "NCN",
                "category": "National Cycle Network",
                "source_id": "ncn",
                "feature_count": 1,
                "geometry": LineString([(0, 0), (0.05, 0.01), (0.1, 0)]),
            }
        ],
        crs=4326,
    )
    graph = RoadGraph(mark_ncn_edges(network, context))

    selected, _, reason = choose_alignment(
        graph,
        graph.nearest_node(Point(0, 0))[0],
        graph.nearest_node(Point(0.1, 0))[0],
    )

    assert selected is not None
    assert selected.role == "ncn-informed"
    assert selected.ncn_share == 1
    assert "National Cycle Network" in reason


def test_ncn_crossing_does_not_mark_a_perpendicular_road_as_ncn() -> None:
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "crossing",
                "highway": "unclassified",
                "geometry": LineString([(0, -0.01), (0, 0.01)]),
            }
        ],
        crs=4326,
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "ncn",
                "feature_type": "ncn-route",
                "name": "NCN",
                "category": "National Cycle Network",
                "source_id": "ncn",
                "feature_count": 1,
                "geometry": LineString([(-0.01, 0), (0.01, 0)]),
            }
        ],
        crs=4326,
    )

    marked = mark_ncn_edges(network, context)

    assert not bool(marked.iloc[0]["satn_ncn"])
