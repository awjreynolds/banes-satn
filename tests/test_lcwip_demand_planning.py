from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from pydantic import ValidationError
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.demand import (
    CriterionAssessment,
    DecisionSource,
    DemandAnalysisConfig,
    DemandAnalysisManifest,
    DemandFlow,
    DemandPoint,
    DemandScale,
    DemandScenario,
    RouteCondition,
    RouteCriterion,
    RoutedAlternative,
    RouteNetworkSource,
    RouteQualityAssessment,
    RouteSelectionDecision,
    RouteSelectionProfile,
    RoutingRequest,
    SatnNetworkHypothesis,
    ScaleFilter,
    SensitivityCase,
    build_demand_analysis,
    load_demand_conformance_artifacts,
    route_candidate_fingerprint,
    validate_demand_bundle,
)
from lcwip.evidence import (
    AdapterKind,
    EvidenceFamily,
    EvidenceFamilyRequirement,
    EvidenceQuality,
    EvidenceRegistryConfig,
    EvidenceRole,
    EvidenceSourceSpec,
    SpatialCoverage,
    snapshot_evidence_registry,
)
from lcwip.models import GuidanceProfile
from satn import PublishedArtifactReference, PublishedNetworkFeatureReference

PROJECT = Path(__file__).parents[1]
EVIDENCE_FIXTURES = PROJECT / "tests" / "fixtures" / "lcwip" / "evidence"


def guidance_profile() -> GuidanceProfile:
    return GuidanceProfile.model_validate_json(
        (
            PROJECT
            / "src"
            / "lcwip"
            / "profiles"
            / "dft-lcwip-2017.json"
        ).read_text()
    )


def demand_evidence_snapshot(tmp_path: Path) -> Path:
    source = EvidenceSourceSpec(
        evidence_id="od-evidence",
        adapter=AdapterKind.ORIGIN_DESTINATION,
        family=EvidenceFamily.DEMAND,
        role=EvidenceRole.OBSERVED,
        path=EVIDENCE_FIXTURES / "origin-destination.json",
        source_uri="fixture://banes/origin-destination",
        publisher="B&NES synthetic fixture publisher",
        licence="Open Government Licence v3.0",
        retrieved_on=date(2026, 2, 1),
        observed_from=date(2025, 1, 1),
        observed_to=date(2026, 1, 31),
        spatial_coverage=SpatialCoverage(
            expected_units=("BANES",),
            covered_units=("BANES",),
            description="Synthetic B&NES OD coverage.",
        ),
        version="2026.1",
        methodology="Synthetic directed OD fixture.",
        known_bias="Synthetic values are not planning evidence.",
        quality=EvidenceQuality.HIGH,
        permitted_uses=("demand-analysis",),
    )
    return snapshot_evidence_registry(
        EvidenceRegistryConfig(
            snapshot_id="banes-demand-evidence",
            council_id="bath-and-north-east-somerset",
            profile_id="dft-lcwip-2017",
            reference_date=date(2026, 2, 1),
            output_dir=tmp_path / "evidence",
            requirements=(
                EvidenceFamilyRequirement(
                    family=EvidenceFamily.DEMAND,
                    required_units=("BANES",),
                    maximum_age_days=730,
                    minimum_quality=EvidenceQuality.MEDIUM,
                    required_use="demand-analysis",
                ),
            ),
            sources=(source,),
        )
    )


def satn_hypothesis(tmp_path: Path) -> SatnNetworkHypothesis:
    artifact_path = tmp_path / "satn-network.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "satn-spine",
                "properties": {
                    "feature_type": "strategic-spine",
                    "network_role": "strategic-spine",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-2.6, 51.4], [-2.4, 51.4]],
                },
            },
            {
                "type": "Feature",
                "id": "satn-gap",
                "properties": {
                    "feature_type": "network-gap",
                    "network_role": "network-gap",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-2.5, 51.3], [-2.4, 51.3]],
                },
            },
        ],
    }
    artifact_path.write_text(json.dumps(payload, sort_keys=True))
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    artifact = PublishedArtifactReference(
        run_id="satn-run-1",
        artifact_key="geojson",
        uri=artifact_path.resolve().as_uri(),
        sha256=digest,
    )

    def feature(feature_id: str, feature_type: str) -> PublishedNetworkFeatureReference:
        return PublishedNetworkFeatureReference(
            run_id=artifact.run_id,
            artifact_key=artifact.artifact_key,
            feature_id=feature_id,
            feature_type=feature_type,
            network_role=feature_type,
            source_artifact_uri=artifact.uri,
            source_artifact_sha256=artifact.sha256,
        )

    return SatnNetworkHypothesis(
        artifact=artifact,
        features=(
            feature("satn-gap", "network-gap"),
            feature("satn-spine", "strategic-spine"),
        ),
    )


