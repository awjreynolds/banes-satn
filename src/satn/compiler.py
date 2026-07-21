"""Community Connection compilation over the governed OSM network."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
from shapely.geometry import MultiPoint

from satn.agents import AgentRuntime
from satn.models import AgentRecord, CouncilConfig, TrafficLight
from satn.routing import RoadGraph, RouteOption, choose_alignment, serialise_options
from satn.urban import derive_urban_structure


@dataclass
class CompiledNetwork:
    places: gpd.GeoDataFrame
    connections: gpd.GeoDataFrame
    gaps: gpd.GeoDataFrame
    urban_spines: gpd.GeoDataFrame
    low_traffic_areas: gpd.GeoDataFrame
    agent_records: list[AgentRecord]
    criteria: dict[str, TrafficLight]


def _connection_id(left: str, right: str) -> str:
    pair = "::".join(sorted((left, right)))
    return f"connection-{hashlib.sha256(pair.encode()).hexdigest()[:12]}"


def compile_network(
    config: CouncilConfig,
    source: dict[str, gpd.GeoDataFrame],
    runtime: AgentRuntime,
) -> CompiledNetwork:
    places = source["places"].copy().sort_values("place_id").reset_index(drop=True)
    communities = places[places["kind"] == "community"].copy()
    if len(communities) < 2:
        raise ValueError("a network requires at least two Communities")
    road_graph = RoadGraph(source["network"])
    attachments = _community_attachments(places, communities, road_graph)
    candidate_pairs = _nearest_neighbour_pairs(communities, road_graph, attachments)
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    records: list[AgentRecord] = []
    connection_columns = [
        "connection_id",
        "from_place",
        "to_place",
        "distance_km",
        "classification",
        "status",
        "selection_reason",
        "alignment_options",
        "criterion_endpoints",
        "criterion_continuity",
        "criterion_bidirectional",
        "criterion_distance",
        "geometry",
    ]
    community_lookup = communities.set_index("place_id", drop=False)
    for left_id, right_id in sorted(candidate_pairs):
        left = community_lookup.loc[left_id]
        right = community_lookup.loc[right_id]
        selected, options, reason, snap_distance = _route_pair(
            road_graph, attachments[left_id], attachments[right_id]
        )
        row, record = _gate_connection(
            config, runtime, left, right, selected, options, reason, snap_distance
        )
        records.append(record)
        (accepted if record.decision == "accept" else rejected).append(row)

    crs = source["network"].crs
    connections = gpd.GeoDataFrame(
        accepted, columns=connection_columns, geometry="geometry", crs=crs
    )
    gaps = gpd.GeoDataFrame(rejected, columns=connection_columns, geometry="geometry", crs=crs)
    urban_spines, low_traffic_areas = derive_urban_structure(places, source["network"])
    connection_graph = nx.Graph(
        (row["from_place"], row["to_place"]) for row in accepted
    )
    connected = len(connection_graph) > 0 and all(
        place_id in connection_graph for place_id in communities["place_id"]
    ) and nx.is_connected(connection_graph)
    criteria = {
        "connections": TrafficLight.RED if rejected else TrafficLight.GREEN,
        "network": TrafficLight.GREEN if connected else TrafficLight.AMBER,
        "atm_comparison": TrafficLight.GREY,
    }
    return CompiledNetwork(
        places,
        connections,
        gaps,
        urban_spines,
        low_traffic_areas,
        records,
        criteria,
    )


def _community_attachments(
    places: gpd.GeoDataFrame,
    communities: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> dict[str, list[tuple[str, float]]]:
    portals = places[places["kind"] == "community_portal"]
    result: dict[str, list[tuple[str, float]]] = {}
    for _, community in communities.iterrows():
        candidates = (
            portals[portals["parent_place_id"] == community.place_id]
            if "parent_place_id" in portals
            else portals
        )
        points = list(candidates.geometry) or [community.geometry]
        result[community.place_id] = [graph.nearest_node(point) for point in points]
    return result


def _nearest_neighbour_pairs(
    communities: gpd.GeoDataFrame,
    graph: RoadGraph,
    attachments: dict[str, list[tuple[str, float]]],
) -> set[tuple[str, str]]:
    identifiers = list(communities["place_id"])
    geometries = communities.set_index("place_id")["geometry"]
    pairs: set[tuple[str, str]] = set()
    for left in identifiers:
        distances: list[tuple[float, str]] = []
        for right in identifiers:
            if left == right:
                continue
            distance = _network_distance(graph, attachments[left], attachments[right])
            distances.append((distance, right))
        reachable = [item for item in distances if item[0] < float("inf")]
        if reachable:
            right = min(reachable)[1]
        else:
            right = min(
                (candidate for candidate in identifiers if candidate != left),
                key=lambda candidate: geometries[left].distance(geometries[candidate]),
            )
        pairs.add(tuple(sorted((left, right))))
    return pairs


def _network_distance(
    graph: RoadGraph,
    starts: list[tuple[str, float]],
    ends: list[tuple[str, float]],
) -> float:
    best = float("inf")
    for start, start_snap in starts:
        for end, end_snap in ends:
            try:
                routed = nx.shortest_path_length(
                    graph.graph, start, end, weight=lambda _u, _v, edge: edge["length_m"]
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            best = min(best, float(routed) + start_snap + end_snap)
    return best


def _route_pair(
    graph: RoadGraph,
    starts: list[tuple[str, float]],
    ends: list[tuple[str, float]],
) -> tuple[RouteOption | None, list[RouteOption], str, float]:
    candidates: list[tuple[RouteOption, list[RouteOption], str, float]] = []
    for start, start_snap in starts:
        for end, end_snap in ends:
            selected, options, reason = choose_alignment(graph, start, end)
            if selected is not None:
                candidates.append((selected, options, reason, start_snap + end_snap))
    if not candidates:
        return None, [], "No continuous OSM cycling-network path exists.", float("inf")
    return min(candidates, key=lambda candidate: candidate[0].length_km + candidate[3] / 1000)


def _gate_connection(
    config: CouncilConfig,
    runtime: AgentRuntime,
    left: object,
    right: object,
    selected: RouteOption | None,
    options: list[RouteOption],
    reason: str,
    snap_distance: float,
) -> tuple[dict[str, object], AgentRecord]:
    connection_id = _connection_id(str(left.place_id), str(right.place_id))
    endpoints_valid = selected is not None and snap_distance <= 2000
    continuous = selected is not None and not selected.geometry.is_empty
    bidirectional = selected is not None and selected.bidirectional
    distance_km = selected.length_km if selected else 0
    checks_passed = endpoints_valid and continuous and bidirectional
    record = runtime.review(
        connection_id,
        {
            "checks_passed": checks_passed,
            "distance_km": round(distance_km, 3),
            "from_place": left.place_id,
            "to_place": right.place_id,
            "selection_reason": reason,
        },
    )
    geometry = selected.geometry if selected else MultiPoint([left.geometry, right.geometry])
    classification = selected.role if selected else "network-gap"
    row = {
        "connection_id": connection_id,
        "from_place": left.place_id,
        "to_place": right.place_id,
        "distance_km": round(distance_km, 3) if selected else None,
        "classification": classification,
        "status": "validated" if record.decision == "accept" else "gap",
        "selection_reason": reason,
        "alignment_options": serialise_options(options),
        "criterion_endpoints": "green" if endpoints_valid else "red",
        "criterion_continuity": "green" if continuous else "red",
        "criterion_bidirectional": "green" if bidirectional else "red",
        "criterion_distance": (
            "grey"
            if selected is None
            else "green"
            if distance_km <= config.compilation.max_connection_km
            else "amber"
        ),
        "geometry": geometry,
    }
    return row, record
