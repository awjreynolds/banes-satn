from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from pypdf import PdfReader
from shapely.geometry import LineString

from satn import compile
from satn.constants import DISCLAIMER
from satn.models import CouncilConfig, OfficialRoadClassificationConfig
from satn.sources import snapshot

PROJECT = Path(__file__).parents[1]


def prepared_config(tmp_path: Path) -> CouncilConfig:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    snapshot(config)
    return config


def prepared_governed_urban_config(tmp_path: Path) -> CouncilConfig:
    fixture = tmp_path / "governed-urban-fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    places_path = fixture / "source" / "places.geojson"
    places = gpd.read_file(places_path)
    places["place_class"] = "town"
    places.to_file(places_path, driver="GeoJSON")
    context_path = fixture / "source" / "context.geojson"
    context = gpd.read_file(context_path)
    context.loc[context["feature_type"] == "ncn-route", "network_scope"] = "urban"
    context.to_file(context_path, driver="GeoJSON")
    classification_path = fixture / "source" / "official-roads.geojson"
    gpd.GeoDataFrame(
        [
            {
                "road_id": f"official-{classification}",
                "classification": classification,
                "geometry": LineString([(longitude, 51.395), (longitude, 51.43)]),
            }
            for classification, longitude in (
                ("A road", -2.49),
                ("B road", -2.48),
                ("Classified Unnumbered", -2.47),
                ("Unclassified", -2.475),
                ("", -2.465),
            )
        ],
        crs=4326,
    ).to_file(classification_path, driver="GeoJSON")
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    config.source.official_road_classification = OfficialRoadClassificationConfig(
        path=classification_path,
        source_id="tiny-council-highways",
        effective_date="2026-04-01",
        licence="Open Government Licence v3.0",
    )
    snapshot(config)
    return config


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundle_identifiers_zip_and_pdf_are_consistent(tmp_path: Path) -> None:
    result = compile(prepared_config(tmp_path))
    connections = gpd.read_file(result.artifacts["geopackage"], layer="connections")
    network = json.loads(result.artifacts["geojson"].read_text())
    run = json.loads(result.artifacts["run"].read_text())
    agents = json.loads(result.artifacts["agents"].read_text())
    geojson_ids = {
        feature["id"]
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "connection"
    }
    gated_access_ids = {
        feature["id"]
        for feature in network["features"]
        if feature["properties"]["feature_type"]
        in {"spine-access-connection", "school-access-connection"}
    }

    assert geojson_ids == set(connections["connection_id"])
    assert geojson_ids | gated_access_ids == {
        record["connection_id"] for record in agents["records"]
    }
    assert run["connection_count"] == len(geojson_ids)
    assert run["criteria"] == {
        section: {criterion: status for criterion, status in values.items()}
        for section, values in result.criteria.items()
    }

    review = result.artifacts["review_map"].parent
    expected = {
        f"review-map/{item.relative_to(review)}"
        for item in review.rglob("*")
        if item.is_file()
    }
    with zipfile.ZipFile(result.artifacts["review_zip"]) as archive:
        assert set(archive.namelist()) == expected

    pdf = PdfReader(result.artifacts["pdf"])
    width = float(pdf.pages[0].mediabox.width)
    height = float(pdf.pages[0].mediabox.height)
    assert width > height
    assert width == pytest.approx(1190.55, abs=1)
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert all(value in text for value in (DISCLAIMER, "Legend", "scale", "Compiled"))


def test_failed_publication_preserves_the_previous_complete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = prepared_config(tmp_path)
    first = compile(config)
    before = {name: checksum(path) for name, path in first.artifacts.items() if path.is_file()}

    def fail_pdf(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated print failure")

    monkeypatch.setattr("satn.publisher._write_pdf", fail_pdf)
    with pytest.raises(RuntimeError, match="simulated print failure"):
        compile(config)

    after = {name: checksum(path) for name, path in first.artifacts.items() if path.is_file()}
    assert after == before


def test_governed_urban_spines_and_ncn_evidence_publish_distinctly(tmp_path: Path) -> None:
    result = compile(prepared_governed_urban_config(tmp_path))
    network = json.loads(result.artifacts["geojson"].read_text())
    run = json.loads(result.artifacts["run"].read_text())
    urban_spines = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "urban-spine"
    ]
    ncn_evidence = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "ncn-route"
    ]
    classification_unknowns = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"]
        == "urban-classification-unknown"
    ]

    assert network["urban_classification_status"] == "explicit-unknown"
    assert run["urban_classification_status"] == "explicit-unknown"
    assert run["layer_counts"]["urban_spines"] == 3
    assert run["layer_counts"]["urban_classification_unknowns"] == 1
    assert {feature["properties"]["official_classification"] for feature in urban_spines} == {
        "a-road",
        "b-road",
        "classified-unnumbered",
    }
    assert len({feature["id"] for feature in urban_spines}) == 3
    assert all(feature["id"].startswith("urban-spine-") for feature in urban_spines)
    assert all(
        feature["properties"]["source_id"] == "tiny-council-highways"
        and feature["properties"]["effective_date"] == "2026-04-01"
        and len(feature["properties"]["content_fingerprint"]) == 64
        for feature in urban_spines
    )
    assert len(classification_unknowns) == 1
    assert classification_unknowns[0]["properties"]["classification_status"] == (
        "explicit-unknown"
    )
    assert len(ncn_evidence) == 1
    assert ncn_evidence[0]["id"] == "ncn-fixture"
    assert ncn_evidence[0]["properties"]["network_scope"] == "urban"
    published_layers = set(gpd.list_layers(result.artifacts["geopackage"])["name"])
    assert {"urban_spines", "urban_classification_unknowns"} <= published_layers
    review_html = result.artifacts["review_map"].read_text()
    review_js = (result.artifacts["review_map"].parent / "assets/review-map.js").read_text()
    assert "Urban Main-Road Spines" in review_html
    assert "not automatically a Circulation Boundary" in review_html
    assert '"network_scope"], "urban"' in review_js
