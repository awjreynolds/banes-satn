"""Atomic publication of spatial, machine-readable and visual artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from html import escape
from importlib.resources import files
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A2, A3, A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from shapely.geometry import MultiLineString, mapping

from satn.compiler import CompiledNetwork
from satn.constants import DISCLAIMER, SCHEMA_VERSION
from satn.models import CouncilConfig
from satn.sources import NCN_ATTRIBUTION, OSM_ATTRIBUTION


def publish(
    config: CouncilConfig,
    compiled: CompiledNetwork,
    run_id: str,
) -> dict[str, Path]:
    output = config.publication.output_dir
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_geopackage(temporary / "network.gpkg", compiled)
        _write_geojson(temporary / "network.geojson", compiled)
        _write_json_records(temporary, config, compiled, run_id)
        review = temporary / "review-map"
        review.mkdir()
        _write_review_map(review, config, compiled)
        _zip_review_map(temporary / "review-map.zip", review)
        _write_pdf(temporary / "network-map.pdf", config, compiled)
        _validate_artifacts(temporary, config)
        backup = output.with_name(f".{output.name}-previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            output.replace(backup)
        temporary.replace(output)
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "geopackage": output / "network.gpkg",
        "geojson": output / "network.geojson",
        "run": output / "run.json",
        "agents": output / "agent-records.json",
        "divergences": output / "divergence-records.json",
        "review_map": output / "review-map" / "index.html",
        "review_zip": output / "review-map.zip",
        "pdf": output / "network-map.pdf",
    }


def _metadata_frame(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [{"schema_version": SCHEMA_VERSION, "disclaimer": DISCLAIMER, "geometry": None}],
        geometry="geometry",
        crs=crs,
    )


def _write_geopackage(path: Path, compiled: CompiledNetwork) -> None:
    compiled.connections.to_file(path, layer="connections", driver="GPKG")
    compiled.places.to_file(path, layer="places", driver="GPKG")
    if not compiled.strategic_spines.empty:
        compiled.strategic_spines.to_file(path, layer="strategic_spines", driver="GPKG")
    if not compiled.access_obligations.empty:
        compiled.access_obligations.to_file(path, layer="access_obligations", driver="GPKG")
    if not compiled.spine_access_connections.empty:
        compiled.spine_access_connections.to_file(
            path, layer="spine_access_connections", driver="GPKG"
        )
    if not compiled.spine_access_branches.empty:
        compiled.spine_access_branches.to_file(path, layer="spine_access_branches", driver="GPKG")
    if not compiled.gaps.empty:
        compiled.gaps.to_file(path, layer="gaps", driver="GPKG")
    if not compiled.urban_spines.empty:
        compiled.urban_spines.to_file(path, layer="urban_spines", driver="GPKG")
    if not compiled.low_traffic_areas.empty:
        compiled.low_traffic_areas.to_file(path, layer="candidate_low_traffic_areas", driver="GPKG")
    if not compiled.crossing_warnings.empty:
        compiled.crossing_warnings.to_file(path, layer="crossing_warnings", driver="GPKG")
    for layer_name, frame in (
        ("a_road_spines", compiled.a_road_spines),
        ("ncn_routes", compiled.ncn_routes),
        ("schools", compiled.schools),
        ("retail_centres", compiled.retail_centres),
        ("healthcare", compiled.healthcare),
    ):
        if not frame.empty:
            _geopackage_safe(frame).to_file(path, layer=layer_name, driver="GPKG")
    if compiled.atm_reference is not None:
        _geopackage_safe(compiled.atm_reference).to_file(path, layer="atm_reference", driver="GPKG")
    _metadata_frame(compiled.places.crs).to_file(path, layer="metadata", driver="GPKG")


def _geopackage_safe(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Preserve source attributes without colliding with GeoPackage internals."""
    renamed: dict[str, str] = {}
    occupied = set(frame.columns)
    for column in frame.columns:
        if column.lower() != "fid":
            continue
        candidate = "source_fid"
        suffix = 2
        while candidate in occupied:
            candidate = f"source_fid_{suffix}"
            suffix += 1
        renamed[column] = candidate
        occupied.add(candidate)
    return frame.rename(columns=renamed)