def points(*, equality_relevant: bool = False) -> tuple[DemandPoint, ...]:
    return (
        DemandPoint(
            point_id="bath",
            name="Bath",
            longitude=-2.36,
            latitude=51.38,
            inside_study_area=True,
            equality_relevant=equality_relevant,
            source_evidence_ids=("od-evidence",),
        ),
        DemandPoint(
            point_id="keynsham",
            name="Keynsham",
            longitude=-2.50,
            latitude=51.42,
            inside_study_area=True,
            source_evidence_ids=("od-evidence",),
        ),
    )


def scenario() -> DemandScenario:
    return DemandScenario(
        scenario_id="observed-2026",
        name="Observed synthetic baseline",
        evidence_role=EvidenceRole.OBSERVED,
        assumptions=("Synthetic fixture only.",),
        source_evidence_ids=("od-evidence",),
    )


def flows(*, trips: float = 120, duplicate: bool = False) -> tuple[DemandFlow, ...]:
    records = [
        DemandFlow(
            flow_id="flow-1",
            scenario_id="observed-2026",
            origin_id="bath",
            destination_id="keynsham",
            trips=trips,
            unit="daily-trips",
            source_evidence_ids=("od-evidence",),
        )
    ]
    if duplicate:
        records.append(
            DemandFlow(
                flow_id="flow-2",
                scenario_id="observed-2026",
                origin_id="bath",
                destination_id="keynsham",
                trips=30,
                unit="daily-trips",
                source_evidence_ids=("od-evidence",),
            )
        )
    return tuple(records)


def quality(
    condition: RouteCondition,
    *,
    unknown: tuple[RouteCriterion, ...] = (),
) -> RouteQualityAssessment:
    return RouteQualityAssessment(
        condition=condition,
        criteria=tuple(
            CriterionAssessment(
                criterion=criterion,
                score=None if criterion in unknown else 4,
                evidence_ids=(() if criterion in unknown else ("od-evidence",)),
                rationale=(
                    "Evidence is unavailable."
                    if criterion in unknown
                    else "Synthetic evidence supports the assessment."
                ),
            )
            for criterion in RouteCriterion
        ),
    )


def routed_alternative(
    alternative_id: str,
    *,
    satn: SatnNetworkHypothesis,
    feature_id: str = "satn-spine",
    length_km: float = 12,
    network_source: RouteNetworkSource = RouteNetworkSource.SATN,
    unknown_potential: tuple[RouteCriterion, ...] = (),
) -> RoutedAlternative:
    feature = next(feature for feature in satn.features if feature.feature_id == feature_id)
    route_offset = (sum(ord(character) for character in alternative_id) % 7) * 0.002
    return RoutedAlternative(
        alternative_id=alternative_id,
        network_source=network_source,
        coordinates=(
            (-2.36, 51.38),
            (-2.43, 51.40 + route_offset),
            (-2.50, 51.42),
        ),
        length_km=length_km,
        satn_feature_references=((feature,) if network_source is RouteNetworkSource.SATN else ()),
        external_or_local_network_ids=(
            ("local-network-1",)
            if network_source is not RouteNetworkSource.SATN
            else ()
        ),
        evidence_ids=("od-evidence",),
        current_quality=quality(RouteCondition.CURRENT),
        potential_quality=quality(
            RouteCondition.POTENTIAL,
            unknown=unknown_potential,
        ),
    )


class FixtureRoutingBoundary:
    boundary_id = "fixture-deterministic-routing"
    boundary_version = "1.0"

    def __init__(self, alternatives: tuple[RoutedAlternative, ...]) -> None:
        self.supplied = alternatives
        self.requests: list[RoutingRequest] = []

    def route_alternatives(
        self, request: RoutingRequest
    ) -> tuple[RoutedAlternative, ...]:
        self.requests.append(request)
        return self.supplied


