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
    interventions = json.loads(
        (review_map / "human-intervention-requests.json").read_text(encoding="utf-8")
    )
    comparison = json.loads((review_map / "backbone-comparison.json").read_text(encoding="utf-8"))
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
        network_path = content / "network.geojson"
        network = json.loads(network_path.read_text(encoding="utf-8"))
        topography_features = []
        governed_profile_features = []
        public_features = []
        for feature in network["features"]:
            feature_type = feature["properties"].get("feature_type")
            if feature_type == "gradient-section":
                topography_features.append(feature)
                continue
            if feature_type == "topography-profile":
                governed_profile_features.append({**feature, "geometry": None})
                properties = dict(feature["properties"])
                capability = json.loads(properties.get("micro_gradient_capability") or "{}")
                capability.pop("uncertainty", None)
                properties["micro_gradient_capability"] = json.dumps(
                    capability,
                    separators=(",", ":"),
                )
                intervals = json.loads(properties.get("micro_gradient_intervals") or "[]")
                properties["micro_gradient_intervals"] = json.dumps(
                    [
                        {
                            key: interval.get(key)
                            for key in (
                                "window_m",
                                "start_distance_m",
                                "end_distance_m",
                                "forward_gradient_pct",
                                "gradient_band",
                                "status",
                            )
                        }
                        for interval in intervals
                    ],
                    separators=(",", ":"),
                )
                topography_features.append(
                    {
                        "type": "Feature",
                        "id": feature["id"],
                        "properties": {
                            "feature_type": feature_type,
                            "profile_id": feature["properties"].get("profile_id"),
                            "evidence_status": feature["properties"].get("evidence_status"),
                        },
                        "geometry": feature["geometry"],
                    }
                )
                feature = {**feature, "properties": properties, "geometry": None}
            public_features.append(feature)
        network["features"] = public_features
        network_path.write_text(
            json.dumps(network, separators=(",", ":")),
            encoding="utf-8",
        )
        (content / "topography.geojson").write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": topography_features},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        evidence_directory = content / "evidence"
        evidence_directory.mkdir()
        evidence_chunks = []
        for index in range(0, len(governed_profile_features), 200):
            filename = f"topography-profiles-{index // 200:03d}.geojson"
            chunk = governed_profile_features[index : index + 200]
            (evidence_directory / filename).write_text(
                json.dumps(
                    {"type": "FeatureCollection", "features": chunk},
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            evidence_chunks.append(
                {
                    "path": f"evidence/{filename}",
                    "profile_count": len(chunk),
                }
            )
        profile_evidence_index = {
            "schema_version": run["schema_version"],
            "profile_count": len(governed_profile_features),
            "chunks": evidence_chunks,
            "disclaimer": DISCLAIMER,
        }
        (content / "topography-profile-evidence.json").write_text(
            json.dumps(profile_evidence_index, indent=2),
            encoding="utf-8",
        )
        data_path = content / "data.js"
        prefix = "window.SATN_DATA = "
        source = data_path.read_text(encoding="utf-8")
        if not source.startswith(prefix) or not source.endswith(";\n"):
            raise SystemExit("review-map data.js has an unsupported format")
        data = json.loads(source.removeprefix(prefix).removesuffix(";\n"))
        data.pop("network", None)
        data["network_url"] = "network.geojson"
        data["topography_url"] = "topography.geojson"
        data["profile_evidence_index_url"] = "topography-profile-evidence.json"
        data_path.write_text(
            f"{prefix}{json.dumps(data, separators=(',', ':')).replace('</', '<\\/')};\n",
            encoding="utf-8",
        )
        shutil.copy2(pdf_map, content / "network-map.pdf")
        (content / ".nojekyll").write_text("", encoding="utf-8")
        publication = {
            "schema_version": run["schema_version"],
            "run_id": run["run_id"],
            "status": run["status"],
            "network_model": run["network_model"],
            "connection_count": run["connection_count"],
            "gap_count": run["gap_count"],
            "human_intervention_request_count": len(interventions["records"]),
            "superseded_hypotheses": run["superseded_hypotheses"],
            "layer_counts": run["layer_counts"],
            "criteria": run["criteria"],
            "compilation_diagnostics": run["compilation_diagnostics"],
            "comparison_role": comparison["comparison_role"],
            "topography_profile_evidence_index": "topography-profile-evidence.json",
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