def _features(frame: gpd.GeoDataFrame, feature_type: str) -> list[dict[str, object]]:
    return [
        {
            "type": "Feature",
            "id": _feature_id(row, feature_type),
            "properties": {
                key: _json_value(value)
                for key, value in row.items()
                if key != "geometry" and _json_value(value) is not None
            }
            | {"feature_type": feature_type},
            "geometry": mapping(row.geometry) if row.geometry is not None else None,
        }
        for _, row in frame.to_crs(4326).iterrows()
    ]


def _feature_id(row: pd.Series, feature_type: str | None = None) -> str:
    preferred = {
        "access-obligation": "obligation_id",
        "spine-access-connection": "access_connection_id",
        "spine-access-branch": "branch_id",
        "strategic-spine": "spine_id",
        "connection": "connection_id",
        "gap": "connection_id",
    }.get(feature_type)
    if preferred:
        value = _json_value(row.get(preferred))
        if value is not None:
            return str(value)
    for key in (
        "connection_id",
        "obligation_id",
        "access_connection_id",
        "branch_id",
        "spine_id",
        "place_id",
        "structure_id",
        "warning_id",
        "portal_feature_id",
        "evidence_id",
        "id",
        "fid",
    ):
        value = _json_value(row.get(key))
        if value is not None:
            return str(value)
    digest = hashlib.sha256(row.geometry.wkb).hexdigest()[:12]
    return f"feature-{digest}"


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or (not isinstance(value, str) and bool(pd.isna(value))):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _network_collection(compiled: CompiledNetwork) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "name": "SATN compiled network",
        "disclaimer": DISCLAIMER,
        "features": (
            _features(compiled.connections, "connection")
            + _features(compiled.strategic_spines, "strategic-spine")
            + _features(compiled.access_obligations, "access-obligation")
            + _features(compiled.spine_access_connections, "spine-access-connection")
            + _features(compiled.spine_access_branches, "spine-access-branch")
            + _features(compiled.gaps, "gap")
            + _features(compiled.urban_spines, "urban-spine")
            + _features(compiled.low_traffic_areas, "low-traffic-area")
            + _features(compiled.crossing_warnings, "crossing-warning")
            + _features(compiled.a_road_spines, "a-road-spine")
            + _features(compiled.ncn_routes, "ncn-route")
            + _features(compiled.schools, "school")
            + _features(compiled.retail_centres, "retail-centre")
            + _features(compiled.healthcare, "healthcare")
            + (
                _features(compiled.atm_reference, "atm-reference")
                if compiled.atm_reference is not None
                else []
            )
        ),
    }


def _write_geojson(path: Path, compiled: CompiledNetwork) -> None:
    path.write_text(json.dumps(_network_collection(compiled), indent=2), encoding="utf-8")


def _layer_counts(compiled: CompiledNetwork) -> dict[str, int]:
    return {
        "strategic_spines": len(compiled.strategic_spines),
        "access_obligations": len(compiled.access_obligations),
        "spine_access_connections": len(compiled.spine_access_connections),
        "spine_access_branches": len(compiled.spine_access_branches),
        "a_road_spines": len(compiled.a_road_spines),
        "ncn_routes": len(compiled.ncn_routes),
        "schools": len(compiled.schools),
        "retail_centres": len(compiled.retail_centres),
        "healthcare": len(compiled.healthcare),
    }


