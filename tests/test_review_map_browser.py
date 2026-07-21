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
    shutil.copytree(PROJECT / "examples" / "fixture", fixture)
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

        page.locator("#criteria-network").check()
        assert page.locator("#criteria-heading").inner_text() == "network criteria"
        assert "connected graph" in page.locator("#criteria-list").inner_text()
        page.locator("#layer-community-connections").uncheck()
        assert not page.locator("#layer-community-connections").is_checked()
        assert not page.locator("#layer-schools").is_checked()
        page.locator("#layer-schools").check()
        assert page.locator("#layer-schools").is_checked()
        assert "education sites" in page.locator("#layer-summary").inner_text()
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
