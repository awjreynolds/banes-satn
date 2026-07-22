"""Deterministic rural Backbone-Outward Assembly over the governed cycling graph."""

from __future__ import annotations

import heapq
import json
import logging
import time
from dataclasses import dataclass, replace

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import MultiPoint, Point
from shapely.ops import nearest_points

from satn.agents import CompilationGate
from satn.identifiers import stable_id as _stable_id
from satn.models import (
    ACCESS_OBLIGATION_COLUMNS,
    AccessPointStatus,
    AccessServiceStatus,
    AgentRecord,
    PublishedFeatureReference,
    TopographyConfig,
    TrafficLight,
)
from satn.routing import (
    RoadGraph,
    RouteOption,
    choose_alignment,
    serialise_options,
    stationary_route_option,
)
from satn.topography_alternatives import TopographyComparison, compare_alignment_topography

LOGGER = logging.getLogger(__name__)

MAX_OBLIGATION_ATTACHMENT_M = 2000.0
MAX_SPINE_ATTACHMENT_M = 20.0
MAX_SCHOOL_ATTACHMENT_M = 20.0

ACCESS_COLUMNS = [
    "access_connection_id",
    "obligation_id",
    "obligation_kind",
    "place_id",
    "place_name",
    "place_kind",
    "community_id",
    "community_name",
    "school_id",
    "school_name",
    "school_kind",
    "access_point_status",
    "access_point_source_id",
    "access_point_rationale",
    "spine_id",
    "spine_name",
    "spine_kind",
    "root_spine_id",
    "branch_id",
    "parent_branch_id",
    "parent_role",
    "parent_target_id",
    "parent_target_name",
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
    "topography_alternative_trigger",
    "topography_comparison_status",
    "topography_comparison_rationale",
    "topography_original_role",
    "topography_selected_role",
    "alignment_options",
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
    "topography_alternative_trigger",
    "topography_comparison_status",
    "topography_comparison_rationale",
    "topography_original_role",
    "topography_selected_role",
    "alignment_options",
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
    "school_id",
    "school_kind",
    "access_point_status",
    "access_point_source_id",
    "access_point_rationale",
    "source_ids",
    "cache_status",
    "alignment_options",
    "criterion_endpoints",
    "criterion_continuity",
    "criterion_bidirectional",
    "criterion_distance",
    "topography_alternative_trigger",
    "topography_comparison_status",
    "topography_comparison_rationale",
    "topography_original_role",
    "topography_selected_role",
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
    compilation_diagnostics: dict[str, object]


@dataclass(frozen=True)
class _Frontier:
    target_id: str
    target_name: str
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
    geometry: object
    projected_geometry: object


@dataclass(frozen=True)
class _Candidate:
    rank: tuple[object, ...]
    place: pd.Series
    frontier: _Frontier
    option: RouteOption
    options: tuple[RouteOption, ...]
    topography: TopographyComparison | None
    start_node: str
    start_snap_m: float
    end_node: str
    end_snap_m: float
    start_point: Point
    end_point: Point
    start_attachment_id: str
    end_attachment_id: str


@dataclass(frozen=True)
class _MeetingCandidate:
    rank: tuple[object, ...]
    left: pd.Series
    right: pd.Series
    option: RouteOption
    start_node: str
    end_node: str
    options: tuple[RouteOption, ...] = ()
    topography: TopographyComparison | None = None


def assemble_backbone_outward(
    communities: gpd.GeoDataFrame,
    schools: gpd.GeoDataFrame,
    gateways: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
    gate: CompilationGate,
    max_connection_km: float,
    elevation_evidence: gpd.GeoDataFrame | None = None,
    topography_config: TopographyConfig | None = None,
) -> BackboneAssembly:
    """Grow one deterministic served frontier from every Strategic Spine concurrently."""
    crs = communities.crs or schools.crs or strategic_spines.crs or graph.crs
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
    candidate_evaluations = 0
    total_communities = len(unserved)
    assembly_started = time.perf_counter()
    LOGGER.info(
        "Backbone assembly started strategic_spines=%d communities=%d schools=%d gateways=%d",
        len(strategic_spines),
        total_communities,
        len(schools),
        len(gateways),
    )

    def add_frontier_candidates(frontier: _Frontier) -> None:
        nonlocal candidate_evaluations, sequence
        for place_id in sorted(unserved):
            candidate_evaluations += 1
            candidate = _candidate(
                unserved[place_id],
                frontier,
                graph,
                obligation_kind="community",
                elevation_evidence=elevation_evidence,
                topography_config=topography_config,
            )
            if candidate is not None:
                heapq.heappush(candidate_heap, (candidate.rank, sequence, candidate))
                sequence += 1
            if candidate_evaluations % 250 == 0:
                elapsed_seconds = time.perf_counter() - assembly_started
                LOGGER.info(
                    "Backbone candidate heartbeat evaluated=%d served=%d/%d queue=%d "
                    "elapsed=%.1fs rate=%.1f/s",
                    candidate_evaluations,
                    total_communities - len(unserved),
                    total_communities,
                    len(candidate_heap),
                    elapsed_seconds,
                    candidate_evaluations / max(elapsed_seconds, 0.001),
                )

    initial_frontier_count = len(frontiers)
    for frontier in frontiers:
        add_frontier_candidates(frontier)

    while candidate_heap:
        _, _, selected = heapq.heappop(candidate_heap)
        place_id = str(selected.place["place_id"])
        if place_id not in unserved:
            continue
        selected = _with_topography(
            selected,
            graph,
            elevation_evidence,
            topography_config,
        )
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
        served_count = total_communities - len(unserved)
        LOGGER.debug(
            "Community access accepted place_id=%s served=%d/%d parent_role=%s",
            place_id,
            served_count,
            total_communities,
            row["parent_role"],
        )
        if served_count == 1 or served_count % 10 == 0 or not unserved:
            LOGGER.info(
                "Backbone community progress served=%d/%d remaining=%d candidate_queue=%d",
                served_count,
                total_communities,
                len(unserved),
                len(candidate_heap),
            )
        served_frontier = _served_frontier(row, graph)
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
    if unserved:
        LOGGER.warning("Unserved communities emitted as Network Gaps count=%d", len(unserved))

    community_connections = gpd.GeoDataFrame(
        rows, columns=ACCESS_COLUMNS, geometry="geometry", crs=crs
    )
    meeting_connections, cross_spine_connectors, meeting_records = _cross_spine_meetings(
        community_connections,
        strategic_spines,
        graph,
        gate,
        max_connection_km=max_connection_km,
        elevation_evidence=elevation_evidence,
        topography_config=topography_config,
    )
    agent_records.extend(meeting_records)
    LOGGER.info(
        "Cross-spine assembly completed meetings=%d connectors=%d",
        len(meeting_connections),
        len(cross_spine_connectors),
    )

    school_frontiers = _school_attachment_frontiers(
        strategic_spines,
        community_connections,
        cross_spine_connectors,
        graph,
    )
    for school_index, (_, school) in enumerate(schools.sort_values("place_id").iterrows(), start=1):
        if str(school.get("access_point_status")) == "unresolved":
            gap_rows.append(_gap_row(school, graph, obligation_kind="school"))
            continue
        rejected_school_records: list[AgentRecord] = []
        excluded_pairs: set[tuple[str, str]] = set()
        while selected := _school_candidate(
            school,
            school_frontiers,
            graph,
            excluded_pairs=excluded_pairs,
            elevation_evidence=elevation_evidence,
            topography_config=topography_config,
        ):
            row = _connection_row(selected, graph, obligation_kind="school")
            record = _evaluate(row, gate)
            agent_records.append(record)
            if record.decision != "accept":
                rejected_school_records.append(record)
                excluded_pairs.add((selected.start_node, selected.end_node))
                continue
            _record_gate_acceptance(row, record)
            for rejected in rejected_school_records:
                rejected.decision = "superseded"
                rejected.outcome_reason = (
                    "A different governed School-to-backbone attachment was accepted."
                )
            rows.append(row)
            break
        else:
            gap_rows.append(
                _gap_row(
                    school,
                    graph,
                    obligation_kind="school",
                    gate_reason=(
                        rejected_school_records[-1].outcome_reason
                        if rejected_school_records
                        else None
                    ),
                )
            )
        if school_index == 1 or school_index % 10 == 0 or school_index == len(schools):
            LOGGER.info(
                "School access progress assessed=%d/%d",
                school_index,
                len(schools),
            )

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
                    elevation_evidence=elevation_evidence,
                    topography_config=topography_config,
                )
            )
            is not None
        ]
        if not candidates:
            gap_rows.append(_gap_row(gateway, graph, obligation_kind="gateway"))
            continue
        for selected in sorted(candidates, key=lambda candidate: candidate.rank):
            selected = _with_topography(
                selected,
                graph,
                elevation_evidence,
                topography_config,
            )
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

    LOGGER.info(
        "Backbone assembly completed access_connections=%d gaps=%d "
        "connected_gateways=%d/%d elapsed=%.1fs",
        len(rows),
        len(gap_rows),
        connected_gateways,
        len(gateways),
        time.perf_counter() - assembly_started,
    )
    LOGGER.debug("Backbone candidate evaluations total=%d", candidate_evaluations)

    connections = gpd.GeoDataFrame(
        rows, columns=ACCESS_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("access_connection_id")
    gaps = gpd.GeoDataFrame(
        gap_rows, columns=GAP_COLUMNS, geometry="geometry", crs=crs
    ).sort_values("connection_id")
    obligations = _obligations(communities, schools, connections, gaps)
    branches = _branches(connections, strategic_spines, crs)
    graph_diagnostics = graph.compilation_diagnostics()
    optimization_findings: list[dict[str, object]] = []
    if candidate_evaluations >= 1_000:
        optimization_findings.append(
            {
                "finding_id": "serial-frontier-candidate-evaluation",
                "finding": (
                    "Backbone candidates were evaluated serially across a large finite "
                    "frontier-obligation search space."
                ),
                "evidence": {
                    "candidate_evaluations": candidate_evaluations,
                    "initial_frontiers": initial_frontier_count,
                    "final_frontiers": len(frontiers),
                },
                "potential_optimization": (
                    "Batch or safely parallelise independent initial-frontier searches while "
                    "preserving deterministic candidate ranking."
                ),
            }
        )
    if graph_diagnostics["nearby_node_candidate_set_reuses"]:
        optimization_findings.append(
            {
                "finding_id": "repeated-node-association-search",
                "status": "optimized-during-compilation-development",
                "finding": (
                    "Multiple spine candidates reused the same community-to-node association set."
                ),
                "evidence": {
                    "unique_candidate_sets": graph_diagnostics["nearby_node_candidate_sets"],
                    "candidate_set_reuses": graph_diagnostics["nearby_node_candidate_set_reuses"],
                },
                "applied_optimization": (
                    "Cache immutable point-to-node candidate sets for the duration of a run."
                ),
            }
        )
    if graph_diagnostics["unmaterializable_attachment_paths"]:
        optimization_findings.append(
            {
                "finding_id": "unmaterializable-osm-attachment-paths",
                "status": "bounded-and-visible",
                "finding": ("Some graph paths could not be merged into valid governed linework."),
                "evidence": {"path_count": graph_diagnostics["unmaterializable_attachment_paths"]},
                "applied_optimization": (
                    "Reject the affected candidate pair without exhaustive start/end retries; "
                    "continue evaluating other governed frontiers."
                ),
                "potential_optimization": (
                    "Normalize disconnected OSM edge geometry at snapshot ingestion."
                ),
            }
        )
    compilation_diagnostics: dict[str, object] = {
        "assembly_strategy": "backbone-outward",
        "candidate_evaluations": candidate_evaluations,
        "initial_frontiers": initial_frontier_count,
        "final_frontiers": len(frontiers),
        "served_communities": total_communities - len(unserved),
        "unserved_communities": len(unserved),
        "optimization_findings": optimization_findings,
        **graph_diagnostics,
    }
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
        compilation_diagnostics=compilation_diagnostics,
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
                target_name=str(spine.get("name") or spine["spine_id"]),
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
                geometry=spine.geometry,
                projected_geometry=gpd.GeoSeries([spine.geometry], crs=graph.crs)
                .to_crs(27700)
                .iloc[0],
            )
        )
    return sorted(frontiers, key=_frontier_key)


