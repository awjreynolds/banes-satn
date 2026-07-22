"""Assess Urban Community access through Candidate Low-Traffic Area fabric."""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations, pairwise

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, MultiPoint
from shapely.ops import unary_union

from satn.backbone import GAP_COLUMNS
from satn.evidence import continuous_linework
from satn.identifiers import coordinate_key as _coordinate
from satn.identifiers import stable_id as _stable_id
from satn.models import ACCESS_OBLIGATION_COLUMNS, AccessServiceStatus, NetworkScope, TrafficLight
from satn.routing import LOW_TRAFFIC, RoadGraph, RoutedAttachment
from satn.tags import tag_values as _tag_values

FABRIC_CONTACT_TOLERANCE_M = 0.1
COMMUNITY_POINT_ASSOCIATION_MAX_M = 250.0
SPINE_NODE_ASSOCIATION_MAX_M = 20.0
SPINE_PORTAL_MAPPING_MAX_M = 250.0


@dataclass(frozen=True)
class _FabricRecord:
    start: str
    end: str
    source_id: str
    geometry: LineString


@dataclass(frozen=True)
class _FabricComponent:
    source_ids: tuple[str, ...]
    geometry: object


@dataclass(frozen=True)
class _PortalTarget:
    node_id: str
    association_m: float
    portal: pd.Series
    fabric_source_ids: tuple[str, ...]
    portal_mapping_distance_m: float


@dataclass(frozen=True)
class _CommunityTarget:
    node_id: str
    association_m: float
    community_id: str
    community_name: str


