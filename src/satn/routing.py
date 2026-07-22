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
    ncn_share: float
    bidirectional: bool
    reverse_length_km: float | None
    reverse_edge_ids: list[str]
    reverse_corridor_share: float
    impracticable_alongside: bool

    def summary(self) -> dict[str, object]:
        return {
            "role": self.role,
            "length_km": round(self.length_km, 3),
            "a_road_share": round(self.a_road_share, 3),
            "ncn_share": round(self.ncn_share, 3),
            "bidirectional": self.bidirectional,
            "reverse_length_km": (
                round(self.reverse_length_km, 3) if self.reverse_length_km is not None else None
            ),
            "reverse_edge_ids": self.reverse_edge_ids,
            "reverse_corridor_share": round(self.reverse_corridor_share, 3),
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
                "ncn": _truthy(row.get("satn_ncn")),
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
        self._projected_node_index = self._projected_nodes.sindex

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

    def nodes_on_geometry(
        self,
        geometry: object,
        *,
        tolerance_m: float = 20,
    ) -> list[tuple[str, float]]:
        """Return routable graph nodes evidenced on a corridor, never an unbounded snap."""
        if geometry is None or geometry.is_empty or not self._node_ids:
            return []
        target = gpd.GeoSeries([geometry], crs=self.crs).to_crs(27700).iloc[0]
        positions = self._projected_node_index.query(
            target.buffer(tolerance_m), predicate="intersects"
        )
        matches = [
            (
                self._node_ids[int(position)],
                float(self._projected_nodes.iloc[int(position)].distance(target)),
            )
            for position in positions
        ]
        return sorted(
            (match for match in matches if match[1] <= tolerance_m),
            key=lambda match: (match[1], match[0]),
        )

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
        if geometry is None:
            return None
        length_m = sum(float(edge["length_m"]) for edge in edge_data)
        a_length = sum(float(edge["length_m"]) for edge in edge_data if _is_a_road(edge["ref"]))
        ncn_length = sum(float(edge["length_m"]) for edge in edge_data if edge["ncn"])
        try:
            reverse_nodes = nx.shortest_path(self.graph, end, start, weight=weight)
            reverse_edges = [self.graph[left][right] for left, right in pairwise(reverse_nodes)]
            reverse_geometry = _merge_route([edge["geometry"] for edge in reverse_edges])
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            reverse_edges = []
            reverse_geometry = None
        reverse_corridor_share = (
            min(
                _corridor_share(reverse_geometry, geometry, self.crs),
                _corridor_share(geometry, reverse_geometry, self.crs),
            )
            if reverse_geometry is not None
            else 0.0
        )
        reverse_exists = reverse_corridor_share >= 0.5
        reverse_length_m = (
            sum(float(edge["length_m"]) for edge in reverse_edges)
            if reverse_geometry is not None
            else None
        )
        return RouteOption(
            role=role,
            geometry=geometry,
            length_km=length_m / 1000,
            edge_ids=[str(edge["edge_id"]) for edge in edge_data],
            a_road_share=a_length / length_m if length_m else 0,
            ncn_share=ncn_length / length_m if length_m else 0,
            bidirectional=reverse_exists,
            reverse_length_km=(reverse_length_m / 1000 if reverse_length_m is not None else None),
            reverse_edge_ids=[str(edge["edge_id"]) for edge in reverse_edges],
            reverse_corridor_share=reverse_corridor_share,
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
    ncn = graph.option(start, end, "ncn-informed")
    quiet = graph.option(start, end, "low-traffic")
    options = _unique_options([direct, strategic, ncn, quiet])

    if (
        strategic
        and strategic.a_road_share >= 0.8
        and strategic.length_km <= direct.length_km * 1.5
    ):
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
    if ncn and ncn.ncn_share > 0 and ncn.length_km <= direct.length_km * 1.35:
        return (
            ncn,
            options,
            "National Cycle Network evidence informed the selected continuous alignment.",
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
        if role == "ncn-informed":
            return length * (0.4 if edge["ncn"] else 1.3)
        return length

    return weight


def _merge_route(lines: list[LineString]) -> LineString | None:
    unioned = unary_union(lines)
    if isinstance(unioned, LineString):
        return unioned
    merged = linemerge(unioned)
    if isinstance(merged, LineString):
        return merged
    return None


def _corridor_share(route: LineString, corridor: LineString, crs: object) -> float:
    projected = gpd.GeoSeries([route, corridor], crs=crs).to_crs(3857)
    route_geometry, corridor_geometry = projected.iloc[0], projected.iloc[1]
    if not route_geometry.length:
        return 0.0
    return route_geometry.intersection(corridor_geometry.buffer(250)).length / route_geometry.length


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