def config(
    tmp_path: Path,
    *,
    evidence_snapshot: Path,
    scales: tuple[ScaleFilter, ...] | None = None,
    sensitivity_cases: tuple[SensitivityCase, ...] = (),
    decisions: tuple[RouteSelectionDecision, ...] = (),
    allow_unknown: bool = False,
) -> DemandAnalysisConfig:
    profile = guidance_profile()
    return DemandAnalysisConfig(
        analysis_id="banes-demand-2026",
        council_id="bath-and-north-east-somerset",
        guidance_profile=profile,
        guidance_profile_id=profile.profile_id,
        guidance_profile_fingerprint=profile.fingerprint,
        evidence_snapshot=evidence_snapshot,
        output_dir=tmp_path / "demand-output",
        transformation_version="demand-transform-v1",
        scales=scales
        or (
            ScaleFilter(
                scale=DemandScale.STRATEGIC,
                minimum_distance_km=5,
                maximum_distance_km=30,
                minimum_trips=10,
                protect_equality_access=True,
            ),
        ),
        sensitivity_cases=sensitivity_cases,
        maximum_route_alternatives=3,
        minimum_route_alternatives=2,
        maximum_route_endpoint_offset_m=250,
        route_selection_profile=RouteSelectionProfile(
            profile_id="dft-rst-compatible-v1",
            guidance_profile_id="dft-lcwip-2017",
            version="1.0",
            selection_condition=RouteCondition.POTENTIAL,
            criterion_order=tuple(RouteCriterion),
            allow_unknown=allow_unknown,
        ),
        decisions=decisions,
    )


def test_outputs_are_reproducible_spatial_and_trace_aggregated_flows(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    boundary = FixtureRoutingBoundary(
        (
            routed_alternative("route-a", satn=satn, length_km=11),
            routed_alternative("route-b", satn=satn, length_km=13),
        )
    )
    first_config = config(tmp_path / "first", evidence_snapshot=evidence)
    second_config = config(tmp_path / "second", evidence_snapshot=evidence)

    first_path = build_demand_analysis(
        first_config,
        points=points(),
        scenarios=(scenario(),),
        flows=flows(duplicate=True),
        satn=satn,
        routing_boundary=boundary,
    )
    second_path = build_demand_analysis(
        second_config,
        points=tuple(reversed(points())),
        scenarios=(scenario(),),
        flows=tuple(reversed(flows(duplicate=True))),
        satn=satn,
        routing_boundary=FixtureRoutingBoundary(boundary.supplied),
    )
    first = validate_demand_bundle(first_path)
    second = validate_demand_bundle(second_path)

    assert first.analysis_fingerprint == second.analysis_fingerprint
    assert first.input_fingerprint == second.input_fingerprint
    assert first.desire_lines[0].trips == 150
    assert first.desire_lines[0].flow_lineage == ("flow-1", "flow-2")
    assert first.desire_lines[0].transformation_version == "demand-transform-v1"
    assert first.desire_lines[0].retained
    assert first.network_density[0].retained_desire_line_count == 1
    assert first.network_density[0].preferred_route_count == 1
    assert first.network_density[0].coverage_ratio == 1
    assert first.route_selection_profile.profile_id == "dft-rst-compatible-v1"
    assert (
        first.route_selection_profile.guidance_profile_id
        == first.guidance_profile_id
    )
    assert first.scale_filters[0].minimum_distance_km == 5
    assert first.maximum_route_endpoint_offset_m == 250
    assert (first_path / "demand-network.geojson").read_bytes() == (
        second_path / "demand-network.geojson"
    ).read_bytes()
    network = json.loads((first_path / "demand-network.geojson").read_text())
    assert {feature["geometry"]["type"] for feature in network["features"]} >= {
        "Point",
        "LineString",
    }
    assert len(boundary.requests) == 1
    assert boundary.requests[0].maximum_alternatives == 3


def test_filters_scales_and_sensitivity_are_config_not_hidden_constants(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    local_only = (
        ScaleFilter(
            scale=DemandScale.LOCAL,
            minimum_distance_km=0,
            maximum_distance_km=5,
            minimum_trips=200,
        ),
    )
    boundary = FixtureRoutingBoundary(())
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(
                tmp_path,
                evidence_snapshot=evidence,
                scales=local_only,
                sensitivity_cases=(
                    SensitivityCase(
                        case_id="lower-local-threshold",
                        scale=DemandScale.LOCAL,
                        minimum_trips=1,
                        minimum_distance_km=0,
                        maximum_distance_km=20,
                    ),
                ),
            ),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=boundary,
        )
    )

    assert not manifest.desire_lines[0].retained
    assert {outcome.rule for outcome in manifest.filter_outcomes} == {
        "minimum-distance-km",
        "maximum-distance-km",
        "minimum-trips",
    }
    sensitivity = manifest.sensitivity_results[0]
    assert sensitivity.case_id == "lower-local-threshold"
    assert sensitivity.retained_desire_line_ids == (manifest.desire_lines[0].desire_line_id,)
    sensitivity_artifact = json.loads(
        (
            tmp_path
            / "demand-output"
            / manifest.analysis_id
            / "sensitivity.json"
        ).read_text()
    )
    assert sensitivity_artifact["scale_filters"][0]["maximum_distance_km"] == 5
    assert sensitivity_artifact["sensitivity_cases"][0]["case_id"] == (
        "lower-local-threshold"
    )
    assert boundary.requests == []