def assess_urban_community_access(
    communities: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
    urban_spines: gpd.GeoDataFrame,
    road_graph: RoadGraph,
    *,
    attachment_maximum_m: float,
) -> gpd.GeoDataFrame:
    """Account for every Urban Community without selecting residential centrelines."""
    crs = communities.crs or network.crs or areas.crs or portals.crs
    if communities.empty:
        return gpd.GeoDataFrame(
            columns=ACCESS_OBLIGATION_COLUMNS,
            geometry="geometry",
            crs=crs,
        )

    projected_communities = communities.to_crs(27700)
    projected_areas = areas.to_crs(27700)
    projected_portals = portals.to_crs(27700)
    projected_urban_spines = urban_spines.to_crs(27700)
    components = _fabric_components(network.to_crs(27700), projected_areas)
    area_graph, area_components = _area_graph(projected_areas, components)
    rooted_portals = _rooted_portals(projected_portals, area_components)
    portal_targets = _portal_targets(
        road_graph,
        rooted_portals,
        projected_urban_spines,
    )

    rows: list[dict[str, object]] = []
    for _, community in projected_communities.sort_values("place_id").iterrows():
        candidate_areas = projected_areas[
            projected_areas.geometry.covers(community.geometry)
        ].sort_values("structure_id")
        if candidate_areas.empty:
            routed = _routable_portal_attachment(
                community,
                road_graph,
                portal_targets,
                attachment_maximum_m,
            )
            if routed is None:
                rows.append(
                    _record(
                        community,
                        service_status=AccessServiceStatus.NETWORK_GAP,
                        service_rationale=(
                            "The Urban Community Reference Point has no bidirectionally "
                            "routable association to an Urban Main-Road Spine connected to "
                            "a rooted Candidate Low-Traffic Area portal within "
                            f"the governed {attachment_maximum_m:.1f}-metre route maximum "
                            f"and {COMMUNITY_POINT_ASSOCIATION_MAX_M:.1f}-metre point "
                            "association maximum."
                        ),
                        finding="no-bounded-routable-urban-spine",
                        criterion_continuity=TrafficLight.RED,
                    )
                )
                continue
            route, target = routed
            area = projected_areas[
                projected_areas["structure_id"].astype(str) == str(target.portal["area_id"])
            ].iloc[0]
            rows.append(
                _record(
                    community,
                    service_status=AccessServiceStatus.SERVED_PROVISIONAL,
                    service_rationale=(
                        "The Urban Community Reference Point has a provisional point-only "
                        "association to an Urban Main-Road Spine through the governed "
                        "bidirectional road graph, attributed to a rooted Candidate "
                        "Low-Traffic Area portal; total route cost "
                        f"{route.total_distance_km * 1000 + target.portal_mapping_distance_m:.1f} "
                        "metres is within the "
                        f"{attachment_maximum_m:.1f}-metre maximum and no residential "
                        "centreline is published."
                    ),
                    finding=None,
                    criterion_continuity=TrafficLight.AMBER,
                    area=area,
                    portal=target.portal,
                    area_chain=[str(area["structure_id"])],
                    fabric_source_ids=target.fabric_source_ids,
                    service_via="routable-urban-main-road-spine",
                    attachment_distance_m=route.start_snap_m,
                    attachment_maximum_m=attachment_maximum_m,
                    network_distance_m=route.option.length_km * 1000,
                    portal_association_distance_m=route.end_snap_m,
                    portal_mapping_distance_m=target.portal_mapping_distance_m,
                    total_route_cost_m=(
                        route.total_distance_km * 1000 + target.portal_mapping_distance_m
                    ),
                    route_edge_source_ids=tuple(route.option.edge_ids),
                    reverse_route_edge_source_ids=tuple(route.option.reverse_edge_ids),
                )
            )
            continue

        selected = _select_rooted_path(candidate_areas, area_graph, rooted_portals)
        if selected is None:
            area = candidate_areas.iloc[0] if not candidate_areas.empty else None
            finding = (
                "no-candidate-low-traffic-area"
                if candidate_areas.empty
                else "no-urban-main-road-portal"
                if not rooted_portals
                else "discontinuous-low-traffic-area-chain"
            )
            rationale = {
                "no-candidate-low-traffic-area": (
                    "The Urban Community Reference Point is not inside a Candidate "
                    "Low-Traffic Area."
                ),
                "no-urban-main-road-portal": (
                    "No Candidate Low-Traffic Area has a continuous fabric portal on an "
                    "Urban Main-Road Spine."
                ),
                "discontinuous-low-traffic-area-chain": (
                    "The Community's Candidate Low-Traffic Area has no continuous chain "
                    "through adjoining area fabric to an Urban Main-Road Spine portal."
                ),
            }[finding]
            rows.append(
                _record(
                    community,
                    service_status=AccessServiceStatus.NETWORK_GAP,
                    service_rationale=rationale,
                    finding=finding,
                    criterion_continuity=TrafficLight.RED,
                    area=area,
                )
            )
            continue

        path, portal, source_ids = selected
        origin = projected_areas[projected_areas["structure_id"].astype(str) == path[0]].iloc[0]
        direct = len(path) == 1
        rows.append(
            _record(
                community,
                service_status=AccessServiceStatus.SERVED,
                service_rationale=(
                    "The Urban Community Reference Point is served through its Candidate "
                    "Low-Traffic Area to a portal on an Urban Main-Road Spine."
                    if direct
                    else "The Urban Community Reference Point is served through continuous "
                    "adjoining Candidate Low-Traffic Area fabric to a Community area with "
                    "a portal on an Urban Main-Road Spine."
                ),
                finding=None,
                criterion_continuity=TrafficLight.GREEN,
                area=origin,
                portal=portal,
                area_chain=path,
                fabric_source_ids=source_ids,
                service_via=(
                    "candidate-low-traffic-area-portal"
                    if direct
                    else "adjoining-community-area-chain"
                ),
            )
        )

    rows = _resolve_community_chains(
        rows,
        projected_communities,
        projected_areas,
        projected_portals,
        road_graph,
        attachment_maximum_m,
    )
    return gpd.GeoDataFrame(
        rows,
        columns=ACCESS_OBLIGATION_COLUMNS,
        geometry="geometry",
        crs=27700,
    ).to_crs(crs)


