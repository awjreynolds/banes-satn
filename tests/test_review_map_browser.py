from __future__ import annotations

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
        page.locator("#layer-network-routes").uncheck()
        assert not page.locator("#layer-network-routes").is_checked()
        assert page.locator("#layer-atm").count() == 0
        browser.close()
