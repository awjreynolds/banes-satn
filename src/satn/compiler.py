"""Community Connection compilation over the governed OSM network."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, MultiLineString, MultiPoint
from shapely.ops import linemerge, unary_union

from satn.agents import AgentRuntime, CompilationGate
from satn.atm import choose_seeded_alignment
from satn.cache import ConnectionCache
from satn.evidence import empty_context, mark_ncn_edges
from satn.models import (
    AgentRecord,
    CouncilConfig,
    DivergenceRecord,
    NetworkScope,
    TrafficLight,
)
from satn.routing import RoadGraph, RouteOption, choose_alignment, serialise_options
from satn.urban import derive_urban_structure


@dataclass
class CompiledNetwork:
    boundary: gpd.GeoDataFrame
    road_context: gpd.GeoDataFrame
    label_places: gpd.GeoDataFrame
    places: gpd.GeoDataFrame
    connections: gpd.GeoDataFrame
    gaps: gpd.GeoDataFrame
    urban_spines: gpd.GeoDataFrame
    low_traffic_areas: gpd.GeoDataFrame
    crossing_warnings: gpd.GeoDataFrame
    strategic_spines: gpd.GeoDataFrame
    access_obligations: gpd.GeoDataFrame
    spine_access_connections: gpd.GeoDataFrame
    a_road_spines: gpd.GeoDataFrame
    ncn_routes: gpd.GeoDataFrame
    schools: gpd.GeoDataFrame
    retail_centres: gpd.GeoDataFrame
    healthcare: gpd.GeoDataFrame
    agent_records: list[AgentRecord]
    criteria: dict[str, dict[str, TrafficLight]]
    network_units: list[dict[str, object]]
    atm_reference: gpd.GeoDataFrame | None
    divergence_records: list[DivergenceRecord]
    cache_hits: int
    cache_misses: int
    superseded_hypotheses: int

    @property
    def status(self) -> str:
        has_red = any(
            status == TrafficLight.RED
            for section in self.criteria.values()
            for status in section.values()
        )
        return "complete" if self.gaps.empty and not has_red else "reviewable"


def _connection_id(left: str, right: str) -> str:
    pair = "::".join(sorted((left, right)))
    return f"connection-{hashlib.sha256(pair.encode()).hexdigest()[:12]}"


def compile_network(
    config: CouncilConfig,
    source: dict[str, gpd.GeoDataFrame],
    runtime: AgentRuntime,
    *,
    cache: ConnectionCache | None = None,
    atm_seed: gpd.GeoDataFrame | None = None,
) -> CompiledNetwork:
    places = source["places"].copy().sort_values("place_id").reset_index(drop=True)
    context = source.get("context", empty_context(source["network"].crs)).copy()
    communities = places[places["kind"] == "community"].copy()
    if len(communities) < 2:
        raise ValueError("a network requires at least two Communities")
    gateways = places[places["kind"] == "cross_boundary_gateway"].copy()
    participants = gpd.GeoDataFrame(
        pd.concat([communities, gateways], ignore_index=True),
        geometry="geometry",
        crs=places.crs,
    )
    routable_network = mark_ncn_edges(source["network"], context)
    road_graph = RoadGraph(routable_network)
    gate = CompilationGate(runtime, config.compilation.agent)
    attachments = _network_place_attachments(places, participants, road_graph)
    strategic_spines = _strategic_spines(context)
    spine_access_connections = _first_spine_access_connection(
        communities, strategic_spines, road_graph
    )
    access_obligations = _access_obligations(communities, spine_access_connections)
    candidate_pairs = _local_adjacency_pairs(communities, road_graph, attachments)
    candidate_pairs.update(_gateway_pairs(gateways, communities, road_graph, attachments))
    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    records: list[AgentRecord] = []
    connection_columns = [
        "connection_id",
        "from_place",
        "to_place",
        "from_place_name",
        "to_place_name",
        "distance_km",
        "classification",
        "intervention_archetype",
        "geometry_semantics",
        "status",
        "selection_reason",
        "agent_outcome",
        "agent_attempt_count",
        "agent_findings",
        "source_ids",
        "cache_status",
        "alignment_options",
        "criterion_endpoints",
        "criterion_continuity",
        "criterion_bidirectional",
        "criterion_distance",
        "geometry",
    ]
    place_lookup = participants.set_index("place_id", drop=False)
    attempted_pairs: set[tuple[str, str]] = set()
    cache_hits = 0
    cache_misses = 0

    def compile_pair(pair: tuple[str, str]) -> bool:
        nonlocal cache_hits, cache_misses
        if pair in attempted_pairs:
            return False
        attempted_pairs.add(pair)
        cached = cache.load(pair) if cache is not None else None
        if cached is not None:
            row, record = cached
            accepted.append(row)
            records.append(record)
            cache_hits += 1
            return True
        cache_misses += 1
        left_id, right_id = pair
        left = place_lookup.loc[left_id]
        right = place_lookup.loc[right_id]
        selected, options, reason, snap_distance = _route_pair(
            road_graph, attachments[left_id], attachments[right_id]
        )
        if atm_seed is not None:
            seeded = choose_seeded_alignment(options, atm_seed, left.geometry, right.geometry)
            if seeded is not None:
                selected = seeded
                reason = (
                    "ATM-seeded starting hypothesis selected the closest available OSM "
                    f"alignment role: {seeded.role}."
                )
        row, record = _gate_connection(
            config, gate, left, right, selected, options, reason, snap_distance
        )
        records.append(record)
        (accepted if record.decision == "accept" else rejected).append(row)
        if cache is not None:
            cache.store(pair, row, record)
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
    urban_spines, low_traffic_areas = derive_urban_structure(places, source["network"])
    crossing_warnings = _crossing_warnings(connections)
    connection_graph = _connection_graph(participants, accepted)
    covered = all(place_id in connection_graph for place_id in communities["place_id"])
    connected = bool(connection_graph) and covered and nx.is_connected(connection_graph)
    internal_termini = [
        place_id for place_id in communities["place_id"] if connection_graph.degree(place_id) == 1
    ]
    if len(communities) <= 2:
        internal_termini = []
    unresolved = _unresolved_rejections(
        connection_graph,
        rejected,
        set(communities["place_id"]),
        set(internal_termini),
    )
    gaps = gpd.GeoDataFrame(unresolved, columns=connection_columns, geometry="geometry", crs=crs)
    unresolved_ids = {str(row["connection_id"]) for row in unresolved}
    superseded = [row for row in rejected if str(row["connection_id"]) not in unresolved_ids]
    record_by_id = {record.connection_id: record for record in records}
    for row in superseded:
        row["status"] = "superseded"
        row["agent_outcome"] = "Rejected hypothesis superseded by the complete assembled network."
        record = record_by_id[str(row["connection_id"])]
        record.decision = "superseded"
        record.outcome_reason = str(row["agent_outcome"])
    pairs = [tuple(sorted((row["from_place"], row["to_place"]))) for row in accepted]
    network_units = _network_units(connection_graph, accepted)
    criteria = {
        "connections": {
            "mandatory_checks": TrafficLight.RED if unresolved else TrafficLight.GREEN,
            "distance_challenges": (
                TrafficLight.AMBER
                if "amber" in set(connections.get("criterion_distance", []))
                else TrafficLight.GREEN
            ),
        },
        "network": {
            "community_coverage": (TrafficLight.GREEN if covered else TrafficLight.RED),
            "connected_graph": TrafficLight.GREEN if connected else TrafficLight.RED,
            "unique_pairs": (
                TrafficLight.GREEN if len(pairs) == len(set(pairs)) else TrafficLight.RED
            ),
            "internal_termini": (TrafficLight.GREEN if not internal_termini else TrafficLight.RED),
            "intervention_coverage": (
                TrafficLight.GREEN
                if not connections.empty and connections["intervention_archetype"].notna().all()
                else TrafficLight.RED
            ),
        },
        "spine_network": {
            "governed_spine_evidence": (
                TrafficLight.GREEN if not strategic_spines.empty else TrafficLight.GREY
            ),
            "first_reachable_access": (
                TrafficLight.GREEN
                if not spine_access_connections.empty
                else TrafficLight.RED
                if not strategic_spines.empty
                else TrafficLight.GREY
            ),
            "a_road_intervention_assumptions": (
                TrafficLight.GREEN
                if _a_road_assumptions_complete(strategic_spines)
                else TrafficLight.RED
                if "a-road" in set(strategic_spines.get("spine_kind", []))
                else TrafficLight.GREY
            ),
        },
        "atm_comparison": {"compared": TrafficLight.GREY},
    }
    return CompiledNetwork(
        boundary=source["boundary"].copy(),
        road_context=source["network"].copy(),
        label_places=source.get("label_places", places).copy(),
        places=places,
        connections=connections,
        gaps=gaps,
        urban_spines=urban_spines,
        low_traffic_areas=low_traffic_areas,
        crossing_warnings=crossing_warnings,
        strategic_spines=strategic_spines,
        access_obligations=access_obligations,
        spine_access_connections=spine_access_connections,
        a_road_spines=_context_frame(context, "a-road-spine"),
        ncn_routes=_context_frame(context, "ncn-route"),
        schools=_context_frame(context, "school"),
        retail_centres=_context_frame(context, "retail-centre"),
        healthcare=_context_frame(context, "healthcare"),
        agent_records=records,
        criteria=criteria,
        network_units=network_units,
        atm_reference=None,
        divergence_records=[],
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        superseded_hypotheses=len(superseded),
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
                _network_distance(graph, attachments[gateway_id], attachments[community_id]),
                community_id,
            )
            for community_id in communities["place_id"]
        ]
        reachable = [candidate for candidate in candidates if candidate[0] < float("inf")]
        if reachable:
            pairs.add(tuple(sorted((gateway_id, min(reachable)[1]))))
    return pairs


def _local_adjacency_pairs(
    communities: gpd.GeoDataFrame,
    graph: RoadGraph,
    attachments: dict[str, list[tuple[str, float]]],
) -> set[tuple[str, str]]:
    """Build a cycling-network relative-neighbourhood frontier.

    A pair remains local when no third Community is closer to both endpoints. The
    rule has no fixed radius or neighbour count, so an isolated long bridge remains
    eligible for challenge by the compilation gate.
    """
    identifiers = list(communities["place_id"])
    geometries = communities.set_index("place_id")["geometry"]
    distances: dict[tuple[str, str], float] = {}
    ranks: dict[tuple[str, str], tuple[float, float, str]] = {}
    for index, left in enumerate(identifiers):
        for right in identifiers[index + 1 :]:
            pair = tuple(sorted((left, right)))
            distances[pair] = _network_distance(graph, attachments[left], attachments[right])
            ranks[pair] = (
                distances[pair],
                geometries[left].distance(geometries[right]),
                "::".join(pair),
            )

    pairs: set[tuple[str, str]] = set()
    for (left, right), distance in distances.items():
        if distance == float("inf"):
            continue
        blocked = any(
            ranks[tuple(sorted((left, third)))] < ranks[(left, right)]
            and ranks[tuple(sorted((right, third)))] < ranks[(left, right)]
            for third in identifiers
            if third not in {left, right}
        )
        if not blocked:
            pairs.add((left, right))

    covered = {place_id for pair in pairs for place_id in pair}
    for left in set(identifiers) - covered:
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
            place_id for place_id in communities["place_id"] if assembled.degree(place_id) == 1
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
                distance = _network_distance(graph, attachments[terminus], attachments[neighbour])
                if distance < float("inf"):
                    candidates.append((distance, pair))
        if not candidates:
            geometry = participants.set_index("place_id")["geometry"]
            unresolved = [
                (
                    geometry[terminus].distance(geometry[neighbour]),
                    tuple(sorted((terminus, neighbour))),
                )
                for terminus in termini
                for neighbour in participant_ids
                if terminus != neighbour and tuple(sorted((terminus, neighbour))) not in attempted
            ]
            if not unresolved or not compile_pair(min(unresolved)[1]):
                return
            continue
        compile_pair(min(candidates)[1])


def _connection_graph(
    participants: gpd.GeoDataFrame,
    accepted: list[dict[str, object]],
) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(participants["place_id"])
    graph.add_edges_from((row["from_place"], row["to_place"]) for row in accepted)
    return graph


def _unresolved_rejections(
    graph: nx.Graph,
    rejected: list[dict[str, object]],
    communities: set[str],
    internal_termini: set[str],
) -> list[dict[str, object]]:
    """Keep only failures that still correspond to an unresolved network obligation."""
    component_by_place = {
        place_id: index
        for index, component in enumerate(nx.connected_components(graph))
        for place_id in component
    }
    uncovered = {place_id for place_id in communities if graph.degree(place_id) == 0}
    unresolved_places = uncovered | internal_termini
    unresolved: list[dict[str, object]] = []
    for row in rejected:
        left = str(row["from_place"])
        right = str(row["to_place"])
        separates_components = component_by_place.get(left) != component_by_place.get(right)
        if separates_components or left in unresolved_places or right in unresolved_places:
            unresolved.append(row)
    return unresolved


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
        "from_place_name": left.get("name", left.place_id),
        "to_place_name": right.get("name", right.place_id),
        "distance_km": round(distance_km, 3) if selected else None,
        "classification": classification,
        "intervention_archetype": _intervention_archetype(classification),
        "geometry_semantics": (
            "A-road corridor centreline; cartographically offset to depict alongside provision"
            if classification == "strategic-spine"
            else "indicative OSM alignment centreline"
        ),
        "status": "validated" if record.decision == "accept" else "gap",
        "selection_reason": (
            reason
            if selected is None or selected.role == (outcome.selected_role or selected.role)
            else f"Compilation Gate revised the alignment to {outcome.selected_role}."
        ),
        "agent_outcome": record.outcome_reason,
        "agent_attempt_count": len(record.attempts),
        "agent_findings": json.dumps(_agent_findings(record), sort_keys=True),
        "source_ids": json.dumps(option_evidence_ids(options), sort_keys=True),
        "cache_status": "compiled",
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


def _intervention_archetype(classification: str) -> str | None:
    return {
        "strategic-spine": "wide shared path alongside A-road corridor",
        "ncn-informed": "NCN-aligned route upgrade",
        "low-traffic": "low-traffic route treatment",
        "direct": "protected or filtered direct link",
    }.get(classification)


def _context_frame(context: gpd.GeoDataFrame, feature_type: str) -> gpd.GeoDataFrame:
    return context[context["feature_type"] == feature_type].copy()


def _stable_role_id(prefix: str, *parts: object) -> str:
    value = "::".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"


def _strategic_spines(context: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Promote explicitly rural, governed A-road and established NCN evidence."""
    columns = [
        "spine_id",
        "network_role",
        "spine_kind",
        "name",
        "category",
        "evidence_id",
        "source_id",
        "network_scope",
        "intervention_assumption",
        "design_status",
        "provenance",
        "geometry",
    ]
    candidates = context[context["feature_type"].isin(["a-road-spine", "ncn-route"])].copy()
    network_scope = candidates.get(
        "network_scope",
        pd.Series(NetworkScope.UNRESOLVED.value, index=candidates.index, dtype=object),
    ).map(_network_scope)
    candidates = candidates[network_scope.eq(NetworkScope.RURAL)]
    rows: list[dict[str, object]] = []
    for feature_type, spine_kind in (
        ("a-road-spine", "a-road"),
        ("ncn-route", "ncn"),
    ):
        for _, evidence in candidates[candidates["feature_type"] == feature_type].iterrows():
            evidence_id = str(evidence.get("evidence_id", evidence.get("source_id", "")))
            source_id = str(evidence.get("source_id", evidence_id))
            is_a_road = spine_kind == "a-road"
            for geometry in _continuous_linework(evidence.geometry):
                segment_key = hashlib.sha256(geometry.wkb).hexdigest()[:12]
                rows.append(
                    {
                        "spine_id": _stable_role_id(
                            "strategic-spine",
                            spine_kind,
                            evidence_id,
                            source_id,
                            segment_key,
                        ),
                        "network_role": "strategic-spine",
                        "spine_kind": spine_kind,
                        "name": evidence.get("name"),
                        "category": evidence.get("category"),
                        "evidence_id": evidence_id,
                        "source_id": source_id,
                        "network_scope": NetworkScope.RURAL.value,
                        "intervention_assumption": (
                            "Major engineering required to provide high-quality protected or "
                            "shared provision"
                            if is_a_road
                            else (
                                "Established National Cycle Network route retained as governed "
                                "evidence"
                            )
                        ),
                        "design_status": (
                            "strategic assumption; not a carriageway or final design"
                            if is_a_road
                            else "established route evidence; not a final design"
                        ),
                        "provenance": json.dumps(
                            {
                                "evidence_id": evidence_id,
                                "source_id": source_id,
                                "source_feature_type": feature_type,
                                "network_scope": NetworkScope.RURAL.value,
                            },
                            sort_keys=True,
                        ),
                        "geometry": geometry,
                    }
                )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=context.crs)


