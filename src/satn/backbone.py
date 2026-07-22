"""Deterministic rural Backbone-Outward Assembly over the governed cycling graph."""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import MultiPoint

from satn.agents import CompilationGate
from satn.models import AgentRecord
from satn.routing import RoadGraph, RouteOption

MAX_OBLIGATION_ATTACHMENT_M = 2000.0
MAX_SPINE_ATTACHMENT_M = 20.0

ACCESS_COLUMNS = [
    "access_connection_id",
    "obligation_id",
    "obligation_kind",
    "place_id",
    "place_name",
    "place_kind",
    "community_id",
    "community_name",
    "spine_id",
    "spine_name",
    "spine_kind",
    "root_spine_id",
    "branch_id",
    "parent_branch_id",
    "parent_role",
    "parent_place_id",
    "parent_access_connection_id",
    "attachment_depth",
    "network_role",
    "distance_km",
    "status",
    "agent_outcome",
    "agent_attempt_count",
    "agent_findings",
    "intervention_archetype",
    "selection_reason",
    "geometry_semantics",
    "community_attachment_node",
    "community_attachment_distance_m",
    "community_attachment_point",
    "target_attachment_node",
    "target_attachment_distance_m",
    "target_attachment_point",
    "spine_attachment_node",
    "spine_attachment_distance_m",
    "spine_attachment_point",
    "source_ids",
    "provenance",
    "criterion_continuity",
    "criterion_bidirectional",
    "geometry",
]

OBLIGATION_COLUMNS = [
    "obligation_id",
    "obligation_kind",
    "place_id",
    "community_id",
    "name",
    "network_role",
    "service_status",
    "access_connection_id",
    "root_spine_id",
    "branch_id",
    "provenance",
    "geometry",
]

BRANCH_COLUMNS = [
    "branch_id",
    "root_spine_id",
    "root_spine_name",
    "network_role",
    "connection_ids",
    "place_ids",
    "max_attachment_depth",
    "provenance",
    "geometry",
]

MEETING_COLUMNS = [
    "meeting_connection_id",
    "network_role",
    "from_place_id",
    "from_place_name",
    "to_place_id",
    "to_place_name",
    "from_branch_id",
    "to_branch_id",
    "from_root_spine_id",
    "to_root_spine_id",
    "distance_km",
    "status",
    "agent_outcome",
    "agent_attempt_count",
    "agent_findings",
    "intervention_archetype",
    "selection_reason",
    "geometry_semantics",
    "from_attachment_node",
    "to_attachment_node",
    "source_ids",
    "provenance",
    "criterion_continuity",
    "criterion_bidirectional",
    "criterion_distance",
    "geometry",
]

CONNECTOR_COLUMNS = [
    "cross_spine_connector_id",
    "network_role",
    "from_root_spine_id",
    "from_root_spine_name",
    "to_root_spine_id",
    "to_root_spine_name",
    "meeting_connection_id",
    "branch_ids",
    "connection_ids",
    "community_ids",
    "distance_km",
    "status",
    "selection_reason",
    "geometry_semantics",
    "source_ids",
    "provenance",
    "geometry",
]

