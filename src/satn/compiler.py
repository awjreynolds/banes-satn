"""Community Connection compilation over the governed OSM network."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import MultiPoint

from satn.agents import AgentRuntime, CompilationGate
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
    crossing_warnings: gpd.GeoDataFrame
    agent_records: list[AgentRecord]
    criteria: dict[str, dict[str, TrafficLight]]
    network_units: list[dict[str, object]]


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
    gateways = places[places["kind"] == "cross_boundary_gateway"].copy()
    participants = gpd.GeoDataFrame(
        pd.concat([communities, gateways], ignore_index=True),
        geometry="geometry",
        crs=places.crs,
    )
    road_graph = RoadGraph(source["network"])
    gate = CompilationGate(runtime, config.compilation.agent)
    attachments = _network_place_attachments(places, participants, road_graph)
    candidate_pairs = _nearest_neighbour_pairs(communities, road_graph, attachments)
    candidate_pairs.update(
        _gateway_pairs(gateways, communities, road_graph, attachments)
    )
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
        "agent_outcome",
        "agent_attempt_count",
        "alignment_options",
        "criterion_endpoints",
        "criterion_continuity",
        "criterion_bidirectional",
        "criterion_distance",
        "geometry",
    ]
    place_lookup = participants.set_index("place_id", drop=False)
    attempted_pairs: set[tuple[str, str]] = set()

    def compile_pair(pair: tuple[str, str]) -> bool:
        if pair in attempted_pairs:
            return False
        attempted_pairs.add(pair)
        left_id, right_id = pair
        left = place_lookup.loc[left_id]
        right = place_lookup.loc[right_id]
        selected, options, reason, snap_distance = _route_pair(
            road_graph, attachments[left_id], attachments[right_id]
        )
        row, record = _gate_connection(
            config, gate, left, right, selected, options, reason, snap_distance
        )
        records.append(record)
        (accepted if record.decision == "accept" else rejected).append(row)
        return record.decision == "accept"

    for left_id, right_id in sorted(candidate_pairs):
        compile_pair((left_id, right_id))

    _repair_components(
        participants,
        road_graph,
        attachments,
        attempted_pairs,
        accepted,
        compile_pair,
    )
    _repair_internal_termini(
        communities,
        participants,
        road_graph,
        attachments,
        attempted_pairs,
        accepted,
        compile_pair,
    )

    crs = source["network"].crs
    connections = gpd.GeoDataFrame(
        accepted, columns=connection_columns, geometry="geometry", crs=crs
    )
    gaps = gpd.GeoDataFrame(rejected, columns=connection_columns, geometry="geometry", crs=crs)
    urban_spines, low_traffic_areas = derive_urban_structure(places, source["network"])
    crossing_warnings = _crossing_warnings(connections)
    connection_graph = _connection_graph(participants, accepted)
    covered = all(place_id in connection_graph for place_id in communities["place_id"])
    connected = bool(connection_graph) and covered and nx.is_connected(connection_graph)
    internal_termini = [
        place_id
        for place_id in communities["place_id"]
        if connection_graph.degree(place_id) == 1
    ]
    if len(communities) <= 2:
        internal_termini = []
    pairs = [tuple(sorted((row["from_place"], row["to_place"]))) for row in accepted]
    network_units = _network_units(connection_graph, accepted)
    criteria = {
        "connections": {
            "mandatory_checks": TrafficLight.RED if rejected else TrafficLight.GREEN,
            "distance_challenges": (
                TrafficLight.AMBER
                if "amber" in set(connections.get("criterion_distance", []))
                else TrafficLight.GREEN
            ),
        },
        "network": {
            "community_coverage": (
                TrafficLight.GREEN
                if covered
                else TrafficLight.RED
            ),
            "connected_graph": TrafficLight.GREEN if connected else TrafficLight.RED,
            "unique_pairs": (
                TrafficLight.GREEN if len(pairs) == len(set(pairs)) else TrafficLight.RED
            ),
            "internal_termini": (
                TrafficLight.GREEN if not internal_termini else TrafficLight.RED
            ),
        },
        "atm_comparison": {"compared": TrafficLight.GREY},
    }
    return CompiledNetwork(
        places,
        connections,
        gaps,
        urban_spines,
        low_traffic_areas,
        crossing_warnings,
        records,
        criteria,
        network_units,
    )


def _network_place_attachments(
    places: gpd.GeoDataFrame,
    participants: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> dict[str, list[tuple[str, float]]]:
    portals = places[places["kind"] == "community_portal"]
    result: dict[str, list[tuple[str, float]]] = {}
    for _, place in participants.iterrows():
        candidates = (
            portals[portals["parent_place_id"] == place.place_id]
            if "parent_place_id" in portals
            else portals
        )
        points = list(candidates.geometry) or [place.geometry]
        result[place.place_id] = [graph.nearest_node(point) for point in points]
    return result


def _gateway_pairs(
    gateways: gpd.GeoDataFrame,
    communities: gpd.GeoDataFrame,
    graph: RoadGraph,
    attachments: dict[str, list[tuple[str, float]]],
) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for gateway_id in gateways["place_id"]:
        candidates = [
            (
                _network_distance(
                    graph, attachments[gateway_id], attachments[community_id]
                ),
                community_id,
            )
            for community_id in communities["place_id"]
        ]
        reachable = [candidate for candidate in candidates if candidate[0] < float("inf")]
        if reachable:
            pairs.add(tuple(sorted((gateway_id, min(reachable)[1]))))
    return pairs


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
    return graph.network_distance(starts, ends)


def _repair_components(
    participants: gpd.GeoDataFrame,
    graph: RoadGraph,
    attachments: dict[str, list[tuple[str, float]]],
    attempted: set[tuple[str, str]],
    accepted: list[dict[str, object]],
    compile_pair: Callable[[tuple[str, str]], bool],
) -> None:
    identifiers = list(participants["place_id"])
    maximum_pairs = len(identifiers) * (len(identifiers) - 1) // 2
    while len(attempted) < maximum_pairs:
        assembled = _connection_graph(participants, accepted)
        components = list(nx.connected_components(assembled))
        if len(components) <= 1:
            return
        candidates: list[tuple[float, tuple[str, str]]] = []
        for left_component, right_component in combinations(components, 2):
            for left in left_component:
                for right in right_component:
                    pair = tuple(sorted((left, right)))
                    if pair in attempted:
                        continue
                    distance = _network_distance(graph, attachments[left], attachments[right])
                    if distance < float("inf"):
                        candidates.append((distance, pair))
        if not candidates:
            geometry = participants.set_index("place_id")["geometry"]
            unresolved = [
                (geometry[left].distance(geometry[right]), tuple(sorted((left, right))))
                for left_component, right_component in combinations(components, 2)
                for left in left_component
                for right in right_component
                if tuple(sorted((left, right))) not in attempted
            ]
            if unresolved:
                compile_pair(min(unresolved)[1])
            return
        compile_pair(min(candidates)[1])


def _repair_internal_termini(
    communities: gpd.GeoDataFrame,
    participants: gpd.GeoDataFrame,
    graph: RoadGraph,
    attachments: dict[str, list[tuple[str, float]]],
    attempted: set[tuple[str, str]],
    accepted: list[dict[str, object]],
    compile_pair: Callable[[tuple[str, str]], bool],
) -> None:
    if len(communities) <= 2:
        return
    participant_ids = list(participants["place_id"])
    maximum_pairs = len(participant_ids) * (len(participant_ids) - 1) // 2
    while len(attempted) < maximum_pairs:
        assembled = _connection_graph(participants, accepted)
        termini = sorted(
            place_id
            for place_id in communities["place_id"]
            if assembled.degree(place_id) == 1
        )
        if not termini:
            return
        candidates: list[tuple[float, tuple[str, str]]] = []
        for terminus in termini:
            for neighbour in participant_ids:
                if terminus == neighbour:
                    continue
                pair = tuple(sorted((terminus, neighbour)))
                if pair in attempted:
                    continue
                distance = _network_distance(
                    graph, attachments[terminus], attachments[neighbour]
                )
                if distance < float("inf"):
                    candidates.append((distance, pair))
        if not candidates:
            return
        compile_pair(min(candidates)[1])


def _connection_graph(
    participants: gpd.GeoDataFrame,
    accepted: list[dict[str, object]],
) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(participants["place_id"])
    graph.add_edges_from((row["from_place"], row["to_place"]) for row in accepted)
    return graph


def _network_units(
    graph: nx.Graph,
    accepted: list[dict[str, object]],
) -> list[dict[str, object]]:
    units: list[dict[str, object]] = []
    for place_ids in sorted(nx.connected_components(graph), key=lambda values: sorted(values)):
        members = sorted(place_ids)
        connections = sorted(
            row["connection_id"]
            for row in accepted
            if row["from_place"] in place_ids and row["to_place"] in place_ids
        )
        digest = hashlib.sha256("::".join(members).encode()).hexdigest()[:10]
        units.append(
            {
                "unit_id": f"network-unit-{digest}",
                "place_ids": members,
                "connection_ids": connections,
            }
        )
    return units


def _crossing_warnings(connections: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = ["warning_id", "connection_a", "connection_b", "status", "message", "geometry"]
    rows: list[dict[str, object]] = []
    for (_, left), (_, right) in combinations(connections.iterrows(), 2):
        if not left.geometry.crosses(right.geometry):
            continue
        intersection = left.geometry.intersection(right.geometry)
        points = list(intersection.geoms) if hasattr(intersection, "geoms") else [intersection]
        for point in points:
            if point.geom_type != "Point":
                continue
            pair = "::".join(sorted((left.connection_id, right.connection_id)))
            digest = hashlib.sha256(f"{pair}:{point.wkt}".encode()).hexdigest()[:10]
            rows.append(
                {
                    "warning_id": f"crossing-{digest}",
                    "connection_a": left.connection_id,
                    "connection_b": right.connection_id,
                    "status": "amber",
                    "message": "Routes cross without a declared shared Junction Node.",
                    "geometry": point,
                }
            )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=connections.crs)


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
    gate: CompilationGate,
    left: object,
    right: object,
    selected: RouteOption | None,
    options: list[RouteOption],
    reason: str,
    snap_distance: float,
) -> tuple[dict[str, object], AgentRecord]:
    connection_id = _connection_id(str(left.place_id), str(right.place_id))
    checks_by_role = {
        option.role: _option_checks(config, option, snap_distance) for option in options
    }
    outcome = gate.evaluate(
        connection_id=connection_id,
        facts={
            "from_place": left.place_id,
            "to_place": right.place_id,
            "selection_reason": reason,
            "evidence_ids": option_evidence_ids(options),
            "checks_by_role": checks_by_role,
        },
        initial_role=selected.role if selected else None,
        available_roles=[option.role for option in options],
    )
    record = outcome.record
    gated_selection = next(
        (option for option in options if option.role == outcome.selected_role), None
    )
    if record.decision == "accept" and gated_selection is None:
        record.decision = "gap"
        record.outcome_reason = "Compilation Gate accepted no available alignment."
    selected = gated_selection if record.decision == "accept" else selected
    endpoints_valid = selected is not None and snap_distance <= 2000
    continuous = selected is not None and not selected.geometry.is_empty
    bidirectional = selected is not None and selected.bidirectional
    distance_km = selected.length_km if selected else 0
    geometry = selected.geometry if selected else MultiPoint([left.geometry, right.geometry])
    classification = selected.role if selected else "network-gap"
    row = {
        "connection_id": connection_id,
        "from_place": left.place_id,
        "to_place": right.place_id,
        "distance_km": round(distance_km, 3) if selected else None,
        "classification": classification,
        "status": "validated" if record.decision == "accept" else "gap",
        "selection_reason": (
            reason
            if selected is None or selected.role == (outcome.selected_role or selected.role)
            else f"Compilation Gate revised the alignment to {outcome.selected_role}."
        ),
        "agent_outcome": record.outcome_reason,
        "agent_attempt_count": len(record.attempts),
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


def _option_checks(
    config: CouncilConfig,
    option: RouteOption,
    snap_distance: float,
) -> dict[str, str]:
    return {
        "endpoints": "green" if snap_distance <= 2000 else "red",
        "continuity": "green" if not option.geometry.is_empty else "red",
        "bidirectional": "green" if option.bidirectional else "red",
        "distance": (
            "green"
            if option.length_km <= config.compilation.max_connection_km
            else "amber"
        ),
    }


def option_evidence_ids(options: list[RouteOption]) -> list[str]:
    return sorted({edge_id for option in options for edge_id in option.edge_ids})
