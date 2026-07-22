from __future__ import annotations

import json
from pathlib import Path

from test_backbone_assembly import parallel_spine_source

from satn.agents import FakeAgentRuntime
from satn.compiler import _human_intervention_requests, compile_network
from satn.models import AgentRecord, CouncilConfig, TrafficLight
from satn.publisher import _write_backbone_comparison

PROJECT = Path(__file__).parents[1]


def test_default_compilation_exposes_only_backbone_outward_connections(
    tmp_path: Path,
) -> None:
    config = CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")
    config.publication.output_dir = tmp_path / "publication"

    compiled = compile_network(config, parallel_spine_source(), FakeAgentRuntime())
    assert set(compiled.spine_access_connections["parent_role"]) <= {
        "strategic-spine",
        "spine-access-connection",
        "cross-spine-connector",
    }
    assert set(compiled.access_obligations["service_status"]) <= {
        "served",
        "served-provisional",
        "network-gap",
    }
    assert len(compiled.access_obligations) == (
        compiled.access_obligations["access_connection_id"].notna().sum()
        + (compiled.access_obligations["service_status"] == "network-gap").sum()
    )
    assert len(compiled.gaps) == int(
        (compiled.access_obligations["service_status"] == "network-gap").sum()
    )
    assert compiled.human_intervention_requests == []


def test_only_exhausted_material_ambiguity_requests_human_intervention() -> None:
    attempts = [
        {
            "attempt": attempt,
            "proposal": {"selected_role": "direct"},
            "deterministic_findings": [
                {
                    "code": "missing-evidence",
                    "severity": "blocking",
                    "message": "The governing evidence is ambiguous.",
                    "evidence_ids": ["evidence-needed"],
                }
            ],
        }
        for attempt in range(1, 4)
    ]
    record = AgentRecord(
        connection_id="spine-access-ambiguous",
        governing_status=TrafficLight.AMBER,
        review_policy=(TrafficLight.AMBER, TrafficLight.RED),
        review_required=True,
        runtime="fake",
        model="fake",
        proposal="direct",
        critique="blocking",
        revision="exhausted",
        decision="gap",
        outcome_reason="Compilation gate exhausted its bounded attempts.",
        attempts=attempts,
    )

    requests = _human_intervention_requests([record], 3)

    assert len(requests) == 1
    assert requests[0].connection_id == record.connection_id
    assert requests[0].missing_evidence == ["evidence-needed"]
    assert requests[0].smallest_human_input
    partial = record.model_copy(update={"attempts": attempts[:2]})
    assert _human_intervention_requests([partial], 3) == []

    no_progress = partial.model_copy(
        update={"outcome_reason": "Compilation gate stopped after a no-progress revision."}
    )
    assert len(_human_intervention_requests([no_progress], 3)) == 1

    routine_failure = record.model_copy(
        update={
            "attempts": [
                {
                    **attempt,
                    "deterministic_findings": [
                        {
                            "code": "deterministic-continuity",
                            "severity": "blocking",
                            "message": "Deterministic criterion continuity is red.",
                            "evidence_ids": ["osm-network"],
                        }
                    ],
                }
                for attempt in attempts
            ]
        }
    )
    assert _human_intervention_requests([routine_failure], 3) == []


def test_comparison_labels_previous_pairwise_output_as_a_non_truth_reference(
    tmp_path: Path,
) -> None:
    config = CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")
    compiled = compile_network(config, parallel_spine_source(), FakeAgentRuntime())
    previous = tmp_path / "previous"
    previous.mkdir()
    (previous / "network.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "connection-legacy",
                        "properties": {"feature_type": "connection"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[0, 0], [0.01, 0]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "comparison.json"

    _write_backbone_comparison(report_path, compiled, previous)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["comparison_role"] == "superseded-reference-not-ground-truth"
    assert report["superseded_pairwise_reference"]["network_model"] == "legacy-pairwise"
    assert report["superseded_pairwise_reference"]["connection_count"] == 1
    assert report["topology"]["current"]["strategic_spine_count"] == len(compiled.strategic_spines)
    previous_topology = report["topology"]["previous"]
    assert previous_topology["network_model"] == "legacy-pairwise"
    assert previous_topology["network_gap_count"] == 0
    assert previous_topology["feature_role_counts"] == {"connection": 1}
    assert previous_topology["edge_count"] == 0
    assert report["current_backbone"]["connection_count"] == compiled.connection_count
    assert report["explainability"]["all_current_connections_have_typed_roles"]


def test_comparison_accepts_the_immutable_banes_pairwise_summary(tmp_path: Path) -> None:
    config = CouncilConfig.from_yaml(PROJECT / "examples" / "fixture" / "council.yaml")
    compiled = compile_network(config, parallel_spine_source(), FakeAgentRuntime())
    report_path = tmp_path / "comparison.json"

    _write_backbone_comparison(
        report_path,
        compiled,
        PROJECT / "references" / "banes-legacy-pairwise-summary.json",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    previous = report["superseded_pairwise_reference"]
    assert previous == {
        "network_model": "legacy-pairwise",
        "connection_count": 163,
        "linework_length_m": 319649.0,
    }
    assert report["topology"]["previous"]["feature_role_counts"] == {
        "connection": 163
    }
    assert report["topology"]["previous"]["component_count"] == 1
