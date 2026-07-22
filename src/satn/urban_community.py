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
from satn.routing import LOW_TRAFFIC, _tag_values

FABRIC_CONTACT_TOLERANCE_M = 0.1


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


def assess_urban_community_access(
    communities: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
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
    components = _fabric_components(network.to_crs(27700), projected_areas)
    area_graph, area_components = _area_graph(projected_areas, components)
    rooted_portals = _rooted_portals(projected_portals, area_components)

    rows: list[dict[str, object]] = []
    for _, community in projected_communities.sort_values("place_id").iterrows():
        candidate_areas = projected_areas[
            projected_areas.geometry.covers(community.geometry)
        ].sort_values("structure_id")
        proximity_association = candidate_areas.empty
        if proximity_association:
            candidate_areas = projected_areas[
                projected_areas.geometry.distance(community.geometry) <= attachment_maximum_m
            ].sort_values("structure_id")
        selected = _select_rooted_path(
            candidate_areas,
            community.geometry,
            area_graph,
            rooted_portals,
        )
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

        path, portal, source_ids, attachment_distance_m = selected
        origin = projected_areas[projected_areas["structure_id"].astype(str) == path[0]].iloc[0]
        direct = len(path) == 1
        provisional = proximity_association and attachment_distance_m > 0
        rows.append(
            _record(
                community,
                service_status=(
                    AccessServiceStatus.SERVED_PROVISIONAL
                    if provisional
                    else AccessServiceStatus.SERVED
                ),
                service_rationale=(
                    "The Urban Community Reference Point has a provisional point-only "
                    f"association to the nearest rooted Candidate Low-Traffic Area, "
                    f"{attachment_distance_m:.1f} metres away within the governed "
                    f"{attachment_maximum_m:.1f}-metre maximum; local permeability "
                    "requires validation and no residential centreline is asserted."
                    if provisional
                    else "The Urban Community Reference Point is served through its Candidate "
                    "Low-Traffic Area to a portal on an Urban Main-Road Spine."
                    if direct
                    else "The Urban Community Reference Point is served through continuous "
                    "adjoining Candidate Low-Traffic Area fabric to a Community area with "
                    "a portal on an Urban Main-Road Spine."
                ),
                finding=None,
                criterion_continuity=(TrafficLight.AMBER if provisional else TrafficLight.GREEN),
                area=origin,
                portal=portal,
                area_chain=path,
                fabric_source_ids=source_ids,
                service_via=(
                    "nearby-candidate-low-traffic-area"
                    if provisional
                    else "candidate-low-traffic-area-portal"
                    if direct
                    else "adjoining-community-area-chain"
                ),
                attachment_distance_m=attachment_distance_m,
                attachment_maximum_m=attachment_maximum_m,
            )
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


def _select_rooted_path(
    candidate_areas: gpd.GeoDataFrame,
    community_geometry: object,
    graph: nx.Graph,
    roots: dict[str, list[tuple[pd.Series, tuple[str, ...]]]],
) -> tuple[list[str], pd.Series, tuple[str, ...], float] | None:
    candidates: list[tuple[list[str], pd.Series, tuple[str, ...], float]] = []
    ordered = candidate_areas.sort_values("structure_id")
    for _, area in ordered.iterrows():
        origin = str(area["structure_id"])
        for root in sorted(roots):
            if origin not in graph or root not in graph or not nx.has_path(graph, origin, root):
                continue
            path = nx.shortest_path(graph, origin, root)
            portal, root_sources = roots[root][0]
            path_sources = set(root_sources)
            for left, right in pairwise(path):
                path_sources.update(graph.edges[left, right].get("source_ids", ()))
            candidates.append(
                (
                    path,
                    portal,
                    tuple(sorted(path_sources)),
                    round(float(area.geometry.distance(community_geometry)), 3),
                )
            )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda value: (
            value[3],
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
