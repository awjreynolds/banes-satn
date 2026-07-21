"""Urban main-road skeleton and Candidate Low-Traffic Area derivation."""

from __future__ import annotations

import hashlib

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import unary_union

from satn.routing import LOW_TRAFFIC, MAIN_ROADS, _tag_values


def derive_urban_structure(
    places: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    columns = ["structure_id", "role", "intervention", "geometry"]
    place_class = places.get("place_class")
    if place_class is None:
        place_class = [""] * len(places)
    urban = places[
        (places["kind"] == "community")
        & pd.Series(place_class, index=places.index).isin(["suburb", "quarter", "neighbourhood"])
    ]
    if urban.empty or network.empty:
        return (
            gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=network.crs),
            gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=network.crs),
        )
    projected_network = network.to_crs(27700).copy()
    urban_zone = urban.to_crs(27700).geometry.buffer(2000).union_all()
    projected_network = projected_network[projected_network.intersects(urban_zone)].copy()
    highway = projected_network.get("highway")
    if highway is None:
        highway = [""] * len(projected_network)
    projected_network["_classes"] = [_tag_values(value) for value in highway]

    main_mask = (
        projected_network["_classes"]
        .map(lambda values: bool(set(values) & MAIN_ROADS))
        .astype(bool)
    )
    main = projected_network.loc[main_mask].copy()
    spine_rows = [
        {
            "structure_id": _geometry_id("urban-spine", geometry),
            "role": "urban-main-road-spine",
            "intervention": "protected-cycle-infrastructure",
            "geometry": geometry,
        }
        for geometry in main.geometry
        if isinstance(geometry, LineString)
    ]

    minor_mask = (
        projected_network["_classes"]
        .map(lambda values: bool(set(values) & LOW_TRAFFIC))
        .astype(bool)
    )
    minor = projected_network.loc[minor_mask].copy()
    area_rows = _minor_road_areas(minor, main)
    spines = gpd.GeoDataFrame(spine_rows, columns=columns, geometry="geometry", crs=27700)
    areas = gpd.GeoDataFrame(area_rows, columns=columns, geometry="geometry", crs=27700)
    return spines.to_crs(network.crs), areas.to_crs(network.crs)


def _minor_road_areas(
    minor: gpd.GeoDataFrame,
    main: gpd.GeoDataFrame,
) -> list[dict[str, object]]:
    if not main.empty:
        main_road_barrier = unary_union(main.geometry.tolist()).buffer(20)
        minor["geometry"] = minor.geometry.map(
            lambda geometry: geometry.difference(main_road_barrier)
        )
        minor = minor.explode(index_parts=False).loc[
            lambda frame: frame.geometry.map(lambda geometry: isinstance(geometry, LineString))
        ]
    graph = nx.Graph()
    geometries: dict[tuple[str, str], LineString] = {}
    for _, row in minor.iterrows():
        geometry = row.geometry
        if not isinstance(geometry, LineString):
            continue
        start = _coordinate(geometry.coords[0])
        end = _coordinate(geometry.coords[-1])
        graph.add_edge(start, end)
        geometries[(start, end)] = geometry
    rows: list[dict[str, object]] = []
    for component in nx.connected_components(graph):
        component_lines = [
            geometry
            for (start, end), geometry in geometries.items()
            if start in component and end in component
        ]
        if len(component_lines) < 2:
            continue
        area = unary_union(component_lines).buffer(18, cap_style="square", join_style="mitre")
        rows.append(
            {
                "structure_id": _geometry_id("low-traffic-area", area),
                "role": "candidate-low-traffic-area",
                "intervention": "candidate-ltn",
                "geometry": area,
            }
        )
    return rows


def _coordinate(value: tuple[float, ...]) -> str:
    return f"{value[0]:.3f}:{value[1]:.3f}"


def _geometry_id(prefix: str, geometry: object) -> str:
    return f"{prefix}-{hashlib.sha256(geometry.wkb).hexdigest()[:10]}"