def urban_community_gaps(
    obligations: gpd.GeoDataFrame,
    crs: object,
) -> gpd.GeoDataFrame:
    """Materialise unserved Urban Communities as visible point-only Network Gaps."""
    rows: list[dict[str, object]] = []
    unserved = obligations[
        obligations["service_status"] == AccessServiceStatus.NETWORK_GAP.value
    ].sort_values("obligation_id")
    for _, obligation in unserved.iterrows():
        community_id = str(obligation["community_id"])
        rationale = str(obligation["service_rationale"])
        source_ids = json.loads(str(obligation.get("fabric_source_ids") or "[]"))
        rows.append(
            {
                "connection_id": _stable_id(
                    "urban-community-access-gap", obligation["obligation_id"]
                ),
                "network_role": "urban-community-access-gap",
                "from_place": community_id,
                "to_place": None,
                "from_place_name": obligation.get("name"),
                "to_place_name": None,
                "distance_km": None,
                "classification": "network-gap",
                "intervention_archetype": "urban permeability investigation",
                "geometry_semantics": (
                    "unserved Urban Community Reference Point evidence; no residential "
                    "centreline is fabricated"
                ),
                "status": "gap",
                "selection_reason": rationale,
                "agent_outcome": rationale,
                "agent_attempt_count": 0,
                "agent_findings": json.dumps(
                    [
                        {
                            "code": str(obligation.get("finding") or "urban-community-access-gap"),
                            "severity": "blocking",
                            "message": rationale,
                            "evidence_ids": source_ids,
                        }
                    ],
                    sort_keys=True,
                ),
                "school_id": None,
                "school_kind": None,
                "access_point_status": None,
                "access_point_source_id": None,
                "access_point_rationale": None,
                "source_ids": json.dumps(source_ids),
                "cache_status": "not-cacheable",
                "alignment_options": "[]",
                "criterion_endpoints": obligation.get("criterion_access_point"),
                "criterion_continuity": obligation.get("criterion_continuity"),
                "criterion_bidirectional": "grey",
                "criterion_distance": "grey",
                "topography_alternative_trigger": False,
                "topography_comparison_status": "not-evaluated",
                "topography_comparison_rationale": (
                    "Urban Community service is assessed through area permeability; no "
                    "routed alignment exists for topography comparison."
                ),
                "topography_original_role": None,
                "topography_selected_role": None,
                "geometry": MultiPoint([obligation.geometry]),
            }
        )
    return gpd.GeoDataFrame(rows, columns=GAP_COLUMNS, geometry="geometry", crs=crs)


def _fabric_components(
    network: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
) -> list[_FabricComponent]:
    if network.empty or areas.empty:
        return []
    admitted = network[
        network.get("highway", pd.Series("", index=network.index, dtype=object)).map(
            lambda value: bool(set(_tag_values(value)) & LOW_TRAFFIC)
        )
    ]
    area_fabric = areas.geometry.union_all()
    records: list[_FabricRecord] = []
    for index, edge in admitted.iterrows():
        for geometry in continuous_linework(edge.geometry.intersection(area_fabric)):
            if geometry.length <= FABRIC_CONTACT_TOLERANCE_M:
                continue
            records.append(
                _FabricRecord(
                    start=_coordinate(geometry.coords[0]),
                    end=_coordinate(geometry.coords[-1]),
                    source_id=_source_id(edge, index),
                    geometry=geometry,
                )
            )
    graph = nx.Graph()
    for record in records:
        graph.add_edge(record.start, record.end)
    components: list[_FabricComponent] = []
    for nodes in nx.connected_components(graph):
        selected = [record for record in records if record.start in nodes and record.end in nodes]
        components.append(
            _FabricComponent(
                source_ids=tuple(sorted({record.source_id for record in selected})),
                geometry=unary_union([record.geometry for record in selected]),
            )
        )
    return sorted(components, key=lambda value: (value.source_ids, value.geometry.wkb_hex))


