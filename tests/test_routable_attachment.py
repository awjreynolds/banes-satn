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
