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
                "Strategic network route",
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

        information = page.get_by_role("button", name="About the strategic network")
        information.click()
        popover = page.locator("#legend-strategic-network")
        assert popover.is_visible()
        assert information.get_attribute("aria-expanded") == "true"
        assert page.evaluate("() => window.SATN_REVIEW_MAP.getStyle().layers.at(-1).id") == (
            "strategic-network"
        )

        page.locator("#feature-index summary").click()
        path_candidates = page.evaluate(
            """() => {
              const eligible = new Set([
                "strategic-spine", "spine-access-connection",
                "school-access-connection", "branch-meeting-connection", "urban-spine"
              ]);
              const features = window.SATN_DATA.network.features.filter((feature) =>
                eligible.has(feature.properties.feature_type) &&
                feature.properties.topography_profile_id &&
                feature.geometry?.type === "LineString"
              );
              const key = (coordinate) =>
                `${Number(coordinate[0]).toFixed(5)},${Number(coordinate[1]).toFixed(5)}`;
              for (const first of features) {
                const firstEnd = first.geometry.coordinates.at(-1);
                const second = features.find((candidate) => {
                  if (candidate.id === first.id) return false;
                  const coordinates = candidate.geometry.coordinates;
                  return [coordinates[0], coordinates.at(-1)].some(
                    (endpoint) => key(endpoint) === key(firstEnd)
                  );
                });
                if (!second) continue;
                const secondCoordinates = second.geometry.coordinates;
                const secondFarEnd = key(secondCoordinates[0]) === key(firstEnd)
                  ? secondCoordinates.at(-1) : secondCoordinates[0];
                const disconnected = features.find((candidate) => {
                  if ([first.id, second.id].includes(candidate.id)) return false;
                  const coordinates = candidate.geometry.coordinates;
                  return [coordinates[0], coordinates.at(-1)].every(
                    (endpoint) => key(endpoint) !== key(secondFarEnd)
                  );
                });
                if (disconnected) return [first.id, second.id, disconnected.id];
              }
              return null;
            }"""
        )
        assert path_candidates is not None
        first_id, second_id, disconnected_id = path_candidates
        card = page.locator(f'[data-feature-id="{first_id}"]')
        card.click()
        assert card.get_attribute("aria-pressed") == "true"
        assert page.locator("#gradient-path-start").is_enabled()
        page.locator("#gradient-path-start").click()
        page.locator(f'[data-feature-id="{second_id}"]').click()
        page.locator("#gradient-path-append").click()

        assert "2 edges selected" in page.locator("#gradient-path-status").inner_text()
        page.locator(f'[data-feature-id="{disconnected_id}"]').click()
        page.locator("#gradient-path-append").click()
        assert "does not share its junction" in page.locator("#gradient-path-status").inner_text()
        assert page.locator(".track-cell.boundary").count() == 2
        assert "shared distance axis" in page.locator("#route-summary").inner_text()
        assert page.locator(".evidence-track").count() == 4
        assert page.locator(".track-label", has_text="Path order").count() == 1
        assert page.locator(".track-label", has_text="Gradient").count() == 2
        assert page.locator(".track-label", has_text="Gradient · 50 m").count() == 1
        assert page.locator(".track-label", has_text="Gradient · 20 m").count() == 1
        assert page.locator(".track-label", has_text="Road type").count() == 1
        assert page.locator(".track-cell.unavailable").count() >= 1
        assert "steepest sustained" in page.locator("#route-summary").inner_text()
        synchronized_cell = page.locator(
            '.track-cell[data-gradient-section-ids]:not([data-gradient-section-ids=""])'
        ).first
        section_id = synchronized_cell.get_attribute("data-gradient-section-ids").split()[0]
        synchronized_cell.focus()
        section_filter = page.evaluate(
            "window.SATN_REVIEW_MAP.getFilter('gradient-section-highlight')"
        )
        assert section_id in str(section_filter)

        page.locator("#gradient-path-reverse").click()
        assert "2 edges selected" in page.locator("#gradient-path-status").inner_text()
        reversed_cell = page.locator(
            '.track-cell[data-gradient-section-ids]:not([data-gradient-section-ids=""])'
        ).first
        reversed_section_id = reversed_cell.get_attribute("data-gradient-section-ids").split()[0]
        reversed_cell.focus()
        reversed_filter = page.evaluate(
            "window.SATN_REVIEW_MAP.getFilter('gradient-section-highlight')"
        )
        assert reversed_section_id in str(reversed_filter)
        page.locator("#terrain-mode").click()
        page.wait_for_function(
            "!document.querySelector('#terrain-mode').checked",
            timeout=10_000,
        )
        assert "restored 2D" in page.locator("#terrain-status").inner_text()
        assert "2 edges selected" in page.locator("#gradient-path-status").inner_text()
        page.locator("#gradient-path-remove").click()
        assert "1 edge selected" in page.locator("#gradient-path-status").inner_text()
        page.locator("#gradient-path-reset").click()
        assert "No path selected" in page.locator("#gradient-path-status").inner_text()

        browser.close()
