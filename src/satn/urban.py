"""Urban main-road skeleton and Candidate Low-Traffic Area derivation."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely import set_precision
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

from satn.evidence import continuous_linework
from satn.identifiers import coordinate_key as _coordinate
from satn.models import OfficialRoadClassification, UrbanClassificationStatus
from satn.tags import tag_values as _tag_values

LOGGER = logging.getLogger(__name__)

TOPOLOGY_PRECISION_GRID_M = 0.01
# Absorb normal centreline/source topology offsets without annexing nearby rural corridors.
URBAN_A_ROAD_EVIDENCE_TOLERANCE_M = 50.0
URBAN_SPINE_CLASSES = {
    OfficialRoadClassification.A_ROAD.value,
    OfficialRoadClassification.B_ROAD.value,
    OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value,
}
URBAN_STREET_FABRIC_CLASSES = {
    "living_street",
    "residential",
    "service",
    "unclassified",
}
URBAN_STREET_FABRIC_BUFFER_M = 150.0
URBAN_STREET_CLUSTER_OPENING_M = 200.0
URBAN_SPINE_TERMINUS_TOLERANCE_M = 25.0
LTA_BOUNDARY_ALIGNMENT_TOLERANCE_M = 1.0
LTA_MAXIMUM_UNGOVERNED_BOUNDARY_SHARE = 0.01
LTA_RESIDENTIAL_STREET_CLASSES = {"living_street", "residential"}


@dataclass(frozen=True)
class UrbanStructure:
    spines: gpd.GeoDataFrame
    classification_unknowns: gpd.GeoDataFrame
    low_traffic_areas: gpd.GeoDataFrame
    low_traffic_area_portals: gpd.GeoDataFrame


@dataclass(frozen=True)
class _MinorStreetEvidence:
    start: str
    end: str
    source_id: str
    observed_through_traffic: bool
    observed_evidence_ids: tuple[str, ...]
    observed_source_ids: tuple[str, ...]
    street_classes: tuple[str, ...]
    geometry: LineString


def derive_urban_structure(
    places: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    official_classification: gpd.GeoDataFrame | None = None,
    context: gpd.GeoDataFrame | None = None,
    observed_through_traffic: gpd.GeoDataFrame | None = None,
    council_boundary: gpd.GeoDataFrame | None = None,
) -> UrbanStructure:
    columns = [
        "structure_id",
        "role",
        "official_classification",
        "official_feature_id",
        "source_id",
        "effective_date",
        "licence",
        "content_fingerprint",
        "classification_status",
        "intervention",
        "intervention_assumption",
        "design_status",
        "geometry",
    ]
    area_columns = [
        "structure_id",
        "name",
        "role",
        "status",
        "intervention",
        "intervention_need",
        "permeability_representation",
        "boundary_ids",
        "observed_through_traffic_evidence_ids",
        "observed_through_traffic_source_ids",
        "portal_count",
        "geometry",
    ]
    portal_columns = [
        "portal_id",
        "area_id",
        "name",
        "role",
        "boundary_id",
        "boundary_name",
        "boundary_kind",
        "geometry",
    ]
    # The compiler supplies the governed urban Community scope, including explicit
    # council overrides for settlements whose OSM place class alone is insufficient.
    urban = places[places["kind"] == "community"]
    if urban.empty or network.empty:
        return UrbanStructure(
            spines=gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=network.crs),
            classification_unknowns=gpd.GeoDataFrame(
                [], columns=columns, geometry="geometry", crs=network.crs
            ),
            low_traffic_areas=gpd.GeoDataFrame(
                [], columns=area_columns, geometry="geometry", crs=network.crs
            ),
            low_traffic_area_portals=gpd.GeoDataFrame(
                [], columns=portal_columns, geometry="geometry", crs=network.crs
            ),
        )
    projected_network = network.to_crs(27700).copy()
    urban_zone = urban.to_crs(27700).geometry.buffer(2000).union_all()
    if context is not None and not context.empty:
        feature_type = context.get("feature_type", pd.Series("", index=context.index, dtype=object))
        network_scope = context.get(
            "network_scope", pd.Series("", index=context.index, dtype=object)
        )
        urban_a_roads = context[feature_type.eq("a-road-spine") & network_scope.eq("urban")]
        if not urban_a_roads.empty:
            urban_a_road_zone = (
                urban_a_roads.to_crs(27700)
                .geometry.buffer(URBAN_A_ROAD_EVIDENCE_TOLERANCE_M)
                .union_all()
            )
            urban_zone = unary_union([urban_zone, urban_a_road_zone])
    projected_network = projected_network[projected_network.intersects(urban_zone)].copy()
    highway = projected_network.get("highway")
    if highway is None:
        highway = [""] * len(projected_network)
    projected_network["_classes"] = [_tag_values(value) for value in highway]
    _, spine_rows, unknown_rows = _official_urban_evidence(
        official_classification,
        urban_zone,
    )
    primary_network = _primary_network_geometry(context, council_boundary, spine_rows)
    spine_rows = _retain_anchored_spine_rows(spine_rows, primary_network)
    main = _urban_spine_boundaries(spine_rows)
    circulation_boundaries = _qualifying_circulation_boundaries(context, urban_zone)
    boundary_frames = [frame for frame in (main, circulation_boundaries) if not frame.empty]
    boundary_network = (
        gpd.GeoDataFrame(
            pd.concat(boundary_frames, ignore_index=True),
            geometry="geometry",
            crs=27700,
        )
        if boundary_frames
        else _empty_boundaries()
    )

    minor_mask = (
        projected_network["_classes"]
        .map(lambda values: bool(set(values) & URBAN_STREET_FABRIC_CLASSES))
        .astype(bool)
    )
    minor = projected_network.loc[minor_mask].copy()
    area_rows, portal_rows = _minor_road_areas(
        minor,
        boundary_network,
        observed_through_traffic,
    )
    spines = gpd.GeoDataFrame(spine_rows, columns=columns, geometry="geometry", crs=27700)
    unknowns = gpd.GeoDataFrame(unknown_rows, columns=columns, geometry="geometry", crs=27700)
    areas = gpd.GeoDataFrame(area_rows, columns=area_columns, geometry="geometry", crs=27700)
    portals = gpd.GeoDataFrame(portal_rows, columns=portal_columns, geometry="geometry", crs=27700)
    return UrbanStructure(
        spines=spines.to_crs(network.crs),
        classification_unknowns=unknowns.to_crs(network.crs),
        low_traffic_areas=areas.to_crs(network.crs),
        low_traffic_area_portals=portals.to_crs(network.crs),
    )


def _official_urban_evidence(
    official_classification: gpd.GeoDataFrame | None,
    urban_zone: object,
) -> tuple[
    gpd.GeoDataFrame,
    list[dict[str, object]],
    list[dict[str, object]],
]:
    if official_classification is None or official_classification.empty:
        return (
            gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=27700),
            [],
            [],
        )
    official = official_classification.to_crs(27700).copy()
    official = official[official.intersects(urban_zone)].copy()
    spine_rows: list[dict[str, object]] = []
    unknown_rows: list[dict[str, object]] = []
    main_rows: list[dict[str, object]] = []
    for _, feature in official.iterrows():
        classification = str(feature["official_classification"])
        if classification not in {*URBAN_SPINE_CLASSES, OfficialRoadClassification.UNKNOWN.value}:
            continue
        for raw_geometry in continuous_linework(feature.geometry.intersection(urban_zone)):
            geometry = _normalise_topology(raw_geometry)
            source_id = str(feature["source_id"])
            feature_id = str(feature["official_feature_id"])
            fingerprint = str(feature["content_fingerprint"])
            governed = {
                "official_classification": classification,
                "official_feature_id": feature_id,
                "source_id": source_id,
                "effective_date": _effective_date(feature["effective_date"]),
                "licence": feature["licence"],
                "content_fingerprint": fingerprint,
                "geometry": geometry,
            }
            if classification == OfficialRoadClassification.UNKNOWN.value:
                unknown_rows.append(
                    governed
                    | {
                        "structure_id": _geometry_id(
                            "urban-classification-unknown",
                            geometry,
                            source_id,
                            feature_id,
                            fingerprint,
                        ),
                        "role": "urban-road-classification-unknown",
                        "classification_status": (UrbanClassificationStatus.EXPLICIT_UNKNOWN.value),
                        "intervention": "classification-required",
                        "intervention_assumption": (
                            "No through-traffic or cycling role inferred without official "
                            "classification"
                        ),
                        "design_status": "evidence gap; human verification required",
                    }
                )
                continue
            is_a_road = classification == OfficialRoadClassification.A_ROAD.value
            structure_id = _geometry_id(
                "urban-spine",
                geometry,
                source_id,
                feature_id,
                classification,
                fingerprint,
            )
            main_rows.append(
                {
                    "boundary_id": structure_id,
                    "boundary_name": (f"{_classification_name(classification)} ({feature_id})"),
                    "boundary_kind": "urban-main-road-spine",
                    "geometry": geometry,
                }
            )
            spine_rows.append(
                governed
                | {
                    "structure_id": structure_id,
                    "role": "urban-main-road-spine",
                    "classification_status": (UrbanClassificationStatus.GOVERNED_OFFICIAL.value),
                    "intervention": "protected-cycle-infrastructure",
                    "intervention_assumption": (
                        "Major engineering required to provide high-quality protected or "
                        "shared provision"
                        if is_a_road
                        else "Protected cycle infrastructure on an official through road"
                    ),
                    "design_status": "strategic assumption; not a carriageway or final design",
                }
            )
    return (
        gpd.GeoDataFrame(
            main_rows,
            columns=["boundary_id", "boundary_name", "boundary_kind", "geometry"],
            geometry="geometry",
            crs=27700,
        ),
        spine_rows,
        unknown_rows,
    )


def _primary_network_geometry(
    context: gpd.GeoDataFrame | None,
    council_boundary: gpd.GeoDataFrame | None,
    spine_rows: list[dict[str, object]],
) -> object:
    geometries = [
        row["geometry"]
        for row in spine_rows
        if row["official_classification"] == OfficialRoadClassification.A_ROAD.value
    ]
    if context is not None and not context.empty:
        feature_type = context.get(
            "feature_type", pd.Series("", index=context.index, dtype=object)
        )
        primary = context[
            feature_type.isin({"a-road-spine", "ncn-route", "ncn-link", "strategic-spine"})
        ]
        geometries.extend(primary.to_crs(27700).geometry.tolist())
    if council_boundary is not None and not council_boundary.empty:
        for geometry in council_boundary.to_crs(27700).geometry:
            geometries.append(
                geometry.boundary if geometry.geom_type in {"Polygon", "MultiPolygon"} else geometry
            )
    return unary_union(geometries)


def _retain_anchored_spine_rows(
    spine_rows: list[dict[str, object]],
    primary_network: object,
) -> list[dict[str, object]]:
    if not spine_rows or primary_network is None or primary_network.is_empty:
        return []
    noded = unary_union([row["geometry"] for row in spine_rows])
    edges = [
        geometry
        for geometry in continuous_linework(noded)
        if isinstance(geometry, LineString) and geometry.length > TOPOLOGY_PRECISION_GRID_M
    ]
    endpoints = [
        (_coordinate(geometry.coords[0]), _coordinate(geometry.coords[-1]))
        for geometry in edges
    ]
    active = set(range(len(edges)))
    while active:
        incident: dict[str, list[int]] = defaultdict(list)
        for edge_index in active:
            for endpoint in endpoints[edge_index]:
                incident[endpoint].append(edge_index)
        dangling = {
            edge_indexes[0]
            for endpoint, edge_indexes in incident.items()
            if len(edge_indexes) == 1
            and Point(tuple(float(value) for value in endpoint.split(":"))).distance(
                primary_network
            )
            > URBAN_SPINE_TERMINUS_TOLERANCE_M
        }
        if not dangling:
            break
        active.difference_update(dangling)
    if not active:
        return []
    retained_linework = unary_union([edges[index] for index in sorted(active)])
    retained_rows: list[dict[str, object]] = []
    for row in spine_rows:
        for raw_geometry in continuous_linework(row["geometry"].intersection(retained_linework)):
            geometry = _normalise_topology(raw_geometry)
            if geometry.length <= TOPOLOGY_PRECISION_GRID_M:
                continue
            retained = row | {"geometry": geometry}
            retained["structure_id"] = _geometry_id(
                "urban-spine",
                geometry,
                retained["source_id"],
                retained["official_feature_id"],
                retained["official_classification"],
                retained["content_fingerprint"],
            )
            retained_rows.append(retained)
    return retained_rows


def _urban_spine_boundaries(
    spine_rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "boundary_id": row["structure_id"],
                "boundary_name": (
                    f"{_classification_name(str(row['official_classification']))} "
                    f"({row['official_feature_id']})"
                ),
                "boundary_kind": "urban-main-road-spine",
                "geometry": row["geometry"],
            }
            for row in spine_rows
        ],
        columns=["boundary_id", "boundary_name", "boundary_kind", "geometry"],
        geometry="geometry",
        crs=27700,
    )


def _minor_road_areas(
    minor: gpd.GeoDataFrame,
    boundaries: gpd.GeoDataFrame,
    observed_through_traffic: gpd.GeoDataFrame | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if boundaries.empty or minor.empty:
        return [], []
    boundaries = boundaries.copy()
    boundaries["geometry"] = boundaries.geometry.map(_normalise_topology)
    minor = minor.copy()
    minor["geometry"] = minor.geometry.map(_normalise_topology)
    buffered_streets = minor.geometry.buffer(URBAN_STREET_FABRIC_BUFFER_M).union_all(
        method="disjoint_subset"
    )
    clustered_fabric = buffered_streets.buffer(-URBAN_STREET_CLUSTER_OPENING_M).buffer(
        URBAN_STREET_CLUSTER_OPENING_M
    )
    clustered_fabric = clustered_fabric.intersection(buffered_streets)
    street_fabric = _normalise_topology(
        clustered_fabric if not clustered_fabric.is_empty else buffered_streets
    )
    if street_fabric is None or street_fabric.is_empty:
        return [], []
    governed_boundary_linework = unary_union(boundaries.geometry.tolist())
    governed_boundary_zone = governed_boundary_linework.buffer(
        LTA_BOUNDARY_ALIGNMENT_TOLERANCE_M
    )
    dividing_linework = [street_fabric.boundary]
    for geometry in boundaries.geometry:
        dividing_linework.extend(continuous_linework(geometry.intersection(street_fabric)))
    boundary_linework = unary_union(dividing_linework)
    cells = sorted(
        (
            _normalise_topology(cell.intersection(street_fabric))
            for cell in polygonize(boundary_linework)
        ),
        key=lambda value: value.wkb_hex,
    )
    LOGGER.info(
        "Urban LTA derivation started street_segments=%d boundaries=%d cells=%d",
        len(minor),
        len(boundaries),
        len(cells),
    )
    governed_observations = None
    if observed_through_traffic is not None and not observed_through_traffic.empty:
        governed_observations = observed_through_traffic.to_crs(27700)
        governed_observations = governed_observations.copy()
        governed_observations["geometry"] = governed_observations.geometry.map(_normalise_topology)
    rows: list[dict[str, object]] = []
    portals: list[dict[str, object]] = []
    for cell_index, cell in enumerate(cells, start=1):
        if cell_index % 250 == 0:
            LOGGER.info(
                "Urban LTA derivation progress assessed=%d/%d candidates=%d portals=%d",
                cell_index,
                len(cells),
                len(rows),
                len(portals),
            )
        if cell is None or cell.is_empty or cell.area <= 1.0:
            continue
        uncovered_boundary_m = float(
            cell.boundary.difference(governed_boundary_zone).length
        )
        if uncovered_boundary_m > max(
            LTA_BOUNDARY_ALIGNMENT_TOLERANCE_M,
            float(cell.boundary.length) * LTA_MAXIMUM_UNGOVERNED_BOUNDARY_SHARE,
        ):
            continue
        evidence = _minor_evidence_in_cell(minor, cell, governed_observations)
        component_records = [
            record for component in _connected_components(evidence) for record in component
        ]
        if len(component_records) < 2:
            continue
        if not any(
            set(record.street_classes) & LTA_RESIDENTIAL_STREET_CLASSES
            for record in component_records
        ):
            continue
        source_ids = sorted({record.source_id for record in component_records})
        structure_id = _geometry_id("low-traffic-area", cell, *source_ids)
        name = f"Candidate Low-Traffic Area {structure_id.rsplit('-', 1)[-1]}"
        boundary_positions = boundaries.sindex.query(cell.boundary, predicate="intersects")
        cell_boundaries = boundaries.iloc[sorted(int(value) for value in boundary_positions)]
        cell_boundaries = cell_boundaries[
            cell_boundaries.geometry.intersection(cell.boundary).length > 0.01
        ].sort_values("boundary_id")
        area_portals = _low_traffic_area_portals(
            structure_id,
            name,
            component_records,
            cell,
            cell_boundaries,
        )
        if not area_portals:
            continue
        boundary_ids = sorted(set(cell_boundaries["boundary_id"]))
        rows.append(
            {
                "structure_id": structure_id,
                "name": name,
                "role": "candidate-low-traffic-area",
                "status": "candidate",
                "intervention": "candidate-ltn",
                "intervention_need": (
                    "observed-through-traffic"
                    if any(record.observed_through_traffic for record in component_records)
                    else "prevent-through-traffic"
                ),
                "permeability_representation": "area-no-internal-centreline",
                "boundary_ids": json.dumps(boundary_ids),
                "observed_through_traffic_evidence_ids": json.dumps(
                    sorted(
                        {
                            evidence_id
                            for record in component_records
                            for evidence_id in record.observed_evidence_ids
                        }
                    )
                ),
                "observed_through_traffic_source_ids": json.dumps(
                    sorted(
                        {
                            source_id
                            for record in component_records
                            for source_id in record.observed_source_ids
                        }
                    )
                ),
                "portal_count": len(area_portals),
                "geometry": cell,
            }
        )
        portals.extend(area_portals)
    LOGGER.info(
        "Urban LTA derivation completed cells=%d candidates=%d portals=%d",
        len(cells),
        len(rows),
        len(portals),
    )
    return rows, portals


def _minor_evidence_in_cell(
    minor: gpd.GeoDataFrame,
    cell: object,
    governed_observations: gpd.GeoDataFrame | None,
) -> list[_MinorStreetEvidence]:
    evidence: list[_MinorStreetEvidence] = []
    positions = minor.sindex.query(cell, predicate="intersects")
    candidates = minor.iloc[sorted(int(value) for value in positions)]
    for index, row in candidates.iterrows():
        for geometry in continuous_linework(row.geometry.intersection(cell)):
            if geometry.length <= 0.01:
                continue
            observed_evidence_ids, observed_source_ids = _observed_evidence(
                geometry, governed_observations
            )
            evidence.append(
                _MinorStreetEvidence(
                    start=_coordinate(geometry.coords[0]),
                    end=_coordinate(geometry.coords[-1]),
                    source_id=_network_source_id(row, index),
                    observed_through_traffic=(
                        _has_observed_through_traffic(row.get("observed_through_traffic"))
                        or bool(observed_evidence_ids)
                    ),
                    observed_evidence_ids=observed_evidence_ids,
                    observed_source_ids=observed_source_ids,
                    street_classes=tuple(sorted(_tag_values(row.get("highway")))),
                    geometry=geometry,
                )
            )
    return evidence


def _observed_evidence(
    geometry: LineString,
    governed_observations: gpd.GeoDataFrame | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if governed_observations is None or governed_observations.empty:
        return (), ()
    matched = governed_observations[governed_observations.geometry.intersects(geometry.buffer(10))]
    return (
        tuple(sorted({str(value) for value in matched["evidence_id"]})),
        tuple(sorted({str(value) for value in matched["source_id"]})),
    )


def _connected_components(
    evidence: list[_MinorStreetEvidence],
) -> list[list[_MinorStreetEvidence]]:
    graph = nx.Graph()
    for record in evidence:
        graph.add_edge(record.start, record.end)
    components = sorted(
        nx.connected_components(graph),
        key=lambda component: (-len(component), sorted(component)),
    )
    return [
        [record for record in evidence if record.start in component and record.end in component]
        for component in components
    ]


def _low_traffic_area_portals(
    area_id: str,
    area_name: str,
    evidence: list[_MinorStreetEvidence],
    cell: object,
    boundaries: gpd.GeoDataFrame,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for _, boundary in boundaries.iterrows():
        for record in evidence:
            intersection = record.geometry.intersection(boundary.geometry)
            for point in _intersection_points(intersection):
                if point.distance(cell.boundary) > 0.1:
                    continue
                coordinate = _coordinate(point.coords[0])
                key = (str(boundary["boundary_id"]), coordinate)
                if key in seen:
                    continue
                seen.add(key)
                portal_id = _geometry_id(
                    "low-traffic-area-portal",
                    point,
                    area_id,
                    boundary["boundary_id"],
                )
                rows.append(
                    {
                        "portal_id": portal_id,
                        "area_id": area_id,
                        "name": f"{area_name} portal to {boundary['boundary_name']}",
                        "role": "low-traffic-area-portal",
                        "boundary_id": boundary["boundary_id"],
                        "boundary_name": boundary["boundary_name"],
                        "boundary_kind": boundary["boundary_kind"],
                        "geometry": point,
                    }
                )
    return sorted(rows, key=lambda row: str(row["portal_id"]))


def _intersection_points(geometry: object) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, LineString):
        return [Point(geometry.coords[0]), Point(geometry.coords[-1])]
    if hasattr(geometry, "geoms"):
        return [point for part in geometry.geoms for point in _intersection_points(part)]
    return []


def _qualifying_circulation_boundaries(
    context: gpd.GeoDataFrame | None,
    urban_zone: object,
) -> gpd.GeoDataFrame:
    if context is None or context.empty:
        return _empty_boundaries()
    category = context.get("category", pd.Series("", index=context.index, dtype=object))
    feature_type = context.get("feature_type", pd.Series("", index=context.index, dtype=object))
    qualifying = context[
        (feature_type == "circulation-boundary")
        & category.isin({"built-up-edge", "river", "canal", "railway"})
    ].to_crs(27700)
    rows: list[dict[str, object]] = []
    for index, boundary in qualifying.iterrows():
        boundary_id = str(
            boundary.get("evidence_id")
            or boundary.get("source_id")
            or f"circulation-boundary-{index}"
        )
        for position, raw_geometry in enumerate(
            continuous_linework(boundary.geometry.intersection(urban_zone))
        ):
            geometry = _normalise_topology(raw_geometry)
            rows.append(
                {
                    "boundary_id": (
                        boundary_id if position == 0 else f"{boundary_id}-{position + 1}"
                    ),
                    "boundary_name": str(boundary.get("name") or boundary["category"]),
                    "boundary_kind": str(boundary["category"]),
                    "geometry": geometry,
                }
            )
    return gpd.GeoDataFrame(
        rows,
        columns=["boundary_id", "boundary_name", "boundary_kind", "geometry"],
        geometry="geometry",
        crs=27700,
    )


def _empty_boundaries() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        columns=["boundary_id", "boundary_name", "boundary_kind", "geometry"],
        geometry="geometry",
        crs=27700,
    )


def _normalise_topology(geometry: object) -> object:
    return set_precision(geometry, grid_size=TOPOLOGY_PRECISION_GRID_M)


def _classification_name(classification: str) -> str:
    return {
        OfficialRoadClassification.A_ROAD.value: "A road",
        OfficialRoadClassification.B_ROAD.value: "B road",
        OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value: ("Classified Unnumbered road"),
    }[classification]


def _network_source_id(row: pd.Series, fallback: object) -> str:
    for key in ("source_id", "osmid", "osm_id", "id"):
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(fallback)


def _has_observed_through_traffic(value: object) -> bool:
    return value is True or str(value).strip().lower() in {"yes", "true", "1"}


def _effective_date(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat() if callable(isoformat) else value)


def _geometry_id(prefix: str, geometry: object, *parts: object) -> str:
    identity = "::".join([geometry.wkb_hex, *(str(part) for part in parts)])
    return f"{prefix}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
