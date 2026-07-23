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
        assert legend.get_attribute("open") is None
        page.get_by_text("Map legend", exact=True).click()
        assert legend.get_attribute("open") is not None
        legend_text = legend.inner_text()
        assert all(
            label in legend_text
            for label in (
                "A-road spine",
                "NCN spine",
                "Access connection",
                "Cross-spine connector",
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
def test_gradient_inspection_path_popovers_and_linear_evidence(tmp_path: Path) -> None:
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
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
        page.route("https://tiles.mapterhorn.com/**", lambda route: route.abort())
        page.goto(result.artifacts["review_map"].as_uri())
        page.wait_for_function("document.documentElement.dataset.mapReady === 'true'")

        assert page.locator("#layer-rail").is_visible()
        assert page.locator("#linear-evidence-panel").is_visible()
        assert page.locator("#terrain-mode").is_visible()
        assert not page.locator("#terrain-mode").is_checked()
        assert "analytical default" in page.locator("#terrain-status").inner_text()
        assert page.locator("#criteria-controls").count() == 0
        assert page.locator("#criteria-panel").count() == 0

        information = page.get_by_role("button", name="About Strategic Spines")
        information.click()
        popover = page.locator("#legend-strategic-spines")
        assert popover.is_visible()
        assert information.get_attribute("aria-expanded") == "true"

        page.locator("#feature-index summary").click()
        card = page.locator('[data-feature-type="strategic-spine"]').first
        card.click()
        assert card.get_attribute("aria-pressed") == "true"
        assert page.locator("#gradient-path-start").is_enabled()
        page.locator("#gradient-path-start").click()

        assert "1 edge selected" in page.locator("#gradient-path-status").inner_text()
        assert "shared distance axis" in page.locator("#route-summary").inner_text()
        assert page.locator(".evidence-track").count() == 2
        assert page.locator(".track-label", has_text="Gradient").count() == 1
        assert page.locator(".track-label", has_text="Road type").count() == 1
        assert page.locator(".track-cell.unavailable").count() >= 1

        page.locator("#gradient-path-reverse").click()
        assert "1 edge selected" in page.locator("#gradient-path-status").inner_text()
        page.locator("#gradient-path-remove").click()
        assert "No path selected" in page.locator("#gradient-path-status").inner_text()

        browser.close()