def test_low_demand_equality_access_is_retained_and_unserved_places_stay_visible(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(
                tmp_path,
                evidence_snapshot=evidence,
                scales=(
                    ScaleFilter(
                        scale=DemandScale.STRATEGIC,
                        minimum_distance_km=0,
                        maximum_distance_km=30,
                        minimum_trips=100,
                        protect_equality_access=True,
                    ),
                ),
            ),
            points=points(equality_relevant=True),
            scenarios=(scenario(),),
            flows=flows(trips=0),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )
    )

    assert manifest.desire_lines[0].retained
    trip_filter = next(
        outcome
        for outcome in manifest.filter_outcomes
        if outcome.rule == "minimum-trips"
    )
    assert not trip_filter.passed
    assert trip_filter.overridden_by_equality_access
    assert {gap.point_id for gap in manifest.coverage_gaps} == {"bath", "keynsham"}
    assert all(gap.reason == "no-route-alternatives" for gap in manifest.coverage_gaps)


def test_route_selection_keeps_alternatives_quality_states_and_bounded_decision(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    desire_line_id = "desire-observed-2026-strategic-bath-keynsham"
    decision = RouteSelectionDecision(
        decision_id="officer-choice-1",
        desire_line_id=desire_line_id,
        source=DecisionSource.HUMAN,
        selected_alternative_id="route-b",
        candidate_alternative_ids=("route-a", "route-b"),
        candidate_fingerprint=route_candidate_fingerprint(
            (
                routed_alternative("route-a", satn=satn, length_km=11),
                routed_alternative("route-b", satn=satn, length_km=12),
            )
        ),
        authority_or_agent="Named transport officer",
        rationale="Retain the safer potential corridor for review.",
        evidence_ids=("od-evidence",),
    )
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(
                tmp_path,
                evidence_snapshot=evidence,
                decisions=(decision,),
            ),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (
                    routed_alternative("route-a", satn=satn, length_km=11),
                    routed_alternative("route-b", satn=satn, length_km=12),
                )
            ),
        )
    )

    selection = manifest.route_selections[0]
    assert selection.preferred_alternative_id == "route-b"
    assert selection.decision == decision
    alternatives = {
        alternative.alternative_id: alternative
        for alternative in manifest.route_alternatives
    }
    assert alternatives["route-b"].disposition == "preferred"
    assert alternatives["route-a"].disposition == "rejected"
    assert alternatives["route-a"].rejection_reason
    assert alternatives["route-a"].current_quality.condition is RouteCondition.CURRENT
    assert (
        alternatives["route-a"].potential_quality.condition
        is RouteCondition.POTENTIAL
    )
    assert len(alternatives["route-a"].current_quality.criteria) == len(RouteCriterion)

    stale_decision = decision.model_copy(
        update={"candidate_alternative_ids": ("route-b",)}
    )
    with pytest.raises(ValueError, match="candidate alternatives"):
        build_demand_analysis(
            config(
                tmp_path / "stale-decision",
                evidence_snapshot=evidence,
                decisions=(stale_decision,),
            ),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (
                    routed_alternative("route-a", satn=satn),
                    routed_alternative("route-b", satn=satn),
                )
            ),
        )


