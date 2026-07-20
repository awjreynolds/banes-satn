from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live-osm",
        action="store_true",
        default=False,
        help="run tests that retrieve live OSM data",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live-osm"):
        return
    skip = pytest.mark.skip(reason="requires --live-osm")
    for item in items:
        if "live_osm" in item.keywords:
            item.add_marker(skip)

