"""Deterministic rural Backbone-Outward Assembly over the governed cycling graph."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiPoint

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
    gaps: gpd.GeoDataFrame
    gateway_count: int
    connected_gateway_count: int


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


def assemble_backbone_outward(
    communities: gpd.GeoDataFrame,
    gateways: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> BackboneAssembly:
    """Grow one deterministic served frontier from every Strategic Spine concurrently."""
    crs = communities.crs or strategic_spines.crs or graph.crs
    frontiers = _spine_frontiers(strategic_spines, graph)
    unserved = {
        str(row["place_id"]): row for _, row in communities.sort_values("place_id").iterrows()
    }
    rows: list[dict[str, object]] = []
    gap_rows: list[dict[str, object]] = []

    while unserved:
        candidates = [
            candidate
            for place_id in sorted(unserved)
            for frontier in frontiers
            if (
                candidate := _candidate(
                    unserved[place_id], frontier, graph, obligation_kind="community"
                )
            )
            is not None
        ]
        if not candidates:
            break
        selected = min(candidates, key=lambda candidate: candidate.rank)
        row = _connection_row(selected, graph, obligation_kind="community")
        rows.append(row)
        place_id = str(selected.place["place_id"])
        del unserved[place_id]
        frontiers.append(_served_frontier(row))
        frontiers.sort(key=_frontier_key)

    for place_id in sorted(unserved):
        gap_rows.append(_gap_row(unserved[place_id], graph, obligation_kind="community"))

    connected_gateways = 0
    for _, gateway in gateways.sort_values("place_id").iterrows():
        candidates = [
            candidate
            for frontier in frontiers
            if (candidate := _candidate(gateway, frontier, graph, obligation_kind="gateway"))
            is not None
        ]
        if not candidates:
            gap_rows.append(_gap_row(gateway, graph, obligation_kind="gateway"))
            continue
        selected = min(candidates, key=lambda candidate: candidate.rank)
        rows.append(_connection_row(selected, graph, obligation_kind="gateway"))
        connected_gateways += 1

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
        gaps=gaps,
        gateway_count=len(gateways),
        connected_gateway_count=connected_gateways,
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
) -> _Candidate | None:
    start_node, start_snap_m = graph.nearest_node(place.geometry)
    if start_snap_m > MAX_OBLIGATION_ATTACHMENT_M:
        return None
    routes: list[_Candidate] = []
    for end_node, end_snap_m in frontier.attachments:
        if end_snap_m > MAX_SPINE_ATTACHMENT_M:
            continue
        option = (
            _stationary_option(graph, start_node)
            if start_node == end_node
            else graph.option(start_node, end_node, "direct")
        )
        if option is None or not option.bidirectional:
            continue
        total_distance_km = option.length_km + (start_snap_m + end_snap_m) / 1000
        rank = (
            round(total_distance_km, 9),
            str(place["place_id"]),
            0 if frontier.target_role == "strategic-spine" else 1,
            frontier.root_spine_id,
            frontier.target_id,
            start_node,
            end_node,
            obligation_kind,
        )
        routes.append(
            _Candidate(
                rank=rank,
                place=place,
                frontier=frontier,
                option=option,
                start_node=start_node,
                start_snap_m=start_snap_m,
                end_node=end_node,
                end_snap_m=end_snap_m,
            )
        )
    return min(routes, key=lambda candidate: candidate.rank) if routes else None


def _stationary_option(graph: RoadGraph, node_id: str) -> RouteOption:
    point = graph.node_points[node_id]
    return RouteOption(
        role="direct",
        geometry=LineString([point, point]),
        length_km=0.0,
        edge_ids=[],
        a_road_share=0.0,
        ncn_share=0.0,
        bidirectional=True,
        reverse_length_km=0.0,
        reverse_edge_ids=[],
        reverse_corridor_share=1.0,
        impracticable_alongside=False,
    )


def _connection_row(
    candidate: _Candidate,
    graph: RoadGraph,
    *,
    obligation_kind: str,
) -> dict[str, object]:
    place_id = str(candidate.place["place_id"])
    frontier = candidate.frontier
    branch_id = frontier.branch_id or _stable_id(
        "spine-access-branch", frontier.root_spine_id, place_id
    )
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
        "status": "validated",
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
) -> dict[str, object]:
    place_id = str(place["place_id"])
    _, snap_distance_m = graph.nearest_node(place.geometry)
    bounded = snap_distance_m <= MAX_OBLIGATION_ATTACHMENT_M
    reason = (
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


def _branches(
    connections: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    crs: object,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    spine_names = strategic_spines.set_index("spine_id").get("name", pd.Series(dtype=object))
    for branch_id, members in connections.groupby("branch_id", sort=True):
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
