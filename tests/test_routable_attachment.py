from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.routing import RoadGraph


def test_dominant_routable_component_avoids_nearby_isolated_fragment() -> None:
    rows = []
    for index in range(20):
        rows.append(
            {
                "osmid": f"main-{index}",
                "highway": "unclassified",
                "geometry": LineString([(index * 0.01, 0), ((index + 1) * 0.01, 0)]),
            }
        )
    rows.append(
        {
            "osmid": "isolated",
            "highway": "path",
            "geometry": LineString([(0.05, 0.001), (0.051, 0.001)]),
        }
    )
    graph = RoadGraph(gpd.GeoDataFrame(rows, geometry="geometry", crs=4326))

    node, _ = graph.nearest_node(Point(0.05, 0.001))

    assert node not in {
        "xy:0.0500000:0.0010000",
        "xy:0.0510000:0.0010000",
    }


def test_nearest_node_breaks_exact_distance_ties_by_stable_node_id() -> None:
    rows = [
        {
            "osmid": "left",
            "highway": "unclassified",
            "geometry": LineString([(-2, 0), (-1, 0)]),
        },
        {
            "osmid": "right",
            "highway": "unclassified",
            "geometry": LineString([(1, 0), (2, 0)]),
        },
    ]
    forward = RoadGraph(gpd.GeoDataFrame(rows, geometry="geometry", crs=27700))
    reverse = RoadGraph(gpd.GeoDataFrame(list(reversed(rows)), geometry="geometry", crs=27700))

    assert forward.nearest_node(Point(0, 0)) == reverse.nearest_node(Point(0, 0))
