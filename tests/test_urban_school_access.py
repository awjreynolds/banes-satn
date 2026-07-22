from __future__ import annotations

import json

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

from satn.urban_school import assess_urban_school_access


def frame(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=27700)


def test_urban_school_service_uses_area_permeability_without_a_centreline() -> None:
    schools = frame(
        [
            {
                "place_id": "mapped-school",
                "evidence_id": "mapped-school",
                "source_id": "school-site-1",
                "name": "Mapped School",
                "school_kind": "primary",
                "access_point_status": "mapped",
                "access_point_source_id": "entrance-1",
                "access_point_rationale": "Mapped main entrance.",
                "geometry": Point(10, 50),
            },
            {
                "place_id": "inferred-school",
                "evidence_id": "inferred-school",
                "source_id": "school-site-2",
                "name": "Inferred School",
                "school_kind": "secondary",
                "access_point_status": "inferred",
                "access_point_source_id": None,
                "access_point_rationale": "Inferred boundary intersection.",
                "geometry": Point(30, 50),
            },
        ]
    )
    network = frame(
        [
            {
                "osmid": "quiet-1",
                "highway": "residential",
                "geometry": LineString([(0, 50), (50, 50)]),
            },
            {
                "osmid": "quiet-2",
                "highway": "path",
                "geometry": LineString([(50, 50), (100, 50)]),
            },
        ]
    )
    areas = frame(
        [
            {
                "structure_id": "area-1",
                "name": "Candidate Low-Traffic Area one",
                "geometry": Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            }
        ]
    )
    portals = frame(
        [
            {
                "portal_id": "portal-main-road",
                "area_id": "area-1",
                "name": "Area one portal to A road",
                "boundary_id": "urban-spine-1",
                "boundary_name": "A road",
                "boundary_kind": "urban-main-road-spine",
                "geometry": Point(100, 50),
            }
        ]
    )

    assessed = assess_urban_school_access(schools, network, areas, portals)

    assert list(assessed["service_status"]) == ["served-provisional", "served"]
    assert set(assessed["geometry_semantics"]) == {
        "area-permeability-no-internal-centreline"
    }
    assert set(assessed.geometry.geom_type) == {"Point"}
    assert set(assessed["low_traffic_area_id"]) == {"area-1"}
    assert set(assessed["portal_id"]) == {"portal-main-road"}
    assert all(
        json.loads(value) == ["quiet-1", "quiet-2"]
        for value in assessed["fabric_source_ids"]
    )
    assert set(assessed["criterion_continuity"]) == {"green"}
    assert all(value is None for value in assessed["finding"])


def test_unresolved_or_discontinuous_urban_school_access_is_a_visible_finding() -> None:
    schools = frame(
        [
            {
                "place_id": "disconnected-school",
                "evidence_id": "disconnected-school",
                "source_id": "school-site-3",
                "name": "Disconnected School",
                "school_kind": "primary",
                "access_point_status": "mapped",
                "access_point_source_id": "entrance-3",
                "access_point_rationale": "Mapped entrance.",
                "geometry": Point(10, 69),
            },
            {
                "place_id": "unresolved-school",
                "evidence_id": "unresolved-school",
                "source_id": "school-site-4",
                "name": "Unresolved School",
                "school_kind": "special",
                "access_point_status": "unresolved",
                "access_point_source_id": None,
                "access_point_rationale": "No usable entrance evidence.",
                "geometry": Point(10, 50),
            },
        ]
    )
    network = frame(
        [
            {
                "osmid": "quiet-1",
                "highway": "residential",
                "geometry": LineString([(0, 50), (100, 50)]),
            }
        ]
    )
    areas = frame(
        [
            {
                "structure_id": "area-1",
                "name": "Candidate Low-Traffic Area one",
                "geometry": Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            }
        ]
    )
    portals = frame(
        [
            {
                "portal_id": "portal-main-road",
                "area_id": "area-1",
                "name": "Area one portal to A road",
                "boundary_id": "urban-spine-1",
                "boundary_name": "A road",
                "boundary_kind": "urban-main-road-spine",
                "geometry": Point(100, 50),
            }
        ]
    )

    assessed = assess_urban_school_access(schools, network, areas, portals).set_index(
        "school_id"
    )

    disconnected = assessed.loc["disconnected-school"]
    assert disconnected["service_status"] == "network-gap"
    assert disconnected["criterion_continuity"] == "red"
    assert disconnected["finding"] == "discontinuous-access-fabric"
    assert disconnected["portal_id"] == "portal-main-road"
    assert json.loads(disconnected["fabric_source_ids"]) == ["quiet-1"]
    unresolved = assessed.loc["unresolved-school"]
    assert unresolved["service_status"] == "network-gap"
    assert unresolved["criterion_access_point"] == "grey"
    assert unresolved["criterion_continuity"] == "grey"
    assert unresolved["finding"] == "unresolved-school-access-point"


def test_non_main_road_boundary_portal_does_not_serve_an_urban_school() -> None:
    schools = frame(
        [
            {
                "place_id": "mapped-school",
                "evidence_id": "mapped-school",
                "source_id": "school-site-1",
                "name": "Mapped School",
                "school_kind": "primary",
                "access_point_status": "mapped",
                "access_point_source_id": "entrance-1",
                "access_point_rationale": "Mapped entrance.",
                "geometry": Point(10, 50),
            }
        ]
    )
    network = frame(
        [
            {
                "osmid": "quiet-1",
                "highway": "residential",
                "geometry": LineString([(0, 50), (100, 50)]),
            }
        ]
    )
    areas = frame(
        [
            {
                "structure_id": "area-1",
                "name": "Candidate Low-Traffic Area one",
                "geometry": Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
            }
        ]
    )
    portals = frame(
        [
            {
                "portal_id": "portal-railway",
                "area_id": "area-1",
                "name": "Area one portal to railway",
                "boundary_id": "railway-1",
                "boundary_name": "Railway",
                "boundary_kind": "railway",
                "geometry": Point(100, 50),
            }
        ]
    )

    assessment = assess_urban_school_access(schools, network, areas, portals).iloc[0]

    assert assessment["service_status"] == "network-gap"
    assert assessment["finding"] == "no-urban-main-road-portal"
    assert assessment["portal_id"] is None