def _served_frontier(row: dict[str, object], graph: RoadGraph) -> _Frontier:
    return _Frontier(
        target_id=str(row["access_connection_id"]),
        target_name=str(row.get("place_name") or row["access_connection_id"]),
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
        geometry=row["geometry"],
        projected_geometry=gpd.GeoSeries([row["geometry"]], crs=graph.crs).to_crs(27700).iloc[0],
    )


def _school_attachment_frontiers(
    strategic_spines: gpd.GeoDataFrame,
    community_connections: gpd.GeoDataFrame,
    cross_spine_connectors: gpd.GeoDataFrame,
    graph: RoadGraph,
) -> list[_Frontier]:
    """Expose fixed backbone geometry to Schools without making Schools new frontiers."""
    frontiers = _spine_frontiers(strategic_spines, graph)
    for _, connection in community_connections.sort_values("access_connection_id").iterrows():
        provenance = json.loads(str(connection["provenance"]))
        attachments = tuple(graph.nodes_on_geometry(connection.geometry))
        if not attachments:
            continue
        frontiers.append(
            _Frontier(
                target_id=str(connection["access_connection_id"]),
                target_name=str(
                    f"{connection.get('place_name')} Spine Access Connection"
                    if connection.get("place_name")
                    else connection["access_connection_id"]
                ),
                target_role="spine-access-connection",
                target_place_id=str(connection["place_id"]),
                root_spine_id=str(connection["root_spine_id"]),
                root_spine_name=str(connection["spine_name"]),
                root_spine_kind=str(connection["spine_kind"]),
                root_evidence_id=str(provenance["root_evidence_id"]),
                root_source_id=str(provenance["root_source_id"]),
                branch_id=str(connection["branch_id"]),
                parent_access_connection_id=str(connection["access_connection_id"]),
                depth=int(connection["attachment_depth"]),
                attachments=attachments,
                geometry=connection.geometry,
                projected_geometry=gpd.GeoSeries([connection.geometry], crs=graph.crs)
                .to_crs(27700)
                .iloc[0],
            )
        )
    spine_by_id = strategic_spines.set_index("spine_id", drop=False)
    for _, connector in cross_spine_connectors.sort_values("cross_spine_connector_id").iterrows():
        root_id = str(connector["from_root_spine_id"])
        spine = spine_by_id.loc[root_id]
        attachments = tuple(graph.nodes_on_geometry(connector.geometry))
        if not attachments:
            continue
        frontiers.append(
            _Frontier(
                target_id=str(connector["cross_spine_connector_id"]),
                target_name=(
                    f"{connector['from_root_spine_name']} → "
                    f"{connector['to_root_spine_name']} connector"
                ),
                target_role="cross-spine-connector",
                target_place_id=None,
                root_spine_id=root_id,
                root_spine_name=str(spine.get("name") or root_id),
                root_spine_kind=str(spine["spine_kind"]),
                root_evidence_id=str(spine["evidence_id"]),
                root_source_id=str(spine["source_id"]),
                branch_id=None,
                parent_access_connection_id=None,
                depth=0,
                attachments=attachments,
                geometry=connector.geometry,
                projected_geometry=gpd.GeoSeries([connector.geometry], crs=graph.crs)
                .to_crs(27700)
                .iloc[0],
            )
        )
    return sorted(frontiers, key=_frontier_key)


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
    elevation_evidence: gpd.GeoDataFrame | None = None,
    topography_config: TopographyConfig | None = None,
) -> _Candidate | None:
    starts = graph.nodes_near(place.geometry, MAX_OBLIGATION_ATTACHMENT_M)
    if not starts:
        return None
    ends = [
        attachment for attachment in frontier.attachments if attachment[1] <= MAX_SPINE_ATTACHMENT_M
    ]
    choices = []
    end_snap_by_node: dict[str, float] = {}
    for node_id, snap_m in ends:
        end_snap_by_node[node_id] = min(
            snap_m,
            end_snap_by_node.get(node_id, float("inf")),
        )
    overlap_nodes = {node_id for node_id, _ in starts if node_id in end_snap_by_node}
    routed_starts = (
        [attachment for attachment in starts if attachment[0] not in overlap_nodes]
        if allow_stationary
        else starts
    )
    # An overlapping start can never improve upon its own zero-length attachment.
    # Excluding those nodes keeps the multi-source search bounded without changing
    # the selected route when a lower-snap routed start is genuinely preferable.
    routed = graph.best_attachment(
        routed_starts,
        ends,
        allow_stationary=allow_stationary,
    )
    if routed is not None:
        choices.append(routed)
    if allow_stationary:
        for start_node, start_snap_m in starts:
            if start_node not in end_snap_by_node:
                continue
            stationary = graph.best_attachment(
                [(start_node, start_snap_m)],
                [(start_node, end_snap_by_node[start_node])],
                allow_stationary=True,
            )
            if stationary is not None:
                choices.append(stationary)
    if not choices:
        return None
    choice = min(
        choices,
        key=lambda candidate: (
            round(candidate.total_distance_km, 9),
            round(candidate.start_snap_m, 9),
            candidate.start_node,
            candidate.end_node,
        ),
    )
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
        options=(choice.option,),
        topography=None,
        start_node=choice.start_node,
        start_snap_m=choice.start_snap_m,
        end_node=choice.end_node,
        end_snap_m=choice.end_snap_m,
        start_point=choice.start_point,
        end_point=choice.end_point,
        start_attachment_id=choice.start_attachment_id,
        end_attachment_id=choice.end_attachment_id,
    )


