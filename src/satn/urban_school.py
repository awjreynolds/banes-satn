"""Assess urban School access through area permeability without selecting a route."""

from __future__ import annotations

import json
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import unary_union

from satn.evidence import continuous_linework
from satn.identifiers import coordinate_key as _coordinate
from satn.identifiers import stable_id as _stable_id
from satn.models import (
    ACCESS_OBLIGATION_COLUMNS,
    AccessPointStatus,
    AccessServiceStatus,
    NetworkScope,
    TrafficLight,
)
from satn.routing import LOW_TRAFFIC
from satn.tags import tag_values as _tag_values

SCHOOL_FABRIC_CONTACT_TOLERANCE_M = 0.1
PORTAL_CONTACT_TOLERANCE_M = 0.1


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
class _ReachablePortal:
    area: pd.Series
    portal: pd.Series
    component: _FabricComponent
    association_m: float


def assess_urban_school_access(
    schools: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Return point records proving area/portal reachability, never an internal route."""
    crs = schools.crs or network.crs or areas.crs or portals.crs
    if schools.empty:
        return gpd.GeoDataFrame(
            columns=ACCESS_OBLIGATION_COLUMNS,
            geometry="geometry",
            crs=crs,
        )
    projected_schools = schools.to_crs(27700)
    projected_network = network.to_crs(27700)
    projected_areas = areas.to_crs(27700)
    projected_portals = portals.to_crs(27700)
    component_cache: dict[str, list[_FabricComponent]] = {}
    rows: list[dict[str, object]] = []
    for _, school in projected_schools.sort_values("place_id").iterrows():
        try:
            access_status = AccessPointStatus(
                str(school.get("access_point_status") or AccessPointStatus.UNRESOLVED)
            )
        except ValueError:
            access_status = AccessPointStatus.UNRESOLVED
        if access_status is AccessPointStatus.UNRESOLVED:
            rows.append(
                _record(
                    school,
                    access_status=access_status,
                    service_status=AccessServiceStatus.NETWORK_GAP,
                    service_rationale=(
                        "No usable School Access Point is resolved, so urban permeability "
                        "is not assumed."
                    ),
                    finding="unresolved-school-access-point",
                    criterion_continuity=TrafficLight.GREY,
                )
            )
            continue
        candidate_areas = projected_areas[
            projected_areas.geometry.covers(school.geometry)
        ].sort_values("structure_id")
        if candidate_areas.empty:
            rows.append(
                _record(
                    school,
                    access_status=access_status,
                    service_status=AccessServiceStatus.NETWORK_GAP,
                    service_rationale=(
                        "The usable School Access Point is not inside a Candidate Low-Traffic Area."
                    ),
                    finding="no-candidate-low-traffic-area",
                    criterion_continuity=TrafficLight.RED,
                )
            )
            continue
        reachable: list[_ReachablePortal] = []
        inspected: list[_ReachablePortal] = []
        has_main_road_portal = False
        for _, area in candidate_areas.iterrows():
            area_id = str(area["structure_id"])
            area_portals = projected_portals[
                (projected_portals["area_id"] == area_id)
                & (projected_portals["boundary_kind"] == "urban-main-road-spine")
            ].sort_values("portal_id")
            has_main_road_portal = has_main_road_portal or not area_portals.empty
            components = component_cache.setdefault(
                area_id,
                _fabric_components(projected_network, area.geometry),
            )
            for component in components:
                association_m = float(component.geometry.distance(school.geometry))
                for _, portal in area_portals.iterrows():
                    if component.geometry.distance(portal.geometry) <= PORTAL_CONTACT_TOLERANCE_M:
                        candidate = _ReachablePortal(
                            area=area,
                            portal=portal,
                            component=component,
                            association_m=association_m,
                        )
                        inspected.append(candidate)
                        if association_m <= SCHOOL_FABRIC_CONTACT_TOLERANCE_M:
                            reachable.append(candidate)
        if not reachable:
            first_area = candidate_areas.iloc[0]
            inspected_selection = (
                min(
                    inspected,
                    key=lambda value: (
                        value.association_m,
                        value.portal.geometry.distance(school.geometry),
                        str(value.area["structure_id"]),
                        str(value.portal["portal_id"]),
                    ),
                )
                if inspected
                else None
            )
            finding_area = (
                inspected_selection.area if inspected_selection is not None else first_area
            )
            finding_portal = (
                inspected_selection.portal
                if inspected_selection is not None
                else _first_main_road_portal(projected_portals, candidate_areas)
            )
            finding_component = (
                inspected_selection.component
                if inspected_selection is not None
                else _nearest_component(
                    component_cache.get(str(finding_area["structure_id"]), []),
                    school.geometry,
                )
            )
            rows.append(
                _record(
                    school,
                    access_status=access_status,
                    service_status=AccessServiceStatus.NETWORK_GAP,
                    service_rationale=(
                        "The Candidate Low-Traffic Area has no portal on an Urban Main-Road Spine."
                        if not has_main_road_portal
                        else "The usable School Access Point does not share continuous "
                        "low-traffic street or path fabric with a main-road portal."
                    ),
                    finding=(
                        "no-urban-main-road-portal"
                        if not has_main_road_portal
                        else "discontinuous-access-fabric"
                    ),
                    criterion_continuity=TrafficLight.RED,
                    area=finding_area,
                    portal=finding_portal,
                    component=finding_component,
                )
            )
            continue
        selected = min(
            reachable,
            key=lambda value: (
                value.association_m,
                value.portal.geometry.distance(school.geometry),
                str(value.area["structure_id"]),
                str(value.portal["portal_id"]),
            ),
        )
        provisional = access_status is AccessPointStatus.INFERRED
        rows.append(
            _record(
                school,
                access_status=access_status,
                service_status=(
                    AccessServiceStatus.SERVED_PROVISIONAL
                    if provisional
                    else AccessServiceStatus.SERVED
                ),
                service_rationale=(
                    "Inferred School Access Point reaches an Urban Main-Road Spine "
                    "portal through continuous low-traffic area fabric; entrance "
                    "verification remains required."
                    if provisional
                    else "Mapped School Access Point reaches an Urban Main-Road Spine "
                    "portal through continuous low-traffic area fabric."
                ),
                finding=None,
                criterion_continuity=TrafficLight.GREEN,
                area=selected.area,
                portal=selected.portal,
                component=selected.component,
            )
        )
    return gpd.GeoDataFrame(
        rows,
        columns=ACCESS_OBLIGATION_COLUMNS,
        geometry="geometry",
        crs=27700,
    ).to_crs(crs)


def _first_main_road_portal(
    portals: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
) -> pd.Series | None:
    area_ids = set(areas["structure_id"].astype(str))
    candidates = portals[
        portals["area_id"].astype(str).isin(area_ids)
        & (portals["boundary_kind"] == "urban-main-road-spine")
    ].sort_values("portal_id")
    return candidates.iloc[0] if not candidates.empty else None


def _nearest_component(
    components: list[_FabricComponent],
    geometry: object,
) -> _FabricComponent | None:
    if not components:
        return None
    return min(
        components,
        key=lambda component: (
            component.geometry.distance(geometry),
            component.source_ids,
        ),
    )


def _fabric_components(
    network: gpd.GeoDataFrame,
    area: object,
) -> list[_FabricComponent]:
    highway = network.get("highway", pd.Series("", index=network.index, dtype=object))
    admitted = network[highway.map(lambda value: bool(set(_tag_values(value)) & LOW_TRAFFIC))]
    records: list[_FabricRecord] = []
    for index, edge in admitted.iterrows():
        for geometry in continuous_linework(edge.geometry.intersection(area)):
            if geometry.length <= 0.01:
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
    return sorted(
        components,
        key=lambda component: (component.source_ids, component.geometry.wkb_hex),
    )


def _record(
    school: pd.Series,
    *,
    access_status: AccessPointStatus,
    service_status: AccessServiceStatus,
    service_rationale: str,
    finding: str | None,
    criterion_continuity: TrafficLight,
    area: pd.Series | None = None,
    portal: pd.Series | None = None,
    component: _FabricComponent | None = None,
) -> dict[str, object]:
    school_id = str(school["place_id"])
    area_id = str(area["structure_id"]) if area is not None else None
    portal_id = str(portal["portal_id"]) if portal is not None else None
    fabric_source_ids = list(component.source_ids) if component is not None else []
    supporting_evidence = {
        "school_evidence_id": str(school.get("evidence_id") or school_id),
        "school_source_id": str(school.get("source_id") or school_id),
        "access_point_source_id": school.get("access_point_source_id"),
        "low_traffic_area_id": area_id,
        "portal_id": portal_id,
        "portal_boundary_id": portal.get("boundary_id") if portal is not None else None,
        "fabric_source_ids": fabric_source_ids,
    }
    return {
        "obligation_id": _stable_id("school-access-obligation", school_id),
        "obligation_kind": "school",
        "place_id": school_id,
        "community_id": None,
        "school_id": school_id,
        "school_kind": school.get("school_kind"),
        "name": school.get("name"),
        "network_role": "urban-school-access-obligation",
        "network_scope": NetworkScope.URBAN.value,
        "service_status": service_status.value,
        "service_rationale": service_rationale,
        "access_point_status": access_status.value,
        "access_point_source_id": school.get("access_point_source_id"),
        "access_point_rationale": school.get("access_point_rationale"),
        "criterion_access_point": {
            AccessPointStatus.MAPPED: TrafficLight.GREEN.value,
            AccessPointStatus.INFERRED: TrafficLight.AMBER.value,
            AccessPointStatus.UNRESOLVED: TrafficLight.GREY.value,
        }[access_status],
        "criterion_continuity": criterion_continuity.value,
        "access_connection_id": None,
        "root_spine_id": None,
        "branch_id": None,
        "low_traffic_area_id": area_id,
        "low_traffic_area_name": area.get("name") if area is not None else None,
        "portal_id": portal_id,
        "portal_name": portal.get("name") if portal is not None else None,
        "urban_spine_id": portal.get("boundary_id") if portal is not None else None,
        "fabric_source_ids": json.dumps(fabric_source_ids),
        "supporting_evidence": json.dumps(supporting_evidence, sort_keys=True),
        "finding": finding,
        "geometry_semantics": "area-permeability-no-internal-centreline",
        "provenance": json.dumps(
            {
                "assessment": "urban-area-permeability",
                "service_status": service_status.value,
                **supporting_evidence,
            },
            sort_keys=True,
        ),
        "geometry": school.geometry,
    }


def _source_id(row: pd.Series, fallback: object) -> str:
    for key in ("source_id", "osmid", "osm_id", "id"):
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(fallback)
