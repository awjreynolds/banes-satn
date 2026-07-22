"""Immutable OSM/fixture snapshots and council-neutral Network Place derivation."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
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
from satn.evidence import derive_context_layers, empty_context, govern_network_scope
from satn.models import CouncilConfig, OfficialRoadClassification

CORE_SOURCE_FILES = ("boundary.geojson", "places.geojson", "network.geojson")
OSM_ATTRIBUTION = "© OpenStreetMap contributors; data available under the ODbL"
NCN_ATTRIBUTION = "Walk Wheel Cycle Trust National Cycle Network; Open Government Licence v3.0"
ROAD_CLASSIFICATION_FILENAME = "official-road-classification.geojson"
ROAD_CLASSIFICATION_COLUMNS = [
    "official_feature_id",
    "official_classification",
    "source_id",
    "effective_date",
    "licence",
    "content_fingerprint",
    "geometry",
]


@dataclass
class OSMData:
    boundary: gpd.GeoDataFrame
    place_features: gpd.GeoDataFrame
    stations: gpd.GeoDataFrame
    network: gpd.GeoDataFrame
    graph: object | None = None
    ncn_routes: gpd.GeoDataFrame | None = None
    facilities: gpd.GeoDataFrame | None = None


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
        ncn_routes = (
            _load_ncn_features(config.source.ncn_feature_service_url, boundary)
            if config.source.ncn_feature_service_url
            else None
        )
        facilities = ox.features_from_polygon(
            governed_polygon,
            tags={
                "amenity": [
                    "school",
                    "college",
                    "university",
                    "doctors",
                    "pharmacy",
                    "clinic",
                    "hospital",
                    "marketplace",
                ],
                "shop": True,
                "landuse": "retail",
                "entrance": True,
                "barrier": ["gate", "lift_gate", "swing_gate"],
            },
        ).reset_index()
        graph = ox.graph_from_polygon(
            governed_polygon,
            network_type=config.source.network_type,
            simplify=True,
            retain_all=True,
        )
        _, network = ox.graph_to_gdfs(graph)
        network = network.reset_index()
        return OSMData(
            boundary,
            place_features,
            stations,
            network,
            graph=graph,
            ncn_routes=ncn_routes,
            facilities=facilities,
        )


def snapshot(
    config: CouncilConfig,
    *,
    replace: bool = False,
    osm_adapter: OSMAdapter | None = None,
) -> Path:
    """Materialise an immutable, attributable source snapshot."""
    destination = config.source.snapshot_dir / config.source.snapshot_id
    if destination.exists() and not replace:
        manifest = json.loads((destination / "snapshot.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") == SCHEMA_VERSION:
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
            attribution = (
                f"{OSM_ATTRIBUTION}; {NCN_ATTRIBUTION}"
                if config.source.ncn_feature_service_url
                else OSM_ATTRIBUTION
            )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": config.source.snapshot_id,
            "council_id": config.council_id,
            "source_kind": config.source.kind,
            "source_identifier": source_identifier,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "attribution": attribution,
            "evidence_sources": {
                "osm": config.source.osm_place_query,
                "ncn": config.source.ncn_feature_service_url,
                "official_road_classification": _road_classification_manifest(
                    config, temporary
                ),
            },
            "files": files,
            "file_sha256": {
                filename: hashlib.sha256((temporary / filename).read_bytes()).hexdigest()
                for filename in files
            },
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
    context_source = config.source.fixture_dir / "context.geojson"
    if context_source.exists():
        shutil.copy2(context_source, temporary / "context.geojson")
    else:
        network = gpd.read_file(temporary / "network.geojson")
        derive_context_layers(network).to_file(temporary / "context.geojson", driver="GeoJSON")
    files = [*CORE_SOURCE_FILES, "context.geojson"]
    if _snapshot_official_road_classification(config, temporary):
        files.append(ROAD_CLASSIFICATION_FILENAME)
    return str(config.source.fixture_dir), files


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
    strategic_destinations = derive_strategic_destinations(
        data.facilities,
        config.source.strategic_destination_source_ids,
        places.crs,
    )
    if not strategic_destinations.empty:
        places = gpd.GeoDataFrame(
            pd.concat([places, strategic_destinations], ignore_index=True),
            geometry="geometry",
            crs=places.crs,
        ).sort_values("place_id")
    context = govern_network_scope(
        derive_context_layers(data.network, data.ncn_routes, data.facilities),
        data.place_features,
        urban_place_types=config.source.urban_place_types,
        urban_scope_buffer_km=config.source.urban_scope_buffer_km,
    )
    frames = {
        "boundary.geojson": data.boundary.to_crs(4326),
        "places.geojson": places.to_crs(4326),
        "network.geojson": data.network.to_crs(4326),
        "osm-place-features.geojson": data.place_features.to_crs(4326),
        "osm-stations.geojson": data.stations.to_crs(4326),
        "context.geojson": context.to_crs(4326),
    }
    for filename, frame in frames.items():
        frame.to_file(temporary / filename, driver="GeoJSON")
    if _snapshot_official_road_classification(config, temporary):
        frames[ROAD_CLASSIFICATION_FILENAME] = gpd.read_file(
            temporary / ROAD_CLASSIFICATION_FILENAME
        )
    if data.graph is not None:
        import osmnx as ox

        ox.save_graphml(data.graph, temporary / "network.graphml")
    return str(config.source.osm_place_query), list(frames)


def _snapshot_official_road_classification(
    config: CouncilConfig,
    temporary: Path,
) -> bool:
    governed = config.source.official_road_classification
    if governed is None:
        return False
    if not governed.path.exists():
        raise ValueError(f"official road classification source is missing: {governed.path}")
    source_bytes = governed.path.read_bytes()
    fingerprint = hashlib.sha256(source_bytes).hexdigest()
    source = gpd.read_file(governed.path)
    if source.crs is None:
        raise ValueError("official road classification source has no CRS")
    classification_column = next(
        (
            column
            for column in ("official_classification", "road_classification", "classification")
            if column in source
        ),
        None,
    )
    if classification_column is None:
        raise ValueError(
            "official road classification requires an official_classification column"
        )
    rows: list[dict[str, object]] = []
    for _, feature in source.iterrows():
        if not isinstance(feature.geometry, (LineString, MultiLineString)):
            continue
        classification = _normalise_official_classification(
            feature.get(classification_column)
        )
        feature_id = _official_road_identifier(feature, classification)
        rows.append(
            {
                "official_feature_id": feature_id,
                "official_classification": classification,
                "source_id": governed.source_id,
                "effective_date": governed.effective_date.isoformat(),
                "licence": governed.licence,
                "content_fingerprint": fingerprint,
                "geometry": feature.geometry,
            }
        )
    if not rows:
        raise ValueError("official road classification source has no line features")
    frame = gpd.GeoDataFrame(
        rows,
        columns=ROAD_CLASSIFICATION_COLUMNS,
        geometry="geometry",
        crs=source.crs,
    )
    frame.to_crs(4326).to_file(
        temporary / ROAD_CLASSIFICATION_FILENAME, driver="GeoJSON"
    )
    return True


def _normalise_official_classification(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if text in {"a", "a road", "class a"}:
        return OfficialRoadClassification.A_ROAD.value
    if text in {"b", "b road", "class b"}:
        return OfficialRoadClassification.B_ROAD.value
    if text in {
        "c",
        "c road",
        "class c",
        "cu",
        "classified unnumbered",
        "classified unnumbered road",
    }:
        return OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value
    if text in {"unclassified", "u", "unclassified road"}:
        return OfficialRoadClassification.UNCLASSIFIED.value
    return OfficialRoadClassification.UNKNOWN.value


def _official_road_identifier(feature: pd.Series, classification: str) -> str:
    for key in ("official_feature_id", "road_id", "osmid", "osm_id", "id"):
        value = feature.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    identity = f"{classification}:{feature.geometry.wkb_hex}"
    return f"official-road-{hashlib.sha256(identity.encode()).hexdigest()[:16]}"


def _road_classification_manifest(
    config: CouncilConfig,
    snapshot_path: Path,
) -> dict[str, object] | None:
    governed = config.source.official_road_classification
    path = snapshot_path / ROAD_CLASSIFICATION_FILENAME
    if governed is None or not path.exists():
        return None
    snapshotted = gpd.read_file(path)
    fingerprint = str(snapshotted.iloc[0]["content_fingerprint"])
    return {
        "source_id": governed.source_id,
        "effective_date": governed.effective_date.isoformat(),
        "licence": governed.licence,
        "content_fingerprint": fingerprint,
        "snapshot_file": ROAD_CLASSIFICATION_FILENAME,
    }


def _load_ncn_features(
    service_url: str,
    boundary: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    min_x, min_y, max_x, max_y = boundary.to_crs(4326).total_bounds
    parameters = urllib.parse.urlencode(
        {
            "f": "geojson",
            "where": "RouteType = 'NCN'",
            "geometry": f"{min_x},{min_y},{max_x},{max_y}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
        }
    )
    request = urllib.request.Request(
        f"{service_url.rstrip('/')}/0/query?{parameters}",
        headers={"User-Agent": "banes-satn/0.1 NCN snapshot"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if "error" in payload:
        raise ValueError(f"NCN feature service failed: {payload['error']}")
    return gpd.GeoDataFrame.from_features(payload.get("features", []), crs=4326)


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


def derive_strategic_destinations(
    facilities: gpd.GeoDataFrame | None,
    source_ids: list[str],
    target_crs: object,
) -> gpd.GeoDataFrame:
    """Promote explicitly configured education sites to Network Places, not Schools."""
    columns = [
        "place_id",
        "name",
        "kind",
        "place_class",
        "parent_place_id",
        "source_id",
        "geometry",
    ]
    if facilities is None or facilities.empty or not source_ids:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=target_crs)
    configured = set(source_ids)
    rows: list[dict[str, object]] = []
    for index, facility in facilities.to_crs(target_crs).iterrows():
        source_id = _source_identifier(facility, index)
        amenity = (_string_value(facility.get("amenity")) or "").lower()
        if source_id not in configured or amenity not in {"college", "university"}:
            continue
        name = _string_value(facility.get("name")) or f"Unnamed {amenity}"
        rows.append(
            {
                "place_id": _stable_id("strategic-destination", source_id, name),
                "name": name,
                "kind": "strategic_destination",
                "place_class": amenity,
                "parent_place_id": None,
                "source_id": source_id,
                "geometry": facility.geometry.representative_point(),
            }
        )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=target_crs)


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
    crossings: list[tuple[Point, Point | None]] = []
    for geometry in network.geometry:
        if geometry.crosses(boundary.boundary):
            for crossing in _extract_points(geometry.intersection(boundary.boundary)):
                crossings.append((crossing, _outward_endpoint(geometry, boundary, crossing)))
    grouped: dict[str, tuple[Point, float]] = {}
    for crossing, outward in crossings:
        if outward is None or not external_centres:
            name = "Unresolved onward corridor"
            grouped.setdefault(name, (crossing, 0.0))
            continue
        destination = min(
            external_centres,
            key=lambda item: _gateway_destination_score(crossing, outward, item["geometry"]),
        )
        distance = _gateway_destination_score(crossing, outward, destination["geometry"])
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


def _outward_endpoint(geometry: object, boundary: object, crossing: Point) -> Point | None:
    """Return the closest exterior endpoint, preserving the road's outward bearing."""
    parts = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
    candidates: list[Point] = []
    for part in parts:
        if not isinstance(part, LineString) or len(part.coords) < 2:
            continue
        for coordinate in (part.coords[0], part.coords[-1]):
            endpoint = Point(coordinate)
            if not boundary.covers(endpoint):
                candidates.append(endpoint)
    return min(candidates, key=crossing.distance) if candidates else None