def _area_graph(
    areas: gpd.GeoDataFrame,
    components: list[_FabricComponent],
) -> tuple[nx.Graph, dict[str, list[_FabricComponent]]]:
    graph = nx.Graph()
    area_components: dict[str, list[_FabricComponent]] = {}
    ordered = areas.sort_values("structure_id")
    for _, area in ordered.iterrows():
        area_id = str(area["structure_id"])
        graph.add_node(area_id)
        area_components[area_id] = [
            component
            for component in components
            if component.geometry.intersection(area.geometry).length > FABRIC_CONTACT_TOLERANCE_M
        ]
    edge_sources: dict[tuple[str, str], tuple[str, ...]] = {}
    for (_, left), (_, right) in combinations(ordered.iterrows(), 2):
        left_id = str(left["structure_id"])
        right_id = str(right["structure_id"])
        if left.geometry.boundary.distance(right.geometry.boundary) > FABRIC_CONTACT_TOLERANCE_M:
            continue
        shared = [
            component
            for component in area_components[left_id]
            if component in area_components[right_id]
        ]
        if not shared:
            continue
        pair = tuple(sorted((left_id, right_id)))
        edge_sources[pair] = tuple(
            sorted({source_id for component in shared for source_id in component.source_ids})
        )
        graph.add_edge(*pair, source_ids=edge_sources[pair])
    return graph, area_components


def _rooted_portals(
    portals: gpd.GeoDataFrame,
    area_components: dict[str, list[_FabricComponent]],
) -> dict[str, list[tuple[pd.Series, tuple[str, ...]]]]:
    roots: dict[str, list[tuple[pd.Series, tuple[str, ...]]]] = {}
    main = portals[
        portals.get("boundary_kind", pd.Series("", index=portals.index, dtype=object))
        == "urban-main-road-spine"
    ].sort_values("portal_id")
    for _, portal in main.iterrows():
        area_id = str(portal["area_id"])
        touching = [
            component
            for component in area_components.get(area_id, [])
            if component.geometry.distance(portal.geometry) <= FABRIC_CONTACT_TOLERANCE_M
        ]
        if touching:
            roots.setdefault(area_id, []).append(
                (
                    portal,
                    tuple(
                        sorted(
                            {
                                source_id
                                for component in touching
                                for source_id in component.source_ids
                            }
                        )
                    ),
                )
            )
    return roots


def _portal_targets(
    road_graph: RoadGraph,
    roots: dict[str, list[tuple[pd.Series, tuple[str, ...]]]],
    urban_spines: gpd.GeoDataFrame,
) -> list[_PortalTarget]:
    """Map each rooted portal's spine nodes back to that same portal and LTA."""
    by_node: dict[str, _PortalTarget] = {}
    portals_by_spine: dict[str, list[tuple[pd.Series, tuple[str, ...]]]] = {}
    for values in roots.values():
        for portal, source_ids in values:
            portals_by_spine.setdefault(str(portal["boundary_id"]), []).append((portal, source_ids))
    for spine_id in sorted(portals_by_spine):
        spine_rows = urban_spines[urban_spines["structure_id"].astype(str) == spine_id]
        if spine_rows.empty:
            continue
        spine_geometry = spine_rows.geometry.union_all()
        routed_geometry = gpd.GeoSeries([spine_geometry], crs=27700).to_crs(road_graph.crs).iloc[0]
        rooted = sorted(
            portals_by_spine[spine_id],
            key=lambda value: str(value[0]["portal_id"]),
        )
        for node_id, association_m in road_graph.nodes_on_geometry(
            routed_geometry,
            tolerance_m=SPINE_NODE_ASSOCIATION_MAX_M,
        ):
            projected_node = (
                gpd.GeoSeries([road_graph.node_points[node_id]], crs=road_graph.crs)
                .to_crs(27700)
                .iloc[0]
            )
            portal, source_ids = min(
                rooted,
                key=lambda value: (
                    projected_node.distance(value[0].geometry),
                    str(value[0]["portal_id"]),
                ),
            )
            target = _PortalTarget(
                node_id=node_id,
                association_m=association_m,
                portal=portal,
                fabric_source_ids=source_ids,
                portal_mapping_distance_m=float(projected_node.distance(portal.geometry)),
            )
            if target.portal_mapping_distance_m > SPINE_PORTAL_MAPPING_MAX_M:
                continue
            existing = by_node.get(node_id)
            if existing is None or (
                target.association_m,
                target.portal_mapping_distance_m,
                str(target.portal["portal_id"]),
            ) < (
                existing.association_m,
                existing.portal_mapping_distance_m,
                str(existing.portal["portal_id"]),
            ):
                by_node[node_id] = target
    return [by_node[node_id] for node_id in sorted(by_node)]


