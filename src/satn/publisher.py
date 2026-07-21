"""Atomic publication of spatial, machine-readable and visual artifacts."""

# Generated HTML, CSS and JavaScript are kept together so the review map is one portable file.
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from shapely.geometry import mapping

from satn.compiler import CompiledNetwork
from satn.constants import DISCLAIMER, SCHEMA_VERSION
from satn.models import CouncilConfig


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
        _validate_artifacts(temporary)
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
    _metadata_frame(compiled.places.crs).to_file(path, layer="metadata", driver="GPKG")


def _features(frame: gpd.GeoDataFrame, feature_type: str) -> list[dict[str, object]]:
    return [
        {
            "type": "Feature",
            "id": row.get("connection_id", row.get("place_id", row.get("structure_id"))),
            "properties": {
                key: value
                for key, value in row.items()
                if key != "geometry" and value is not None
            }
            | {"feature_type": feature_type},
            "geometry": mapping(row.geometry) if row.geometry is not None else None,
        }
        for _, row in frame.to_crs(4326).iterrows()
    ]


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


def _write_review_map(
    review: Path,
    config: CouncilConfig,
    compiled: CompiledNetwork,
) -> None:
    payload = json.dumps(_network_collection(compiled)).replace("</", "<\\/")
    places = json.dumps(
        {"type": "FeatureCollection", "features": _features(compiled.places, "place")}
    ).replace("</", "<\\/")
    cards = "".join(
        f'<button class="connection" id="item-{row.connection_id}" '
        f'data-feature-id="{row.connection_id}"><strong>{row.from_place} → '
        f'{row.to_place}</strong><span>{row.distance_km:.2f} km · {row.status}</span></button>'
        for _, row in compiled.connections.iterrows()
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{config.publication.title}</title>
<link href="https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css" rel="stylesheet">
<style>
html,body{{margin:0;height:100%;font:16px system-ui;color:#17202a}}main{{display:grid;grid-template-columns:minmax(18rem,28rem) 1fr;height:100%}}aside{{padding:1rem;overflow:auto;border-right:1px solid #ccd1d1}}#map{{min-height:28rem}}.notice{{padding:.65rem;background:#fff4cc;border-left:5px solid #f1c40f}}.connection{{display:block;width:100%;text-align:left;margin:.5rem 0;padding:.75rem;border:2px solid #196f3d;background:white;border-radius:.4rem}}.connection span{{display:block}}.connection:hover,.connection:focus,.connection.active{{background:#e9f7ef;outline:3px solid #17202a}}@media(max-width:760px){{main{{grid-template-columns:1fr;grid-template-rows:auto 55vh}}aside{{border:0}}}}
</style></head><body><main><aside aria-label="Network information"><h1>{config.publication.title}</h1>
<p class="notice" role="note">{DISCLAIMER}</p><fieldset><legend>Evaluation section</legend>
<label><input type="radio" name="section" checked> Connections</label>
<label><input type="radio" name="section"> Network</label>
<label><input type="radio" name="section"> ATM comparison</label></fieldset>
<p><a href="agent-records.json" download>Download full typed agent records</a></p>
<section id="connection-list" aria-label="Connections">{cards}</section>
<section id="feature-details" aria-live="polite"><h2>Details</h2><p>Hover or focus a connection.</p></section>
</aside><div id="map" role="application" aria-label="Interactive SATN review map"></div></main>
<script src="https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js"></script><script>
const network={payload}; const places={places};
const map=new maplibregl.Map({{container:'map',style:{{version:8,sources:{{osm:{{type:'raster',tiles:['https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}}}},layers:[{{id:'osm',type:'raster',source:'osm'}}]}},center:[-2.5,51.4],zoom:11}});
map.addControl(new maplibregl.NavigationControl());
function details(id){{const f=network.features.find(x=>x.id===id);if(!f)return;document.querySelector('#feature-details').innerHTML=`<h2>${{f.properties.from_place}} → ${{f.properties.to_place}}</h2><dl><dt>Status</dt><dd>${{f.properties.status}}</dd><dt>Distance</dt><dd>${{f.properties.distance_km ?? 'unknown'}} km</dd><dt>Rationale</dt><dd>${{f.properties.selection_reason ?? ''}}</dd><dt>Agent gate</dt><dd>${{f.properties.agent_outcome ?? ''}}</dd><dt>Stable ID</dt><dd><code>${{id}}</code></dd></dl>`;document.querySelectorAll('.connection').forEach(x=>x.classList.toggle('active',x.dataset.featureId===id));map.setFilter('connections-highlight',['==',['id'],id]);}}
function extendBounds(bounds,coordinates){{if(typeof coordinates[0]==='number')bounds.extend(coordinates);else coordinates.forEach(item=>extendBounds(bounds,item));}}
map.on('load',()=>{{map.addSource('network',{{type:'geojson',data:network,promoteId:'connection_id'}});map.addLayer({{id:'low-traffic-areas',type:'fill',source:'network',filter:['==',['get','feature_type'],'low-traffic-area'],paint:{{'fill-color':'#85c1e9','fill-opacity':0.3,'fill-outline-color':'#2874a6'}}}});map.addLayer({{id:'urban-spines',type:'line',source:'network',filter:['==',['get','feature_type'],'urban-spine'],paint:{{'line-color':'#8e44ad','line-width':5}}}});map.addLayer({{id:'connections',type:'line',source:'network',filter:['==',['get','feature_type'],'connection'],paint:{{'line-color':'#196f3d','line-width':6}}}});map.addLayer({{id:'gaps',type:'circle',source:'network',filter:['==',['get','feature_type'],'gap'],paint:{{'circle-color':'#c0392b','circle-radius':8}}}});map.addLayer({{id:'crossing-warnings',type:'circle',source:'network',filter:['==',['get','feature_type'],'crossing-warning'],paint:{{'circle-color':'#f39c12','circle-radius':7,'circle-stroke-color':'#17202a','circle-stroke-width':2}}}});map.addLayer({{id:'connections-highlight',type:'line',source:'network',filter:['==',['id'],''],paint:{{'line-color':'#f4d03f','line-width':11}}}});map.addSource('places',{{type:'geojson',data:places}});map.addLayer({{id:'places',type:'circle',source:'places',paint:{{'circle-radius':7,'circle-color':'#17202a','circle-stroke-color':'white','circle-stroke-width':2}}}});const b=new maplibregl.LngLatBounds();network.features.forEach(f=>extendBounds(b,f.geometry.coordinates));places.features.forEach(f=>extendBounds(b,f.geometry.coordinates));if(!b.isEmpty())map.fitBounds(b,{{padding:60}});map.on('mousemove','connections',e=>details(e.features[0].id));map.on('click','connections',e=>details(e.features[0].id));}});
document.querySelectorAll('.connection').forEach(x=>{{x.addEventListener('mouseenter',()=>details(x.dataset.featureId));x.addEventListener('focus',()=>details(x.dataset.featureId));x.addEventListener('click',()=>details(x.dataset.featureId));}});
</script></body></html>"""
    (review / "index.html").write_text(html, encoding="utf-8")
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
    (review / "README.txt").write_text(f"{DISCLAIMER}\n", encoding="utf-8")


def _zip_review_map(path: Path, review: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(review.iterdir()):
            archive.write(item, arcname=f"review-map/{item.name}")


def _write_pdf(path: Path, config: CouncilConfig, compiled: CompiledNetwork) -> None:
    width, height = landscape(A3)
    canvas = Canvas(str(path), pagesize=(width, height))
    canvas.setTitle(config.publication.title)
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawString(42, height - 42, config.publication.title)
    map_frames = [
        frame.to_crs(3857)
        for frame in (
            compiled.connections,
            compiled.urban_spines,
            compiled.low_traffic_areas,
            compiled.crossing_warnings,
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
    canvas.setFont("Helvetica", 10)
    text = DISCLAIMER
    if stringWidth(text, "Helvetica", 10) > width - 84:
        text = "Experimental SATN POC — not an adopted council plan."
    canvas.drawString(42, 32, text)
    canvas.save()


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


def _validate_artifacts(output: Path) -> None:
    required = (
        "network.gpkg",
        "network.geojson",
        "run.json",
        "agent-records.json",
        "review-map/index.html",
        "review-map.zip",
        "network-map.pdf",
    )
    missing = [name for name in required if not (output / name).exists()]
    if missing:
        raise ValueError(f"publication incomplete: {', '.join(missing)}")
    gpd.read_file(output / "network.gpkg", layer="connections")
    json.loads((output / "network.geojson").read_text(encoding="utf-8"))
    if not (output / "network-map.pdf").read_bytes().startswith(b"%PDF"):
        raise ValueError("invalid PDF output")