def _with_topography(
    candidate: _Candidate,
    graph: RoadGraph,
    elevation_evidence: gpd.GeoDataFrame | None,
    topography_config: TopographyConfig | None,
) -> _Candidate:
    """Evaluate governed alternatives only after a ranked candidate is selected."""
    option, options, comparison = _topography_choice(
        graph,
        candidate.start_node,
        candidate.end_node,
        candidate.option,
        elevation_evidence,
        topography_config,
    )
    return replace(
        candidate,
        option=option,
        options=tuple(options),
        topography=comparison,
    )


def _topography_choice(
    graph: RoadGraph,
    start_node: str,
    end_node: str,
    fallback: RouteOption,
    elevation_evidence: gpd.GeoDataFrame | None,
    topography_config: TopographyConfig | None,
) -> tuple[RouteOption, list[RouteOption], TopographyComparison | None]:
    if start_node == end_node:
        return fallback, [fallback], None
    selected, options, _ = choose_alignment(graph, start_node, end_node)
    selected = selected or fallback
    options = options or [fallback]
    if elevation_evidence is None or topography_config is None:
        return selected, options, None
    comparison = compare_alignment_topography(
        selected,
        options,
        elevation_evidence,
        topography_config,
        graph.crs,
    )
    return (
        comparison.selected if comparison is not None else selected,
        options,
        comparison,
    )


