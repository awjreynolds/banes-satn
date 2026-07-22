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
from satn.models import (
    CouncilConfig,
    ObservedThroughTrafficConfig,
    OfficialRoadClassificationConfig,
)
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
    context.loc[
        context["feature_type"].isin(["ncn-route", "school"]),
        "network_scope",
    ] = "urban"
    context.to_file(context_path, driver="GeoJSON")
    classification_path = fixture / "source" / "official-roads.geojson"
    gpd.GeoDataFrame(
        [
            {
                "road_id": f"official-{classification}",
                "classification": classification,
                "geometry": LineString([(longitude, 51.4), (longitude, 51.412)]),
            }
            for classification, longitude in (
                ("A road", -2.49),
                ("B road", -2.48),
                ("Classified Unnumbered", -2.47),
                ("Unclassified", -2.475),
                ("", -2.465),
            )
        ]
        + [
            {
                "road_id": f"official-a-boundary-{position}",
                "classification": "A road",
                "geometry": LineString([(-2.49, latitude), (-2.48, latitude)]),
            }
            for position, latitude in (("south", 51.4), ("north", 51.412))
        ],
        crs=4326,
    ).to_file(classification_path, driver="GeoJSON")
    observed_traffic_path = fixture / "source" / "observed-through-traffic.geojson"
    gpd.GeoDataFrame(
        [
            {
                "id": "traffic-study-1",
                "geometry": LineString([(-2.491, 51.406), (-2.481, 51.412)]),
            }
        ],
        crs=4326,
    ).to_file(observed_traffic_path, driver="GeoJSON")
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    config.source.official_road_classification = OfficialRoadClassificationConfig(
        path=classification_path,
        source_id="tiny-council-highways",
        effective_date="2026-04-01",
        licence="Open Government Licence v3.0",
    )
    config.source.observed_through_traffic = ObservedThroughTrafficConfig(
        path=observed_traffic_path,
        source_id="tiny-council-traffic-study",
        effective_date="2026-03-01",
        licence="Open Government Licence v3.0",
    )
    snapshot(config)
    return config


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bundle_identifiers_zip_and_pdf_are_consistent(tmp_path: Path) -> None:
    result = compile(prepared_config(tmp_path))
    connections = gpd.read_file(result.artifacts["geopackage"], layer="spine_access_connections")
    network = json.loads(result.artifacts["geojson"].read_text())
    run = json.loads(result.artifacts["run"].read_text())
    agents = json.loads(result.artifacts["agents"].read_text())
    assert "connections" not in set(gpd.list_layers(result.artifacts["geopackage"])["name"])
    gated_access_ids = {
        feature["id"]
        for feature in network["features"]
        if feature["properties"]["feature_type"]
        in {"spine-access-connection", "school-access-connection"}
    }
    meeting_ids = {
        feature["id"]
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "branch-meeting-connection"
    }

    assert gated_access_ids == set(connections["access_connection_id"])
    assert gated_access_ids | meeting_ids == {
        record["connection_id"] for record in agents["records"]
    }
    assert run["connection_count"] == len(gated_access_ids | meeting_ids)
    assert run["network_model"] == "backbone-outward"
    profiles = gpd.read_file(result.artifacts["geopackage"], layer="topography_profiles")
    profile_features = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "topography-profile"
    ]
    assert {feature["id"] for feature in profile_features} == set(profiles["profile_id"])
    assert set(profiles["evidence_status"]) == {"available", "evidence-unavailable"}
    unavailable_count = int((profiles["evidence_status"] == "evidence-unavailable").sum())
    assert run["topography"] == {
        "profile_count": len(profiles),
        "gradient_section_count": run["layer_counts"]["gradient_sections"],
        "evidence_unavailable_count": unavailable_count,
        "corroboration_count": 0,
        "alternative_trigger_count": int(connections["topography_alternative_trigger"].sum()),
        "easier_alternative_selected_count": int(
            (connections["topography_comparison_status"] == "easier-alternative-selected").sum()
        ),
        "original_retained_count": int(
            connections["topography_comparison_status"]
            .isin(
                [
                    "original-retained-no-easier-option",
                    "strategic-spine-retained",
                ]
            )
            .sum()
        ),
    }
    assert run["criteria"] == {
        section: {criterion: status for criterion, status in values.items()}
        for section, values in result.criteria.items()
    }

    review = result.artifacts["review_map"].parent
    assert (review / "backbone-comparison.json").read_bytes() == result.artifacts[
        "backbone_comparison"
    ].read_bytes()
    review_script = (review / "assets" / "review-map.js").read_text(encoding="utf-8")
    assert '"school-access-topography-warnings"' in review_script
    assert '["connections", "topography-retained-warnings"' not in review_script
    expected = {
        f"review-map/{item.relative_to(review)}" for item in review.rglob("*") if item.is_file()
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
        if feature["properties"]["feature_type"] == "urban-classification-unknown"
    ]
    candidate_areas = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "low-traffic-area"
    ]
    area_portals = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "low-traffic-area-portal"
    ]
    school_obligations = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "school-access-obligation"
    ]
    school_connections = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "school-access-connection"
    ]
    school_street_assessments = [
        feature
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "school-street-assessment"
    ]

    assert network["urban_classification_status"] == "explicit-unknown"
    assert run["urban_classification_status"] == "explicit-unknown"
    assert run["layer_counts"]["urban_spines"] == 5
    assert run["layer_counts"]["urban_classification_unknowns"] == 1
    assert {feature["properties"]["official_classification"] for feature in urban_spines} == {
        "a-road",
        "b-road",
        "classified-unnumbered",
    }
    assert len({feature["id"] for feature in urban_spines}) == 5
    assert all(feature["id"].startswith("urban-spine-") for feature in urban_spines)
    assert all(
        feature["properties"]["source_id"] == "tiny-council-highways"
        and feature["properties"]["effective_date"] == "2026-04-01"
        and len(feature["properties"]["content_fingerprint"]) == 64
        for feature in urban_spines
    )
    assert len(classification_unknowns) == 1
    assert classification_unknowns[0]["properties"]["classification_status"] == ("explicit-unknown")
    assert len(candidate_areas) == 1
    assert candidate_areas[0]["properties"]["status"] == "candidate"
    assert candidate_areas[0]["properties"]["intervention_need"] == ("observed-through-traffic")
    assert json.loads(
        candidate_areas[0]["properties"]["observed_through_traffic_evidence_ids"]
    ) == ["traffic-study-1"]
    assert json.loads(candidate_areas[0]["properties"]["observed_through_traffic_source_ids"]) == [
        "tiny-council-traffic-study"
    ]
    assert candidate_areas[0]["properties"]["permeability_representation"] == (
        "area-no-internal-centreline"
    )
    assert len(area_portals) == candidate_areas[0]["properties"]["portal_count"]
    assert all(
        portal["id"] == portal["properties"]["portal_id"]
        and portal["id"].startswith("low-traffic-area-portal-")
        for portal in area_portals
    )
    assert {portal["properties"]["area_id"] for portal in area_portals} == {
        candidate_areas[0]["id"]
    }
    assert len(school_obligations) == 1
    urban_school = school_obligations[0]
    assert urban_school["geometry"]["type"] == "Point"
    assert urban_school["properties"]["network_role"] == ("urban-school-access-obligation")
    assert urban_school["properties"]["service_status"] == "served"
    assert urban_school["properties"]["low_traffic_area_id"] == candidate_areas[0]["id"]
    assert urban_school["properties"]["portal_id"] in {portal["id"] for portal in area_portals}
    assert urban_school["properties"]["geometry_semantics"] == (
        "area-permeability-no-internal-centreline"
    )
    assert json.loads(urban_school["properties"]["fabric_source_ids"])
    assert not school_connections
    assert len(school_street_assessments) == 1
    school_street = school_street_assessments[0]
    assert school_street["id"].startswith("school-street-assessment-")
    assert school_street["properties"]["assessment_status"] == "red"
    assert school_street["properties"]["assessment_label"] == "Unlikely"
    assert (
        "not scheme feasibility or calibrated probability"
        in school_street["properties"]["qualification"]
    )
    assert all(
        "school-fixture"
        not in {
            str(feature["properties"].get("from_place")),
            str(feature["properties"].get("to_place")),
        }
        for feature in network["features"]
        if feature["properties"]["feature_type"] == "connection"
    )
    assert len(ncn_evidence) == 1
    assert ncn_evidence[0]["id"] == "ncn-fixture"
    assert ncn_evidence[0]["properties"]["network_scope"] == "urban"
    published_layers = set(gpd.list_layers(result.artifacts["geopackage"])["name"])
    assert {
        "urban_spines",
        "urban_classification_unknowns",
        "candidate_low_traffic_areas",
        "low_traffic_area_portals",
        "school_street_assessments",
    } <= published_layers
    published_portals = gpd.read_file(
        result.artifacts["geopackage"], layer="low_traffic_area_portals"
    )
    assert {portal["id"] for portal in area_portals} == set(published_portals["portal_id"])
    published_obligations = gpd.read_file(
        result.artifacts["geopackage"], layer="access_obligations"
    )
    published_urban_school = published_obligations[
        published_obligations["network_role"] == "urban-school-access-obligation"
    ].iloc[0]
    assert published_urban_school["low_traffic_area_id"] == candidate_areas[0]["id"]
    assert published_urban_school["portal_id"] == urban_school["properties"]["portal_id"]
    assert published_urban_school["geometry_semantics"] == (
        "area-permeability-no-internal-centreline"
    )
    published_school_streets = gpd.read_file(
        result.artifacts["geopackage"], layer="school_street_assessments"
    )
    assert list(published_school_streets["assessment_id"]) == [school_street["id"]]
    assert list(published_school_streets["rationale"]) == [school_street["properties"]["rationale"]]
    review_html = result.artifacts["review_map"].read_text()
    review_js = (result.artifacts["review_map"].parent / "assets/review-map.js").read_text()
    assert "Urban Main-Road Spines" in review_html
    assert "not automatically a Circulation Boundary" in review_html
    assert "not an existing LTN" in review_html
    assert "no preferred residential cycling centreline" in review_html
    assert "School Street Candidate Assessments" in review_html
    assert "Green — Promising" in review_html
    assert "Grey — Not Evaluated" in review_html
    assert '"network_scope"], "urban"' in review_js
    assert '"low-traffic-area-portal"].includes' in review_js
