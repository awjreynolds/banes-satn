"""Urban main-road skeleton and Candidate Low-Traffic Area derivation."""

from __future__ import annotations

import hashlib
import json
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
from satn.routing import LOW_TRAFFIC, _tag_values

URBAN_PLACE_CLASSES = {"city", "town", "suburb", "quarter", "neighbourhood"}
TOPOLOGY_PRECISION_GRID_M = 0.01
URBAN_SPINE_CLASSES = {
    OfficialRoadClassification.A_ROAD.value,
    OfficialRoadClassification.B_ROAD.value,
    OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value,
}


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
    geometry: LineString


def derive_urban_structure(
    places: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    official_classification: gpd.GeoDataFrame | None = None,
    context: gpd.GeoDataFrame | None = None,
    observed_through_traffic: gpd.GeoDataFrame | None = None,
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
    place_class = places.get("place_class")
    if place_class is None:
        place_class = [""] * len(places)
    urban = places[
        (places["kind"] == "community")
        & pd.Series(place_class, index=places.index).isin(URBAN_PLACE_CLASSES)
    ]
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
    projected_network = projected_network[projected_network.intersects(urban_zone)].copy()
    highway = projected_network.get("highway")
    if highway is None:
        highway = [""] * len(projected_network)
    projected_network["_classes"] = [_tag_values(value) for value in highway]
    main, spine_rows, unknown_rows = _official_urban_evidence(
        official_classification,
        urban_zone,
    )
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
        .map(lambda values: bool(set(values) & LOW_TRAFFIC))
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
    boundary_linework = unary_union(boundaries.geometry.tolist())
    cells = sorted(list(polygonize(boundary_linework)), key=lambda value: value.wkb_hex)
    governed_observations = None
    if observed_through_traffic is not None and not observed_through_traffic.empty:
        governed_observations = observed_through_traffic.to_crs(27700)
        governed_observations = governed_observations.copy()
        governed_observations["geometry"] = governed_observations.geometry.map(
            _normalise_topology
        )
    rows: list[dict[str, object]] = []
    portals: list[dict[str, object]] = []
    for cell in cells:
        evidence = _minor_evidence_in_cell(minor, cell, governed_observations)
        component_records = [
            record
            for component in _connected_components(evidence)
            for record in component
        ]
        if len(component_records) < 2:
            continue
        source_ids = sorted({record.source_id for record in component_records})
        structure_id = _geometry_id("low-traffic-area", cell, *source_ids)
        name = f"Candidate Low-Traffic Area {structure_id.rsplit('-', 1)[-1]}"
        cell_boundaries = boundaries[
            boundaries.geometry.intersection(cell.boundary).length > 0.01
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
    return rows, portals


def _minor_evidence_in_cell(
    minor: gpd.GeoDataFrame,
    cell: object,
    governed_observations: gpd.GeoDataFrame | None,
) -> list[_MinorStreetEvidence]:
    evidence: list[_MinorStreetEvidence] = []
    for index, row in minor.iterrows():
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
        [
            record
            for record in evidence
            if record.start in component and record.end in component
        ]
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