GAP_COLUMNS = [
    "connection_id",
    "network_role",
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


@dataclass(frozen=True)
class BackboneAssembly:
    connections: gpd.GeoDataFrame
    obligations: gpd.GeoDataFrame
    branches: gpd.GeoDataFrame
    meeting_connections: gpd.GeoDataFrame
    cross_spine_connectors: gpd.GeoDataFrame
    gaps: gpd.GeoDataFrame
    gateway_count: int
    connected_gateway_count: int
    agent_records: list[AgentRecord]


@dataclass(frozen=True)
class _Frontier:
    target_id: str
    target_role: str
    target_place_id: str | None
    root_spine_id: str
    root_spine_name: str
    root_spine_kind: str
    root_evidence_id: str
    root_source_id: str
    branch_id: str | None
    parent_access_connection_id: str | None
    depth: int
    attachments: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class _Candidate:
    rank: tuple[object, ...]
    place: pd.Series
    frontier: _Frontier
    option: RouteOption
    start_node: str
    start_snap_m: float
    end_node: str
    end_snap_m: float


@dataclass(frozen=True)
class _MeetingCandidate:
    rank: tuple[object, ...]
    left: pd.Series
    right: pd.Series
    option: RouteOption
    start_node: str
    end_node: str


def assemble_backbone_outward(
    communities: gpd.GeoDataFrame,
    gateways: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
    gate: CompilationGate,
    max_connection_km: float,
) -> BackboneAssembly:
    """Grow one deterministic served frontier from every Strategic Spine concurrently."""
    crs = communities.crs or strategic_spines.crs or graph.crs
    frontiers = _spine_frontiers(strategic_spines, graph)
    unserved = {
        str(row["place_id"]): row for _, row in communities.sort_values("place_id").iterrows()
    }
    rows: list[dict[str, object]] = []
    gap_rows: list[dict[str, object]] = []
    agent_records: list[AgentRecord] = []
    rejected_by_place: dict[str, list[AgentRecord]] = {}
    candidate_heap: list[tuple[tuple[object, ...], int, _Candidate]] = []
    sequence = 0

    def add_frontier_candidates(frontier: _Frontier) -> None:
        nonlocal sequence
        for place_id in sorted(unserved):
            candidate = _candidate(
                unserved[place_id], frontier, graph, obligation_kind="community"
            )
            if candidate is not None:
                heapq.heappush(candidate_heap, (candidate.rank, sequence, candidate))
                sequence += 1

    for frontier in frontiers:
        add_frontier_candidates(frontier)

    while candidate_heap:
        _, _, selected = heapq.heappop(candidate_heap)
        place_id = str(selected.place["place_id"])
        if place_id not in unserved:
            continue
        row = _connection_row(selected, graph, obligation_kind="community")
        record = _evaluate(row, gate)
        agent_records.append(record)
        if record.decision != "accept":
            rejected_by_place.setdefault(place_id, []).append(record)
            continue
        _record_gate_acceptance(row, record)
        for rejected in rejected_by_place.pop(place_id, []):
            rejected.decision = "superseded"
            rejected.outcome_reason = "A different governed frontier attachment was accepted."
        rows.append(row)
        del unserved[place_id]
        served_frontier = _served_frontier(row)
        frontiers.append(served_frontier)
        frontiers.sort(key=_frontier_key)
        add_frontier_candidates(served_frontier)

    for place_id in sorted(unserved):
        rejected = rejected_by_place.get(place_id, [])
        gap_rows.append(
            _gap_row(
                unserved[place_id],
                graph,
                obligation_kind="community",
                gate_reason=rejected[-1].outcome_reason if rejected else None,
            )
        )

    community_connections = gpd.GeoDataFrame(
        rows, columns=ACCESS_COLUMNS, geometry="geometry", crs=crs
    )
    meeting_connections, cross_spine_connectors, meeting_records = _cross_spine_meetings(
        community_connections,
        strategic_spines,
        graph,
        gate,
        max_connection_km=max_connection_km,
    )
    agent_records.extend(meeting_records)

    connected_gateways = 0
    for _, gateway in gateways.sort_values("place_id").iterrows():
        if _already_connected_gateway(gateway, frontiers, graph):
            connected_gateways += 1
            continue
        candidates = [
            candidate
            for frontier in frontiers
            if (
                candidate := _candidate(
                    gateway,
                    frontier,
                    graph,
                    obligation_kind="gateway",
                    allow_stationary=False,
                )
            )
            is not None
        ]
        if not candidates:
            gap_rows.append(_gap_row(gateway, graph, obligation_kind="gateway"))
            continue
        for selected in sorted(candidates, key=lambda candidate: candidate.rank):
            row = _connection_row(selected, graph, obligation_kind="gateway")
            record = _evaluate(row, gate)
            agent_records.append(record)
            if record.decision == "accept":
                _record_gate_acceptance(row, record)
                rows.append(row)
                connected_gateways += 1
                break
        else:
            gap_rows.append(
                _gap_row(
                    gateway,
                    graph,
                    obligation_kind="gateway",
                    gate_reason=record.outcome_reason,
                )
            )

    connections = gpd.GeoDataFrame(
        rows, columns=ACCESS_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("access_connection_id")
    gaps = gpd.GeoDataFrame(
        gap_rows, columns=GAP_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("connection_id")
    obligations = _obligations(communities, connections, gaps)
    branches = _branches(connections, strategic_spines, crs)
    return BackboneAssembly(
        connections=connections,
        obligations=obligations,
        branches=branches,
        meeting_connections=meeting_connections,
        cross_spine_connectors=cross_spine_connectors,
        gaps=gaps,
        gateway_count=len(gateways),
        connected_gateway_count=connected_gateways,
        agent_records=agent_records,
    )


def _spine_frontiers(
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> list[_Frontier]:
    frontiers: list[_Frontier] = []
    for _, spine in strategic_spines.sort_values("spine_id").iterrows():
        attachments = tuple(graph.nodes_on_geometry(spine.geometry))
        frontiers.append(
            _Frontier(
                target_id=str(spine["spine_id"]),
                target_role="strategic-spine",
                target_place_id=None,
                root_spine_id=str(spine["spine_id"]),
                root_spine_name=str(spine.get("name") or spine["spine_id"]),
                root_spine_kind=str(spine["spine_kind"]),
                root_evidence_id=str(spine["evidence_id"]),
                root_source_id=str(spine["source_id"]),
                branch_id=None,
                parent_access_connection_id=None,
                depth=0,
                attachments=attachments,
            )
        )
    return sorted(frontiers, key=_frontier_key)


def _served_frontier(row: dict[str, object]) -> _Frontier:
    return _Frontier(
        target_id=str(row["access_connection_id"]),
        target_role="spine-access-connection",
        target_place_id=str(row["place_id"]),
        root_spine_id=str(row["root_spine_id"]),
        root_spine_name=str(row["spine_name"]),
        root_spine_kind=str(row["spine_kind"]),
        root_evidence_id=str(json.loads(str(row["provenance"]))["root_evidence_id"]),
        root_source_id=str(json.loads(str(row["provenance"]))["root_source_id"]),
        branch_id=str(row["branch_id"]),
        parent_access_connection_id=str(row["access_connection_id"]),
        depth=int(row["attachment_depth"]),
        attachments=((str(row["community_attachment_node"]), 0.0),),
    )


def _frontier_key(frontier: _Frontier) -> tuple[object, ...]:
    return (
        0 if frontier.target_role == "strategic-spine" else 1,
        frontier.root_spine_id,
        frontier.target_id,
    )


def _candidate(
    place: pd.Series,
    frontier: _Frontier,
    graph: RoadGraph,
    *,
    obligation_kind: str,
    allow_stationary: bool = True,
) -> _Candidate | None:
    starts = graph.nodes_near(place.geometry, MAX_OBLIGATION_ATTACHMENT_M)
    if not starts:
        return None
    choice = graph.best_attachment(
        starts,
        [
            attachment
            for attachment in frontier.attachments
            if attachment[1] <= MAX_SPINE_ATTACHMENT_M
        ],
        allow_stationary=allow_stationary,
    )
    if choice is None:
        return None
    rank = (
        round(choice.total_distance_km, 9),
        str(place["place_id"]),
        0 if frontier.target_role == "strategic-spine" else 1,
        frontier.root_spine_id,
        frontier.target_id,
        choice.start_node,
        choice.end_node,
        obligation_kind,
    )
    return _Candidate(
        rank=rank,
        place=place,
        frontier=frontier,
        option=choice.option,
        start_node=choice.start_node,
        start_snap_m=choice.start_snap_m,
        end_node=choice.end_node,
        end_snap_m=choice.end_snap_m,
    )


def _already_connected_gateway(
    gateway: pd.Series,
    frontiers: list[_Frontier],
    graph: RoadGraph,
) -> bool:
    nearby_nodes = {
        node_id for node_id, _ in graph.nodes_near(gateway.geometry, MAX_SPINE_ATTACHMENT_M)
    }
    frontier_nodes = {
        node_id
        for frontier in frontiers
        for node_id, snap_m in frontier.attachments
        if snap_m <= MAX_SPINE_ATTACHMENT_M
    }
    return bool(nearby_nodes & frontier_nodes)


def _evaluate(row: dict[str, object], gate: CompilationGate) -> AgentRecord:
    return gate.evaluate(
        str(row["access_connection_id"]),
        {
            "from_place": str(row["place_id"]),
            "to_place": str(row["parent_place_id"] or row["root_spine_id"]),
            "selection_reason": str(row["selection_reason"]),
            "evidence_ids": tuple(json.loads(str(row["source_ids"]))),
            "checks_by_role": {
                "direct": {
                    "continuity": row["criterion_continuity"],
                    "bidirectional": row["criterion_bidirectional"],
                }
            },
        },
        "direct",
        ["direct"],
    ).record


def _record_gate_acceptance(row: dict[str, object], record: AgentRecord) -> None:
    row["status"] = "validated"
    row["agent_outcome"] = record.outcome_reason
    row["agent_attempt_count"] = len(record.attempts)
    latest = record.attempts[-1] if record.attempts else {}
    row["agent_findings"] = json.dumps(
        [
            *latest.get("deterministic_findings", []),
            *latest.get("critique", {}).get("findings", []),
            *latest.get("red_team", {}).get("findings", []),
        ],
        sort_keys=True,
    )


def _connection_row(
    candidate: _Candidate,
    graph: RoadGraph,
    *,
    obligation_kind: str,
) -> dict[str, object]:
    place_id = str(candidate.place["place_id"])
    frontier = candidate.frontier
    branch_id = frontier.branch_id
    if branch_id is None and obligation_kind == "community":
        branch_id = _stable_id("spine-access-branch", frontier.root_spine_id, place_id)
    parent_id = frontier.parent_access_connection_id or frontier.root_spine_id
    connection_id = _stable_id("spine-access", place_id, frontier.root_spine_id, parent_id)
    source_ids = sorted(
        {
            *candidate.option.edge_ids,
            *candidate.option.reverse_edge_ids,
            frontier.root_evidence_id,
            frontier.root_source_id,
        }
    )
    network_role = (
        "spine-access-connection" if obligation_kind == "community" else "gateway-access-connection"
    )
    depth = frontier.depth + 1
    provenance = {
        "access_connection_id": connection_id,
        "obligation_kind": obligation_kind,
        "place_id": place_id,
        "root_spine_id": frontier.root_spine_id,
        "root_evidence_id": frontier.root_evidence_id,
        "root_source_id": frontier.root_source_id,
        "branch_id": branch_id,
        "parent_branch_id": frontier.branch_id,
        "parent_role": frontier.target_role,
        "parent_place_id": frontier.target_place_id,
        "parent_access_connection_id": frontier.parent_access_connection_id,
        "source_ids": source_ids,
    }
    direct_to_spine = frontier.target_role == "strategic-spine"
    return {
        "access_connection_id": connection_id,
        "obligation_id": (
            _stable_id("access-obligation", place_id) if obligation_kind == "community" else None
        ),
        "obligation_kind": obligation_kind,
        "place_id": place_id,
        "place_name": candidate.place.get("name"),
        "place_kind": candidate.place.get("kind"),
        "community_id": place_id if obligation_kind == "community" else None,
        "community_name": (candidate.place.get("name") if obligation_kind == "community" else None),
        "spine_id": frontier.root_spine_id,
        "spine_name": frontier.root_spine_name,
        "spine_kind": frontier.root_spine_kind,
        "root_spine_id": frontier.root_spine_id,
        "branch_id": branch_id,
        "parent_branch_id": frontier.branch_id,
        "parent_role": frontier.target_role,
        "parent_place_id": frontier.target_place_id,
        "parent_access_connection_id": frontier.parent_access_connection_id,
        "attachment_depth": depth,
        "network_role": network_role,
        "distance_km": round(
            candidate.option.length_km + (candidate.start_snap_m + candidate.end_snap_m) / 1000,
            3,
        ),
        "status": "candidate",
        "agent_outcome": None,
        "agent_attempt_count": 0,
        "agent_findings": "[]",
        "intervention_archetype": "access link to a high-quality Strategic Spine branch",
        "selection_reason": (
            "Selected by minimum plausible cycling-network cost from all concurrent "
            f"Strategic Spine and served-branch frontiers; extended {frontier.target_role}."
        ),
        "geometry_semantics": (
            "routed OSM network alignment between canonical graph attachment points; "
            "snap distances are evidence associations, not claimed paths or final design"
        ),
        "community_attachment_node": candidate.start_node,
        "community_attachment_distance_m": round(candidate.start_snap_m, 3),
        "community_attachment_point": graph.node_points[candidate.start_node].wkt,
        "target_attachment_node": candidate.end_node,
        "target_attachment_distance_m": round(candidate.end_snap_m, 3),
        "target_attachment_point": graph.node_points[candidate.end_node].wkt,
        "spine_attachment_node": candidate.end_node if direct_to_spine else None,
        "spine_attachment_distance_m": (
            round(candidate.end_snap_m, 3) if direct_to_spine else None
        ),
        "spine_attachment_point": (
            graph.node_points[candidate.end_node].wkt if direct_to_spine else None
        ),
        "source_ids": json.dumps(source_ids),
        "provenance": json.dumps(provenance, sort_keys=True),
        "criterion_continuity": "green",
        "criterion_bidirectional": "green",
        "geometry": candidate.option.geometry,
    }


def _gap_row(
    place: pd.Series,
    graph: RoadGraph,
    *,
    obligation_kind: str,
    gate_reason: str | None = None,
) -> dict[str, object]:
    place_id = str(place["place_id"])
    _, snap_distance_m = graph.nearest_node(place.geometry)
    bounded = snap_distance_m <= MAX_OBLIGATION_ATTACHMENT_M
    reason = gate_reason or (
        "No continuous bidirectional OSM cycling-network path reaches any Strategic Spine "
        "or served branch frontier."
        if bounded
        else (
            "The reference point has no routable graph attachment within the governed "
            f"{MAX_OBLIGATION_ATTACHMENT_M:.0f} metre bound."
        )
    )
    return {
        "connection_id": _stable_id("spine-access-gap", obligation_kind, place_id),
        "network_role": (
            "spine-access-gap" if obligation_kind == "community" else "gateway-access-gap"
        ),
        "from_place": place_id,
        "to_place": None,
        "from_place_name": place.get("name"),
        "to_place_name": None,
        "distance_km": None,
        "classification": "network-gap",
        "intervention_archetype": "route investigation",
        "geometry_semantics": "unserved reference point evidence; no route line is fabricated",
        "status": "gap",
        "selection_reason": reason,
        "agent_outcome": reason,
        "agent_attempt_count": 0,
        "agent_findings": "[]",
        "source_ids": "[]",
        "cache_status": "not-cacheable",
        "alignment_options": "[]",
        "criterion_endpoints": "green" if bounded else "red",
        "criterion_continuity": "red",
        "criterion_bidirectional": "red",
        "criterion_distance": "grey",
        "geometry": MultiPoint([place.geometry]),
    }


def _obligations(
    communities: gpd.GeoDataFrame,
    connections: gpd.GeoDataFrame,
    gaps: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    served = {
        str(row["place_id"]): row
        for _, row in connections[connections["obligation_kind"] == "community"].iterrows()
    }
    gap_ids = set(gaps.loc[gaps["network_role"] == "spine-access-gap", "from_place"].astype(str))
    rows: list[dict[str, object]] = []
    for _, community in communities.sort_values("place_id").iterrows():
        place_id = str(community["place_id"])
        access = served.get(place_id)
        service_status = "served" if access is not None else "network-gap"
        provenance = {
            "community_id": place_id,
            "service_status": service_status,
            "access_connection_id": (
                str(access["access_connection_id"]) if access is not None else None
            ),
            "gap_id": (
                _stable_id("spine-access-gap", "community", place_id)
                if place_id in gap_ids
                else None
            ),
        }
        rows.append(
            {
                "obligation_id": _stable_id("access-obligation", place_id),
                "obligation_kind": "community",
                "place_id": place_id,
                "community_id": place_id,
                "name": community.get("name"),
                "network_role": "community-access-obligation",
                "service_status": service_status,
                "access_connection_id": (
                    access["access_connection_id"] if access is not None else None
                ),
                "root_spine_id": access["root_spine_id"] if access is not None else None,
                "branch_id": access["branch_id"] if access is not None else None,
                "provenance": json.dumps(provenance, sort_keys=True),
                "geometry": community.geometry,
            }
        )
    return gpd.GeoDataFrame(
        rows, columns=OBLIGATION_COLUMNS, geometry="geometry", crs=communities.crs
    )


def _cross_spine_meetings(
    connections: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
    gate: CompilationGate,
    *,
    max_connection_km: float,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, list[AgentRecord]]:
    crs = connections.crs or strategic_spines.crs or graph.crs
    root_ids = sorted(
        str(root_id)
        for root_id in connections.get(
            "root_spine_id", pd.Series(dtype=object)
        ).dropna().unique()
    )
    root_groups = {
        str(root_id): connections[connections["root_spine_id"] == root_id].sort_values("place_id")
        for root_id in root_ids
    }
    candidate_heap: list[
        tuple[
            tuple[object, ...],
            int,
            str,
            str,
            frozenset[tuple[str, str]],
            _MeetingCandidate,
        ]
    ] = []
    sequence = 0

    def add_candidate(
        left_root: str,
        right_root: str,
        excluded_pairs: frozenset[tuple[str, str]],
    ) -> None:
        nonlocal sequence
        candidate = _meeting_candidate(
            root_groups[left_root],
            root_groups[right_root],
            graph,
            excluded_pairs=set(excluded_pairs),
        )
        if candidate is None:
            return
        heapq.heappush(
            candidate_heap,
            (
                candidate.rank,
                sequence,
                left_root,
                right_root,
                excluded_pairs,
                candidate,
            ),
        )
        sequence += 1

    for left_index, left_root in enumerate(root_ids):
        for right_root in root_ids[left_index + 1 :]:
            add_candidate(str(left_root), str(right_root), frozenset())

    root_graph = nx.Graph()
    root_graph.add_nodes_from(root_ids)
    rows: list[dict[str, object]] = []
    records: list[AgentRecord] = []
    rejected_by_roots: dict[tuple[str, str], list[AgentRecord]] = {}
    while candidate_heap:
        _, _, left_root, right_root, excluded_pairs, candidate = heapq.heappop(
            candidate_heap
        )
        if nx.has_path(root_graph, left_root, right_root):
            _supersede_rejected_meetings(
                rejected_by_roots.pop((left_root, right_root), []),
                "Accepted tree meetings made this direct meeting unnecessary.",
            )
            continue
        row = _meeting_row(candidate, max_connection_km=max_connection_km)
        record = _evaluate_meeting(row, gate)
        records.append(record)
        if record.decision != "accept":
            root_pair = (left_root, right_root)
            rejected_by_roots.setdefault(root_pair, []).append(record)
            add_candidate(
                left_root,
                right_root,
                frozenset(
                    {
                        *excluded_pairs,
                        (candidate.start_node, candidate.end_node),
                    }
                ),
            )
            continue
        _record_meeting_acceptance(row, record)
        _supersede_rejected_meetings(
            rejected_by_roots.pop((left_root, right_root), []),
            "A later governed meeting candidate was accepted.",
        )
        rows.append(row)
        root_graph.add_edge(left_root, right_root)
        for root_pair in list(rejected_by_roots):
            if nx.has_path(root_graph, *root_pair):
                _supersede_rejected_meetings(
                    rejected_by_roots.pop(root_pair),
                    "Accepted tree meetings made this direct meeting unnecessary.",
                )

    meetings = gpd.GeoDataFrame(
        rows, columns=MEETING_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("meeting_connection_id")
    connectors = _cross_spine_connectors(meetings, connections, strategic_spines, crs)
    return meetings, connectors, records


def _supersede_rejected_meetings(
    records: list[AgentRecord],
    reason: str,
) -> None:
    for record in records:
        record.decision = "superseded"
        record.outcome_reason = reason


def _meeting_candidate(
    left_group: gpd.GeoDataFrame,
    right_group: gpd.GeoDataFrame,
    graph: RoadGraph,
    *,
    excluded_pairs: set[tuple[str, str]],
) -> _MeetingCandidate | None:
    choice = graph.best_attachment(
        [
            (str(row["community_attachment_node"]), 0.0)
            for _, row in left_group.iterrows()
        ],
        [
            (str(row["community_attachment_node"]), 0.0)
            for _, row in right_group.iterrows()
        ],
        allow_stationary=False,
        excluded_pairs=excluded_pairs,
    )
    if choice is None:
        return None
    left = left_group[
        left_group["community_attachment_node"] == choice.start_node
    ].iloc[0]
    right = right_group[
        right_group["community_attachment_node"] == choice.end_node
    ].iloc[0]
    return _MeetingCandidate(
        rank=(
            round(choice.total_distance_km, 9),
            str(left["root_spine_id"]),
            str(right["root_spine_id"]),
            str(left["place_id"]),
            str(right["place_id"]),
        ),
        left=left,
        right=right,
        option=choice.option,
        start_node=choice.start_node,
        end_node=choice.end_node,
    )


def _meeting_row(
    candidate: _MeetingCandidate,
    *,
    max_connection_km: float,
) -> dict[str, object]:
    left = candidate.left
    right = candidate.right
    left_root = str(left["root_spine_id"])
    right_root = str(right["root_spine_id"])
    left_place = str(left["place_id"])
    right_place = str(right["place_id"])
    meeting_id = _stable_id(
        "branch-meeting", left_root, right_root, left_place, right_place
    )
    source_ids = sorted(
        {*candidate.option.edge_ids, *candidate.option.reverse_edge_ids}
    )
    route_length_km = candidate.option.length_km
    distance_km = round(route_length_km, 3)
    provenance = {
        "meeting_connection_id": meeting_id,
        "from_place_id": left_place,
        "to_place_id": right_place,
        "from_branch_id": str(left["branch_id"]),
        "to_branch_id": str(right["branch_id"]),
        "from_root_spine_id": left_root,
        "to_root_spine_id": right_root,
        "source_ids": source_ids,
    }
    return {
        "meeting_connection_id": meeting_id,
        "network_role": "branch-meeting-connection",
        "from_place_id": left_place,
        "from_place_name": left["place_name"],
        "to_place_id": right_place,
        "to_place_name": right["place_name"],
        "from_branch_id": left["branch_id"],
        "to_branch_id": right["branch_id"],
        "from_root_spine_id": left_root,
        "to_root_spine_id": right_root,
        "distance_km": distance_km,
        "status": "candidate",
        "agent_outcome": None,
        "agent_attempt_count": 0,
        "agent_findings": "[]",
        "intervention_archetype": "transverse link between Strategic Spine branches",
        "selection_reason": (
            "Selected as the first justified cycling-network adjacency between differently "
            "rooted served fronts; later parallel or cyclic meetings are suppressed."
        ),
        "geometry_semantics": (
            "routed OSM network alignment joining two served Community attachment nodes; "
            "not a general pairwise link or final design"
        ),
        "from_attachment_node": candidate.start_node,
        "to_attachment_node": candidate.end_node,
        "source_ids": json.dumps(source_ids),
        "provenance": json.dumps(provenance, sort_keys=True),
        "criterion_continuity": "green",
        "criterion_bidirectional": "green",
        "criterion_distance": (
            "amber" if route_length_km > max_connection_km else "green"
        ),
        "geometry": candidate.option.geometry,
    }


def _evaluate_meeting(row: dict[str, object], gate: CompilationGate) -> AgentRecord:
    return gate.evaluate(
        str(row["meeting_connection_id"]),
        {
            "from_place": str(row["from_place_id"]),
            "to_place": str(row["to_place_id"]),
            "selection_reason": str(row["selection_reason"]),
            "evidence_ids": tuple(json.loads(str(row["source_ids"]))),
            "checks_by_role": {
                "cross-spine-connector": {
                    "continuity": row["criterion_continuity"],
                    "bidirectional": row["criterion_bidirectional"],
                    "distance": row["criterion_distance"],
                }
            },
        },
        "cross-spine-connector",
        ["cross-spine-connector"],
    ).record


def _record_meeting_acceptance(row: dict[str, object], record: AgentRecord) -> None:
    row["status"] = "validated"
    row["agent_outcome"] = record.outcome_reason
    row["agent_attempt_count"] = len(record.attempts)
    latest = record.attempts[-1] if record.attempts else {}
    row["agent_findings"] = json.dumps(
        [
            *latest.get("deterministic_findings", []),
            *latest.get("critique", {}).get("findings", []),
            *latest.get("red_team", {}).get("findings", []),
        ],
        sort_keys=True,
    )


def _cross_spine_connectors(
    meetings: gpd.GeoDataFrame,
    connections: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    crs: object,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    connection_by_id = connections.set_index("access_connection_id", drop=False)
    spine_names = strategic_spines.set_index("spine_id").get("name", pd.Series(dtype=object))
    for _, meeting in meetings.iterrows():
        member_rows = _lineage(connection_by_id, str(meeting["from_place_id"]))
        member_rows.extend(_lineage(connection_by_id, str(meeting["to_place_id"])))
        members = {
            str(member["access_connection_id"]): member for member in member_rows
        }
        connection_ids = sorted(
            [*members, str(meeting["meeting_connection_id"])]
        )
        community_ids = sorted(str(member["place_id"]) for member in members.values())
        branch_ids = sorted({str(member["branch_id"]) for member in members.values()})
        source_ids = sorted(
            {
                *json.loads(str(meeting["source_ids"])),
                *(
                    source_id
                    for member in members.values()
                    for source_id in json.loads(str(member["source_ids"]))
                ),
            }
        )
        meeting_id = str(meeting["meeting_connection_id"])
        connector_id = _stable_id("cross-spine-connector", meeting_id)
        left_root = str(meeting["from_root_spine_id"])
        right_root = str(meeting["to_root_spine_id"])
        provenance = {
            "cross_spine_connector_id": connector_id,
            "meeting_connection_id": meeting_id,
            "branch_ids": branch_ids,
            "connection_ids": connection_ids,
            "community_ids": community_ids,
            "source_ids": source_ids,
        }
        geometries = [meeting.geometry, *(member.geometry for member in members.values())]
        rows.append(
            {
                "cross_spine_connector_id": connector_id,
                "network_role": "cross-spine-connector",
                "from_root_spine_id": left_root,
                "from_root_spine_name": spine_names.get(left_root),
                "to_root_spine_id": right_root,
                "to_root_spine_name": spine_names.get(right_root),
                "meeting_connection_id": meeting_id,
                "branch_ids": json.dumps(branch_ids),
                "connection_ids": json.dumps(connection_ids),
                "community_ids": json.dumps(community_ids),
                "distance_km": round(
                    float(meeting["distance_km"])
                    + sum(float(member["distance_km"]) for member in members.values()),
                    3,
                ),
                "status": "validated",
                "selection_reason": (
                    "Continuous transverse chain traced from the first Branch Meeting "
                    "Connection through both parent lineages to their Strategic Spines."
                ),
                "geometry_semantics": (
                    "union of the validated meeting and its two parent branch lineages"
                ),
                "source_ids": json.dumps(source_ids),
                "provenance": json.dumps(provenance, sort_keys=True),
                "geometry": gpd.GeoSeries(geometries, crs=crs).union_all(),
            }
        )
    return gpd.GeoDataFrame(
        rows, columns=CONNECTOR_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("cross_spine_connector_id")


def _lineage(
    connection_by_id: gpd.GeoDataFrame,
    place_id: str,
) -> list[pd.Series]:
    matches = connection_by_id[connection_by_id["place_id"] == place_id]
    if matches.empty:
        return []
    lineage: list[pd.Series] = []
    current = matches.sort_index().iloc[0]
    while True:
        lineage.append(current)
        parent_id = current["parent_access_connection_id"]
        if pd.isna(parent_id) or parent_id is None:
            return lineage
        current = connection_by_id.loc[str(parent_id)]


def _branches(
    connections: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    crs: object,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    spine_names = strategic_spines.set_index("spine_id").get("name", pd.Series(dtype=object))
    community_connections = connections[connections["obligation_kind"] == "community"]
    for branch_id, members in community_connections.groupby("branch_id", sort=True):
        root_spine_id = str(members.iloc[0]["root_spine_id"])
        connection_ids = sorted(members["access_connection_id"].astype(str))
        place_ids = sorted(members["place_id"].astype(str))
        provenance = {
            "branch_id": branch_id,
            "root_spine_id": root_spine_id,
            "connection_ids": connection_ids,
            "place_ids": place_ids,
        }
        rows.append(
            {
                "branch_id": branch_id,
                "root_spine_id": root_spine_id,
                "root_spine_name": spine_names.get(root_spine_id),
                "network_role": "spine-access-branch",
                "connection_ids": json.dumps(connection_ids),
                "place_ids": json.dumps(place_ids),
                "max_attachment_depth": int(members["attachment_depth"].max()),
                "provenance": json.dumps(provenance, sort_keys=True),
                "geometry": members.geometry.union_all(),
            }
        )
    return gpd.GeoDataFrame(rows, columns=BRANCH_COLUMNS, geometry="geometry", crs=crs)


def _stable_id(prefix: str, *parts: object) -> str:
    value = "::".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"
