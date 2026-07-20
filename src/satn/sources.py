"""Immutable OSM/fixture snapshots and council-neutral Network Place derivation."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import unary_union

from satn.constants import DISCLAIMER, SCHEMA_VERSION
from satn.models import CouncilConfig

CORE_SOURCE_FILES = ("boundary.geojson", "places.geojson", "network.geojson")
OSM_ATTRIBUTION = "© OpenStreetMap contributors; data available under the ODbL"


@dataclass
class OSMData:
    boundary: gpd.GeoDataFrame
    place_features: gpd.GeoDataFrame
    stations: gpd.GeoDataFrame
    network: gpd.GeoDataFrame
    graph: object | None = None


class OSMAdapter(Protocol):
    def acquire(self, config: CouncilConfig) -> OSMData: ...


class OSMnxAdapter:
    """Thin adapter around OSMnx so acquisition can be replaced in offline tests."""

    def acquire(self, config: CouncilConfig) -> OSMData:
        import osmnx as ox

        query = config.source.osm_place_query
        if not query:
            raise ValueError("OSM sources require source.osm_place_query")
        boundary = ox.geocode_to_gdf(query).to_crs(4326)
        governed_polygon = boundary.geometry.union_all()
        buffered = (
            gpd.GeoSeries([governed_polygon], crs=4326)
            .to_crs(27700)
            .buffer(config.source.external_buffer_km * 1000)
            .to_crs(4326)
            .iloc[0]
        )
        place_features = ox.features_from_polygon(
            buffered,
            tags={"place": [*config.source.community_place_types, "hamlet", "city"]},
        ).reset_index()
        stations = ox.features_from_polygon(
            governed_polygon,
            tags={"railway": "station", "amenity": "bus_station", "public_transport": "station"},
        ).reset_index()
        graph = ox.graph_from_polygon(
            governed_polygon,
            network_type=config.source.network_type,
            simplify=True,
            retain_all=True,
        )
        _, network = ox.graph_to_gdfs(graph)
        network = network.reset_index()
        return OSMData(boundary, place_features, stations, network, graph)


def snapshot(
    config: CouncilConfig,
    *,
    replace: bool = False,
    osm_adapter: OSMAdapter | None = None,
) -> Path:
    """Materialise an immutable, attributable source snapshot."""
    destination = config.source.snapshot_dir / config.source.snapshot_id
    if destination.exists() and not replace:
        _validate_snapshot(destination)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        if config.source.kind == "fixture":
            source_identifier, files = _write_fixture_snapshot(config, temporary)
            attribution = "Synthetic test fixture"
        else:
            source_identifier, files = _write_osm_snapshot(
                config, temporary, osm_adapter or OSMnxAdapter()
            )
            attribution = OSM_ATTRIBUTION
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": config.source.snapshot_id,
            "council_id": config.council_id,
            "source_kind": config.source.kind,
            "source_identifier": source_identifier,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "attribution": attribution,
            "files": files,
            "disclaimer": DISCLAIMER,
        }
        (temporary / "snapshot.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        _validate_snapshot(temporary)
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def _write_fixture_snapshot(config: CouncilConfig, temporary: Path) -> tuple[str, list[str]]:
    if config.source.fixture_dir is None:
        raise ValueError("fixture sources require source.fixture_dir")
    for filename in CORE_SOURCE_FILES:
        shutil.copy2(config.source.fixture_dir / filename, temporary / filename)
    return str(config.source.fixture_dir), list(CORE_SOURCE_FILES)


def _write_osm_snapshot(
    config: CouncilConfig,
    temporary: Path,
    adapter: OSMAdapter,
) -> tuple[str, list[str]]:
    data = adapter.acquire(config)
    places = derive_network_places(
        data.boundary,
        data.place_features,
        data.stations,
        data.network,
        config,
    )
    frames = {
        "boundary.geojson": data.boundary.to_crs(4326),
        "places.geojson": places.to_crs(4326),
        "network.geojson": data.network.to_crs(4326),
        "osm-place-features.geojson": data.place_features.to_crs(4326),
        "osm-stations.geojson": data.stations.to_crs(4326),
    }
    for filename, frame in frames.items():
        frame.to_file(temporary / filename, driver="GeoJSON")
    if data.graph is not None:
        import osmnx as ox

        ox.save_graphml(data.graph, temporary / "network.graphml")
    return str(config.source.osm_place_query), list(frames)


def derive_network_places(
    boundary: gpd.GeoDataFrame,
    place_features: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    config: CouncilConfig,
) -> gpd.GeoDataFrame:
    """Derive Communities, portals, station access points and outward gateways."""
    crs = boundary.crs
    boundary_shape = boundary.to_crs(4326).geometry.union_all()
    features = place_features.to_crs(4326).copy()
    rows: list[dict[str, object]] = []
    external_centres: list[dict[str, object]] = []

    for index, feature in features.iterrows():
        name = _string_value(feature.get("name"))
        place_type = _string_value(feature.get("place"))
        if not name or place_type == "hamlet":
            continue
        point = feature.geometry.representative_point()
        inside = boundary_shape.covers(point)
        source_id = _source_identifier(feature, index)
        if not inside:
            if place_type in {"town", "city"}:
                external_centres.append({"name": name, "geometry": point})
            continue
        if place_type not in config.source.community_place_types:
            continue
        community_id = _stable_id("community", source_id, name)
        rows.append(
            {
                "place_id": community_id,
                "name": name,
                "kind": "community",
                "place_class": place_type,
                "parent_place_id": None,
                "source_id": source_id,
                "geometry": point,
            }
        )
        if _span_km(feature.geometry, features.crs) > config.source.internal_portal_threshold_km:
            portals = _connected_portals(feature.geometry, network.to_crs(4326))
            for number, portal in enumerate(portals, start=1):
                rows.append(
                    {
                        "place_id": f"{community_id}-portal-{number}",
                        "name": f"{name} portal {number}",
                        "kind": "community_portal",
                        "place_class": place_type,
                        "parent_place_id": community_id,
                        "source_id": source_id,
                        "geometry": portal,
                    }
                )

    for index, station in stations.to_crs(4326).iterrows():
        point = station.geometry.representative_point()
        if not boundary_shape.covers(point):
            continue
        source_id = _source_identifier(station, index)
        name = _string_value(station.get("name")) or "Unnamed station"
        rows.append(
            {
                "place_id": _stable_id("station", source_id, name),
                "name": name,
                "kind": "station_access",
                "place_class": _station_class(station),
                "parent_place_id": None,
                "source_id": source_id,
                "geometry": point,
            }
        )

    rows.extend(_derive_gateways(boundary_shape, network.to_crs(4326), external_centres))
    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    if result.empty:
        return result.to_crs(crs)
    return result.drop_duplicates("place_id").sort_values("place_id").to_crs(crs)


def _connected_portals(community: object, network: gpd.GeoDataFrame) -> list[Point]:
    if isinstance(community, Point):
        return []
    lines = [
        geometry.intersection(community)
        for geometry in network.geometry
        if geometry.intersects(community)
    ]
    lines = [line for line in lines if not line.is_empty and line.length > 0]
    if not lines or not _linework_connected(lines):
        return []
    intersections = unary_union(network.geometry.tolist()).intersection(community.boundary)
    points = _extract_points(intersections)
    unique: dict[tuple[float, float], Point] = {
        (round(point.x, 7), round(point.y, 7)): point for point in points
    }
    candidates = list(unique.values())
    if len(candidates) <= 4:
        return candidates
    centre = community.representative_point()
    return sorted(candidates, key=lambda point: point.distance(centre), reverse=True)[:4]


def _linework_connected(lines: list[object]) -> bool:
    graph = nx.Graph()
    for linework in lines:
        parts = list(linework.geoms) if isinstance(linework, MultiLineString) else [linework]
        for line in parts:
            if not isinstance(line, LineString) or len(line.coords) < 2:
                continue
            coordinates = [(round(x, 7), round(y, 7)) for x, y in line.coords]
            nx.add_path(graph, coordinates)
    return bool(graph) and nx.is_connected(graph)


def _derive_gateways(
    boundary: object,
    network: gpd.GeoDataFrame,
    external_centres: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not external_centres:
        return []
    crossings: list[Point] = []
    for geometry in network.geometry:
        if geometry.crosses(boundary.boundary):
            crossings.extend(_extract_points(geometry.intersection(boundary.boundary)))
    grouped: dict[str, tuple[Point, float]] = {}
    for crossing in crossings:
        destination = min(external_centres, key=lambda item: crossing.distance(item["geometry"]))
        distance = crossing.distance(destination["geometry"])
        name = str(destination["name"])
        if name not in grouped or distance < grouped[name][1]:
            grouped[name] = (crossing, distance)
    return [
        {
            "place_id": _stable_id("gateway", name, name),
            "name": f"Towards {name}",
            "kind": "cross_boundary_gateway",
            "place_class": "gateway",
            "parent_place_id": None,
            "source_id": name,
            "geometry": point,
        }
        for name, (point, _) in sorted(grouped.items())
    ]


def _extract_points(geometry: object) -> list[Point]:
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, MultiPoint):
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        points: list[Point] = []
        for item in geometry.geoms:
            points.extend(_extract_points(item))
        return points
    return []


def _span_km(geometry: object, crs: object) -> float:
    projected = gpd.GeoSeries([geometry], crs=crs).to_crs(27700)
    min_x, min_y, max_x, max_y = projected.total_bounds
    return max(max_x - min_x, max_y - min_y) / 1000


def _source_identifier(row: pd.Series, fallback: object) -> str:
    for key in ("osmid", "osm_id", "id"):
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(fallback)


def _stable_id(prefix: str, source_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{source_id}:{name}".encode()).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _station_class(row: pd.Series) -> str:
    if _string_value(row.get("railway")) == "station":
        return "rail"
    if _string_value(row.get("amenity")) == "bus_station":
        return "bus"
    return "public_transport"


def _validate_snapshot(path: Path) -> None:
    manifest_path = path / "snapshot.json"
    if not manifest_path.exists():
        raise ValueError(f"invalid snapshot: missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for filename in manifest["files"]:
        file_path = path / filename
        if not file_path.exists():
            raise ValueError(f"invalid snapshot: missing {file_path}")
        frame = gpd.read_file(file_path)
        if frame.crs is None:
            raise ValueError(f"invalid snapshot: {filename} has no CRS")


def load_snapshot(config: CouncilConfig) -> dict[str, gpd.GeoDataFrame]:
    path = config.source.snapshot_dir / config.source.snapshot_id
    _validate_snapshot(path)
    return {
        "boundary": gpd.read_file(path / "boundary.geojson"),
        "places": gpd.read_file(path / "places.geojson"),
        "network": gpd.read_file(path / "network.geojson"),
    }
