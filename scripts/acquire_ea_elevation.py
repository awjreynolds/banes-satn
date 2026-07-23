"""Acquire council-generic EA LIDAR DTM samples along published SATN edges."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
from PIL import Image, ImageFile
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

ENDPOINT = (
    "https://environment.data.gov.uk/geoservices/datasets/"
    "13787b9a-26a4-4775-8523-806d13af58fc/wcs"
)
COVERAGE_ID = (
    "13787b9a-26a4-4775-8523-806d13af58fc"
    "__Lidar_Composite_Elevation_DTM_1m"
)
ELIGIBLE_FEATURE_TYPES = {
    "strategic-spine",
    "spine-access-connection",
    "school-access-connection",
    "branch-meeting-connection",
    "urban-spine",
}
SOURCE_ID = "ea-lidar-composite-dtm-1m"
LICENCE = "Open Government Licence v3.0"
ATTRIBUTION = "© Environment Agency copyright and/or database right 2022."


def route_sample_points(
    path: Path,
    spacing_m: float,
) -> tuple[list[Point], list[str]]:
    """Return de-duplicated metric points along eligible analytical edges."""

    routes = gpd.read_file(path)
    if routes.crs is None:
        raise ValueError("route GeoJSON must declare a CRS")
    routes = routes.to_crs(27700)
    selected = routes[
        routes.get("feature_type", "").isin(ELIGIBLE_FEATURE_TYPES)
        & routes.get("topography_profile_id").notna()
    ]
    points: dict[tuple[float, float], Point] = {}
    feature_ids: set[str] = set()
    for index, row in selected.iterrows():
        geometry = row.geometry
        if isinstance(geometry, MultiLineString):
            geometry = linemerge(geometry)
        lines = list(geometry.geoms) if isinstance(geometry, MultiLineString) else [geometry]
        for line in lines:
            if not isinstance(line, LineString) or line.is_empty:
                continue
            distance = 0.0
            while distance < line.length:
                point = line.interpolate(distance)
                points[(round(point.x, 3), round(point.y, 3))] = point
                distance += spacing_m
            endpoint = line.interpolate(line.length)
            points[(round(endpoint.x, 3), round(endpoint.y, 3))] = endpoint
        feature_ids.add(str(row.get("feature_id") or row.get("id") or index))
    return [points[key] for key in sorted(points)], sorted(feature_ids)


def tile_key(point: Point, tile_size_m: int) -> tuple[int, int]:
    return math.floor(point.x / tile_size_m), math.floor(point.y / tile_size_m)


def build_getcoverage_url(
    east_index: int,
    north_index: int,
    *,
    tile_size_m: int,
    spacing_m: float,
    endpoint: str = ENDPOINT,
) -> str:
    minimum_east = east_index * tile_size_m
    minimum_north = north_index * tile_size_m
    query = urllib.parse.urlencode(
        [
            ("service", "WCS"),
            ("version", "2.0.1"),
            ("request", "GetCoverage"),
            ("coverageId", COVERAGE_ID),
            ("format", "image/tiff"),
            ("subset", f"E({minimum_east},{minimum_east + tile_size_m})"),
            ("subset", f"N({minimum_north},{minimum_north + tile_size_m})"),
            ("scaleFactor", f"{1 / spacing_m:.8f}"),
        ]
    )
    return f"{endpoint}?{query}"


def acquire_tile(
    key: tuple[int, int],
    cache_dir: Path,
    *,
    tile_size_m: int,
    spacing_m: float,
    endpoint: str = ENDPOINT,
) -> tuple[tuple[int, int], Path, str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"ea-dtm-{key[0]}-{key[1]}-{spacing_m:g}m.tif"
    url = build_getcoverage_url(
        *key,
        tile_size_m=tile_size_m,
        spacing_m=spacing_m,
        endpoint=endpoint,
    )
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "banes-satn/1"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
        if not payload.startswith((b"II", b"MM")):
            raise ValueError(f"EA WCS did not return a GeoTIFF for tile {key}")
        path.write_bytes(payload)
    with Image.open(path) as image:
        image.verify()
    return key, path, url, hashlib.sha256(path.read_bytes()).hexdigest()


def load_tile(path: Path) -> tuple[np.ndarray, tuple[float, ...]]:
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(path) as image:
        transform = image.tag_v2.get(34264)
        if not transform or len(transform) != 16:
            raise ValueError(f"GeoTIFF is missing ModelTransformationTag: {path}")
        pixels = np.asarray(image, dtype=float).copy()
    return pixels, tuple(float(value) for value in transform)


def sample_grid(
    grid: tuple[np.ndarray, tuple[float, ...]],
    point: Point,
) -> float | None:
    pixels, transform = grid
    scale_x, scale_y = transform[0], transform[5]
    origin_x, origin_y = transform[3], transform[7]
    column = math.floor((point.x - origin_x) / scale_x)
    row = math.floor((point.y - origin_y) / scale_y)
    column = min(max(column, 0), pixels.shape[1] - 1)
    row = min(max(row, 0), pixels.shape[0] - 1)
    elevation = float(pixels[row, column])
    if not math.isfinite(elevation) or elevation <= -3e38:
        return None
    return elevation


def sample_tile(path: Path, point: Point) -> float | None:
    return sample_grid(load_tile(path), point)


def write_evidence(
    route_path: Path,
    output_path: Path,
    cache_dir: Path,
    *,
    spacing_m: float = 10.0,
    tile_size_m: int = 5000,
    workers: int = 4,
    endpoint: str = ENDPOINT,
) -> dict[str, object]:
    points, feature_ids = route_sample_points(route_path, spacing_m)
    keys = sorted({tile_key(point, tile_size_m) for point in points})
    with ThreadPoolExecutor(max_workers=workers) as executor:
        acquired = list(
            executor.map(
                lambda key: acquire_tile(
                    key,
                    cache_dir,
                    tile_size_m=tile_size_m,
                    spacing_m=spacing_m,
                    endpoint=endpoint,
                ),
                keys,
            )
        )
    tiles = {key: path for key, path, _url, _digest in acquired}
    grids = {key: load_tile(path) for key, path in tiles.items()}
    rows = []
    for point in points:
        elevation = sample_grid(grids[tile_key(point, tile_size_m)], point)
        if elevation is None:
            continue
        coordinate = f"{point.x:.3f}:{point.y:.3f}"
        rows.append(
            {
                "evidence_id": f"ea-dtm-{hashlib.sha256(coordinate.encode()).hexdigest()[:20]}",
                "elevation_m": round(elevation, 3),
                "source_resolution_m": 1.0,
                "output_sample_spacing_m": spacing_m,
                "geometry": point,
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    evidence = gpd.GeoDataFrame(rows, geometry="geometry", crs=27700).to_crs(4326)
    evidence.sort_values("evidence_id").to_file(output_path, driver="GeoJSON")
    manifest: dict[str, object] = {
        "source_id": SOURCE_ID,
        "coverage_id": COVERAGE_ID,
        "endpoint": endpoint,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "source_resolution_m": 1,
        "output_sample_spacing_m": spacing_m,
        "tile_size_m": tile_size_m,
        "eligible_feature_types": sorted(ELIGIBLE_FEATURE_TYPES),
        "route_feature_count": len(feature_ids),
        "requested_point_count": len(points),
        "evidence_sample_count": len(rows),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "requests": [
            {
                "tile": list(key),
                "url": url,
                "sha256": digest,
            }
            for key, _path, url, digest in sorted(acquired)
        ],
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("routes", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--spacing-m", type=float, default=10.0)
    parser.add_argument("--tile-size-m", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    manifest = write_evidence(
        args.routes,
        args.output,
        args.cache_dir,
        spacing_m=args.spacing_m,
        tile_size_m=args.tile_size_m,
        workers=args.workers,
    )
    print(
        f"Wrote {manifest['evidence_sample_count']} governed elevation samples "
        f"from {len(manifest['requests'])} EA WCS tiles."
    )


if __name__ == "__main__":
    main()