def _school_candidate(
    school: pd.Series,
    frontiers: list[_Frontier],
    graph: RoadGraph,
    *,
    excluded_pairs: set[tuple[str, str]],
    elevation_evidence: gpd.GeoDataFrame | None = None,
    topography_config: TopographyConfig | None = None,
) -> _Candidate | None:
    """Route once from a School to all labelled fixed-backbone attachments."""
    direct = _direct_school_candidate(school, frontiers, graph, excluded_pairs)
    if direct is not None:
        return direct
    ends = [
        attachment
        for frontier in frontiers
        for attachment in frontier.attachments
        if attachment[1] <= MAX_SPINE_ATTACHMENT_M
    ]
    choice = graph.best_point_attachment(
        school.geometry,
        MAX_SCHOOL_ATTACHMENT_M,
        ends,
        excluded_pairs=excluded_pairs,
    )
    if choice is None:
        return None
    option, options, comparison = _topography_choice(
        graph,
        choice.start_node,
        choice.end_node,
        choice.option,
        elevation_evidence,
        topography_config,
    )
    matching_frontiers = [
        (snap_m, frontier)
        for frontier in frontiers
        for node_id, snap_m in frontier.attachments
        if node_id == choice.end_node and snap_m <= MAX_SPINE_ATTACHMENT_M
    ]
    if not matching_frontiers:
        return None
    _, frontier = min(
        matching_frontiers,
        key=lambda match: (round(match[0], 9), _frontier_key(match[1])),
    )
    rank = (
        round(choice.total_distance_km, 9),
        str(school["place_id"]),
        0 if frontier.target_role == "strategic-spine" else 1,
        frontier.root_spine_id,
        frontier.target_id,
        choice.start_node,
        choice.end_node,
        "school",
    )
    return _Candidate(
        rank=rank,
        place=school,
        frontier=frontier,
        option=option,
        options=tuple(options),
        topography=comparison,
        start_node=choice.start_node,
        start_snap_m=choice.start_snap_m,
        end_node=choice.end_node,
        end_snap_m=choice.end_snap_m,
        start_point=choice.start_point,
        end_point=choice.end_point,
        start_attachment_id=choice.start_attachment_id,
        end_attachment_id=choice.end_attachment_id,
    )