def test_unknown_route_quality_prevents_false_preference_and_is_explicit(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    boundary = FixtureRoutingBoundary(
        (
            routed_alternative(
                "route-a",
                satn=satn,
                unknown_potential=(RouteCriterion.SAFETY,),
            ),
            routed_alternative("route-b", satn=satn),
        )
    )
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(tmp_path, evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=boundary,
        )
    )

    assert manifest.route_selections[0].preferred_alternative_id == "route-b"
    rejected = next(
        alternative
        for alternative in manifest.route_alternatives
        if alternative.alternative_id == "route-a"
    )
    assert rejected.explicit_unknowns == ("safety",)
    assert "unknown" in rejected.rejection_reason

    all_unknown = FixtureRoutingBoundary(
        (
            routed_alternative(
                "route-a",
                satn=satn,
                unknown_potential=(RouteCriterion.SAFETY,),
            ),
            routed_alternative(
                "route-b",
                satn=satn,
                unknown_potential=(RouteCriterion.COMFORT,),
            ),
        )
    )
    unresolved = validate_demand_bundle(
        build_demand_analysis(
            config(tmp_path / "unknown", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=all_unknown,
        )
    )
    assert unresolved.route_selections[0].preferred_alternative_id is None
    assert set(unresolved.route_selections[0].explicit_unknowns) == {
        RouteCriterion.SAFETY,
        RouteCriterion.COMFORT,
    }


def test_satn_is_a_reported_hypothesis_and_gap_or_local_divergence_never_mutates_it(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    original = satn.model_dump_json()
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(tmp_path, evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (
                    routed_alternative(
                        "satn-gap-option",
                        satn=satn,
                        feature_id="satn-gap",
                    ),
                    routed_alternative(
                        "local-option",
                        satn=satn,
                        network_source=RouteNetworkSource.LOCAL,
                    ),
                )
            ),
        )
    )

    relationships = {
        relationship.relationship for relationship in manifest.network_reconciliations
    }
    assert relationships == {"local-network", "network-gap"}
    assert all(record.divergence_reported for record in manifest.network_reconciliations)
    assert satn.model_dump_json() == original
    assert not hasattr(manifest, "mutated_satn_features")


