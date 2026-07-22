"""Inspect Community settlement form for Urban Circulation Plan eligibility."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from satn.models import SourceConfig
from satn.tags import tag_values as _tag_values

MINOR_STREET_CLASSES = {
    "living_street",
    "residential",
    "service",
    "unclassified",
}
AMENITY_PROFILE_TYPES = {"school", "healthcare", "retail-centre"}
COMPONENT_ASSOCIATION_STREET_CLASSES = {
    "living_street",
    "residential",
    "unclassified",
}


def assess_community_urban_eligibility(
    communities: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    context: gpd.GeoDataFrame,
    config: SourceConfig,
) -> gpd.GeoDataFrame:
    """Return Communities with an inspectable, non-scored urban eligibility profile."""
    assessed = communities.copy()
    if assessed.empty:
        return assessed

    projected_communities = assessed.to_crs(27700)
    projected_network = network.to_crs(27700)
    highway = projected_network.get(
        "highway", pd.Series("", index=projected_network.index, dtype=object)
    )
    minor = projected_network[
        highway.map(lambda value: bool(set(_tag_values(value)) & MINOR_STREET_CLASSES))
    ].copy()
    minor, junction_graph, junction_points = _minor_street_components(minor)
    projected_context = context.to_crs(27700) if not context.empty else context
    form = config.urban_settlement_form
    configured_types = set(config.urban_place_types)
    configured_source_ids = set(config.urban_place_source_ids)
    form_place_classes = set(form.eligible_place_classes)

    profiles: list[dict[str, object]] = []
    for _, community in projected_communities.iterrows():
        point = community.geometry.representative_point()
        zone = point.buffer(form.assessment_radius_km * 1000.0)
        nearby_minor = minor[minor.intersects(zone)]
        (
            component_id,
            component_association_distance_m,
            nearest_component_association_distance_m,
        ) = _associated_component(
            nearby_minor,
            point,
            form.maximum_component_association_m,
            form.component_association_tolerance_m,
            junction_graph,
            junction_points,
            zone,
        )
        associated_minor = nearby_minor[nearby_minor["_component_id"].eq(component_id)]
        minor_street_length_km, junction_count = _component_evidence(
            associated_minor,
            component_id,
            junction_graph,
            junction_points,
            zone,
        )
        amenity_counts = _amenity_counts(projected_context, zone)
        place_class = str(community.get("place_class") or "")
        source_id = str(community.get("source_id") or "")

        satisfies_settlement_form = (
            place_class in form_place_classes
            and minor_street_length_km >= form.minimum_minor_street_length_km
            and junction_count >= form.minimum_junction_count
        )
        if place_class in configured_types:
            eligible = True
            basis = "configured-place-class"
        elif satisfies_settlement_form:
            eligible = True
            basis = "settlement-form"
        elif source_id in configured_source_ids:
            eligible = True
            basis = "governed-source-override"
        elif place_class in form_place_classes:
            eligible = False
            basis = "insufficient-settlement-form"
        else:
            eligible = False
            basis = "configured-rural-place-class"

        profiles.append(
            {
                "urban_circulation_eligible": eligible,
                "urban_eligibility_basis": basis,
                "urban_eligibility_rationale": _rationale(
                    basis,
                    minor_street_length_km,
                    junction_count,
                    component_association_distance_m,
                    form.minimum_minor_street_length_km,
                    form.minimum_junction_count,
                    form.maximum_component_association_m,
                    form.component_association_tolerance_m,
                ),
                "settlement_form_radius_km": form.assessment_radius_km,
                "maximum_component_association_m": form.maximum_component_association_m,
                "component_association_tolerance_m": (form.component_association_tolerance_m),
                "component_association_distance_m": (
                    round(component_association_distance_m, 3)
                    if component_association_distance_m is not None
                    else None
                ),
                "nearest_component_association_distance_m": (
                    round(nearest_component_association_distance_m, 3)
                    if nearest_component_association_distance_m is not None
                    else None
                ),
                "component_selection_basis": (
                    "strongest-near-equivalent-non-service-component"
                    if component_id is not None
                    else "no-bounded-component-association"
                ),
                "minor_street_component_id": component_id,
                "minor_street_length_km": round(minor_street_length_km, 3),
                "junction_count": junction_count,
                "amenity_profile": json.dumps(amenity_counts, sort_keys=True),
                "minimum_minor_street_length_km": form.minimum_minor_street_length_km,
                "minimum_junction_count": form.minimum_junction_count,
            }
        )

    for column in profiles[0]:
        assessed[column] = pd.Series(
            [profile[column] for profile in profiles],
            index=projected_communities.index,
        ).reindex(assessed.index)
    return assessed


def urban_settlement_form_profiles(
    communities: gpd.GeoDataFrame,
) -> list[dict[str, object]]:
    """Expose the governed facts behind every Community scope decision."""
    columns = [
        "urban_circulation_eligible",
        "urban_eligibility_basis",
        "urban_eligibility_rationale",
        "settlement_form_radius_km",
        "maximum_component_association_m",
        "component_association_tolerance_m",
        "component_association_distance_m",
        "nearest_component_association_distance_m",
        "component_selection_basis",
        "minor_street_component_id",
        "minor_street_length_km",
        "junction_count",
        "amenity_profile",
        "minimum_minor_street_length_km",
        "minimum_junction_count",
    ]
    profiles: list[dict[str, object]] = []
    for _, community in communities.sort_values("place_id").iterrows():
        profiles.append(
            {
                "community_id": str(community["place_id"]),
                "community_name": str(community.get("name") or community["place_id"]),
                "place_class": str(community.get("place_class") or ""),
                "eligibility_basis": str(community["urban_eligibility_basis"]),
                **{
                    column: (
                        json.loads(str(community[column]))
                        if column == "amenity_profile"
                        else _plain(community[column])
                    )
                    for column in columns
                    if column != "urban_eligibility_basis"
                },
            }
        )
    return profiles


def _minor_street_components(
    minor: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, nx.Graph, dict[str, Point]]:
    graph = nx.Graph()
    points: dict[str, Point] = {}
    row_nodes: list[str | None] = []
    for _, row in minor.iterrows():
        geometry = row.geometry
        lines = (
            [geometry] if isinstance(geometry, LineString) else list(getattr(geometry, "geoms", []))
        )
        first_node: str | None = None
        for line in lines:
            if not isinstance(line, LineString) or len(line.coords) < 2:
                continue
            start = _node_id(row.get("u"), line.coords[0])
            end = _node_id(row.get("v"), line.coords[-1])
            graph.add_edge(start, end)
            points.setdefault(start, Point(line.coords[0]))
            points.setdefault(end, Point(line.coords[-1]))
            first_node = first_node or start
        row_nodes.append(first_node)

    component_by_node: dict[str, str] = {}
    for nodes in nx.connected_components(graph):
        component_id = hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest()[:12]
        for node in nodes:
            component_by_node[node] = component_id
            graph.nodes[node]["component_id"] = component_id
    annotated = minor.copy()
    annotated["_component_id"] = [
        component_by_node.get(node) if node is not None else None for node in row_nodes
    ]
    return annotated, graph, points


def _associated_component(
    nearby_minor: gpd.GeoDataFrame,
    point: Point,
    maximum_association_m: float,
    association_tolerance_m: float,
    graph: nx.Graph,
    points: dict[str, Point],
    zone: object,
) -> tuple[str | None, float | None, float | None]:
    candidates: list[tuple[float, str, str, bool]] = []
    for _, edge in nearby_minor.iterrows():
        component_id = edge.get("_component_id")
        if component_id is None or pd.isna(component_id):
            continue
        distance_m = float(edge.geometry.distance(point))
        if distance_m <= maximum_association_m:
            preferred = bool(
                set(_tag_values(edge.get("highway"))) & COMPONENT_ASSOCIATION_STREET_CLASSES
            )
            candidates.append((distance_m, str(component_id), edge.geometry.wkb_hex, preferred))
    if not candidates:
        return None, None, None

    preferred = [candidate for candidate in candidates if candidate[3]]
    eligible = preferred or candidates
    distance_by_component: dict[str, float] = {}
    for distance_m, component_id, _, _ in eligible:
        distance_by_component[component_id] = min(
            distance_m,
            distance_by_component.get(component_id, float("inf")),
        )
    nearest_distance_m = min(distance_by_component.values())
    near_equivalent = [
        component_id
        for component_id, distance_m in distance_by_component.items()
        if distance_m <= nearest_distance_m + association_tolerance_m
    ]

    def rank(component_id: str) -> tuple[int, float, float, str]:
        component_edges = nearby_minor[nearby_minor["_component_id"].eq(component_id)]
        length_km, junction_count = _component_evidence(
            component_edges,
            component_id,
            graph,
            points,
            zone,
        )
        return (
            -junction_count,
            -length_km,
            distance_by_component[component_id],
            component_id,
        )

    component_id = min(near_equivalent, key=rank)
    return component_id, distance_by_component[component_id], nearest_distance_m


def _component_evidence(
    component_edges: gpd.GeoDataFrame,
    component_id: str | None,
    graph: nx.Graph,
    points: dict[str, Point],
    zone: object,
) -> tuple[float, int]:
    if component_id is None:
        return 0.0, 0
    linework = [
        geometry.intersection(zone)
        for geometry in component_edges.geometry
        if geometry is not None and not geometry.is_empty
    ]
    length_km = float(unary_union(linework).length) / 1000.0 if linework else 0.0
    junction_count = sum(
        1
        for node, degree in graph.degree
        if degree >= 3
        and graph.nodes[node]["component_id"] == component_id
        and zone.covers(points[node])
    )
    return length_km, junction_count


def _node_id(value: object, coordinate: tuple[float, ...]) -> str:
    if value is not None and not pd.isna(value):
        return str(value)
    return f"{coordinate[0]:.3f},{coordinate[1]:.3f}"


def _plain(value: object) -> object:
    if value is None or (not isinstance(value, str) and bool(pd.isna(value))):
        return None
    return value.item() if hasattr(value, "item") else value


def _amenity_counts(context: gpd.GeoDataFrame, zone: object) -> dict[str, int]:
    if context.empty:
        return {feature_type: 0 for feature_type in sorted(AMENITY_PROFILE_TYPES)}
    feature_type = context.get("feature_type", pd.Series("", index=context.index, dtype=object))
    nearby = context[feature_type.isin(AMENITY_PROFILE_TYPES) & context.intersects(zone)]
    counts = Counter(str(value) for value in nearby["feature_type"])
    return {feature: counts[feature] for feature in sorted(AMENITY_PROFILE_TYPES)}


def _rationale(
    basis: str,
    minor_street_length_km: float,
    junction_count: int,
    component_association_distance_m: float | None,
    minimum_minor_street_length_km: float,
    minimum_junction_count: int,
    maximum_component_association_m: float,
    component_association_tolerance_m: float,
) -> str:
    if basis == "governed-source-override":
        return "Council Configuration explicitly admits this Community as urban."
    if basis == "configured-place-class":
        return "Its configured OSM place class admits this Community as urban."
    if component_association_distance_m is None:
        comparison = (
            "No minor-street component is reachable within the governed "
            f"{maximum_component_association_m:.1f} m association limit; 0.000 km "
            f"minor-street fabric (minimum {minimum_minor_street_length_km:.3f} km); "
            f"0 junctions (minimum {minimum_junction_count})."
        )
    else:
        comparison = (
            f"The associated component is {component_association_distance_m:.1f} m from the "
            f"Community Reference Point (maximum {maximum_component_association_m:.1f} m); "
            f"near-equivalent components within {component_association_tolerance_m:.1f} m "
            "were compared by junctions then length; "
            f"{minor_street_length_km:.3f} km minor-street fabric "
            f"(minimum {minimum_minor_street_length_km:.3f} km); {junction_count} junctions "
            f"(minimum {minimum_junction_count})."
        )
    if basis == "settlement-form":
        return f"The Community satisfies both governed settlement-form thresholds: {comparison}"
    if basis == "insufficient-settlement-form":
        return (
            f"The Community does not satisfy both governed settlement-form thresholds: {comparison}"
        )
    return "Its place class is not configured for urban circulation assessment."
