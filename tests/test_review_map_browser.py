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
        card = page.locator("#connection-list .connection").first
        assert card.get_attribute("data-feature-id").startswith("connection-")
        card.hover()
        assert "Route role" in page.locator("#feature-details").inner_text()
        assert "Source identifiers" in page.locator("#feature-details").inner_text()
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

        page.locator("#criteria-network").check()
        assert page.locator("#criteria-heading").inner_text() == "network criteria"
        assert "connected graph" in page.locator("#criteria-list").inner_text()
        page.locator("#layer-community-connections").uncheck()
        assert not page.locator("#layer-community-connections").is_checked()
        assert not page.locator("#layer-schools").is_checked()
        school_legend = page.locator("#legend-schools")
        assert school_legend.is_hidden()
        access_legend = page.locator("#legend-spine-access-connections")
        assert access_legend.is_visible()
        connector_legend = page.locator("#legend-cross-spine-connectors")
        assert connector_legend.is_visible()
        page.locator("#layer-spine-access-connections").uncheck()
        assert access_legend.is_hidden()
        page.locator("#layer-cross-spine-connectors").uncheck()
        assert connector_legend.is_hidden()
        ncn_legend = page.locator("#legend-ncn-routes")
        page.locator("#layer-ncn-routes").check()
        assert ncn_legend.is_visible()
        assert "not automatically a Circulation Boundary" in ncn_legend.inner_text()
        urban_legend = page.locator("#legend-urban-spines")
        assert urban_legend.is_visible()
        assert "Classified Unnumbered" in urban_legend.inner_text()
        page.locator("#layer-urban-spines").uncheck()
        assert urban_legend.is_hidden()
        area_legend = page.locator("#legend-low-traffic-areas")
        assert area_legend.is_visible()
        assert "not an existing LTN" in area_legend.inner_text()
        assert "no preferred residential cycling centreline" in area_legend.inner_text()
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
        school_connection = page.locator(
            '[data-feature-id^="spine-access-"]', has_text="Fixture School"
        )
        school_connection.click()
        assert "Fixture School" in page.locator("#details-heading").inner_text()
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
        browser.close()