def _routable_portal_attachment(
    community: pd.Series,
    road_graph: RoadGraph,
    portal_targets: list[_PortalTarget],
    attachment_maximum_m: float,
) -> tuple[RoutedAttachment, _PortalTarget] | None:
    """Prove bounded reciprocal graph access without publishing its centreline."""
    if not portal_targets:
        return None
    point = gpd.GeoSeries([community.geometry], crs=27700).to_crs(road_graph.crs).iloc[0]
    start_nodes = road_graph.nodes_near(point, COMMUNITY_POINT_ASSOCIATION_MAX_M)
    ends = [(target.node_id, target.association_m) for target in portal_targets]
    end_nodes = {target.node_id for target in portal_targets}
    stationary_pairs = {
        (start_node, start_node) for start_node, _ in start_nodes if start_node in end_nodes
    }
    route = road_graph.best_point_attachment(
        point,
        COMMUNITY_POINT_ASSOCIATION_MAX_M,
        ends,
        excluded_pairs=stationary_pairs,
    )
    target = (
        next(target for target in portal_targets if target.node_id == route.end_node)
        if route is not None
        else None
    )
    if (
        route is None
        or target is None
        or not route.option.bidirectional
        or not route.option.edge_ids
        or route.total_distance_km * 1000 + target.portal_mapping_distance_m > attachment_maximum_m
    ):
        return None
    return route, target


def _resolve_community_chains(
    rows: list[dict[str, object]],
    communities: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
    road_graph: RoadGraph,
    attachment_maximum_m: float,
) -> list[dict[str, object]]:
    """Grow acyclic Community access through the prior pass's rooted set."""
    by_id = {str(row["community_id"]): row for row in rows}
    community_by_id = {
        str(community["place_id"]): community
        for _, community in communities.sort_values("place_id").iterrows()
    }
    while True:
        targets = _community_targets(by_id, community_by_id, road_graph)
        replacements: dict[str, dict[str, object]] = {}
        for community_id in sorted(by_id):
            current = by_id[community_id]
            if current["service_status"] != AccessServiceStatus.NETWORK_GAP.value:
                continue
            community = community_by_id[community_id]
            routed = _routable_community_attachment(
                community,
                road_graph,
                targets,
                attachment_maximum_m,
            )
            if routed is None:
                continue
            route, target = routed
            parent = by_id[target.community_id]
            parent_provenance = json.loads(str(parent["provenance"]))
            area_rows = areas[
                areas["structure_id"].astype(str) == str(parent["low_traffic_area_id"])
            ]
            portal_rows = portals[portals["portal_id"].astype(str) == str(parent["portal_id"])]
            if area_rows.empty or portal_rows.empty:
                continue
            community_chain = [
                target.community_id,
                *parent_provenance.get("community_chain", []),
            ]
            replacements[community_id] = _record(
                community,
                service_status=AccessServiceStatus.SERVED_PROVISIONAL,
                service_rationale=(
                    "The Urban Community Reference Point has a provisional point-only "
                    f"bidirectional graph association to already rooted Community "
                    f"{target.community_name}; the inherited chain reaches Urban Main-Road "
                    f"Spine {parent['urban_spine_id']} and no residential centreline is "
                    "published."
                ),
                finding=None,
                criterion_continuity=TrafficLight.AMBER,
                area=area_rows.iloc[0],
                portal=portal_rows.iloc[0],
                area_chain=list(parent_provenance.get("low_traffic_area_chain", [])),
                fabric_source_ids=tuple(json.loads(str(parent.get("fabric_source_ids") or "[]"))),
                service_via="adjoining-community-graph-chain",
                attachment_distance_m=route.start_snap_m,
                attachment_maximum_m=attachment_maximum_m,
                network_distance_m=route.option.length_km * 1000,
                portal_association_distance_m=parent_provenance.get(
                    "portal_association_distance_m"
                ),
                portal_mapping_distance_m=parent_provenance.get("portal_mapping_distance_m"),
                total_route_cost_m=route.total_distance_km * 1000,
                route_edge_source_ids=tuple(route.option.edge_ids),
                reverse_route_edge_source_ids=tuple(route.option.reverse_edge_ids),
                target_community_id=target.community_id,
                target_community_name=target.community_name,
                target_community_association_distance_m=route.end_snap_m,
                community_chain=community_chain,
            )
        if not replacements:
            break
        by_id.update(replacements)
    return [by_id[community_id] for community_id in sorted(by_id)]