def _write_json_records(
    output: Path,
    config: CouncilConfig,
    compiled: CompiledNetwork,
    run_id: str,
) -> None:
    run = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "council_id": config.council_id,
        "status": compiled.status,
        "criteria": {
            section: {criterion: status.value for criterion, status in values.items()}
            for section, values in compiled.criteria.items()
        },
        "connection_count": len(compiled.connections),
        "gap_count": len(compiled.gaps),
        "crossing_warning_count": len(compiled.crossing_warnings),
        "layer_counts": _layer_counts(compiled),
        "network_units": compiled.network_units,
        "superseded_hypotheses": compiled.superseded_hypotheses,
        "cache": {"hits": compiled.cache_hits, "misses": compiled.cache_misses},
        "atm_mode": config.atm.mode if config.atm.enabled else "disabled",
        "atm_geometry_included": compiled.atm_reference is not None,
        "disclaimer": DISCLAIMER,
    }
    (output / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    records = {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": DISCLAIMER,
        "records": [record.model_dump(mode="json") for record in compiled.agent_records],
    }
    (output / "agent-records.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    divergences = {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": DISCLAIMER,
        "records": [record.model_dump(mode="json") for record in compiled.divergence_records],
    }
    (output / "divergence-records.json").write_text(
        json.dumps(divergences, indent=2), encoding="utf-8"
    )


def _write_review_map(
    review: Path,
    config: CouncilConfig,
    compiled: CompiledNetwork,
) -> None:
    asset_root = files("satn.assets")
    asset_output = review / "assets"
    asset_output.mkdir()
    for name in (
        "maplibre-gl.js",
        "maplibre-gl.css",
        "MAPLIBRE-LICENSE.txt",
        "review-map.js",
        "review-map.css",
    ):
        (asset_output / name).write_bytes((asset_root / name).read_bytes())
    template = (asset_root / "review-map.html").read_text(encoding="utf-8")
    atm_state = "" if compiled.atm_reference is not None else "disabled"
    atm_status = (
        "A governed ATM reference is bundled locally; toggle it to compare before/after."
        if compiled.atm_reference is not None
        else "ATM geometry is not published. Load a governed local GeoJSON to compare it."
    )
    html = (
        template.replace("__TITLE__", escape(config.publication.title))
        .replace("__DISCLAIMER__", DISCLAIMER)
        .replace("__ATM_STATE__", atm_state)
        .replace("__ATM_STATUS__", atm_status)
    )
    (review / "index.html").write_text(html, encoding="utf-8")
    data = {
        "network": _network_collection(compiled),
        "places": {
            "type": "FeatureCollection",
            "features": _features(compiled.places, "place"),
        },
        "criteria": {
            section: {criterion: status.value for criterion, status in values.items()}
            for section, values in compiled.criteria.items()
        },
        "disclaimer": DISCLAIMER,
        "layer_counts": _layer_counts(compiled),
    }
    (review / "data.js").write_text(
        f"window.SATN_DATA = {json.dumps(data).replace('</', '<\\/')};\n",
        encoding="utf-8",
    )
    (review / "network.geojson").write_text(
        json.dumps(_network_collection(compiled), indent=2), encoding="utf-8"
    )
    (review / "agent-records.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "disclaimer": DISCLAIMER,
                "records": [record.model_dump(mode="json") for record in compiled.agent_records],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (review / "divergence-records.json").write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "disclaimer": DISCLAIMER,
                "records": [
                    record.model_dump(mode="json") for record in compiled.divergence_records
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (review / "README.txt").write_text(
        f"{DISCLAIMER}\n{OSM_ATTRIBUTION}\n{NCN_ATTRIBUTION}\n", encoding="utf-8"
    )


def _zip_review_map(path: Path, review: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(path for path in review.rglob("*") if path.is_file()):
            archive.write(item, arcname=f"review-map/{item.relative_to(review)}")


def _write_pdf(path: Path, config: CouncilConfig, compiled: CompiledNetwork) -> None:
    page_sizes = {"A2": A2, "A3": A3, "A4": A4}
    requested = config.publication.pdf_page_size.upper()
    if requested not in page_sizes:
        raise ValueError(f"unsupported PDF page size: {requested}")
    width, height = landscape(page_sizes[requested])
    canvas = Canvas(str(path), pagesize=(width, height), pageCompression=1)
    canvas.setTitle(config.publication.title)
    canvas.setFillColor(HexColor("#17202a"))
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(42, height - 34, config.publication.title)
    canvas.setFillColor(HexColor("#566573"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(
        42,
        height - 50,
        f"Experimental network review | {len(compiled.connections)} connections | "
        f"Compiled {datetime.now(UTC).date().isoformat()}",
    )
    _draw_legend(canvas, width, height, compiled.atm_reference is not None)
    if not compiled.boundary.empty:
        boundary = compiled.boundary.to_crs(3857)
        boundary_shape = boundary.geometry.union_all()
        min_x, min_y, max_x, max_y = boundary.total_bounds
        padding = max(max_x - min_x, max_y - min_y) * 0.025
        min_x, min_y = min_x - padding, min_y - padding
        max_x, max_y = max_x + padding, max_y + padding
        map_left, map_bottom = 42.0, 58.0
        map_right, map_top = width - 42.0, height - 76.0
        map_width, map_height = map_right - map_left, map_top - map_bottom
        scale = min(map_width / (max_x - min_x), map_height / (max_y - min_y))
        origin_x = map_left + (map_width - (max_x - min_x) * scale) / 2
        origin_y = map_bottom + (map_height - (max_y - min_y) * scale) / 2
        clip_shape = boundary_shape.buffer(1200)

        canvas.setFillColor(HexColor("#f5f3eb"))
        canvas.setStrokeColor(HexColor("#7b8794"))
        canvas.setLineWidth(0.9)
        _draw_geometry(canvas, boundary_shape, min_x, min_y, scale, origin_x, origin_y, fill=True)

        roads = compiled.road_context.to_crs(3857)
        context_mask = roads.get("highway", pd.Series(index=roads.index, dtype=object)).map(
            _is_pdf_context_road
        )
        road_geometries = [
            geometry.intersection(boundary_shape)
            for geometry in roads.loc[context_mask].geometry
            if geometry is not None and not geometry.is_empty
        ]
        canvas.setStrokeColor(HexColor("#d2d5d8"))
        canvas.setLineWidth(0.32)
        _draw_line_collection(canvas, road_geometries, min_x, min_y, scale, origin_x, origin_y)

        canvas.setStrokeColor(HexColor("#c56a1a"))
        canvas.setLineWidth(2.4)
        _draw_line_collection(
            canvas,
            _clipped_linework(compiled.a_road_spines, clip_shape),
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )

        canvas.setStrokeColor(HexColor("#187aa5"))
        canvas.setLineWidth(1.25)
        canvas.setDash(5, 3)
        _draw_line_collection(
            canvas,
            _clipped_linework(compiled.ncn_routes, clip_shape),
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )
        canvas.setDash()

        if compiled.atm_reference is not None:
            canvas.setStrokeColor(HexColor("#7b61a8"))
            canvas.setLineWidth(1.1)
            canvas.setDash(2, 2)
            _draw_line_collection(
                canvas,
                _clipped_linework(compiled.atm_reference, clip_shape),
                min_x,
                min_y,
                scale,
                origin_x,
                origin_y,
            )
            canvas.setDash()

        connection_geometries: list[object] = []
        for _, connection in compiled.connections.to_crs(3857).iterrows():
            geometry = connection.geometry.intersection(clip_shape)
            if connection["classification"] == "strategic-spine":
                geometry = _offset_linework(geometry, 3.2 / scale)
            connection_geometries.append(geometry)
        canvas.setStrokeColor(HexColor("#ffffff"))
        canvas.setLineWidth(3.4)
        _draw_line_collection(
            canvas,
            connection_geometries,
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )
        canvas.setStrokeColor(HexColor("#08783f"))
        canvas.setLineWidth(1.8)
        _draw_line_collection(
            canvas,
            connection_geometries,
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )

        _draw_pdf_places(
            canvas,
            compiled.label_places,
            min_x,
            min_y,
            max_x,
            max_y,
            scale,
            origin_x,
            origin_y,
            boundary_shape,
        )
        if not compiled.crossing_warnings.empty:
            canvas.setStrokeColor(HexColor("#7d5100"))
            canvas.setFillColor(HexColor("#f4b942"))
            for point in compiled.crossing_warnings.to_crs(3857).geometry:
                px, py = _page_point(point.x, point.y, min_x, min_y, scale, origin_x, origin_y)
                canvas.circle(px, py, 2.8, stroke=1, fill=1)
        _draw_scale(canvas, scale, origin_x, origin_y)

    canvas.setFillColor(HexColor("#566573"))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(
        42,
        24,
        "Sources: OpenStreetMap contributors (ODbL); Walk Wheel Cycle Trust NCN (OGL v3.0).",
    )
    canvas.drawRightString(width - 42, 24, DISCLAIMER)
    canvas.save()


def _draw_legend(canvas: Canvas, width: float, height: float, include_atm: bool) -> None:
    entries = [
        ("#c56a1a", "A-road corridor"),
        ("#08783f", "Community connection"),
        ("#187aa5", "National Cycle Network"),
        ("#f4b942", "Crossing warning"),
    ]
    if include_atm:
        entries.append(("#7b61a8", "ATM reference"))
    x = width - 430
    y = height - 31
    canvas.setFillColor(HexColor("#17202a"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawRightString(x - 10, y, "Legend")
    canvas.setFont("Helvetica", 8)
    for index, (colour, label) in enumerate(entries):
        column = index % 2
        row = index // 2
        item_x = x + column * 190
        item_y = y - row * 16
        canvas.setStrokeColor(HexColor(colour))
        canvas.setLineWidth(3)
        canvas.line(item_x, item_y + 2, item_x + 22, item_y + 2)
        canvas.setFillColor(HexColor("#17202a"))
        canvas.drawString(item_x + 28, item_y, label)


def _is_pdf_context_road(value: object) -> bool:
    text = str(value).lower()
    return any(
        road_class in text
        for road_class in (
            "trunk",
            "primary",
            "secondary",
            "tertiary",
            "residential",
            "unclassified",
        )
    )


def _clipped_linework(frame: gpd.GeoDataFrame, clip_shape: object) -> list[object]:
    if frame.empty:
        return []
    return [
        geometry.intersection(clip_shape)
        for geometry in frame.to_crs(3857).geometry
        if geometry is not None and not geometry.is_empty and geometry.intersects(clip_shape)
    ]


def _line_coordinate_sets(geometry: object) -> list[object]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry.coords]
    if geometry.geom_type == "MultiLineString":
        return [part.coords for part in geometry.geoms]
    if hasattr(geometry, "geoms"):
        return [
            coordinates for part in geometry.geoms for coordinates in _line_coordinate_sets(part)
        ]
    return []


def _page_point(
    x: float,
    y: float,
    min_x: float,
    min_y: float,
    scale: float,
    origin_x: float,
    origin_y: float,
) -> tuple[float, float]:
    return origin_x + (x - min_x) * scale, origin_y + (y - min_y) * scale


def _draw_line_collection(
    canvas: Canvas,
    geometries: list[object],
    min_x: float,
    min_y: float,
    scale: float,
    origin_x: float,
    origin_y: float,
) -> None:
    path_obj = canvas.beginPath()
    drew_line = False
    for geometry in geometries:
        for coordinates in _line_coordinate_sets(geometry):
            for index, (x, y) in enumerate(coordinates):
                px, py = _page_point(x, y, min_x, min_y, scale, origin_x, origin_y)
                (path_obj.moveTo if index == 0 else path_obj.lineTo)(px, py)
            drew_line = True
    if drew_line:
        canvas.drawPath(path_obj, stroke=1, fill=0)


def _draw_pdf_places(
    canvas: Canvas,
    places: gpd.GeoDataFrame,
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    scale: float,
    origin_x: float,
    origin_y: float,
    boundary_shape: object,
) -> None:
    projected = places.to_crs(3857)
    if "kind" in projected.columns:
        projected = projected[
            projected["kind"].isin(["community", "cross_boundary_gateway"])
        ].copy()
    else:
        projected = projected.copy()
        projected["kind"] = "community"
        projected["place_class"] = projected.get("place", "village")
    if "place_class" not in projected.columns:
        projected["place_class"] = projected["kind"].map(
            {"cross_boundary_gateway": "gateway", "community": "village"}
        )
    projected = projected[
        projected["name"].notna()
        & ~projected["name"].astype(str).str.startswith("Towards ")
        & projected["place_class"].ne("hamlet")
    ].copy()
    projected["geometry"] = projected.geometry.representative_point()
    projected = projected.cx[min_x:max_x, min_y:max_y]
    projected = projected[projected.geometry.map(boundary_shape.covers)]
    projected = projected.drop_duplicates("name")
    priorities = {
        "city": 0,
        "gateway": 1,
        "town": 2,
        "quarter": 3,
        "neighbourhood": 4,
        "village": 5,
        "suburb": 6,
    }
    projected["_priority"] = projected["place_class"].map(priorities).fillna(9)
    projected = projected.sort_values(["_priority", "name"])

    canvas.setStrokeColor(HexColor("#34495e"))
    for _, place in projected.iterrows():
        px, py = _page_point(
            place.geometry.x,
            place.geometry.y,
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )
        radius = 2.8 if place["place_class"] in {"city", "town", "gateway"} else 1.45
        canvas.setFillColor(HexColor("#ffffff"))
        canvas.circle(px, py, radius, stroke=1, fill=1)

    occupied: list[tuple[float, float, float, float]] = []
    label_count = 0
    map_right = origin_x + (max_x - min_x) * scale
    map_top = origin_y + (max_y - min_y) * scale
    for _, place in projected.iterrows():
        if label_count >= 48:
            break
        name = str(place["name"])
        place_class = str(place["place_class"])
        font_size = (
            8.4 if place_class == "city" else 7.2 if place_class in {"town", "gateway"} else 5.8
        )
        font_name = "Helvetica-Bold" if place_class in {"city", "town", "gateway"} else "Helvetica"
        width = stringWidth(name, font_name, font_size)
        px, py = _page_point(
            place.geometry.x,
            place.geometry.y,
            min_x,
            min_y,
            scale,
            origin_x,
            origin_y,
        )
        candidates = (
            (px + 3.5, py + 1.5),
            (px + 3.5, py - font_size - 1),
            (px - width - 3.5, py + 1.5),
            (px - width - 3.5, py - font_size - 1),
        )
        selected: tuple[float, float, float, float] | None = None
        for label_x, label_y in candidates:
            box = (label_x - 1, label_y - 1, label_x + width + 1, label_y + font_size + 1)
            inside = (
                box[0] >= origin_x
                and box[1] >= origin_y
                and box[2] <= map_right
                and box[3] <= map_top
            )
            overlaps = any(
                box[0] < other[2] + 2
                and box[2] + 2 > other[0]
                and box[1] < other[3] + 2
                and box[3] + 2 > other[1]
                for other in occupied
            )
            if inside and not overlaps:
                selected = box
                break
        if selected is None:
            continue
        canvas.setFillColor(HexColor("#ffffff"))
        canvas.rect(
            selected[0],
            selected[1],
            selected[2] - selected[0],
            selected[3] - selected[1],
            stroke=0,
            fill=1,
        )
        canvas.setFillColor(HexColor("#263238"))
        canvas.setFont(font_name, font_size)
        canvas.drawString(selected[0] + 1, selected[1] + 1, name)
        occupied.append(selected)
        label_count += 1


def _draw_scale(
    canvas: Canvas,
    map_scale: float,
    origin_x: float,
    origin_y: float,
) -> None:
    distance_km = min((0.5, 1, 2, 5, 10), key=lambda value: abs(value * 1000 * map_scale - 120))
    pixels = distance_km * 1000 * map_scale
    canvas.setStrokeColor(HexColor("#17202a"))
    canvas.setLineWidth(1.2)
    y = origin_y + 7
    x = origin_x + 8
    canvas.line(x, y, x + pixels, y)
    canvas.line(x, y - 3, x, y + 3)
    canvas.line(x + pixels, y - 3, x + pixels, y + 3)
    canvas.setFillColor(HexColor("#17202a"))
    canvas.setFont("Helvetica", 7)
    canvas.drawString(x, y + 5, f"{distance_km:g} km scale")


def _draw_geometry(
    canvas: Canvas,
    geometry: object,
    min_x: float,
    min_y: float,
    scale: float,
    origin_x: float,
    origin_y: float,
    *,
    fill: bool = False,
) -> None:
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        coordinate_sets = [geometry.exterior.coords]
    elif geometry.geom_type == "MultiPolygon":
        coordinate_sets = [part.exterior.coords for part in geometry.geoms]
    elif geometry.geom_type == "LineString":
        coordinate_sets = [geometry.coords]
    elif geometry.geom_type == "MultiLineString":
        coordinate_sets = [part.coords for part in geometry.geoms]
    else:
        return
    for coordinates in coordinate_sets:
        path_obj = canvas.beginPath()
        for index, (x, y) in enumerate(coordinates):
            px, py = _page_point(x, y, min_x, min_y, scale, origin_x, origin_y)
            (path_obj.moveTo if index == 0 else path_obj.lineTo)(px, py)
        if fill:
            path_obj.close()
        canvas.drawPath(path_obj, stroke=1, fill=int(fill))


def _offset_linework(geometry: object, distance: float) -> object:
    """Apply a print-only cartographic offset without changing governed geometry."""
    if geometry.geom_type == "LineString":
        return geometry.offset_curve(distance)
    if geometry.geom_type == "MultiLineString":
        return MultiLineString([part.offset_curve(distance) for part in geometry.geoms])
    return geometry


def _validate_artifacts(output: Path, config: CouncilConfig) -> None:
    required = (
        "network.gpkg",
        "network.geojson",
        "run.json",
        "agent-records.json",
        "divergence-records.json",
        "review-map/index.html",
        "review-map/data.js",
        "review-map/assets/maplibre-gl.js",
        "review-map/assets/maplibre-gl.css",
        "review-map/assets/review-map.js",
        "review-map/assets/review-map.css",
        "review-map.zip",
        "network-map.pdf",
    )
    missing = [name for name in required if not (output / name).exists()]
    if missing:
        raise ValueError(f"publication incomplete: {', '.join(missing)}")
    connections = gpd.read_file(output / "network.gpkg", layer="connections")
    metadata = gpd.read_file(output / "network.gpkg", layer="metadata")
    if set(metadata["disclaimer"]) != {DISCLAIMER}:
        raise ValueError("GeoPackage metadata disclaimer mismatch")
    geojson = json.loads((output / "network.geojson").read_text(encoding="utf-8"))
    if geojson.get("disclaimer") != DISCLAIMER:
        raise ValueError("GeoJSON disclaimer mismatch")
    geojson_connection_ids = {
        feature["id"]
        for feature in geojson["features"]
        if feature["properties"].get("feature_type") == "connection"
    }
    if geojson_connection_ids != set(connections["connection_id"]):
        raise ValueError("connection identifiers differ between GeoPackage and GeoJSON")
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    if run.get("disclaimer") != DISCLAIMER or run.get("connection_count") != len(connections):
        raise ValueError("run manifest does not describe the current publication")
    spatial_layer_names = set(gpd.list_layers(output / "network.gpkg")["name"])
    layer_types = {
        "strategic_spines": "strategic-spine",
        "access_obligations": "access-obligation",
        "spine_access_connections": "spine-access-connection",
        "spine_access_branches": "spine-access-branch",
        "a_road_spines": "a-road-spine",
        "ncn_routes": "ncn-route",
        "schools": "school",
        "retail_centres": "retail-centre",
        "healthcare": "healthcare",
    }
    for layer_name, feature_type in layer_types.items():
        expected_count = run.get("layer_counts", {}).get(layer_name, 0)
        actual_count = sum(
            feature["properties"].get("feature_type") == feature_type
            for feature in geojson["features"]
        )
        if actual_count != expected_count:
            raise ValueError(f"{layer_name} count differs between run and GeoJSON")
        if expected_count and layer_name not in spatial_layer_names:
            raise ValueError(f"GeoPackage is missing populated layer: {layer_name}")
    for filename in ("agent-records.json", "divergence-records.json"):
        record_file = json.loads((output / filename).read_text(encoding="utf-8"))
        if record_file.get("disclaimer") != DISCLAIMER:
            raise ValueError(f"{filename} disclaimer mismatch")
    html = (output / "review-map" / "index.html").read_text(encoding="utf-8")
    if DISCLAIMER not in html:
        raise ValueError("review map disclaimer missing")
    for control in (
        "layer-strategic-spines",
        "layer-spine-access-connections",
        "layer-a-road-spines",
        "layer-community-connections",
        "layer-ncn-routes",
        "layer-schools",
        "layer-retail-centres",
        "layer-healthcare",
        "layer-atm",
        "atm-upload",
    ):
        if f'id="{control}"' not in html:
            raise ValueError(f"review map control missing: {control}")
    expected_zip_files = {
        f"review-map/{item.relative_to(output / 'review-map')}"
        for item in (output / "review-map").rglob("*")
        if item.is_file()
    }
    with zipfile.ZipFile(output / "review-map.zip") as archive:
        if set(archive.namelist()) != expected_zip_files:
            raise ValueError("review-map ZIP differs from the static directory")
    if not (output / "network-map.pdf").read_bytes().startswith(b"%PDF"):
        raise ValueError("invalid PDF output")
    pdf_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(output / "network-map.pdf").pages
    )
    for required_text in (
        config.publication.title,
        DISCLAIMER,
        "Legend",
        "scale",
        "Compiled",
    ):
        if required_text not in pdf_text:
            raise ValueError(f"PDF is missing required text: {required_text}")
