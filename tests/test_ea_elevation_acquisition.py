from __future__ import annotations

import importlib.util
import urllib.parse
from pathlib import Path

import geopandas as gpd
import pytest
from PIL import Image, TiffImagePlugin
from shapely.geometry import LineString, Point

SCRIPT = Path(__file__).parents[1] / "scripts" / "acquire_ea_elevation.py"
SPEC = importlib.util.spec_from_file_location("acquire_ea_elevation", SCRIPT)
assert SPEC and SPEC.loader
acquisition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquisition)


def test_route_sampling_is_generic_bounded_and_deduplicated(tmp_path: Path) -> None:
    routes = tmp_path / "routes.geojson"
    gpd.GeoDataFrame(
        [
            {
                "feature_type": "strategic-spine",
                "topography_profile_id": "profile-1",
                "geometry": LineString([(350000, 150000), (350025, 150000)]),
            },
            {
                "feature_type": "cross-spine-connector",
                "topography_profile_id": "aggregate",
                "geometry": LineString([(350000, 150000), (350100, 150000)]),
            },
        ],
        geometry="geometry",
        crs=27700,
    ).to_file(routes, driver="GeoJSON")

    points, feature_ids = acquisition.route_sample_points(routes, 10)

    assert [(point.x, point.y) for point in points] == [
        (350000, 150000),
        (350010, 150000),
        (350020, 150000),
        (350025, 150000),
    ]
    assert len(feature_ids) == 1


def test_getcoverage_url_uses_verified_axes_coverage_and_scaling() -> None:
    url = acquisition.build_getcoverage_url(
        70,
        30,
        tile_size_m=5000,
        spacing_m=10,
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert query["coverageId"] == [acquisition.COVERAGE_ID]
    assert query["subset"] == ["E(350000,355000)", "N(150000,155000)"]
    assert query["scaleFactor"] == ["0.10000000"]
    assert query["format"] == ["image/tiff"]


def test_float_geotiff_sampling_uses_embedded_model_transform(tmp_path: Path) -> None:
    path = tmp_path / "tile.tif"
    image = Image.new("F", (2, 2))
    image.putdata([10.0, 20.0, 30.0, 40.0])
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[34264] = (
        10.0,
        0.0,
        0.0,
        350000.0,
        0.0,
        -10.0,
        0.0,
        150020.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )
    image.save(path, tiffinfo=tags)

    assert acquisition.sample_tile(path, Point(350005, 150015)) == pytest.approx(10)
    assert acquisition.sample_tile(path, Point(350015, 150005)) == pytest.approx(40)
