from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from pydantic import ValidationError
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.evidence import (
    AccessLevel,
    AdapterKind,
    EvidenceFamily,
    EvidenceFamilyRequirement,
    EvidenceQuality,
    EvidenceRegistryConfig,
    EvidenceRole,
    EvidenceSourceSpec,
    PublicDisposition,
    SpatialCoverage,
    snapshot_evidence_registry,
)
from lcwip.interventions import (
    CatalogueEntry,
    ConceptGeometry,
    ConfidenceLevel,
    ConstraintAssessment,
    ConstraintState,
    ConstraintTopic,
    CostRange,
    DeficiencyReference,
    DesiredOutcome,
    HumanVerification,
    InterventionCatalogue,
    InterventionConcept,
    InterventionFamily,
    InterventionPackage,
    InterventionPlanningConfig,
    InterventionStatus,
    ProgrammeMode,
    ProgrammeUser,
    SourceWorkflow,
    StageVerification,
    build_intervention_packages,
    validate_intervention_bundle,
)
from lcwip.models import ArtifactLink, GuidanceProfile

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "tests" / "fixtures" / "lcwip" / "evidence"


def guidance_profile() -> GuidanceProfile:
    return GuidanceProfile.model_validate_json(
        (
            PROJECT / "src" / "lcwip" / "profiles" / "dft-lcwip-2017.json"
        ).read_text()
    )