def _direct_school_candidate(
    school: pd.Series,
    frontiers: list[_Frontier],
    graph: RoadGraph,
    excluded_pairs: set[tuple[str, str]],
) -> _Candidate | None:
    projected_school = gpd.GeoSeries([school.geometry], crs=graph.crs).to_crs(27700).iloc[0]
    nearby: list[tuple[float, _Frontier, Point, str]] = []
    for frontier in frontiers:
        distance_m = float(projected_school.distance(frontier.projected_geometry))
        if distance_m > MAX_SCHOOL_ATTACHMENT_M:
            continue
        _, projected_attachment = nearest_points(projected_school, frontier.projected_geometry)
        attachment = gpd.GeoSeries([projected_attachment], crs=27700).to_crs(graph.crs).iloc[0]
        virtual_node = _stable_id(
            "school-frontier-attachment", frontier.target_id, attachment.wkb_hex
        )
        if (virtual_node, virtual_node) not in excluded_pairs:
            nearby.append((distance_m, frontier, attachment, virtual_node))
    if not nearby or not graph.has_point_attachment(school.geometry, MAX_SCHOOL_ATTACHMENT_M):
        return None
    association_m, frontier, attachment, virtual_node = min(
        nearby,
        key=lambda match: (round(match[0], 9), _frontier_key(match[1])),
    )
    option = stationary_route_option(attachment)
    return _Candidate(
        rank=(
            round(association_m / 1000, 9),
            str(school["place_id"]),
            0 if frontier.target_role == "strategic-spine" else 1,
            frontier.root_spine_id,
            frontier.target_id,
            virtual_node,
            virtual_node,
            "school",
        ),
        place=school,
        frontier=frontier,
        option=option,
        options=(option,),
        topography=None,
        start_node=virtual_node,
        start_snap_m=association_m,
        end_node=virtual_node,
        end_snap_m=0.0,
        start_point=attachment,
        end_point=attachment,
        start_attachment_id=virtual_node,
        end_attachment_id=virtual_node,
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
            "to_place": str(row["parent_target_id"]),
            "target_role": str(row["parent_role"]),
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
    record.network_role = str(row["network_role"])
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
    if branch_id is None and obligation_kind in {"community", "school"}:
        branch_id = _stable_id("spine-access-branch", frontier.root_spine_id, place_id)
    parent_id = frontier.target_id
    route_identity = json.dumps(
        [
            candidate.start_node,
            candidate.end_node,
            *candidate.option.edge_ids,
            "reverse",
            *candidate.option.reverse_edge_ids,
        ]
    )
    connection_id = _stable_id(
        "spine-access",
        place_id,
        frontier.root_spine_id,
        parent_id,
        route_identity,
    )
    source_ids = sorted(
        {
            *candidate.option.edge_ids,
            *candidate.option.reverse_edge_ids,
            frontier.root_evidence_id,
            frontier.root_source_id,
            *(
                {
                    str(candidate.place.get("evidence_id")),
                    str(candidate.place.get("source_id")),
                    str(candidate.place.get("access_point_source_id")),
                }
                if obligation_kind == "school"
                else set()
            ),
        }
    )
    source_ids = [source_id for source_id in source_ids if source_id not in {"None", "nan"}]
    network_role = {
        "community": "spine-access-connection",
        "school": "school-access-connection",
        "gateway": "gateway-access-connection",
    }[obligation_kind]
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
        "parent_target_id": frontier.target_id,
        "parent_target_name": frontier.target_name,
        "parent_place_id": frontier.target_place_id,
        "parent_access_connection_id": frontier.parent_access_connection_id,
        "source_ids": source_ids,
    }
    if obligation_kind == "school":
        provenance.update(
            {
                "school_id": place_id,
                "school_kind": candidate.place.get("school_kind"),
                "access_point_status": candidate.place.get("access_point_status"),
                "access_point_source_id": candidate.place.get("access_point_source_id"),
                "access_point_rationale": candidate.place.get("access_point_rationale"),
            }
        )
    direct_to_spine = frontier.target_role == "strategic-spine"
    topography = candidate.topography
    default_selection_reason = (
        (
            "Selected from the governed School Access Point by minimum plausible "
            "cycling-network cost to fixed Strategic Spine, Cross-Spine Connector "
            f"or established branch geometry; attached to {frontier.target_role} "
            "without creating a School peer journey objective."
        )
        if obligation_kind == "school"
        else (
            "Selected by minimum plausible cycling-network cost from all concurrent "
            f"Strategic Spine and served-branch frontiers; extended {frontier.target_role}."
        )
    )
    return {
        "access_connection_id": connection_id,
        "obligation_id": (
            _stable_id(
                "school-access-obligation" if obligation_kind == "school" else "access-obligation",
                place_id,
            )
            if obligation_kind in {"community", "school"}
            else None
        ),
        "obligation_kind": obligation_kind,
        "place_id": place_id,
        "place_name": candidate.place.get("name"),
        "place_kind": candidate.place.get("kind"),
        "community_id": place_id if obligation_kind == "community" else None,
        "community_name": (candidate.place.get("name") if obligation_kind == "community" else None),
        "school_id": place_id if obligation_kind == "school" else None,
        "school_name": candidate.place.get("name") if obligation_kind == "school" else None,
        "school_kind": candidate.place.get("school_kind") if obligation_kind == "school" else None,
        "access_point_status": (
            candidate.place.get("access_point_status") if obligation_kind == "school" else None
        ),
        "access_point_source_id": (
            candidate.place.get("access_point_source_id") if obligation_kind == "school" else None
        ),
        "access_point_rationale": (
            candidate.place.get("access_point_rationale") if obligation_kind == "school" else None
        ),
        "spine_id": frontier.root_spine_id,
        "spine_name": frontier.root_spine_name,
        "spine_kind": frontier.root_spine_kind,
        "root_spine_id": frontier.root_spine_id,
        "branch_id": branch_id,
        "parent_branch_id": frontier.branch_id,
        "parent_role": frontier.target_role,
        "parent_target_id": frontier.target_id,
        "parent_target_name": frontier.target_name,
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
            topography.rationale
            if topography is not None and topography.triggered
            else default_selection_reason
        ),
        "geometry_semantics": (
            "routed OSM network alignment between canonical graph attachment points; "
            "snap distances are evidence associations, not claimed paths or final design"
        ),
        "community_attachment_node": candidate.start_attachment_id,
        "community_attachment_distance_m": round(candidate.start_snap_m, 3),
        "community_attachment_point": candidate.start_point.wkt,
        "target_attachment_node": candidate.end_attachment_id,
        "target_attachment_distance_m": round(candidate.end_snap_m, 3),
        "target_attachment_point": candidate.end_point.wkt,
        "spine_attachment_node": candidate.end_attachment_id if direct_to_spine else None,
        "spine_attachment_distance_m": (
            round(candidate.end_snap_m, 3) if direct_to_spine else None
        ),
        "spine_attachment_point": (candidate.end_point.wkt if direct_to_spine else None),
        "source_ids": json.dumps(source_ids),
        "provenance": json.dumps(provenance, sort_keys=True),
        "criterion_continuity": "green",
        "criterion_bidirectional": "green",
        **_topography_payload(
            topography,
            candidate.option,
            candidate.options,
            publish_alignment_options=obligation_kind == "community",
        ),
        "geometry": candidate.option.geometry,
    }


