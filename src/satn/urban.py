"""Urban main-road skeleton and Candidate Low-Traffic Area derivation."""

from __future__ import annotations

import hashlib

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import unary_union

from satn.evidence import continuous_linework
from satn.models import OfficialRoadClassification, UrbanClassificationStatus
from satn.routing import LOW_TRAFFIC, _tag_values

URBAN_PLACE_CLASSES = {"city", "town", "suburb", "quarter", "neighbourhood"}
URBAN_SPINE_CLASSES = {
    OfficialRoadClassification.A_ROAD.value,
    OfficialRoadClassification.B_ROAD.value,
    OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value,
}


def derive_urban_structure(
    places: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    official_classification: gpd.GeoDataFrame | None = None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
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
    area_columns = ["structure_id", "role", "intervention", "geometry"]
    place_class = places.get("place_class")
    if place_class is None:
        place_class = [""] * len(places)
    urban = places[
        (places["kind"] == "community")
        & pd.Series(place_class, index=places.index).isin(URBAN_PLACE_CLASSES)
    ]
    if urban.empty or network.empty:
        return (
            gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=network.crs),
            gpd.GeoDataFrame([], columns=columns, geometry="geometry", crs=network.crs),
            gpd.GeoDataFrame([], columns=area_columns, geometry="geometry", crs=network.crs),
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

    minor_mask = (
        projected_network["_classes"]
        .map(lambda values: bool(set(values) & LOW_TRAFFIC))
        .astype(bool)
    )
    minor = projected_network.loc[minor_mask].copy()
    area_rows = _minor_road_areas(minor, main)
    spines = gpd.GeoDataFrame(spine_rows, columns=columns, geometry="geometry", crs=27700)
    unknowns = gpd.GeoDataFrame(
        unknown_rows, columns=columns, geometry="geometry", crs=27700
    )
    areas = gpd.GeoDataFrame(
        area_rows, columns=area_columns, geometry="geometry", crs=27700
    )
    return (
        spines.to_crs(network.crs),
        unknowns.to_crs(network.crs),
        areas.to_crs(network.crs),
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
    main_geometries: list[LineString] = []
    for _, feature in official.iterrows():
        classification = str(feature["official_classification"])
        if classification not in {*URBAN_SPINE_CLASSES, OfficialRoadClassification.UNKNOWN.value}:
            continue
        for geometry in continuous_linework(feature.geometry.intersection(urban_zone)):
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
                        "classification_status": (
                            UrbanClassificationStatus.EXPLICIT_UNKNOWN.value
                        ),
                        "intervention": "classification-required",
                        "intervention_assumption": (
                            "No through-traffic or cycling role inferred without official "
                            "classification"
                        ),
                        "design_status": "evidence gap; human verification required",
                    }
                )
                continue
            main_geometries.append(geometry)
            is_a_road = classification == OfficialRoadClassification.A_ROAD.value
            spine_rows.append(
                governed
                | {
                    "structure_id": _geometry_id(
                        "urban-spine",
                        geometry,
                        source_id,
                        feature_id,
                        classification,
                        fingerprint,
                    ),
                    "role": "urban-main-road-spine",
                    "classification_status": (
                        UrbanClassificationStatus.GOVERNED_OFFICIAL.value
                    ),
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
            {"geometry": main_geometries}, geometry="geometry", crs=27700
        ),
        spine_rows,
        unknown_rows,
    )


def _minor_road_areas(
    minor: gpd.GeoDataFrame,
    main: gpd.GeoDataFrame,
) -> list[dict[str, object]]:
    if not main.empty:
        main_road_barrier = unary_union(main.geometry.tolist()).buffer(20)
        minor["geometry"] = minor.geometry.map(
            lambda geometry: geometry.difference(main_road_barrier)
        )
        minor = minor.explode(index_parts=False).loc[
            lambda frame: frame.geometry.map(lambda geometry: isinstance(geometry, LineString))
        ]
    graph = nx.Graph()
    geometries: dict[tuple[str, str], LineString] = {}
    for _, row in minor.iterrows():
        geometry = row.geometry
        if not isinstance(geometry, LineString):
            continue
        start = _coordinate(geometry.coords[0])
        end = _coordinate(geometry.coords[-1])
        graph.add_edge(start, end)
        geometries[(start, end)] = geometry
    rows: list[dict[str, object]] = []
    for component in nx.connected_components(graph):
        component_lines = [
            geometry
            for (start, end), geometry in geometries.items()
            if start in component and end in component
        ]
        if len(component_lines) < 2:
            continue
        area = unary_union(component_lines).buffer(18, cap_style="square", join_style="mitre")
        rows.append(
            {
                "structure_id": _geometry_id("low-traffic-area", area),
                "role": "candidate-low-traffic-area",
                "intervention": "candidate-ltn",
                "geometry": area,
            }
        )
    return rows


def _coordinate(value: tuple[float, ...]) -> str:
    return f"{value[0]:.3f}:{value[1]:.3f}"


def _effective_date(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat() if callable(isoformat) else value)


def _geometry_id(prefix: str, geometry: object, *parts: object) -> str:
    identity = "::".join([geometry.wkb_hex, *(str(part) for part in parts)])
    return f"{prefix}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
