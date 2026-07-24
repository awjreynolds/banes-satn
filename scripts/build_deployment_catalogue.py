"""Build the small GitHub Pages deployment selector from its tracked definition."""

from __future__ import annotations

import argparse
from pathlib import Path

from satn.deployment_catalogue import build_deployment_catalogue

PROJECT = Path(__file__).parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--catalogue", type=Path, default=PROJECT / "deployments" / "catalogue.yaml"
    )
    parser.add_argument("--destination", type=Path, default=PROJECT / "build" / "pages")
    args = parser.parse_args()
    print(build_deployment_catalogue(args.catalogue, args.destination))


if __name__ == "__main__":
    main()