def _community_targets(
    rows: dict[str, dict[str, object]],
    communities: dict[str, pd.Series],
    road_graph: RoadGraph,
) -> list[_CommunityTarget]:
    """Materialise deterministic graph-node targets from the prior served set."""
    by_node: dict[str, _CommunityTarget] = {}
    for community_id in sorted(rows):
        row = rows[community_id]
        if row["service_status"] not in {
            AccessServiceStatus.SERVED.value,
            AccessServiceStatus.SERVED_PROVISIONAL.value,
        }:
            continue
        if not row.get("urban_spine_id"):
            continue
        community = communities[community_id]
        point = gpd.GeoSeries([community.geometry], crs=27700).to_crs(road_graph.crs).iloc[0]
        for node_id, association_m in road_graph.nodes_near(
            point,
            COMMUNITY_POINT_ASSOCIATION_MAX_M,
        ):
            target = _CommunityTarget(
                node_id=node_id,
                association_m=association_m,
                community_id=community_id,
                community_name=str(row.get("name") or community_id),
            )
            existing = by_node.get(node_id)
            if existing is None or (
                target.association_m,
                target.community_id,
            ) < (
                existing.association_m,
                existing.community_id,
            ):
                by_node[node_id] = target
    return [by_node[node_id] for node_id in sorted(by_node)]


def _routable_community_attachment(
    community: pd.Series,
    road_graph: RoadGraph,
    targets: list[_CommunityTarget],
    attachment_maximum_m: float,
) -> tuple[RoutedAttachment, _CommunityTarget] | None:
    """Prove one bounded reciprocal Community-to-rooted-Community graph step."""
    if not targets:
        return None
    point = gpd.GeoSeries([community.geometry], crs=27700).to_crs(road_graph.crs).iloc[0]
    start_nodes = road_graph.nodes_near(point, COMMUNITY_POINT_ASSOCIATION_MAX_M)
    ends = [(target.node_id, target.association_m) for target in targets]
    end_nodes = {target.node_id for target in targets}
    stationary_pairs = {
        (start_node, start_node) for start_node, _ in start_nodes if start_node in end_nodes
    }
    route = road_graph.best_point_attachment(
        point,
        COMMUNITY_POINT_ASSOCIATION_MAX_M,
        ends,
        excluded_pairs=stationary_pairs,
    )
    if (
        route is None
        or not route.option.bidirectional
        or not route.option.edge_ids
        or route.total_distance_km * 1000 > attachment_maximum_m
    ):
        return None
    target = next(target for target in targets if target.node_id == route.end_node)
    return route, target


def _select_rooted_path(
    candidate_areas: gpd.GeoDataFrame,
    graph: nx.Graph,
    roots: dict[str, list[tuple[pd.Series, tuple[str, ...]]]],
) -> tuple[list[str], pd.Series, tuple[str, ...]] | None:
    candidates: list[tuple[list[str], pd.Series, tuple[str, ...]]] = []
    for origin in sorted(candidate_areas.get("structure_id", []).astype(str)):
        for root in sorted(roots):
            if origin not in graph or root not in graph or not nx.has_path(graph, origin, root):
                continue
            path = nx.shortest_path(graph, origin, root)
            portal, root_sources = roots[root][0]
            path_sources = set(root_sources)
            for left, right in pairwise(path):
                path_sources.update(graph.edges[left, right].get("source_ids", ()))
            candidates.append((path, portal, tuple(sorted(path_sources))))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda value: (
            len(value[0]),
            value[0],
            str(value[1]["portal_id"]),
        ),
    )


