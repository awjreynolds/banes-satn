from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from satn.evidence import derive_context_layers, govern_network_scope, mark_ncn_edges
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
            },
            {
                "osmid": "relation-local",
                "network": "rcn",
                "route": "bicycle",
                "ref": "Local 4",
                "geometry": LineString([(0, 0.01), (0.02, 0.01)]),
            },
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
    assert list(context.loc[context["feature_type"] == "ncn-route", "source_id"]) == ["relation-24"]
    assert set(
        context.loc[
            context["feature_type"].isin(["a-road-spine", "ncn-route"]),
            "network_scope",
        ]
    ) == {"unresolved"}


def test_governed_urban_extent_splits_strategic_evidence_into_typed_parts() -> None:
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "a1",
                "ref": "A1",
                "geometry": LineString([(-0.02, 0), (0.02, 0)]),
            }
        ],
        crs=4326,
    )
    urban_places = gpd.GeoDataFrame([{"place": "town", "geometry": Point(0, 0)}], crs=4326)

    context = govern_network_scope(
        derive_context_layers(network),
        urban_places,
        urban_place_types=["town"],
        urban_scope_buffer_km=0.5,
    )

    assert context.groupby("network_scope").size().to_dict() == {"rural": 2, "urban": 1}
    assert context["evidence_id"].is_unique
    assert set(context.geometry.geom_type) == {"LineString"}


def test_only_stable_non_road_edges_become_circulation_boundary_evidence() -> None:
    network = gpd.GeoDataFrame(
        [{"osmid": "street", "geometry": LineString([(0, 0), (0.02, 0)])}],
        crs=4326,
    )
    boundary_features = gpd.GeoDataFrame(
        [
            {
                "osmid": "river-1",
                "waterway": "river",
                "name": "River Test",
                "geometry": LineString([(0, -0.01), (0, 0.01)]),
            },
            {
                "osmid": "canal-1",
                "waterway": "canal",
                "name": "Test Canal",
                "geometry": LineString([(0.01, -0.01), (0.01, 0.01)]),
            },
            {
                "osmid": "rail-1",
                "railway": "rail",
                "name": "Main line",
                "geometry": LineString([(0.02, -0.01), (0.02, 0.01)]),
            },
            {
                "osmid": "ward-1",
                "boundary": "administrative",
                "geometry": LineString([(0.03, -0.01), (0.03, 0.01)]),
            },
            {
                "osmid": "field-1",
                "landuse": "farmland",
                "geometry": Polygon([(0.05, -0.01), (0.06, -0.01), (0.06, 0.01), (0.05, 0.01)]),
            },
            {
                "osmid": "built-1",
                "landuse": "residential",
                "geometry": Polygon([(0.06, -0.01), (0.07, -0.01), (0.07, 0.01), (0.06, 0.01)]),
            },
            {
                "osmid": "subway-1",
                "railway": "subway",
                "tunnel": "yes",
                "geometry": LineString([(0.08, -0.01), (0.08, 0.01)]),
            },
            {
                "osmid": "short-river",
                "waterway": "river",
                "geometry": LineString([(0.09, 0), (0.0905, 0)]),
            },
        ],
        crs=4326,
    )

    context = derive_context_layers(network, circulation_boundaries=boundary_features)
    boundaries = context[context["feature_type"] == "circulation-boundary"]

    assert set(boundaries["category"]) == {
        "built-up-edge",
        "river",
        "canal",
        "railway",
    }
    assert set(boundaries["source_id"]) == {
        "built-1",
        "river-1",
        "canal-1",
        "rail-1",
    }


def test_built_up_edge_id_ignores_unrelated_built_up_polygons() -> None:
    network = gpd.GeoDataFrame(
        [{"osmid": "street", "geometry": LineString([(0, 0), (0.02, 0)])}],
        crs=4326,
    )
    shared = [
        {
            "osmid": "open-land",
            "landuse": "farmland",
            "geometry": Polygon([(0, -0.01), (0.01, -0.01), (0.01, 0.01), (0, 0.01)]),
        },
        {
            "osmid": "built-local",
            "landuse": "residential",
            "geometry": Polygon([(0.01, -0.01), (0.02, -0.01), (0.02, 0.01), (0.01, 0.01)]),
        },
    ]
    unrelated = {
        "osmid": "built-unrelated",
        "landuse": "residential",
        "geometry": Polygon([(0.1, -0.01), (0.11, -0.01), (0.11, 0.01), (0.1, 0.01)]),
    }

    before = derive_context_layers(
        network,
        circulation_boundaries=gpd.GeoDataFrame(shared, crs=4326),
    )
    after = derive_context_layers(
        network,
        circulation_boundaries=gpd.GeoDataFrame([*shared, unrelated], crs=4326),
    )

    before_edges = before[before["category"] == "built-up-edge"]
    after_edges = after[after["category"] == "built-up-edge"]
    assert list(before_edges["evidence_id"]) == list(after_edges["evidence_id"])
    assert set(after_edges["source_id"]) == {"built-local"}


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