def test_missing_flows_create_gaps_without_calling_routing_or_guessing(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    boundary = FixtureRoutingBoundary(())
    manifest = validate_demand_bundle(
        build_demand_analysis(
            config(tmp_path, evidence_snapshot=evidence),
            points=points(equality_relevant=True),
            scenarios=(scenario(),),
            flows=(),
            satn=satn,
            routing_boundary=boundary,
        )
    )

    assert manifest.desire_lines == ()
    assert boundary.requests == []
    assert {gap.reason for gap in manifest.coverage_gaps} == {
        "no-governed-flow-evidence"
    }
    assert {gap.point_id for gap in manifest.coverage_gaps} == {"bath", "keynsham"}
    assert len(manifest.network_density) == 1
    assert manifest.network_density[0].retained_desire_line_count == 0
    assert manifest.network_density[0].coverage_ratio == 0
    assert manifest.network_density[0].gap_point_ids == ("bath", "keynsham")


def test_routing_boundary_is_finite_and_cannot_return_unoffered_satn_features(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    too_many = tuple(
        routed_alternative(f"route-{index}", satn=satn)
        for index in range(4)
    )
    with pytest.raises(ValueError, match="maximum_route_alternatives"):
        build_demand_analysis(
            config(tmp_path / "too-many", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(too_many),
        )

    unknown_feature = PublishedNetworkFeatureReference(
        run_id=satn.artifact.run_id,
        artifact_key=satn.artifact.artifact_key,
        feature_id="not-in-hypothesis",
        feature_type="strategic-spine",
        network_role="strategic-spine",
        source_artifact_uri=satn.artifact.uri,
        source_artifact_sha256=satn.artifact.sha256,
    )
    invalid = routed_alternative("invalid", satn=satn).model_copy(
        update={"satn_feature_references": (unknown_feature,)}
    )
    with pytest.raises(ValueError, match="not in the SATN hypothesis"):
        build_demand_analysis(
            config(tmp_path / "unknown-feature", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (invalid, routed_alternative("valid", satn=satn))
            ),
        )

    route_a = routed_alternative("route-a", satn=satn)
    duplicate_geometry = route_a.model_copy(
        update={"alternative_id": "duplicate-geometry"}
    )
    with pytest.raises(ValueError, match="geometrically distinct"):
        build_demand_analysis(
            config(tmp_path / "duplicate-geometry", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (route_a, duplicate_geometry)
            ),
        )

    impossible_length = route_a.model_copy(
        update={"alternative_id": "impossible-length", "length_km": 0.1}
    )
    with pytest.raises(ValueError, match="shorter than its geometry"):
        build_demand_analysis(
            config(tmp_path / "impossible-length", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (impossible_length, routed_alternative("valid-length", satn=satn))
            ),
        )

    detached = routed_alternative("detached", satn=satn).model_copy(
        update={"coordinates": ((-1.0, 50.0), (-1.1, 50.1))}
    )
    with pytest.raises(ValueError, match="endpoint offset"):
        build_demand_analysis(
            config(tmp_path / "detached", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (detached, routed_alternative("valid-2", satn=satn))
            ),
        )


def test_existing_bundle_rejects_nondeterministic_routing_under_the_same_version(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    analysis_config = config(tmp_path, evidence_snapshot=evidence)
    build_demand_analysis(
        analysis_config,
        points=points(),
        scenarios=(scenario(),),
        flows=flows(),
        satn=satn,
        routing_boundary=FixtureRoutingBoundary(
            (
                routed_alternative("route-a", satn=satn, length_km=12),
                routed_alternative("route-b", satn=satn, length_km=14),
            )
        ),
    )

    with pytest.raises(ValueError, match="not reproducible"):
        build_demand_analysis(
            analysis_config,
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(
                (
                    routed_alternative("route-a", satn=satn, length_km=13),
                    routed_alternative("route-b", satn=satn, length_km=15),
                )
            ),
        )


def test_cross_boundary_od_point_remains_spatial_and_traceable(tmp_path: Path) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    external = points()[1].model_copy(update={"inside_study_area": False})
    bundle = build_demand_analysis(
        config(tmp_path, evidence_snapshot=evidence),
        points=(points()[0], external),
        scenarios=(scenario(),),
        flows=flows(),
        satn=satn,
        routing_boundary=FixtureRoutingBoundary(
            (
                routed_alternative("route-a", satn=satn),
                routed_alternative("route-b", satn=satn),
            )
        ),
    )
    manifest = validate_demand_bundle(bundle)
    restored = next(
        point for point in manifest.points if point.point_id == "keynsham"
    )
    network = json.loads((bundle / "demand-network.geojson").read_text())
    feature = next(
        item
        for item in network["features"]
        if item["id"] == "demand-point-keynsham"
    )

    assert not restored.inside_study_area
    assert not feature["properties"]["inside_study_area"]


def test_quality_contract_requires_current_and_potential_complete_distinct_assessments() -> None:
    with pytest.raises(ValidationError, match="criteria"):
        RouteQualityAssessment(
            condition=RouteCondition.CURRENT,
            criteria=(
                CriterionAssessment(
                    criterion=RouteCriterion.DIRECTNESS,
                    score=4,
                    evidence_ids=("od-evidence",),
                    rationale="Only one criterion.",
                ),
            ),
        )
    with pytest.raises(ValidationError, match="current_quality"):
        RoutedAlternative(
            alternative_id="invalid",
            network_source=RouteNetworkSource.LOCAL,
            coordinates=((-2.36, 51.38), (-2.50, 51.42)),
            length_km=12,
            external_or_local_network_ids=("local",),
            evidence_ids=("od-evidence",),
            current_quality=quality(RouteCondition.POTENTIAL),
            potential_quality=quality(RouteCondition.POTENTIAL),
        )


def test_bundle_integrity_review_map_and_conformance_links_are_cross_validated(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    bundle = build_demand_analysis(
        config(tmp_path, evidence_snapshot=evidence),
        points=points(),
        scenarios=(scenario(),),
        flows=flows(),
        satn=satn,
        routing_boundary=FixtureRoutingBoundary(
            (
                routed_alternative("route-a", satn=satn),
                routed_alternative("route-b", satn=satn, length_km=14),
            )
        ),
    )
    manifest = validate_demand_bundle(bundle)
    links = load_demand_conformance_artifacts(bundle)

    assert {link.kind for link in links} == {
        "baseline-evidence",
        "cycling-network-plan",
    }
    assert links == manifest.conformance_artifacts
    html = (bundle / "review-map.html").read_text()
    assert "LCWIP demand review map" in html
    assert "SATN divergence is reported, never silently resolved" in html
    assert manifest.desire_lines[0].desire_line_id in html
    assert (bundle / "demand-network.geojson").is_file()
    assert (bundle / "route-selection.json").is_file()
    assert (bundle / "sensitivity.json").is_file()
    assert (bundle / "conformance-artifacts.json").is_file()
    cli_result = CliRunner().invoke(app, ["demand", "validate", str(bundle)])
    assert cli_result.exit_code == 0, cli_result.output
    assert manifest.analysis_fingerprint in cli_result.output

    route_selection = bundle / "route-selection.json"
    route_selection.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="content hash"):
        validate_demand_bundle(bundle)

    payload = manifest.model_dump()
    payload["points"] = (manifest.points[0], manifest.points[0])
    with pytest.raises(ValidationError, match="manifest point IDs must be unique"):
        DemandAnalysisManifest.model_validate(payload)


def test_inputs_must_resolve_to_governed_evidence_and_profile_council_boundary(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    unknown = points()[0].model_copy(
        update={"source_evidence_ids": ("not-governed",)}
    )
    with pytest.raises(ValueError, match="not present in the Evidence Registry"):
        build_demand_analysis(
            config(tmp_path / "unknown", evidence_snapshot=evidence),
            points=(unknown, points()[1]),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )

    mismatch = config(tmp_path / "mismatch", evidence_snapshot=evidence).model_copy(
        update={"council_id": "another-council"}
    )
    with pytest.raises(ValueError, match="council"):
        build_demand_analysis(
            mismatch,
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )

    profile_mismatch = config(
        tmp_path / "profile-mismatch",
        evidence_snapshot=evidence,
    ).model_copy(update={"guidance_profile_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="Guidance Profile fingerprint"):
        build_demand_analysis(
            profile_mismatch,
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )

    with pytest.raises(
        ValidationError,
        match="demand scenarios must be observed, modelled, or derived",
    ):
        DemandScenario.model_validate(
            scenario().model_copy(
                update={"evidence_role": EvidenceRole.POLICY}
            ).model_dump()
        )

    conflicting_unit = flows()[0].model_copy(
        update={"flow_id": "flow-conflicting-unit", "unit": "weekly-trips"}
    )
    with pytest.raises(ValueError, match="conflicting demand-flow units"):
        build_demand_analysis(
            config(tmp_path / "conflicting-unit", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=(*flows(), conflicting_unit),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )

    (tmp_path / "satn-network.geojson").write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="content hash mismatch"):
        build_demand_analysis(
            config(tmp_path / "tampered-satn", evidence_snapshot=evidence),
            points=points(),
            scenarios=(scenario(),),
            flows=flows(),
            satn=satn,
            routing_boundary=FixtureRoutingBoundary(()),
        )


@pytest.mark.browser
def test_demand_review_map_is_spatial_and_accessibly_inspectable(
    tmp_path: Path,
) -> None:
    evidence = demand_evidence_snapshot(tmp_path)
    satn = satn_hypothesis(tmp_path)
    bundle = build_demand_analysis(
        config(tmp_path, evidence_snapshot=evidence),
        points=points(),
        scenarios=(scenario(),),
        flows=flows(),
        satn=satn,
        routing_boundary=FixtureRoutingBoundary(
            (
                routed_alternative("route-a", satn=satn),
                routed_alternative("route-b", satn=satn, length_km=14),
            )
        ),
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((bundle / "review-map.html").as_uri())

        assert page.get_by_role("heading", name="LCWIP demand review map").is_visible()
        assert page.get_by_role(
            "img",
            name="Demand points, desire lines and route alternatives",
        ).is_visible()
        assert page.get_by_role("table").is_visible()
        assert page.get_by_role(
            "row",
            name=(
                "desire-observed-2026-strategic-bath-keynsham "
                "desire line retained"
            ),
        ).is_visible()
        assert page.get_by_role(
            "link", name="Download demand network GeoJSON"
        ).is_visible()
        browser.close()