def evidence_snapshot(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    controlled = FIXTURES / "controlled-local-import.json"
    common = {
        "publisher": "B&NES synthetic fixture publisher",
        "licence": "Open Government Licence v3.0",
        "retrieved_on": date(2026, 2, 1),
        "observed_from": date(2025, 1, 1),
        "observed_to": date(2026, 1, 31),
        "version": "2026.1",
        "known_bias": "Synthetic evidence is not a delivery decision.",
        "quality": EvidenceQuality.HIGH,
        "permitted_uses": ("intervention-packaging",),
        "spatial_coverage": SpatialCoverage(
            expected_units=("BANES",),
            covered_units=("BANES",),
            description="Synthetic B&NES intervention coverage.",
        ),
    }
    sources = (
        EvidenceSourceSpec(
            evidence_id="cycling-deficiency-evidence",
            adapter=AdapterKind.COLLISIONS_TRAFFIC,
            family=EvidenceFamily.SAFETY_TRAFFIC,
            role=EvidenceRole.OBSERVED,
            path=FIXTURES / "collisions-traffic.json",
            source_uri="fixture://banes/cycling-deficiency",
            methodology="Synthetic cycling audit evidence.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="walking-deficiency-evidence",
            adapter=AdapterKind.RIGHTS_OF_WAY_INFRASTRUCTURE,
            family=EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE,
            role=EvidenceRole.OBSERVED,
            path=FIXTURES / "rights-of-way-infrastructure.json",
            source_uri="fixture://banes/walking-deficiency",
            methodology="Synthetic walking audit evidence.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="constraint-evidence",
            adapter=AdapterKind.DEVELOPMENT_POLICY,
            family=EvidenceFamily.DEVELOPMENT_POLICY,
            role=EvidenceRole.POLICY,
            path=FIXTURES / "development-policy.json",
            source_uri="fixture://banes/constraints",
            methodology="Synthetic constraint record.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="cost-evidence",
            adapter=AdapterKind.CONTROLLED_LOCAL_IMPORT,
            family=EvidenceFamily.LOCAL_EVIDENCE,
            role=EvidenceRole.EXPERT_JUDGEMENT,
            path=controlled,
            redacted_path=controlled,
            source_uri="fixture://banes/cost-benchmark",
            methodology="Privacy-safe synthetic cost benchmark.",
            access_level=AccessLevel.CONTROLLED,
            public_disposition=PublicDisposition.REDACTED,
            **common,
        ),
    )
    requirements = tuple(
        EvidenceFamilyRequirement(
            family=family,
            required_units=("BANES",),
            maximum_age_days=730,
            minimum_quality=EvidenceQuality.MEDIUM,
            required_use="intervention-packaging",
        )
        for family in (
            EvidenceFamily.SAFETY_TRAFFIC,
            EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE,
            EvidenceFamily.DEVELOPMENT_POLICY,
            EvidenceFamily.LOCAL_EVIDENCE,
        )
    )
    return snapshot_evidence_registry(
        EvidenceRegistryConfig(
            snapshot_id="banes-intervention-evidence",
            council_id="bath-and-north-east-somerset",
            profile_id="dft-lcwip-2017",
            reference_date=date(2026, 2, 1),
            output_dir=tmp_path / "evidence",
            requirements=requirements,
            sources=sources,
        )
    )


def verification(
    verification_id: str,
    *,
    purpose: str = "Material judgement reviewed.",
) -> HumanVerification:
    return HumanVerification(
        verification_id=verification_id,
        authority_name="Accountable B&NES officer",
        authority_role="Strategic transport programme manager",
        verified_on=date(2026, 2, 1),
        rationale=purpose,
        evidence_ids=("cost-evidence",),
    )


def catalogue() -> InterventionCatalogue:
    return InterventionCatalogue(
        catalogue_id="banes-intervention-catalogue",
        version="1.0",
        entries=(
            CatalogueEntry(
                catalogue_item_id="controlled-crossing",
                version="1.0",
                family=InterventionFamily.CROSSING,
                title="Controlled crossing concept",
                permitted_geometry_types=("point",),
                supported_modes=(ProgrammeMode.CYCLING, ProgrammeMode.WALKING),
                supported_users=(
                    ProgrammeUser.CYCLIST,
                    ProgrammeUser.PEDESTRIAN,
                    ProgrammeUser.WHEELCHAIR_USER,
                ),
                strategic_scope="Crossing control and approximate location only.",
                excluded_detailed_scope=(
                    "Signal design",
                    "Road-safety audit",
                    "Construction approval",
                ),
            ),
            CatalogueEntry(
                catalogue_item_id="continuous-footway",
                version="1.0",
                family=InterventionFamily.ROUTE_SECTION,
                title="Continuous accessible footway concept",
                permitted_geometry_types=("line",),
                supported_modes=(ProgrammeMode.WALKING, ProgrammeMode.WHEELING),
                supported_users=(
                    ProgrammeUser.PEDESTRIAN,
                    ProgrammeUser.WHEELCHAIR_USER,
                    ProgrammeUser.MOBILITY_AID_USER,
                ),
                strategic_scope="Route section and desired continuity outcome.",
                excluded_detailed_scope=(
                    "Detailed levels",
                    "Materials specification",
                    "Land negotiation",
                ),
            ),
        ),
    )


def deficiencies() -> tuple[DeficiencyReference, ...]:
    return (
        DeficiencyReference(
            deficiency_id="cycling-crossing-gap",
            source_workflow=SourceWorkflow.CYCLING,
            source_artifact=ArtifactLink(
                artifact_id="cycling-plan",
                uri="cycling-manifest.json#coverage_gaps",
                kind="cycling-network-plan",
            ),
            source_fingerprint="1" * 64,
            source_record_id="cycling-gap-1",
            subject_id="cycling-route-1",
            description="No suitable crossing on a strategic cycling desire line.",
            modes=(ProgrammeMode.CYCLING,),
            users_served=(ProgrammeUser.CYCLIST,),
            evidence_ids=("cycling-deficiency-evidence",),
            accepted_by=verification("accept-cycling-deficiency"),
        ),
        DeficiencyReference(
            deficiency_id="walking-continuity-gap",
            source_workflow=SourceWorkflow.WALKING_WHEELING,
            source_artifact=ArtifactLink(
                artifact_id="walking-audit",
                uri="walking-manifest.json#audits",
                kind="walking-route-area-audit",
            ),
            source_fingerprint="2" * 64,
            source_record_id="deficiency-walk-1",
            subject_id="walking-route-1",
            description="Wheelchair and mobility-aid continuity is deficient.",
            modes=(ProgrammeMode.WALKING, ProgrammeMode.WHEELING),
            users_served=(
                ProgrammeUser.PEDESTRIAN,
                ProgrammeUser.WHEELCHAIR_USER,
                ProgrammeUser.MOBILITY_AID_USER,
            ),
            evidence_ids=("walking-deficiency-evidence",),
            accepted_by=verification("accept-walking-deficiency"),
        ),
    )


def outcomes() -> tuple[DesiredOutcome, ...]:
    return (
        DesiredOutcome(
            outcome_id="safer-crossing-outcome",
            statement="Provide a legible, direct crossing opportunity.",
            success_measure="Crossing concept resolves the accepted severance.",
            evidence_ids=("cycling-deficiency-evidence",),
            assumptions=("Subject to traffic and signal feasibility.",),
            unknowns=("Detailed signal staging is unknown.",),
        ),
        DesiredOutcome(
            outcome_id="continuous-accessible-route",
            statement="Provide continuous wheelchair and mobility-aid access.",
            success_measure="No unresolved footway continuity break remains.",
            evidence_ids=("walking-deficiency-evidence",),
            assumptions=("Concept remains within adopted highway where possible.",),
            unknowns=("Detailed levels and drainage are unknown.",),
        ),
    )


def costs() -> tuple[CostRange, ...]:
    return (
        CostRange(
            cost_range_id="cost-crossing",
            intervention_id="concept-crossing",
            currency="GBP",
            lower_bound=250_000,
            upper_bound=500_000,
            rounding_increment=25_000,
            price_base_year=2026,
            basis="benchmark-range",
            confidence=ConfidenceLevel.LOW,
            included_scope=("Concept crossing works", "Basic traffic management"),
            excluded_scope=("Land", "Utility diversions", "Detailed design"),
            quantity_assumptions=("One controlled crossing",),
            unknowns=("Utility diversions", "Signal-controller requirements"),
            source_evidence_ids=("cost-evidence",),
            verified_by=verification("verify-crossing-cost"),
        ),
        CostRange(
            cost_range_id="cost-footway",
            intervention_id="concept-footway",
            currency="GBP",
            lower_bound=100_000,
            upper_bound=250_000,
            rounding_increment=25_000,
            price_base_year=2026,
            basis="quantity-and-benchmark-range",
            confidence=ConfidenceLevel.MEDIUM,
            included_scope=("Approximate route-section construction",),
            excluded_scope=("Land", "Detailed drainage design"),
            quantity_assumptions=("Approximately 250 metres of route section",),
            unknowns=("Subsurface condition",),
            source_evidence_ids=("cost-evidence",),
            verified_by=verification("verify-footway-cost"),
        ),
    )


def concepts(
    *,
    status: InterventionStatus = InterventionStatus.CONCEPT,
) -> tuple[InterventionConcept, ...]:
    return (
        InterventionConcept(
            intervention_id="concept-crossing",
            catalogue_item_id="controlled-crossing",
            catalogue_item_version="1.0",
            title="Strategic crossing concept",
            deficiency_ids=("cycling-crossing-gap",),
            outcome_ids=("safer-crossing-outcome",),
            geometry=ConceptGeometry(
                geometry_type="point",
                coordinates=((-2.36, 51.38),),
            ),
            modes=(ProgrammeMode.CYCLING, ProgrammeMode.WALKING),
            users_served=(ProgrammeUser.CYCLIST, ProgrammeUser.PEDESTRIAN),
            evidence_ids=("cycling-deficiency-evidence",),
            assumptions=("Exact crossing form remains subject to feasibility.",),
            alternative_intervention_ids=(),
            depends_on_intervention_ids=(),
            mutually_exclusive_intervention_ids=(),
            residual_deficiency_ids=("walking-continuity-gap",),
            cost_range_id="cost-crossing",
            status=status,
            stage_verifications=(),
            detailed_design_in_scope=False,
        ),
        InterventionConcept(
            intervention_id="concept-footway",
            catalogue_item_id="continuous-footway",
            catalogue_item_version="1.0",
            title="Accessible footway continuity concept",
            deficiency_ids=("walking-continuity-gap",),
            outcome_ids=("continuous-accessible-route",),
            geometry=ConceptGeometry(
                geometry_type="line",
                coordinates=((-2.361, 51.379), (-2.355, 51.381)),
            ),
            modes=(ProgrammeMode.WALKING, ProgrammeMode.WHEELING),
            users_served=(
                ProgrammeUser.PEDESTRIAN,
                ProgrammeUser.WHEELCHAIR_USER,
                ProgrammeUser.MOBILITY_AID_USER,
            ),
            evidence_ids=("walking-deficiency-evidence",),
            assumptions=("Concept alignment follows the audited route section.",),
            alternative_intervention_ids=(),
            depends_on_intervention_ids=("concept-crossing",),
            mutually_exclusive_intervention_ids=(),
            residual_deficiency_ids=(),
            cost_range_id="cost-footway",
            status=status,
            stage_verifications=(),
            detailed_design_in_scope=False,
        ),
    )


def constraints(*, all_known: bool = False) -> tuple[ConstraintAssessment, ...]:
    records = []
    for intervention_id in ("concept-crossing", "concept-footway"):
        for topic in ConstraintTopic:
            unknown = topic is ConstraintTopic.UTILITIES and not all_known
            records.append(
                ConstraintAssessment(
                    assessment_id=f"constraint-{intervention_id}-{topic}",
                    intervention_id=intervention_id,
                    topic=topic,
                    state=(
                        ConstraintState.UNKNOWN
                        if unknown
                        else ConstraintState.KNOWN_CLEAR
                    ),
                    material=not unknown,
                    evidence_ids=(
                        () if unknown else ("constraint-evidence",)
                    ),
                    assumptions=(
                        "Strategic evidence only; detailed investigation excluded.",
                    ),
                    unknowns=(
                        ("Utility location and diversion requirement.",)
                        if unknown
                        else ()
                    ),
                    verified_by=(
                        None
                        if unknown
                        else verification(
                            f"verify-{intervention_id}-{topic}",
                            purpose=f"{topic.value} constraint judgement reviewed.",
                        )
                    ),
                )
            )
    return tuple(records)


def packages() -> tuple[InterventionPackage, ...]:
    return (
        InterventionPackage(
            package_id="city-centre-access-package",
            name="City-centre access concepts",
            intervention_ids=("concept-crossing", "concept-footway"),
            outcome_ids=(
                "continuous-accessible-route",
                "safer-crossing-outcome",
            ),
            depends_on_package_ids=(),
            mutually_exclusive_package_ids=(),
            residual_deficiency_ids=(),
            assumptions=("Concept package for later strategic appraisal.",),
        ),
    )


def config(output: Path, snapshot: Path) -> InterventionPlanningConfig:
    profile = guidance_profile()
    active_catalogue = catalogue()
    return InterventionPlanningConfig(
        analysis_id="banes-intervention-packages",
        council_id="bath-and-north-east-somerset",
        guidance_profile=profile,
        guidance_profile_id=profile.profile_id,
        guidance_profile_fingerprint=profile.fingerprint,
        evidence_snapshot=snapshot,
        output_dir=output,
        transformation_version="intervention-packaging-1.0",
        catalogue=active_catalogue,
        catalogue_fingerprint=active_catalogue.fingerprint,
    )


def build_fixture(
    tmp_path: Path,
    *,
    supplied_concepts: tuple[InterventionConcept, ...] | None = None,
    supplied_costs: tuple[CostRange, ...] | None = None,
    supplied_constraints: tuple[ConstraintAssessment, ...] | None = None,
    supplied_packages: tuple[InterventionPackage, ...] | None = None,
) -> Path:
    snapshot = evidence_snapshot(tmp_path)
    return build_intervention_packages(
        config(tmp_path / "output", snapshot),
        deficiencies=deficiencies(),
        outcomes=outcomes(),
        concepts=supplied_concepts or concepts(),
        costs=costs() if supplied_costs is None else supplied_costs,
        constraints=(
            constraints()
            if supplied_constraints is None
            else supplied_constraints
        ),
        packages=packages() if supplied_packages is None else supplied_packages,
    )


def test_candidates_trace_both_audit_models_through_evidence_outcome_and_package(
    tmp_path: Path,
) -> None:
    manifest = validate_intervention_bundle(build_fixture(tmp_path))
    assert {item.source_workflow for item in manifest.deficiencies} == {
        SourceWorkflow.CYCLING,
        SourceWorkflow.WALKING_WHEELING,
    }
    assert all(item.accepted_by for item in manifest.deficiencies)
    assert all(item.deficiency_ids and item.outcome_ids for item in manifest.concepts)
    package = manifest.packages[0]
    assert set(package.intervention_ids) == {
        "concept-crossing",
        "concept-footway",
    }
    assert {
        evidence_id
        for item in manifest.deficiencies
        for evidence_id in item.evidence_ids
    } == {
        "cycling-deficiency-evidence",
        "walking-deficiency-evidence",
    }


def test_catalogue_selection_is_versioned_and_unsupported_selection_is_rejected(
    tmp_path: Path,
) -> None:
    invalid = concepts()[0].model_copy(
        update={"catalogue_item_id": "invented-treatment"}
    )
    with pytest.raises(ValueError, match="catalogue"):
        build_fixture(tmp_path, supplied_concepts=(invalid, concepts()[1]))


def test_cost_ranges_reject_false_precision_and_unsupported_costs(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="range"):
        costs()[0].model_copy(
            update={"lower_bound": 250_000, "upper_bound": 250_000}
        ).model_validate(
            costs()[0].model_copy(
                update={"lower_bound": 250_000, "upper_bound": 250_000}
            ).model_dump()
        )

    unverified = costs()[0].model_copy(update={"verified_by": None})
    with pytest.raises(ValueError, match="human verification"):
        build_fixture(tmp_path / "unverified", supplied_costs=(unverified, costs()[1]))

    unsupported = costs()[0].model_copy(
        update={"source_evidence_ids": ("cycling-deficiency-evidence",)}
    )
    with pytest.raises(ValueError, match="cost evidence"):
        build_fixture(tmp_path / "unsupported", supplied_costs=(unsupported, costs()[1]))


def test_missing_cost_remains_strategic_option_and_creates_typed_request(
    tmp_path: Path,
) -> None:
    strategic = concepts()[0].model_copy(
        update={"cost_range_id": None, "status": InterventionStatus.STRATEGIC_OPTION}
    )
    bundle = build_fixture(
        tmp_path,
        supplied_concepts=(strategic, concepts()[1]),
        supplied_costs=(costs()[1],),
    )
    manifest = validate_intervention_bundle(bundle)
    assert any(
        request.intervention_id == "concept-crossing"
        and request.kind == "outline-cost"
        for request in manifest.evidence_requests
    )
    assert next(
        item for item in manifest.concepts if item.intervention_id == "concept-crossing"
    ).status is InterventionStatus.STRATEGIC_OPTION

    unsupported_status = strategic.model_copy(update={"status": InterventionStatus.CONCEPT})
    with pytest.raises(ValueError, match="cost"):
        build_fixture(
            tmp_path / "concept",
            supplied_concepts=(unsupported_status, concepts()[1]),
            supplied_costs=(costs()[1],),
        )


def test_constraints_are_complete_human_verified_and_unknowns_remain_requests(
    tmp_path: Path,
) -> None:
    manifest = validate_intervention_bundle(build_fixture(tmp_path))
    assert len(manifest.constraints) == len(tuple(ConstraintTopic)) * 2
    assert any(item.state is ConstraintState.UNKNOWN for item in manifest.constraints)
    assert any(
        request.kind == "constraint"
        and request.topic is ConstraintTopic.UTILITIES
        for request in manifest.evidence_requests
    )
    assert all(
        item.verified_by is not None
        for item in manifest.constraints
        if item.material and item.state is not ConstraintState.UNKNOWN
    )


def test_lifecycle_cannot_advance_without_external_human_evidence(tmp_path: Path) -> None:
    feasible = tuple(
        item.model_copy(update={"status": InterventionStatus.FEASIBLE})
        for item in concepts()
    )
    with pytest.raises(ValueError, match="feasibility"):
        build_fixture(
            tmp_path / "missing-gate",
            supplied_concepts=feasible,
            supplied_constraints=constraints(all_known=True),
        )

    verified_feasible = tuple(
        item.model_copy(
            update={
                "status": InterventionStatus.FEASIBLE,
                "stage_verifications": (
                    StageVerification(
                        stage=InterventionStatus.FEASIBLE,
                        verification=verification(
                            f"feasibility-{item.intervention_id}",
                            purpose="External feasibility evidence reviewed.",
                        ),
                    ),
                ),
            }
        )
        for item in concepts()
    )
    manifest = validate_intervention_bundle(
        build_fixture(
            tmp_path / "verified",
            supplied_concepts=verified_feasible,
            supplied_constraints=constraints(all_known=True),
        )
    )
    assert all(item.status is InterventionStatus.FEASIBLE for item in manifest.concepts)
    assert all(item.detailed_design_in_scope is False for item in manifest.concepts)


def test_dependency_and_mutual_exclusion_graphs_reject_cycles_and_asymmetry(
    tmp_path: Path,
) -> None:
    cyclic = (
        concepts()[0].model_copy(
            update={"depends_on_intervention_ids": ("concept-footway",)}
        ),
        concepts()[1],
    )
    with pytest.raises(ValueError, match="cycle"):
        build_fixture(tmp_path / "cycle", supplied_concepts=cyclic)

    asymmetric_packages = (
        packages()[0].model_copy(
            update={"mutually_exclusive_package_ids": ("alternative-package",)}
        ),
        InterventionPackage(
            package_id="alternative-package",
            name="Alternative",
            intervention_ids=("concept-crossing",),
            outcome_ids=("safer-crossing-outcome",),
            depends_on_package_ids=(),
            mutually_exclusive_package_ids=(),
            residual_deficiency_ids=("walking-continuity-gap",),
            assumptions=("Alternative package.",),
        ),
    )
    with pytest.raises(ValueError, match="symmetric"):
        build_fixture(
            tmp_path / "asymmetric",
            supplied_packages=asymmetric_packages,
        )


def test_bundle_is_reproducible_spatial_cross_validated_and_cli_readable(
    tmp_path: Path,
) -> None:
    first = build_fixture(tmp_path / "first")
    second = build_fixture(tmp_path / "second")
    first_manifest = validate_intervention_bundle(first)
    second_manifest = validate_intervention_bundle(second)
    assert first_manifest.analysis_fingerprint == second_manifest.analysis_fingerprint
    network = json.loads((first / "intervention-concepts.geojson").read_text())
    assert {feature["properties"]["delivery_status"] for feature in network["features"]} == {
        "concept"
    }
    result = CliRunner().invoke(app, ["interventions", "validate", str(first)])
    assert result.exit_code == 0, result.output
    assert first_manifest.analysis_fingerprint in result.output

    costs_path = first / "costs-and-constraints.json"
    costs_path.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="content hash"):
        validate_intervention_bundle(first)


@pytest.mark.browser
def test_review_map_distinguishes_aspiration_concept_and_delivery_status(
    tmp_path: Path,
) -> None:
    bundle = build_fixture(tmp_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((bundle / "review-map.html").as_uri())
        assert page.get_by_role(
            "heading", name="Infrastructure intervention review"
        ).is_visible()
        assert page.get_by_role(
            "heading",
            name="Network aspirations and accepted deficiencies",
        ).is_visible()
        assert page.get_by_text("Intervention concept", exact=True).first.is_visible()
        assert page.get_by_role(
            "table", name="Intervention delivery status table"
        ).is_visible()
        assert page.get_by_text("Detailed design is out of scope", exact=False).is_visible()
        browser.close()
