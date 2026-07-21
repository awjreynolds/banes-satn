from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live-osm",
        action="store_true",
        default=False,
        help="run tests that retrieve live OSM data",
    )
    parser.addoption(
        "--live-agent",
        action="store_true",
        default=False,
        help="run tests that call a configured Pydantic AI model",
    )
    parser.addoption(
        "--browser",
        action="store_true",
        default=False,
        help="run Playwright browser interaction tests",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live-osm"):
        osm_skip = None
    else:
        osm_skip = pytest.mark.skip(reason="requires --live-osm")
    agent_skip = (
        None
        if config.getoption("--live-agent")
        else pytest.mark.skip(reason="requires --live-agent")
    )
    browser_skip = (
        None
        if config.getoption("--browser")
        else pytest.mark.skip(reason="requires --browser and Playwright Chromium")
    )
    for item in items:
        if "live_osm" in item.keywords and osm_skip:
            item.add_marker(osm_skip)
        if "live_agent" in item.keywords and agent_skip:
            item.add_marker(agent_skip)
        if "browser" in item.keywords and browser_skip:
            item.add_marker(browser_skip)
