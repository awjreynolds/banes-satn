from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from satn.models import CouncilConfig
from satn.sources import OSMData, derive_network_places, snapshot

PROJECT = Path(__file__).parents[1]


def base_config() -> CouncilConfig:
    return CouncilConfig.from_yaml(PROJECT / "config" / "banes.yaml")


def source_frames() -> OSMData:
    boundary_shape = Polygon(
        [(-2.6, 51.3), (-2.4, 51.3), (-2.4, 51.5), (-2.6, 51.5), (-2.6, 51.3)]
    )
    boundary = gpd.GeoDataFrame(
        [{"name": "Test Council", "geometry": boundary_shape}], crs=4326
    )
    large_village = Polygon(
        [(-2.54, 51.38), (-2.51, 51.38), (-2.51, 51.41), (-2.54, 51.41), (-2.54, 51.38)]
    )
    place_features = gpd.GeoDataFrame(
        [
            {"osmid": 1, "name": "Compact Town", "place": "town", "geometry": Point(-2.47, 51.44)},
            {"osmid": 2, "name": "Large Village", "place": "village", "geometry": large_village},
            {
                "osmid": 3,
                "name": "Named Quarter",
                "place": "neighbourhood",
                "geometry": Point(-2.48, 51.42),
            },
            {"osmid": 4, "name": "Tiny Hamlet", "place": "hamlet", "geometry": Point(-2.56, 51.34)},
            {"osmid": 5, "name": "Outside Town", "place": "town", "geometry": Point(-2.3, 51.4)},
        ],
        crs=4326,
    )
    stations = gpd.GeoDataFrame(
        [
            {
                "osmid": 6,
                "name": "Test Station",
                "railway": "station",
                "geometry": Point(-2.49, 51.43),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {"osmid": 10, "geometry": LineString([(-2.56, 51.395), (-2.49, 51.395)])},
            {"osmid": 11, "geometry": LineString([(-2.5, 51.4), (-2.3, 51.4)])},
        ],
        crs=4326,
    )
    return OSMData(boundary, place_features, stations, network)


def test_derives_places_and_excludes_hamlets() -> None:
    config = base_config()
    data = source_frames()

    places = derive_network_places(
        data.boundary, data.place_features, data.stations, data.network, config
    )

    by_kind = places.groupby("kind").size().to_dict()
    assert by_kind == {
        "community": 3,
        "community_portal": 2,
        "cross_boundary_gateway": 1,
        "station_access": 1,
    }
    assert "Tiny Hamlet" not in set(places["name"])
    compact = places[places["name"] == "Compact Town"]
    assert len(compact) == 1
    portals = places[places["kind"] == "community_portal"]
    assert portals["parent_place_id"].nunique() == 1
    assert set(places.loc[places["kind"] == "station_access", "place_class"]) == {"rail"}
    assert set(places.loc[places["kind"] == "cross_boundary_gateway", "name"]) == {
        "Towards Outside Town"
    }


class FakeOSMAdapter:
    def acquire(self, config: CouncilConfig) -> OSMData:
        return source_frames()


def test_osm_snapshot_is_attributable_and_reloadable(tmp_path: Path) -> None:
    config = base_config()
    config.source.snapshot_dir = tmp_path
    config.source.snapshot_id = "offline-osm"

    path = snapshot(config, osm_adapter=FakeOSMAdapter())

    manifest = json.loads((path / "snapshot.json").read_text())
    assert manifest["source_kind"] == "osm"
    assert "OpenStreetMap" in manifest["attribution"]
    assert set(manifest["files"]) >= {
        "boundary.geojson",
        "places.geojson",
        "network.geojson",
    }
    reloaded = gpd.read_file(path / "places.geojson")
    assert set(reloaded["kind"]) >= {"community", "station_access", "cross_boundary_gateway"}
    assert snapshot(config, osm_adapter=FakeOSMAdapter()) == path


@pytest.mark.live_osm
def test_live_banes_snapshot(tmp_path: Path) -> None:
    config = base_config()
    config.source.snapshot_dir = tmp_path
    config.source.snapshot_id = "banes-live-smoke"

    path = snapshot(config, replace=True)

    manifest = json.loads((path / "snapshot.json").read_text())
    assert manifest["council_id"] == "bath-and-north-east-somerset"
    places = gpd.read_file(path / "places.geojson")
    assert not places[places["kind"] == "community"].empty
