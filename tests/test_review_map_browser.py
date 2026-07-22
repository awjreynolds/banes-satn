from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from satn import compile
from satn.models import CouncilConfig
from satn.sources import snapshot

PROJECT = Path(__file__).parents[1]


@pytest.mark.browser
def test_mobile_map_has_a_visible_compact_legend(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    snapshot(config)
    result = compile(config)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.goto(result.artifacts["review_map"].as_uri())
        page.wait_for_function("document.documentElement.dataset.mapReady === 'true'")
        page.locator("#map").scroll_into_view_if_needed()

        legend = page.get_by_role("region", name="Map legend")
        assert legend.is_visible()
        legend_text = legend.inner_text()
        assert all(
            label in legend_text
            for label in (
                "A-road spine",
                "NCN spine",
                "Access connection",
                "Cross-spine connector",
                "Branch meeting",
                "Urban through-road",
                "Candidate low-traffic area",
                "Served community",
                "Place reference",
                "Network gap",
                "Crossing warning",
            )
        )
        map_box = page.locator("#map").bounding_box()
        legend_box = legend.bounding_box()
        assert map_box is not None
        assert legend_box is not None
        assert legend_box["x"] >= map_box["x"]
        assert legend_box["y"] >= map_box["y"]
        assert legend_box["x"] + legend_box["width"] <= map_box["x"] + map_box["width"]
        assert legend_box["width"] <= 300
        browser.close()


@pytest.mark.browser
def test_accessible_hover_pin_layers_and_criteria(tmp_path: Path) -> None:
    fixture = tmp_path / "fixture"
    shutil.copytree(
        PROJECT / "examples" / "fixture",
        fixture,
        ignore=shutil.ignore_patterns("work", ".satn-cache"),
    )
    config = CouncilConfig.from_yaml(fixture / "council.yaml")
    snapshot(config)
    result = compile(config)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.goto(result.artifacts["review_map"].as_uri())
        page.wait_for_function("document.documentElement.dataset.mapReady === 'true'")
        layer_ids = page.evaluate(
            "window.SATN_REVIEW_MAP.getStyle().layers.map((layer) => layer.id)"
        )
        assert layer_ids.index("places") < layer_ids.index("access-obligations")
        assert "low-traffic-area-outlines" in layer_ids
        assert (
            page.evaluate(
                "window.SATN_REVIEW_MAP.getPaintProperty('low-traffic-areas', 'fill-opacity')"
            )
            >= 0.4
        )
        card = page.locator('[data-feature-id^="spine-access-"]').first
        assert card.get_attribute("data-feature-id").startswith("spine-access-")
        card.hover()
        assert "Route role" in page.locator("#feature-details").inner_text()
        assert "Source identifiers" in page.locator("#feature-details").inner_text()
        assert "Topography comparison" in page.locator("#feature-details").inner_text()
        assert "Topography comparison rationale" in page.locator("#feature-details").inner_text()
        assert "Community road association" in page.locator("#feature-details").inner_text()
        card.click()
        assert card.get_attribute("aria-pressed") == "true"
        page.locator("h1").hover()
        assert "Route role" in page.locator("#feature-details").inner_text()
        card.click()
        assert card.get_attribute("aria-pressed") == "false"

        access_card = page.locator('[data-feature-id^="spine-access-"]').first
        access_card.press("Enter")
        assert access_card.get_attribute("aria-pressed") == "true"
        access_card.press("Enter")
        assert access_card.get_attribute("aria-pressed") == "false"

        spine_card = page.locator('[data-feature-type="strategic-spine"]').first
        spine_card.focus()
        assert "Network role" in page.locator("#feature-details").inner_text()
        place_card = page.locator('[data-feature-type="place"]').first
        place_card.focus()
        place_details = page.locator("#feature-details").inner_text()
        assert "Stable ID" in place_details
        assert "Place role" in place_details
        obligation_card = page.locator('[data-feature-type="access-obligation"]').first
        assert obligation_card.count() == 1
        obligation_card.click()
        obligation_details = page.locator("#feature-details").inner_text()
        assert "Service status" in obligation_details
        assert "Service rationale" in obligation_details
        assert "Network scope" in obligation_details
        assert "Continuity criterion" in obligation_details
        assert "Geometry meaning" in obligation_details
        assert page.locator('[data-feature-type="a-road-spine"]').count() > 0
        assert page.locator('[data-feature-type="ncn-route"]').count() > 0
        assert page.locator('[data-feature-type="school"]').count() > 0
        assert page.locator('[data-feature-type="retail-centre"]').count() > 0
        assert page.locator('[data-feature-type="healthcare"]').count() > 0

        page.locator("#criteria-network").check()
        assert page.locator("#criteria-heading").inner_text() == "network criteria"
        assert "authoritative model" in page.locator("#criteria-list").inner_text()
        for checkbox in page.locator('input[type="checkbox"]').all():
            described_by = checkbox.get_attribute("aria-describedby")
            assert described_by
            assert page.locator(f"#{described_by}").count() == 1
        assert not page.locator("#layer-schools").is_checked()
        school_legend = page.locator("#legend-schools")
        assert school_legend.is_hidden()
        access_legend = page.locator("#legend-spine-access-connections")
        assert access_legend.is_visible()
        assert "Green point" in access_legend.inner_text()
        assert "Amber point" in access_legend.inner_text()
        assert "Red point" in access_legend.inner_text()
        connector_legend = page.locator("#legend-cross-spine-connectors")
        assert connector_legend.is_visible()
        page.locator("#layer-spine-access-connections").uncheck()
        assert access_legend.is_hidden()
        page.locator("#layer-cross-spine-connectors").uncheck()
        assert connector_legend.is_hidden()
        ncn_legend = page.locator("#legend-ncn-routes")
        assert page.locator("#layer-ncn-routes").is_checked()
        assert ncn_legend.is_visible()
        assert "across rural and urban areas" in ncn_legend.inner_text()
        assert "connector LINK evidence" in ncn_legend.inner_text()
        assert "not automatically a Circulation Boundary" in ncn_legend.inner_text()
        repository_link = page.get_by_role("link", name="View source, methodology and issues")
        assert repository_link.is_visible()
        assert repository_link.get_attribute("href") == (
            "https://github.com/awjreynolds/banes-satn"
        )
        urban_legend = page.locator("#legend-urban-spines")
        assert urban_legend.is_visible()
        assert "Classified Unnumbered" in urban_legend.inner_text()
        classification_unknowns = page.locator("#layer-urban-classification-unknowns")
        assert not classification_unknowns.is_checked()
        assert page.locator("#legend-urban-classification-unknowns").is_hidden()
        classification_unknowns.check()
        assert page.locator("#legend-urban-classification-unknowns").is_visible()
        page.locator("#layer-urban-spines").uncheck()
        assert urban_legend.is_hidden()
        area_legend = page.locator("#legend-low-traffic-areas")
        assert area_legend.is_visible()
        assert "not an existing LTN" in area_legend.inner_text()
        assert "no preferred residential cycling centreline" in area_legend.inner_text()
        portals = page.locator("#layer-low-traffic-area-portals")
        assert not portals.is_checked()
        assert page.locator("#legend-low-traffic-area-portals").is_hidden()
        portals.check()
        assert page.locator("#legend-low-traffic-area-portals").is_visible()
        page.locator("#layer-low-traffic-areas").uncheck()
        assert area_legend.is_hidden()
        page.locator("#layer-schools").check()
        assert page.locator("#layer-schools").is_checked()
        assert school_legend.is_visible()
        assert "Inferred access point" in school_legend.inner_text()
        assert "education sites" in page.locator("#layer-summary").inner_text()
        school_card = page.locator('[data-feature-id^="school-access-obligation-"]')
        school_card.click()
        school_details = page.locator("#feature-details")
        assert "School access point" in school_details.inner_text()
        assert "mapped" in school_details.inner_text()
        assert "Mapped usable entrance" in school_details.inner_text()
        assert "Continuity criterion" in school_details.inner_text()
        assert "Candidate area" in school_details.inner_text()
        assert "Main-road portal" in school_details.inner_text()
        assert "Geometry meaning" in school_details.inner_text()
        school_street_legend = page.locator("#legend-school-streets")
        assert school_street_legend.is_hidden()
        page.locator("#layer-school-streets").check()
        assert school_street_legend.is_visible()
        assert "Green — Promising" in school_street_legend.inner_text()
        assert "Amber — Needs Investigation" in school_street_legend.inner_text()
        assert "Red — Unlikely" in school_street_legend.inner_text()
        assert "Grey — Not Evaluated" in school_street_legend.inner_text()
        school_street_card = page.locator('[data-feature-id^="school-street-assessment-"]')
        school_street_card.click()
        assessment_details = page.locator("#feature-details")
        assert "Assessment" in assessment_details.inner_text()
        assert "Bus access" in assessment_details.inner_text()
        assert "Displacement risk" in assessment_details.inner_text()
        assert "not scheme feasibility or calibrated probability" in (
            assessment_details.inner_text()
        )
        school_connection = page.locator(
            '[data-feature-id^="spine-access-"]', has_text="Fixture School"
        )
        school_connection.click()
        assert "Fixture School" in page.locator("#details-heading").inner_text()
        gradient_legend = page.locator("#legend-gradient-sections")
        assert gradient_legend.is_hidden()
        page.locator("#layer-gradient-sections").check()
        assert gradient_legend.is_visible()
        gradient_legend_text = gradient_legend.inner_text()
        assert all(
            label in gradient_legend_text
            for label in ("Gentle", "Noticeable", "Steep", "Very Steep", "Severe")
        )
        assert "not Criterion Status or route rejection" in gradient_legend_text
        topography_card = page.locator(
            '[data-feature-id^="topography-profile-"]',
            has_text="evidence-unavailable",
        ).first
        topography_card.press("Enter")
        topography_details = page.locator("#feature-details").inner_text()
        assert "Topography Profile" in topography_details
        assert "Elevation Evidence" in topography_details
        assert "evidence-unavailable" in topography_details
        gradient_card = page.locator('[data-feature-id^="gradient-section-"]').first
        gradient_card.press("Enter")
        gradient_details = page.locator("#feature-details").inner_text()
        assert "Gradient band" in gradient_details
        assert "Uphill direction" in gradient_details
        assert "Sustained-window rationale" in gradient_details
        assert "Generated edge" in gradient_details
        page.locator("#criteria-topography").check()
        assert page.locator("#criteria-heading").inner_text() == "topography criteria"
        assert "elevation evidence coverage" in page.locator("#criteria-list").inner_text()
        atm_control = page.locator("#layer-atm")
        assert atm_control.is_disabled()
        local_atm = tmp_path / "local-atm.geojson"
        local_atm.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "Local ATM reference"},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[-2.5, 51.4], [-2.46, 51.42]],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        page.locator("#atm-upload").set_input_files(local_atm)
        page.wait_for_function("!document.querySelector('#layer-atm').disabled")
        assert atm_control.is_enabled()
        assert atm_control.is_checked()
        assert "1 local ATM features loaded" in page.locator("#atm-status").inner_text()
        local_atm_card = page.locator('[data-feature-type="atm-reference"]').first
        local_atm_card.focus()
        assert "Stable ID" in page.locator("#feature-details").inner_text()
        browser.close()