def _topography_payload(
    topography: TopographyComparison | None,
    selected: RouteOption,
    options: tuple[RouteOption, ...],
    *,
    publish_alignment_options: bool,
) -> dict[str, object]:
    """Serialise one governed topography selection without widening domain terms."""
    governed_options = list(options or (selected,))
    return {
        "topography_alternative_trigger": (
            topography.triggered if topography is not None else False
        ),
        "topography_comparison_status": (
            topography.status.value if topography is not None else "not-evaluated"
        ),
        "topography_comparison_rationale": (
            topography.rationale if topography is not None else "Not evaluated."
        ),
        "topography_original_role": (
            topography.original.role if topography is not None else None
        ),
        "topography_selected_role": selected.role,
        "alignment_options": (
            (
                topography.serialise_options(governed_options, selected.role)
                if topography is not None
                else serialise_options(governed_options)
            )
            if publish_alignment_options
            else None
        ),
    }


def _gap_row(
    place: pd.Series,
    graph: RoadGraph,
    *,
    obligation_kind: str,
    gate_reason: str | None = None,
) -> dict[str, object]:
    place_id = str(place["place_id"])
    unresolved_school_access = (
        obligation_kind == "school" and str(place.get("access_point_status")) == "unresolved"
    )
    snap_distance_m = (
        float("inf") if unresolved_school_access else graph.nearest_node(place.geometry)[1]
    )
    attachment_bound_m = (
        MAX_SCHOOL_ATTACHMENT_M if obligation_kind == "school" else MAX_OBLIGATION_ATTACHMENT_M
    )
    bounded = (
        graph.has_point_attachment(place.geometry, attachment_bound_m)
        if obligation_kind == "school" and not unresolved_school_access
        else snap_distance_m <= attachment_bound_m
    )
    reason = gate_reason or (
        str(place.get("access_point_rationale"))
        if unresolved_school_access
        else (
            "No continuous bidirectional OSM cycling-network path reaches any Strategic Spine "
            "or served branch frontier."
            if bounded
            else (
                "The reference point has no routable graph attachment within the governed "
                f"{attachment_bound_m:.0f} metre bound."
            )
        )
    )
    return {
        "connection_id": _stable_id("spine-access-gap", obligation_kind, place_id),
        "network_role": {
            "community": "spine-access-gap",
            "school": "school-access-gap",
            "gateway": "gateway-access-gap",
        }[obligation_kind],
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
        "school_id": place_id if obligation_kind == "school" else None,
        "school_kind": place.get("school_kind") if obligation_kind == "school" else None,
        "access_point_status": (
            place.get("access_point_status") if obligation_kind == "school" else None
        ),
        "access_point_source_id": (
            place.get("access_point_source_id") if obligation_kind == "school" else None
        ),
        "access_point_rationale": (
            place.get("access_point_rationale") if obligation_kind == "school" else None
        ),
        "source_ids": "[]",
        "cache_status": "not-cacheable",
        "alignment_options": "[]",
        "criterion_endpoints": (
            "grey" if unresolved_school_access else "green" if bounded else "red"
        ),
        "criterion_continuity": "red",
        "criterion_bidirectional": "red",
        "criterion_distance": "grey",
        "topography_alternative_trigger": False,
        "topography_comparison_status": (
            "gate-rejected-selection" if gate_reason else "not-evaluated"
        ),
        "topography_comparison_rationale": (
            "Compilation Gate rejected every candidate after bounded review; no "
            "authoritative topography selection is published."
            if gate_reason
            else "No routed alignment was available for topography comparison."
        ),
        "topography_original_role": None,
        "topography_selected_role": None,
        "geometry": MultiPoint([place.geometry]),
    }