def _continuous_linework(geometry: object) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return [merged]
        return sorted(list(merged.geoms), key=lambda line: line.wkb_hex)
    if hasattr(geometry, "geoms"):
        return sorted(
            [line for part in geometry.geoms for line in _continuous_linework(part)],
            key=lambda line: line.wkb_hex,
        )
    return []


def _network_scope(value: object) -> NetworkScope:
    try:
        return NetworkScope(str(value))
    except ValueError as error:
        raise ValueError(f"invalid governed network_scope: {value!r}") from error


MAX_COMMUNITY_ATTACHMENT_M = 2000.0
MAX_SPINE_ATTACHMENT_M = 20.0


def _first_spine_access_connection(
    communities: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> gpd.GeoDataFrame:
    """Publish the smallest deterministic tracer: one reachable Community-to-Spine route."""
    columns = [
        "access_connection_id",
        "community_id",
        "community_name",
        "spine_id",
        "spine_name",
        "spine_kind",
        "network_role",
        "distance_km",
        "status",
        "intervention_archetype",
        "selection_reason",
        "geometry_semantics",
        "source_ids",
        "criterion_continuity",
        "criterion_bidirectional",
        "geometry",
    ]
    spine_rows = [spine for _, spine in strategic_spines.sort_values("spine_id").iterrows()]
    spine_attachments = {
        str(spine["spine_id"]): graph.nodes_on_geometry(spine.geometry) for spine in spine_rows
    }
    community_attachments = {
        str(community["place_id"]): [graph.nearest_node(community.geometry)]
        for _, community in communities.iterrows()
    }
    pair_candidates: list[
        tuple[tuple[object, ...], pd.Series, pd.Series, list[tuple[str, float]]]
    ] = []
    for _, community in communities.sort_values("place_id").iterrows():
        community_id = str(community["place_id"])
        for spine in spine_rows:
            targets = spine_attachments[str(spine["spine_id"])]
            distance_m = graph.network_distance(community_attachments[community_id], targets)
            if distance_m == float("inf"):
                continue
            rank = (
                round(distance_m, 6),
                0 if spine["spine_kind"] == "a-road" else 1,
                community_id,
                str(spine["spine_id"]),
            )
            pair_candidates.append((rank, community, spine, targets))

    for _, community, spine, targets in sorted(pair_candidates, key=lambda candidate: candidate[0]):
        community_id = str(community["place_id"])
        routes: list[tuple[tuple[object, ...], RouteOption, float, LineString]] = []
        for start_node, start_snap in community_attachments[community_id]:
            for end_node, end_snap in targets:
                if start_snap > MAX_COMMUNITY_ATTACHMENT_M or end_snap > MAX_SPINE_ATTACHMENT_M:
                    continue
                option = graph.option(start_node, end_node, "direct")
                if option is None or not option.bidirectional:
                    continue
                geometry = _route_with_attachments(
                    graph,
                    option.geometry,
                    start_node,
                    community.geometry,
                    end_node,
                    spine.geometry,
                )
                if geometry is None:
                    continue
                total_distance_km = option.length_km + (start_snap + end_snap) / 1000
                route_rank = (
                    round(total_distance_km, 9),
                    start_node,
                    end_node,
                )
                routes.append((route_rank, option, total_distance_km, geometry))
        if not routes:
            continue
        _, option, total_distance_km, geometry = min(routes, key=lambda candidate: candidate[0])
        source_ids = sorted(
            {
                *option.edge_ids,
                *option.reverse_edge_ids,
                str(spine["evidence_id"]),
                str(spine["source_id"]),
            }
        )
        row = {
            "access_connection_id": _stable_role_id(
                "spine-access", community_id, spine["spine_id"]
            ),
            "community_id": community_id,
            "community_name": community.get("name"),
            "spine_id": spine["spine_id"],
            "spine_name": spine.get("name"),
            "spine_kind": spine["spine_kind"],
            "network_role": "spine-access-connection",
            "distance_km": round(total_distance_km, 3),
            "status": "validated",
            "intervention_archetype": "community link to a high-quality Strategic Spine",
            "selection_reason": (
                "Nearest reachable governed Strategic Spine attachment selected over an "
                "arbitrary Community pair."
            ),
            "geometry_semantics": (
                "bounded Community and Spine attachment lines joined to a routed OSM "
                "network alignment; indicative, not final design"
            ),
            "source_ids": json.dumps(source_ids),
            "criterion_continuity": "green",
            "criterion_bidirectional": "green",
            "geometry": geometry,
        }
        return gpd.GeoDataFrame([row], columns=columns, geometry="geometry", crs=communities.crs)
    return gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=communities.crs)


