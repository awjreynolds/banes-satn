"""Derive quiet, optional map evidence without turning amenities into Network Places."""

from __future__ import annotations

import ast
import hashlib
from collections import Counter

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, MultiLineString

CONTEXT_COLUMNS = [
    "evidence_id",
    "feature_type",
    "name",
    "category",
    "source_id",
    "feature_count",
    "geometry",
]


def empty_context(crs: object = 4326) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(columns=CONTEXT_COLUMNS, geometry="geometry", crs=crs)


def derive_context_layers(
    network: gpd.GeoDataFrame,
    ncn_features: gpd.GeoDataFrame | None = None,
    facilities: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Build the map hierarchy from OSM road, route and amenity evidence."""
    frames = [derive_a_road_spines(network)]
    if ncn_features is not None and not ncn_features.empty:
        frames.append(derive_ncn_routes(ncn_features, network.crs))
    if facilities is not None and not facilities.empty:
        frames.append(derive_facilities(facilities, network.crs))
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return empty_context(network.crs)
    return gpd.GeoDataFrame(
        pd.concat(populated, ignore_index=True),
        columns=CONTEXT_COLUMNS,
        geometry="geometry",
        crs=network.crs,
    ).sort_values("evidence_id")


def derive_a_road_spines(network: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    for index, edge in network.iterrows():
        refs = _tag_values(edge.get("ref"))
        a_refs = sorted(ref for ref in refs if ref.upper().startswith("A"))
        if not a_refs or not isinstance(edge.geometry, (LineString, MultiLineString)):
            continue
        source_id = _source_id(edge, index)
        rows.append(
            _row(
                "a-road-spine",
                source_id,
                " / ".join(a_refs),
                "A-road strategic spine",
                source_id,
                edge.geometry,
            )
        )
    return _frame(rows, network.crs)


def derive_ncn_routes(features: gpd.GeoDataFrame, target_crs: object) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    for index, feature in features.to_crs(target_crs).iterrows():
        geometry = feature.geometry
        if not isinstance(geometry, (LineString, MultiLineString)):
            continue
        network_tags = {value.lower() for value in _tag_values(feature.get("network"))}
        route_tags = {value.lower() for value in _tag_values(feature.get("route"))}
        route_type = (_text(feature.get("RouteType")) or "").lower()
        if "ncn" not in network_tags and "bicycle" not in route_tags and route_type != "ncn":
            continue
        source_id = _source_id(feature, index)
        ref = " / ".join(_tag_values(feature.get("ref")) or _tag_values(feature.get("RouteNo")))
        name = _text(feature.get("name")) or (f"NCN {ref}" if ref else "National Cycle Network")
        rows.append(
            _row("ncn-route", source_id, name, "National Cycle Network", source_id, geometry)
        )
    return _frame(rows, target_crs)


def derive_facilities(features: gpd.GeoDataFrame, target_crs: object) -> gpd.GeoDataFrame:
    source = features.to_crs(target_crs)
    rows: list[dict[str, object]] = []
    retail_points: list[dict[str, object]] = []
    for index, feature in source.iterrows():
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        amenity = (_text(feature.get("amenity")) or "").lower()
        shop = _text(feature.get("shop"))
        landuse = (_text(feature.get("landuse")) or "").lower()
        source_id = _source_id(feature, index)
        point = feature.geometry.representative_point()
        name = _text(feature.get("name"))
        if amenity in {"school", "college", "university"}:
            rows.append(
                _row(
                    "school",
                    source_id,
                    name or "Unnamed education site",
                    amenity,
                    source_id,
                    point,
                )
            )
        if amenity in {"doctors", "pharmacy", "clinic", "hospital"}:
            rows.append(
                _row(
                    "healthcare",
                    source_id,
                    name or amenity.title(),
                    amenity,
                    source_id,
                    point,
                )
            )
        if shop or landuse == "retail" or amenity == "marketplace":
            retail_points.append(
                {
                    "source_id": source_id,
                    "name": name,
                    "street": _text(feature.get("addr:street")),
                    "is_centre": landuse == "retail" or amenity == "marketplace",
                    "geometry": point,
                }
            )
    rows.extend(_retail_centres(retail_points, target_crs))
    return _frame(rows, target_crs)


def mark_ncn_edges(network: gpd.GeoDataFrame, context: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Annotate routable edges that overlap published NCN evidence."""
    result = network.copy()
    ncn = context[context["feature_type"] == "ncn-route"]
    if ncn.empty:
        result["satn_ncn"] = False
        return result
    projected = result.to_crs(27700)
    corridor = ncn.to_crs(27700).geometry.buffer(20).union_all()
    result["satn_ncn"] = [
        bool(geometry.length and geometry.intersection(corridor).length / geometry.length >= 0.5)
        for geometry in projected.geometry
    ]
    return result


def _retail_centres(points: list[dict[str, object]], crs: object) -> list[dict[str, object]]:
    if not points:
        return []
    frame = gpd.GeoDataFrame(points, geometry="geometry", crs=crs).to_crs(27700)
    graph = nx.Graph()
    graph.add_nodes_from(frame.index)
    spatial_index = frame.sindex
    for index, point in frame.geometry.items():
        neighbours = spatial_index.query(point.buffer(125), predicate="intersects")
        graph.add_edges_from(
            (index, int(neighbour)) for neighbour in neighbours if index != neighbour
        )
    rows: list[dict[str, object]] = []
    for component in nx.connected_components(graph):
        cluster = frame.loc[sorted(component)]
        if len(cluster) < 3 and not bool(cluster["is_centre"].any()):
            continue
        streets = [str(value) for value in cluster["street"] if _text(value)]
        street = Counter(streets).most_common(1)[0][0] if streets else None
        label = (
            f"{street} retail centre" if street else f"Retail centre ({len(cluster)} mapped shops)"
        )
        source_ids = sorted(str(value) for value in cluster["source_id"])
        source_key = ":".join(source_ids)
        rows.append(
            _row(
                "retail-centre",
                source_key,
                label,
                "shop cluster",
                ",".join(source_ids),
                cluster.geometry.union_all().centroid,
                feature_count=len(cluster),
            )
        )
    if not rows:
        return []
    projected = gpd.GeoDataFrame(rows, geometry="geometry", crs=27700).to_crs(crs)
    return projected.to_dict("records")


def _row(
    feature_type: str,
    identity: str,
    name: str,
    category: str,
    source_id: str,
    geometry: object,
    *,
    feature_count: int = 1,
) -> dict[str, object]:
    digest = hashlib.sha256(f"{feature_type}:{identity}".encode()).hexdigest()[:12]
    return {
        "evidence_id": f"{feature_type}-{digest}",
        "feature_type": feature_type,
        "name": name,
        "category": category,
        "source_id": source_id,
        "feature_count": feature_count,
        "geometry": geometry,
    }


def _frame(rows: list[dict[str, object]], crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, columns=CONTEXT_COLUMNS, geometry="geometry", crs=crs)


def _source_id(row: pd.Series, fallback: object) -> str:
    for key in ("SegmentID", "GlobalID", "FID", "osmid", "osm_id", "id", "element_type"):
        value = row.get(key)
        if _text(value):
            return str(value)
    return str(fallback)


def _tag_values(value: object) -> list[str]:
    if value is None or (not isinstance(value, (str, list, tuple)) and bool(pd.isna(value))):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (SyntaxError, ValueError):
            pass
    return [str(value)] if str(value).strip() else []


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        text = ",".join(str(item) for item in value).strip()
        return text or None
    missing = pd.isna(value)
    if not hasattr(missing, "__iter__") and bool(missing):
        return None
    text = str(value).strip()
    return text or None
