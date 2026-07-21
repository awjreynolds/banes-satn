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
from shapely.geometry import mapping

from satn.compiler import CompiledNetwork
from satn.constants import DISCLAIMER, SCHEMA_VERSION
from satn.models import CouncilConfig
from satn.sources import OSM_ATTRIBUTION


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
    if not compiled.gaps.empty:
        compiled.gaps.to_file(path, layer="gaps", driver="GPKG")
    if not compiled.urban_spines.empty:
        compiled.urban_spines.to_file(path, layer="urban_spines", driver="GPKG")
    if not compiled.low_traffic_areas.empty:
        compiled.low_traffic_areas.to_file(
            path, layer="candidate_low_traffic_areas", driver="GPKG"
        )
    if not compiled.crossing_warnings.empty:
        compiled.crossing_warnings.to_file(
            path, layer="crossing_warnings", driver="GPKG"
        )
    if compiled.atm_reference is not None:
        compiled.atm_reference.to_file(path, layer="atm_reference", driver="GPKG")
    _metadata_frame(compiled.places.crs).to_file(path, layer="metadata", driver="GPKG")


def _features(frame: gpd.GeoDataFrame, feature_type: str) -> list[dict[str, object]]:
    return [
        {
            "type": "Feature",
            "id": _feature_id(row),
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


def _feature_id(row: pd.Series) -> str:
    for key in (
        "connection_id",
        "place_id",
        "structure_id",
        "warning_id",
        "portal_feature_id",
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
            + _features(compiled.gaps, "gap")
            + _features(compiled.urban_spines, "urban-spine")
            + _features(compiled.low_traffic_areas, "low-traffic-area")
            + _features(compiled.crossing_warnings, "crossing-warning")
            + (
                _features(compiled.atm_reference, "atm-reference")
                if compiled.atm_reference is not None
                else []
            )
        ),
    }


def _write_geojson(path: Path, compiled: CompiledNetwork) -> None:
    path.write_text(json.dumps(_network_collection(compiled), indent=2), encoding="utf-8")


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
        "status": "complete" if compiled.gaps.empty else "reviewable",
        "criteria": {
            section: {criterion: status.value for criterion, status in values.items()}
            for section, values in compiled.criteria.items()
        },
        "connection_count": len(compiled.connections),
        "gap_count": len(compiled.gaps),
        "crossing_warning_count": len(compiled.crossing_warnings),
        "network_units": compiled.network_units,
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
    (output / "agent-records.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    divergences = {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": DISCLAIMER,
        "records": [
            record.model_dump(mode="json") for record in compiled.divergence_records
        ],
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
    atm_control = (
        '<label><input id="layer-atm" type="checkbox" checked> ATM comparison</label>'
        if compiled.atm_reference is not None
        else ""
    )
    html = (
        template.replace("__TITLE__", escape(config.publication.title))
        .replace("__DISCLAIMER__", DISCLAIMER)
        .replace("__ATM_CONTROL__", atm_control)
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
                "records": [
                    record.model_dump(mode="json") for record in compiled.agent_records
                ],
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
                    record.model_dump(mode="json")
                    for record in compiled.divergence_records
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (review / "README.txt").write_text(
        f"{DISCLAIMER}\n{OSM_ATTRIBUTION}\n", encoding="utf-8"
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
    canvas = Canvas(str(path), pagesize=(width, height), pageCompression=0)
    canvas.setTitle(config.publication.title)
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawString(42, height - 42, config.publication.title)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(42, height - 58, f"Compiled {datetime.now(UTC).date().isoformat()}")
    _draw_legend(canvas, width, height, compiled.atm_reference is not None)
    map_frames = [
        frame.to_crs(3857)
        for frame in (
            compiled.connections,
            compiled.urban_spines,
            compiled.low_traffic_areas,
            compiled.crossing_warnings,
            *([compiled.atm_reference] if compiled.atm_reference is not None else []),
        )
        if not frame.empty
    ]
    if map_frames:
        bounds_frame = gpd.GeoDataFrame(
            geometry=[geometry for frame in map_frames for geometry in frame.geometry], crs=3857
        )
        min_x, min_y, max_x, max_y = bounds_frame.total_bounds
        scale = min((width - 84) / max(max_x - min_x, 1), (height - 140) / max(max_y - min_y, 1))
        if not compiled.low_traffic_areas.empty:
            canvas.setStrokeColor(HexColor("#2874a6"))
            canvas.setFillColor(HexColor("#d6eaf8"))
            for geometry in compiled.low_traffic_areas.to_crs(3857).geometry:
                _draw_geometry(canvas, geometry, min_x, min_y, scale, fill=True)
        if not compiled.urban_spines.empty:
            canvas.setStrokeColor(HexColor("#8e44ad"))
            canvas.setLineWidth(3)
            for geometry in compiled.urban_spines.to_crs(3857).geometry:
                _draw_geometry(canvas, geometry, min_x, min_y, scale)
        if compiled.atm_reference is not None:
            canvas.setStrokeColor(HexColor("#2980b9"))
            canvas.setLineWidth(2)
            for geometry in compiled.atm_reference.to_crs(3857).geometry:
                _draw_geometry(canvas, geometry, min_x, min_y, scale)
        canvas.setStrokeColor(HexColor("#196f3d"))
        canvas.setLineWidth(5)
        for geometry in compiled.connections.to_crs(3857).geometry:
            _draw_geometry(canvas, geometry, min_x, min_y, scale)
        if not compiled.crossing_warnings.empty:
            canvas.setFillColor(HexColor("#f39c12"))
            for point in compiled.crossing_warnings.to_crs(3857).geometry:
                px = 42 + (point.x - min_x) * scale
                py = 70 + (point.y - min_y) * scale
                canvas.circle(px, py, 5, stroke=1, fill=1)
        _draw_scale(canvas, scale)
    canvas.setFont("Helvetica", 10)
    text = DISCLAIMER
    if stringWidth(text, "Helvetica", 10) > width - 84:
        text = "Experimental SATN POC — not an adopted council plan."
    canvas.drawString(42, 32, text)
    canvas.save()


def _draw_legend(canvas: Canvas, width: float, height: float, include_atm: bool) -> None:
    entries = [
        ("#196f3d", "Community Connection"),
        ("#8e44ad", "Urban protected spine"),
        ("#2874a6", "Candidate Low-Traffic Area"),
        ("#c0392b", "Network Gap"),
        ("#f39c12", "Crossing Warning"),
    ]
    if include_atm:
        entries.append(("#2980b9", "ATM reference"))
    x = width - 225
    y = height - 38
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(x, y, "Legend")
    canvas.setFont("Helvetica", 9)
    for colour, label in entries:
        y -= 14
        canvas.setStrokeColor(HexColor(colour))
        canvas.setLineWidth(4)
        canvas.line(x, y + 3, x + 24, y + 3)
        canvas.setFillColor(HexColor("#17202a"))
        canvas.drawString(x + 31, y, label)


def _draw_scale(canvas: Canvas, map_scale: float) -> None:
    distance_km = min((0.5, 1, 2, 5, 10), key=lambda value: abs(value * 1000 * map_scale - 120))
    pixels = distance_km * 1000 * map_scale
    canvas.setStrokeColor(HexColor("#17202a"))
    canvas.setLineWidth(2)
    canvas.line(42, 54, 42 + pixels, 54)
    canvas.line(42, 50, 42, 58)
    canvas.line(42 + pixels, 50, 42 + pixels, 58)
    canvas.setFillColor(HexColor("#17202a"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(42, 60, f"{distance_km:g} km scale")


def _draw_geometry(
    canvas: Canvas,
    geometry: object,
    min_x: float,
    min_y: float,
    scale: float,
    *,
    fill: bool = False,
) -> None:
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
            px = 42 + (x - min_x) * scale
            py = 70 + (y - min_y) * scale
            (path_obj.moveTo if index == 0 else path_obj.lineTo)(px, py)
        if fill:
            path_obj.close()
        canvas.drawPath(path_obj, stroke=1, fill=int(fill))


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
    for filename in ("agent-records.json", "divergence-records.json"):
        record_file = json.loads((output / filename).read_text(encoding="utf-8"))
        if record_file.get("disclaimer") != DISCLAIMER:
            raise ValueError(f"{filename} disclaimer mismatch")
    html = (output / "review-map" / "index.html").read_text(encoding="utf-8")
    if DISCLAIMER not in html:
        raise ValueError("review map disclaimer missing")
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
