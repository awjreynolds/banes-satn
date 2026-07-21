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
    for item in items:
        if "live_osm" in item.keywords and osm_skip:
            item.add_marker(osm_skip)
        if "live_agent" in item.keywords and agent_skip:
            item.add_marker(agent_skip)