def _obligations(
    communities: gpd.GeoDataFrame,
    schools: gpd.GeoDataFrame,
    connections: gpd.GeoDataFrame,
    gaps: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    served_communities = {
        str(row["place_id"]): row
        for _, row in connections[connections["obligation_kind"] == "community"].iterrows()
    }
    served_schools = {
        str(row["place_id"]): row
        for _, row in connections[connections["obligation_kind"] == "school"].iterrows()
    }
    community_gap_ids = set(
        gaps.loc[gaps["network_role"] == "spine-access-gap", "from_place"].astype(str)
    )
    school_gap_ids = set(
        gaps.loc[gaps["network_role"] == "school-access-gap", "from_place"].astype(str)
    )
    rows: list[dict[str, object]] = []
    for _, community in communities.sort_values("place_id").iterrows():
        place_id = str(community["place_id"])
        access = served_communities.get(place_id)
        service_status = (
            AccessServiceStatus.SERVED.value
            if access is not None
            else AccessServiceStatus.NETWORK_GAP.value
        )
        provenance = {
            "community_id": place_id,
            "service_status": service_status,
            "access_connection_id": (
                str(access["access_connection_id"]) if access is not None else None
            ),
            "gap_id": (
                _stable_id("spine-access-gap", "community", place_id)
                if place_id in community_gap_ids
                else None
            ),
        }
        rows.append(
            {
                "obligation_id": _stable_id("access-obligation", place_id),
                "obligation_kind": "community",
                "place_id": place_id,
                "community_id": place_id,
                "school_id": None,
                "school_kind": None,
                "name": community.get("name"),
                "network_role": "community-access-obligation",
                "service_status": service_status,
                "service_rationale": (
                    "Community has one governed parent access edge to the assembled backbone."
                    if access is not None
                    else "Community remains exposed as a Network Gap."
                ),
                "access_point_status": None,
                "access_point_source_id": None,
                "access_point_rationale": None,
                "criterion_access_point": "grey",
                "access_connection_id": (
                    access["access_connection_id"] if access is not None else None
                ),
                "root_spine_id": access["root_spine_id"] if access is not None else None,
                "branch_id": access["branch_id"] if access is not None else None,
                "provenance": json.dumps(provenance, sort_keys=True),
                "geometry": community.geometry,
            }
        )
    for _, school in schools.sort_values("place_id").iterrows():
        school_id = str(school["place_id"])
        access = served_schools.get(school_id)
        access_status = AccessPointStatus(str(school.get("access_point_status"))).value
        service_status = (
            AccessServiceStatus.SERVED.value
            if access is not None and access_status == AccessPointStatus.MAPPED.value
            else AccessServiceStatus.SERVED_PROVISIONAL.value
            if access is not None
            else AccessServiceStatus.NETWORK_GAP.value
        )
        provenance = {
            "school_id": school_id,
            "school_kind": school.get("school_kind"),
            "access_point_status": access_status,
            "access_point_source_id": school.get("access_point_source_id"),
            "service_status": service_status,
            "access_connection_id": (
                str(access["access_connection_id"]) if access is not None else None
            ),
            "gap_id": (
                _stable_id("spine-access-gap", "school", school_id)
                if school_id in school_gap_ids
                else None
            ),
        }
        rows.append(
            {
                "obligation_id": _stable_id("school-access-obligation", school_id),
                "obligation_kind": "school",
                "place_id": school_id,
                "community_id": None,
                "school_id": school_id,
                "school_kind": school.get("school_kind"),
                "name": school.get("name"),
                "network_role": "school-access-obligation",
                "service_status": service_status,
                "service_rationale": (
                    "Mapped School Access Point has one governed parent edge to fixed "
                    "backbone geometry."
                    if service_status == AccessServiceStatus.SERVED.value
                    else (
                        "Inferred School Access Point reaches fixed backbone geometry but "
                        "remains subject to verification."
                        if service_status == AccessServiceStatus.SERVED_PROVISIONAL.value
                        else "School access is unresolved and remains visible as a Network Gap."
                    )
                ),
                "access_point_status": access_status,
                "access_point_source_id": school.get("access_point_source_id"),
                "access_point_rationale": school.get("access_point_rationale"),
                "criterion_access_point": {
                    AccessPointStatus.MAPPED.value: TrafficLight.GREEN.value,
                    AccessPointStatus.INFERRED.value: TrafficLight.AMBER.value,
                    AccessPointStatus.UNRESOLVED.value: TrafficLight.GREY.value,
                }.get(access_status, TrafficLight.GREY.value),
                "access_connection_id": (
                    access["access_connection_id"] if access is not None else None
                ),
                "root_spine_id": access["root_spine_id"] if access is not None else None,
                "branch_id": access["branch_id"] if access is not None else None,
                "provenance": json.dumps(provenance, sort_keys=True),
                "geometry": school.geometry,
            }
        )
    return gpd.GeoDataFrame(
        rows,
        columns=ACCESS_OBLIGATION_COLUMNS,
        geometry="geometry",
        crs=communities.crs or schools.crs,
    )


def _cross_spine_meetings(
    connections: gpd.GeoDataFrame,
    strategic_spines: gpd.GeoDataFrame,
    graph: RoadGraph,
    gate: CompilationGate,
    *,
    max_connection_km: float,
    elevation_evidence: gpd.GeoDataFrame | None = None,
    topography_config: TopographyConfig | None = None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, list[AgentRecord]]:
    crs = connections.crs or strategic_spines.crs or graph.crs
    root_ids = sorted(
        str(root_id)
        for root_id in connections.get("root_spine_id", pd.Series(dtype=object)).dropna().unique()
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
            elevation_evidence=elevation_evidence,
            topography_config=topography_config,
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
        _, _, left_root, right_root, excluded_pairs, candidate = heapq.heappop(candidate_heap)
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
    connectors_by_meeting = {
        str(row.meeting_connection_id): row for row in connectors.itertuples()
    }
    for record in records:
        connector = connectors_by_meeting.get(record.connection_id)
        if record.decision == "accept" and connector is not None:
            record.derived_features = [
                PublishedFeatureReference(
                    feature_id=str(connector.cross_spine_connector_id),
                    network_role=str(connector.network_role),
                )
            ]
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
    elevation_evidence: gpd.GeoDataFrame | None = None,
    topography_config: TopographyConfig | None = None,
) -> _MeetingCandidate | None:
    choice = graph.best_attachment(
        [(str(row["community_attachment_node"]), 0.0) for _, row in left_group.iterrows()],
        [(str(row["community_attachment_node"]), 0.0) for _, row in right_group.iterrows()],
        allow_stationary=False,
        excluded_pairs=excluded_pairs,
    )
    if choice is None:
        return None
    option, options, comparison = _topography_choice(
        graph,
        choice.start_node,
        choice.end_node,
        choice.option,
        elevation_evidence,
        topography_config,
    )
    left = left_group[left_group["community_attachment_node"] == choice.start_node].iloc[0]
    right = right_group[right_group["community_attachment_node"] == choice.end_node].iloc[0]
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
        option=option,
        options=tuple(options),
        topography=comparison,
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
    meeting_id = _stable_id("branch-meeting", left_root, right_root, left_place, right_place)
    source_ids = sorted({*candidate.option.edge_ids, *candidate.option.reverse_edge_ids})
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
    topography = candidate.topography
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
            topography.rationale
            if topography is not None and topography.triggered
            else (
                "Selected as the first justified cycling-network adjacency between differently "
                "rooted served fronts; later parallel or cyclic meetings are suppressed."
            )
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
        "criterion_distance": ("amber" if route_length_km > max_connection_km else "green"),
        **_topography_payload(
            topography,
            candidate.option,
            candidate.options,
            publish_alignment_options=True,
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
    record.network_role = str(row["network_role"])
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
        members = {str(member["access_connection_id"]): member for member in member_rows}
        connection_ids = sorted([*members, str(meeting["meeting_connection_id"])])
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
    branch_connections = connections[connections["obligation_kind"].isin(["community", "school"])]
    for branch_id, members in branch_connections.groupby("branch_id", sort=True):
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