def _gateway_destination_score(
    crossing: Point,
    outward: Point | None,
    destination: object,
) -> float:
    """Prefer a named centre lying along the outward road corridor."""
    if not isinstance(destination, Point) or outward is None:
        return float("inf")
    direction_x = outward.x - crossing.x
    direction_y = outward.y - crossing.y
    magnitude = (direction_x**2 + direction_y**2) ** 0.5
    if magnitude == 0:
        return crossing.distance(destination)
    direction_x /= magnitude
    direction_y /= magnitude
    destination_x = destination.x - crossing.x
    destination_y = destination.y - crossing.y
    progress = destination_x * direction_x + destination_y * direction_y
    perpendicular = abs(destination_x * direction_y - destination_y * direction_x)
    behind_penalty = 10.0 if progress <= 0 else 0.0
    return behind_penalty + perpendicular + 0.1 * crossing.distance(destination)


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
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"invalid snapshot schema: expected {SCHEMA_VERSION}, "
            f"found {manifest.get('schema_version')}"
        )
    for filename in manifest["files"]:
        file_path = path / filename
        if not file_path.exists():
            raise ValueError(f"invalid snapshot: missing {file_path}")
        frame = gpd.read_file(file_path)
        if frame.crs is None:
            raise ValueError(f"invalid snapshot: {filename} has no CRS")
        expected_hash = manifest.get("file_sha256", {}).get(filename)
        if expected_hash and hashlib.sha256(file_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"invalid snapshot: {filename} content hash mismatch")


def load_snapshot(config: CouncilConfig) -> dict[str, gpd.GeoDataFrame]:
    path = config.source.snapshot_dir / config.source.snapshot_id
    _validate_snapshot(path)
    network = gpd.read_file(path / "network.geojson")
    context_path = path / "context.geojson"
    context = (
        gpd.read_file(context_path) if context_path.exists() else derive_context_layers(network)
    )
    if context.empty:
        context = empty_context(network.crs)
    place_features_path = path / "osm-place-features.geojson"
    classification_path = path / ROAD_CLASSIFICATION_FILENAME
    return {
        "boundary": gpd.read_file(path / "boundary.geojson"),
        "places": gpd.read_file(path / "places.geojson"),
        "label_places": (
            gpd.read_file(place_features_path)
            if place_features_path.exists()
            else gpd.read_file(path / "places.geojson")
        ),
        "network": network,
        "context": context,
        "official_road_classification": (
            gpd.read_file(classification_path)
            if classification_path.exists()
            else gpd.GeoDataFrame(
                columns=ROAD_CLASSIFICATION_COLUMNS,
                geometry="geometry",
                crs=network.crs,
            )
        ),
    }