def _record(
    community: pd.Series,
    *,
    service_status: AccessServiceStatus,
    service_rationale: str,
    finding: str | None,
    criterion_continuity: TrafficLight,
    area: pd.Series | None = None,
    portal: pd.Series | None = None,
    area_chain: list[str] | None = None,
    fabric_source_ids: tuple[str, ...] = (),
    service_via: str | None = None,
    attachment_distance_m: float = 0.0,
    attachment_maximum_m: float | None = None,
    network_distance_m: float | None = None,
    portal_association_distance_m: float | None = None,
    portal_mapping_distance_m: float | None = None,
    total_route_cost_m: float | None = None,
    route_edge_source_ids: tuple[str, ...] = (),
    reverse_route_edge_source_ids: tuple[str, ...] = (),
    target_community_id: str | None = None,
    target_community_name: str | None = None,
    target_community_association_distance_m: float | None = None,
    community_chain: list[str] | None = None,
) -> dict[str, object]:
    community_id = str(community["place_id"])
    area_id = str(area["structure_id"]) if area is not None else None
    portal_id = str(portal["portal_id"]) if portal is not None else None
    urban_spine_id = str(portal["boundary_id"]) if portal is not None else None
    chain = area_chain or ([area_id] if area_id is not None else [])
    source_ids = list(fabric_source_ids)
    supporting_evidence = {
        "community_source_id": str(community.get("source_id") or community_id),
        "low_traffic_area_chain": chain,
        "portal_id": portal_id,
        "urban_spine_id": urban_spine_id,
        "fabric_source_ids": source_ids,
        "attachment_distance_m": attachment_distance_m,
        "attachment_maximum_m": attachment_maximum_m,
        "network_distance_m": network_distance_m,
        "portal_association_distance_m": portal_association_distance_m,
        "portal_mapping_distance_m": portal_mapping_distance_m,
        "total_route_cost_m": total_route_cost_m,
        "route_edge_source_ids": list(route_edge_source_ids),
        "reverse_route_edge_source_ids": list(reverse_route_edge_source_ids),
        "target_community_id": target_community_id,
        "target_community_name": target_community_name,
        "target_community_association_distance_m": (target_community_association_distance_m),
        "community_chain": community_chain or [],
    }
    return {
        "obligation_id": _stable_id("access-obligation", community_id),
        "obligation_kind": "community",
        "place_id": community_id,
        "community_id": community_id,
        "school_id": None,
        "school_kind": None,
        "name": community.get("name"),
        "network_role": "urban-community-access-obligation",
        "network_scope": NetworkScope.URBAN.value,
        "service_status": service_status.value,
        "service_rationale": service_rationale,
        "access_point_status": None,
        "access_point_source_id": community.get("source_id"),
        "access_point_rationale": "Governed Community Reference Point.",
        "criterion_access_point": TrafficLight.GREEN.value,
        "criterion_continuity": criterion_continuity.value,
        "access_connection_id": None,
        "root_spine_id": None,
        "branch_id": None,
        "low_traffic_area_id": area_id,
        "low_traffic_area_name": area.get("name") if area is not None else None,
        "portal_id": portal_id,
        "portal_name": portal.get("name") if portal is not None else None,
        "urban_spine_id": urban_spine_id,
        "fabric_source_ids": json.dumps(source_ids),
        "supporting_evidence": json.dumps(supporting_evidence, sort_keys=True),
        "finding": finding,
        "geometry_semantics": "area-permeability-no-internal-centreline",
        "provenance": json.dumps(
            {
                "assessment": "urban-community-area-permeability",
                "service_status": service_status.value,
                "service_via": service_via,
                **supporting_evidence,
            },
            sort_keys=True,
        ),
        "geometry": community.geometry,
    }


def _source_id(row: pd.Series, fallback: object) -> str:
    for key in ("source_id", "osmid", "osm_id", "id"):
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(fallback)
