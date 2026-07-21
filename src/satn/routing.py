"""OSM network graph construction and alignment option routing."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, unary_union

LOW_TRAFFIC = {
    "living_street",
    "residential",
    "unclassified",
    "service",
    "track",
    "path",
    "cycleway",
}
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary"}


@dataclass
class RouteOption:
    role: str
    geometry: LineString
    length_km: float
    edge_ids: list[str]
    a_road_share: float
    bidirectional: bool
    impracticable_alongside: bool

    def summary(self) -> dict[str, object]:
        return {
            "role": self.role,
            "length_km": round(self.length_km, 3),
            "a_road_share": round(self.a_road_share, 3),
            "bidirectional": self.bidirectional,
            "impracticable_alongside": self.impracticable_alongside,
        }


class RoadGraph:
    def __init__(self, edges: gpd.GeoDataFrame):
        self.crs = edges.crs
        self.graph = nx.DiGraph()
        self.node_points: dict[str, Point] = {}
        self._shortest_lengths: dict[str, dict[str, float]] = {}
        for index, row in edges.iterrows():
            geometry = row.geometry
            if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
                continue
            u = str(row.get("u")) if _present(row.get("u")) else _coordinate_id(geometry.coords[0])
            v = str(row.get("v")) if _present(row.get("v")) else _coordinate_id(geometry.coords[-1])
            self.node_points.setdefault(u, Point(geometry.coords[0]))
            self.node_points.setdefault(v, Point(geometry.coords[-1]))
            source_length = row.get("length")
            if _present(source_length):
                length_m = float(source_length)
            else:
                projected = gpd.GeoSeries([geometry], crs=edges.crs).to_crs(27700)
                length_m = float(projected.length.iloc[0])
            attrs = {
                "edge_id": str(row.get("osmid", row.get("source_id", index))),
                "geometry": geometry,
                "length_m": length_m,
                "highway": _tag_values(row.get("highway")),
                "ref": _tag_values(row.get("ref")),
                "oneway": _truthy(row.get("oneway")),
                "alongside": str(row.get("satn_alongside", "possible")),
            }
            self._add_best_edge(u, v, attrs)
            if not _present(row.get("u")) and not attrs["oneway"]:
                reverse = attrs | {"geometry": LineString(list(geometry.coords)[::-1])}
                self._add_best_edge(v, u, reverse)
        self._node_ids = list(self.node_points)
        strong_components = sorted(
            nx.strongly_connected_components(self.graph), key=len, reverse=True
        )
        dominant = strong_components[0] if strong_components else set()
        routable_share = len(dominant) / len(self.graph) if self.graph else 0
        if routable_share >= 0.9:
            self._node_ids = [node for node in self._node_ids if node in dominant]
        self._projected_nodes = gpd.GeoSeries(
            [self.node_points[node] for node in self._node_ids], crs=self.crs
        ).to_crs(27700)

    def _add_best_edge(self, u: str, v: str, attrs: dict[str, object]) -> None:
        existing = self.graph.get_edge_data(u, v)
        if existing is None or float(attrs["length_m"]) < float(existing["length_m"]):
            self.graph.add_edge(u, v, **attrs)

    def nearest_node(self, point: Point) -> tuple[str, float]:
        if not self.node_points:
            raise ValueError("source network has no routable LineString edges")
        target = gpd.GeoSeries([point], crs=self.crs).to_crs(27700).iloc[0]
        distances = self._projected_nodes.distance(target)
        position = int(distances.argmin())
        return self._node_ids[position], float(distances.iloc[position])

    def network_distance(
        self,
        starts: list[tuple[str, float]],
        ends: list[tuple[str, float]],
    ) -> float:
        best = float("inf")
        for start, start_snap in starts:
            if start not in self._shortest_lengths:
                self._shortest_lengths[start] = nx.single_source_dijkstra_path_length(
                    self.graph, start, weight="length_m"
                )
            lengths = self._shortest_lengths[start]
            for end, end_snap in ends:
                if end in lengths:
                    best = min(best, float(lengths[end]) + start_snap + end_snap)
        return best

    def option(self, start: str, end: str, role: str) -> RouteOption | None:
        weight = _weight_for(role)
        try:
            nodes = nx.shortest_path(self.graph, start, end, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        edge_data = [self.graph[a][b] for a, b in pairwise(nodes)]
        if not edge_data:
            return None
        geometry = _merge_route([edge["geometry"] for edge in edge_data])
        length_m = sum(float(edge["length_m"]) for edge in edge_data)
        a_length = sum(
            float(edge["length_m"]) for edge in edge_data if _is_a_road(edge["ref"])
        )
        reverse_exists = nx.has_path(self.graph, end, start)
        return RouteOption(
            role=role,
            geometry=geometry,
            length_km=length_m / 1000,
            edge_ids=[str(edge["edge_id"]) for edge in edge_data],
            a_road_share=a_length / length_m if length_m else 0,
            bidirectional=reverse_exists,
            impracticable_alongside=any(
                edge["alongside"] == "impracticable" and _is_a_road(edge["ref"])
                for edge in edge_data
            ),
        )


def choose_alignment(
    graph: RoadGraph,
    start: str,
    end: str,
) -> tuple[RouteOption | None, list[RouteOption], str]:
    direct = graph.option(start, end, "direct")
    if direct is None:
        return None, [], "No continuous OSM cycling-network path exists."
    strategic = graph.option(start, end, "strategic-spine")
    quiet = graph.option(start, end, "low-traffic")
    options = _unique_options([direct, strategic, quiet])

    if strategic and strategic.a_road_share > 0 and strategic.length_km <= direct.length_km * 1.5:
        if strategic.impracticable_alongside:
            fallback = quiet if quiet and quiet.length_km <= direct.length_km * 1.5 else direct
            return (
                fallback,
                options,
                "Parallel fallback selected because alongside A-road provision is marked "
                "physically impracticable.",
            )
        return (
            strategic,
            options,
            "A-road Strategic Spine selected for directness and social oversight.",
        )
    if quiet and quiet.length_km <= direct.length_km * 1.35:
        return (
            quiet,
            options,
            "Low-traffic OSM alignment selected within the directness challenge margin.",
        )
    return direct, options, "Most direct continuous OSM alignment selected."


def serialise_options(options: list[RouteOption]) -> str:
    return json.dumps([option.summary() for option in options], sort_keys=True)


def _weight_for(role: str) -> Callable[[str, str, dict[str, object]], float]:
    def weight(_u: str, _v: str, edge: dict[str, object]) -> float:
        length = float(edge["length_m"])
        is_a = _is_a_road(edge["ref"])
        highway = set(edge["highway"])
        if role == "strategic-spine":
            return length * (0.35 if is_a else 1.6)
        if role == "low-traffic":
            return length * (0.75 if highway & LOW_TRAFFIC else 4.0)
        return length

    return weight


def _merge_route(lines: list[LineString]) -> LineString:
    unioned = unary_union(lines)
    if isinstance(unioned, LineString):
        return unioned
    merged = linemerge(unioned)
    if isinstance(merged, LineString):
        return merged
    longest = max(merged.geoms, key=lambda geometry: geometry.length)
    return LineString(longest.coords)


def _unique_options(options: list[RouteOption | None]) -> list[RouteOption]:
    result: list[RouteOption] = []
    signatures: set[tuple[str, ...]] = set()
    for option in options:
        if option is None:
            continue
        signature = (option.role, *option.edge_ids)
        if signature not in signatures:
            result.append(option)
            signatures.add(signature)
    return result


def _is_a_road(refs: object) -> bool:
    return any(str(ref).upper().startswith("A") for ref in refs)


def _tag_values(value: object) -> list[str]:
    if not _present(value):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (SyntaxError, ValueError):
            pass
    return [str(value)]


def _truthy(value: object) -> bool:
    return str(value).lower() in {"yes", "true", "1", "-1"}


def _present(value: object) -> bool:
    return value is not None and str(value).lower() not in {"nan", "none", ""}


def _coordinate_id(coordinate: tuple[float, ...]) -> str:
    return f"xy:{coordinate[0]:.7f}:{coordinate[1]:.7f}"