def _route_with_attachments(
    graph: RoadGraph,
    route: LineString,
    start_node: str,
    community_geometry: object,
    end_node: str,
    spine_geometry: object,
) -> LineString | None:
    parts = [
        part
        for part in (
            graph.attachment_line(start_node, community_geometry),
            route,
            graph.attachment_line(end_node, spine_geometry),
        )
        if part is not None and not part.is_empty
    ]
    unioned = unary_union(parts)
    merged = unioned if isinstance(unioned, LineString) else linemerge(unioned)
    if not isinstance(merged, LineString):
        return None
    if not merged.intersects(community_geometry) or not merged.intersects(spine_geometry):
        return None
    return merged


def _access_obligations(
    communities: gpd.GeoDataFrame,
    spine_access_connections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    columns = [
        "obligation_id",
        "community_id",
        "name",
        "network_role",
        "service_status",
        "access_connection_id",
        "spine_id",
        "provenance",
        "geometry",
    ]
    if spine_access_connections.empty:
        return gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=communities.crs)
    access = spine_access_connections.iloc[0]
    community = communities[communities["place_id"] == access["community_id"]].iloc[0]
    obligation_id = _stable_role_id("access-obligation", community["place_id"])
    row = {
        "obligation_id": obligation_id,
        "community_id": community["place_id"],
        "name": community.get("name"),
        "network_role": "community-access-obligation",
        "service_status": "served",
        "access_connection_id": access["access_connection_id"],
        "spine_id": access["spine_id"],
        "provenance": json.dumps(
            {
                "community_id": community["place_id"],
                "access_connection_id": access["access_connection_id"],
            },
            sort_keys=True,
        ),
        "geometry": community.geometry,
    }
    return gpd.GeoDataFrame([row], columns=columns, geometry="geometry", crs=communities.crs)


def _a_road_assumptions_complete(strategic_spines: gpd.GeoDataFrame) -> bool:
    a_roads = strategic_spines[strategic_spines["spine_kind"] == "a-road"]
    return not a_roads.empty and bool(
        a_roads["intervention_assumption"].notna().all()
        and a_roads["design_status"].str.contains("not a carriageway").all()
    )


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
            "green" if option.length_km <= config.compilation.max_connection_km else "amber"
        ),
    }


def option_evidence_ids(options: list[RouteOption]) -> list[str]:
    return sorted({edge_id for option in options for edge_id in option.edge_ids})


def _agent_findings(record: AgentRecord) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for attempt in record.attempts:
        findings.extend(attempt.get("deterministic_findings", []))
        for role in ("critique", "red_team"):
            findings.extend(attempt.get(role, {}).get("findings", []))
        findings.extend(attempt.get("findings", []))
    unique = {
        json.dumps(finding, sort_keys=True): finding
        for finding in findings
        if isinstance(finding, dict)
    }
    return list(unique.values())
