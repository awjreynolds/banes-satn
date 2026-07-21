"""Promote the current validated B&NES review map into the tracked Pages site."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from satn.constants import DISCLAIMER

PROJECT = Path(__file__).parents[1]
OUTPUT = PROJECT / "output"
SITE = PROJECT / "site"


def main() -> None:
    run_path = OUTPUT / "run.json"
    review_map = OUTPUT / "review-map"
    pdf_map = OUTPUT / "network-map.pdf"
    if not run_path.exists() or not (review_map / "index.html").exists() or not pdf_map.exists():
        raise SystemExit("compile config/banes.yaml before publishing the site")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run["council_id"] != "bath-and-north-east-somerset":
        raise SystemExit("only the B&NES reference run may be promoted to this Pages site")
    if run["status"] not in {"complete", "reviewable"}:
        raise SystemExit("the current run is not publishable")
    if run["atm_geometry_included"]:
        raise SystemExit("the public Pages site must not contain governed ATM geometry")

    temporary = Path(tempfile.mkdtemp(prefix=".site-", dir=PROJECT))
    try:
        shutil.copytree(review_map, temporary / "content", dirs_exist_ok=True)
        content = temporary / "content"
        shutil.copy2(pdf_map, content / "network-map.pdf")
        (content / ".nojekyll").write_text("", encoding="utf-8")
        publication = {
            "run_id": run["run_id"],
            "status": run["status"],
            "connection_count": run["connection_count"],
            "gap_count": run["gap_count"],
            "superseded_hypotheses": run["superseded_hypotheses"],
            "layer_counts": run["layer_counts"],
            "criteria": run["criteria"],
            "disclaimer": DISCLAIMER,
        }
        (content / "publication.json").write_text(
            json.dumps(publication, indent=2), encoding="utf-8"
        )
        backup = SITE.with_name(".site-previous")
        if backup.exists():
            shutil.rmtree(backup)
        if SITE.exists():
            SITE.replace(backup)
        content.replace(SITE)
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    main()
