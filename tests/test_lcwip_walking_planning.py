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
from lcwip.models import GuidanceProfile
from lcwip.walking import (
    AccessibilityNeed,
    AuditCondition,
    AuditEvidenceMode,
    AuditItem,
    AuditProvenance,
    AuditSubjectKind,
    CoreWalkingZoneProposal,
    LivedExperienceFinding,
    WalkingAttractor,
    WalkingAttractorKind,
    WalkingAuditObservation,
    WalkingAuditProfile,
    WalkingAuditRequirement,
    WalkingAuditStatus,
    WalkingCatchment,
    WalkingPlanningConfig,
    WalkingPlanningManifest,
    WalkingReviewGate,
    WalkingRouteKind,
    WalkingRoutePath,
    WalkingRouteRequest,
    WalkingRouteSpecification,
    build_walking_plan,
    load_walking_conformance_artifacts,
    validate_walking_bundle,
)

PROJECT = Path(__file__).parents[1]
EVIDENCE_FIXTURES = PROJECT / "tests" / "fixtures" / "lcwip" / "evidence"


def guidance_profile() -> GuidanceProfile:
    return GuidanceProfile.model_validate_json(
        (
            PROJECT / "src" / "lcwip" / "profiles" / "dft-lcwip-2017.json"
        ).read_text()
    )


def walking_evidence_snapshot(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    private = tmp_path / "private-engagement.json"
    private.write_text('{"name":"Private person","theme":"crossing"}')

    def coverage(description: str) -> SpatialCoverage:
        return SpatialCoverage(
            expected_units=("BANES",),
            covered_units=("BANES",),
            description=description,
        )

    common = {
        "publisher": "B&NES synthetic fixture publisher",
        "licence": "Open Government Licence v3.0",
        "retrieved_on": date(2026, 2, 1),
        "observed_from": date(2025, 1, 1),
        "observed_to": date(2026, 1, 31),
        "version": "2026.1",
        "known_bias": "Synthetic values are not planning evidence.",
        "quality": EvidenceQuality.HIGH,
        "permitted_uses": ("walking-analysis",),
    }
    sources = (
        EvidenceSourceSpec(
            evidence_id="attractor-evidence",
            adapter=AdapterKind.PUBLIC_TRANSPORT_ATTRACTORS,
            family=EvidenceFamily.PUBLIC_TRANSPORT_ATTRACTORS,
            role=EvidenceRole.OBSERVED,
            path=EVIDENCE_FIXTURES / "public-transport-attractors.json",
            source_uri="fixture://banes/walking-attractors",
            spatial_coverage=coverage("Synthetic walking-attractor coverage."),
            methodology="Synthetic attractor inventory.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="modelled-evidence",
            adapter=AdapterKind.PUBLIC_TRANSPORT_ATTRACTORS,
            family=EvidenceFamily.PUBLIC_TRANSPORT_ATTRACTORS,
            role=EvidenceRole.MODELLED,
            path=EVIDENCE_FIXTURES / "public-transport-attractors.json",
            source_uri="fixture://banes/modelled-walking-conditions",
            spatial_coverage=coverage("Synthetic modelled walking conditions."),
            methodology="Synthetic desktop model fixture.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="site-evidence",
            adapter=AdapterKind.RIGHTS_OF_WAY_INFRASTRUCTURE,
            family=EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE,
            role=EvidenceRole.OBSERVED,
            path=EVIDENCE_FIXTURES / "rights-of-way-infrastructure.json",
            source_uri="fixture://banes/site-survey",
            spatial_coverage=coverage("Synthetic route and area audit coverage."),
            methodology="Synthetic site-survey fixture.",
            **common,
        ),
        EvidenceSourceSpec(
            evidence_id="panel-evidence",
            adapter=AdapterKind.CONTROLLED_LOCAL_IMPORT,
            family=EvidenceFamily.LOCAL_EVIDENCE,
            role=EvidenceRole.STAKEHOLDER,
            path=private,
            redacted_path=EVIDENCE_FIXTURES / "controlled-local-import.json",
            source_uri="fixture://banes/access-panel",
            spatial_coverage=coverage("Redacted access-panel themes."),
            methodology="Privacy-reviewed access-panel thematic coding.",
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
            required_use="walking-analysis",
        )
        for family in (
            EvidenceFamily.PUBLIC_TRANSPORT_ATTRACTORS,
            EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE,
            EvidenceFamily.LOCAL_EVIDENCE,
        )
    )
    return snapshot_evidence_registry(
        EvidenceRegistryConfig(
            snapshot_id="banes-walking-evidence",
            council_id="bath-and-north-east-somerset",
            profile_id="dft-lcwip-2017",
            reference_date=date(2026, 2, 1),
            output_dir=tmp_path / "evidence",
            requirements=requirements,
            sources=sources,
        )
    )


def audit_profile() -> WalkingAuditProfile:
    route = (AuditSubjectKind.ROUTE,)
    both = (AuditSubjectKind.ZONE, AuditSubjectKind.ROUTE)
    return WalkingAuditProfile(
        profile_id="dft-walking-route-area-review-v1",
        guidance_profile_id="dft-lcwip-2017",
        version="1.0",
        requirements=(
            WalkingAuditRequirement(
                item=AuditItem.FOOTWAY_CONTINUITY,
                applies_to=route,
                mandatory=True,
                site_evidence_required=True,
                accessibility_needs=(
                    AccessibilityNeed.WHEELCHAIR,
                    AccessibilityNeed.MOBILITY_AID,
                ),
            ),
            WalkingAuditRequirement(
                item=AuditItem.CROSSINGS,
                applies_to=route,
                mandatory=True,
                site_evidence_required=True,
                accessibility_needs=(
                    AccessibilityNeed.WHEELCHAIR,
                    AccessibilityNeed.VISUAL,
                ),
            ),
            WalkingAuditRequirement(
                item=AuditItem.SEVERANCE,
                applies_to=both,
                mandatory=True,
                site_evidence_required=False,
            ),
            WalkingAuditRequirement(
                item=AuditItem.LIGHTING_PERSONAL_SAFETY,
                applies_to=both,
                mandatory=True,
                site_evidence_required=True,
                accessibility_needs=(AccessibilityNeed.PERSONAL_SAFETY,),
            ),
            WalkingAuditRequirement(
                item=AuditItem.SEATING_REST,
                applies_to=both,
                mandatory=True,
                site_evidence_required=True,
                accessibility_needs=(
                    AccessibilityNeed.MOBILITY_AID,
                    AccessibilityNeed.RESTING,
                ),
            ),
            *(
                WalkingAuditRequirement(
                    item=item,
                    applies_to=both,
                    mandatory=False,
                    site_evidence_required=False,
                )
                for item in (
                    AuditItem.FOOTWAY_WIDTH,
                    AuditItem.SURFACE,
                    AuditItem.GRADIENT,
                    AuditItem.WAYFINDING,
                )
            ),
        ),
    )


def attractors(*, rural: bool = False) -> tuple[WalkingAttractor, ...]:
    if rural:
        return (
            WalkingAttractor(
                attractor_id="chew-magna-centre",
                name="Chew Magna",
                kind=WalkingAttractorKind.LOCAL_CENTRE,
                longitude=-2.61,
                latitude=51.35,
                inside_study_area=True,
                evidence_ids=("attractor-evidence",),
            ),
            WalkingAttractor(
                attractor_id="rural-health-service",
                name="Rural health service",
                kind=WalkingAttractorKind.SERVICE,
                longitude=-2.602,
                latitude=51.351,
                inside_study_area=True,
                evidence_ids=("attractor-evidence",),
                uncertainties=("Opening-hours evidence requires confirmation.",),
            ),
        )
    return (
        WalkingAttractor(
            attractor_id="bath-centre",
            name="Bath city centre",
            kind=WalkingAttractorKind.LOCAL_CENTRE,
            longitude=-2.36,
            latitude=51.38,
            inside_study_area=True,
            evidence_ids=("attractor-evidence",),
        ),
        WalkingAttractor(
            attractor_id="bath-interchange",
            name="Bath interchange",
            kind=WalkingAttractorKind.INTERCHANGE,
            longitude=-2.358,
            latitude=51.379,
            inside_study_area=True,
            evidence_ids=("attractor-evidence",),
        ),
        WalkingAttractor(
            attractor_id="bath-school",
            name="Bath school",
            kind=WalkingAttractorKind.SCHOOL,
            longitude=-2.352,
            latitude=51.382,
            inside_study_area=True,
            evidence_ids=("attractor-evidence",),
        ),
    )


def catchment(*, rural: bool = False) -> WalkingCatchment:
    return WalkingCatchment(
        catchment_id="chew-magna-catchment" if rural else "bath-centre-catchment",
        centre_attractor_id="chew-magna-centre" if rural else "bath-centre",
        radius_m=1500 if rural else 1000,
        method="Configured radial screening catchment; not a route-distance claim.",
        selection_logic="Includes governed trip attractors within the configured radius.",
        evidence_ids=("attractor-evidence",),
        uncertainties=("Walking-network distance requires route review.",),
    )


def zone(*, rural: bool = False) -> CoreWalkingZoneProposal:
    if rural:
        coordinates = (
            (-2.615, 51.346),
            (-2.595, 51.346),
            (-2.595, 51.355),
            (-2.615, 51.355),
            (-2.615, 51.346),
        )
        return CoreWalkingZoneProposal(
            zone_id="chew-magna-cwz",
            name="Chew Magna Core Walking Zone",
            catchment_id="chew-magna-catchment",
            coordinates=coordinates,
            selected_attractor_ids=(
                "chew-magna-centre",
                "rural-health-service",
            ),
            selection_rationale="Local centre and essential rural service access.",
            evidence_ids=("attractor-evidence",),
            uncertainties=("Boundary requires local officer review.",),
        )
    return CoreWalkingZoneProposal(
        zone_id="bath-centre-cwz",
        name="Bath Centre Core Walking Zone",
        catchment_id="bath-centre-catchment",
        coordinates=(
            (-2.37, 51.375),
            (-2.345, 51.375),
            (-2.345, 51.387),
            (-2.37, 51.387),
            (-2.37, 51.375),
        ),
        selected_attractor_ids=(
            "bath-centre",
            "bath-interchange",
            "bath-school",
        ),
        selection_rationale="Concentration of centre, interchange and school trips.",
        evidence_ids=("attractor-evidence",),
        uncertainties=("Final boundary requires public-realm survey.",),
    )


def route_specs(*, rural: bool = False) -> tuple[WalkingRouteSpecification, ...]:
    if rural:
        return (
            WalkingRouteSpecification(
                route_id="chew-service-funnel",
                zone_id="chew-magna-cwz",
                kind=WalkingRouteKind.FUNNEL,
                origin_attractor_id="chew-magna-centre",
                destination_attractor_id="rural-health-service",
                selection_logic="Essential service-access funnel from the local centre.",
                evidence_ids=("attractor-evidence",),
                uncertainties=("Footway continuity requires site survey.",),
            ),
        )
    return (
        WalkingRouteSpecification(
            route_id="bath-interchange-key-route",
            zone_id="bath-centre-cwz",
            kind=WalkingRouteKind.KEY,
            origin_attractor_id="bath-centre",
            destination_attractor_id="bath-interchange",
            selection_logic="Key route between the Core Walking Zone and interchange.",
            evidence_ids=("attractor-evidence",),
            uncertainties=("Crossing operation requires site survey.",),
        ),
        WalkingRouteSpecification(
            route_id="bath-school-funnel",
            zone_id="bath-centre-cwz",
            kind=WalkingRouteKind.FUNNEL,
            origin_attractor_id="bath-school",
            destination_attractor_id="bath-centre",
            selection_logic="School access funnels into the Core Walking Zone.",
            evidence_ids=("attractor-evidence",),
            uncertainties=("School-gate conditions vary by time of day.",),
        ),
    )


class FixtureWalkingRouter:
    boundary_id = "fixture-walking-router"
    boundary_version = "1.0"

    def route(self, request: WalkingRouteRequest) -> WalkingRoutePath:
        origin = request.origin
        destination = request.destination
        midpoint = (
            round((origin.longitude + destination.longitude) / 2, 6),
            round((origin.latitude + destination.latitude) / 2 + 0.0002, 6),
        )
        return WalkingRoutePath(
            route_id=request.specification.route_id,
            coordinates=(
                (origin.longitude, origin.latitude),
                midpoint,
                (destination.longitude, destination.latitude),
            ),
            length_km=2.0,
            evidence_ids=("site-evidence",),
        )


def observations(
    *,
    rural: bool = False,
    complete_site: bool = False,
    deficient_continuity: bool = False,
) -> tuple[WalkingAuditObservation, ...]:
    zone_id = "chew-magna-cwz" if rural else "bath-centre-cwz"
    route_ids = (
        ("chew-service-funnel",)
        if rural
        else ("bath-interchange-key-route", "bath-school-funnel")
    )
    records: list[WalkingAuditObservation] = []
    for subject_id, subject_kind in (
        (zone_id, AuditSubjectKind.ZONE),
        *((route_id, AuditSubjectKind.ROUTE) for route_id in route_ids),
    ):
        for requirement in audit_profile().requirements:
            if subject_kind not in requirement.applies_to:
                continue
            evidence_mode = (
                AuditEvidenceMode.SITE_SURVEY
                if complete_site or requirement.site_evidence_required
                else AuditEvidenceMode.DESKTOP
            )
            if not complete_site and requirement.item is AuditItem.SEATING_REST:
                evidence_mode = AuditEvidenceMode.DESKTOP
            provenance = (
                AuditProvenance.OBSERVED
                if evidence_mode is AuditEvidenceMode.SITE_SURVEY
                else AuditProvenance.INFERRED
            )
            condition = AuditCondition.COMPLIANT
            if (
                deficient_continuity
                and subject_kind is AuditSubjectKind.ROUTE
                and requirement.item is AuditItem.FOOTWAY_CONTINUITY
            ):
                condition = AuditCondition.DEFICIENT
            records.append(
                WalkingAuditObservation(
                    observation_id=f"obs-{subject_id}-{requirement.item}",
                    subject_id=subject_id,
                    item=requirement.item,
                    condition=condition,
                    provenance=provenance,
                    evidence_mode=evidence_mode,
                    evidence_ids=("site-evidence",),
                    rationale="Synthetic audit observation.",
                    accessibility_needs=requirement.accessibility_needs,
                    site_surveyed_on=(
                        date(2026, 1, 20)
                        if evidence_mode is AuditEvidenceMode.SITE_SURVEY
                        else None
                    ),
                )
            )
    return tuple(records)


def lived_experience(*, rural: bool = False) -> tuple[LivedExperienceFinding, ...]:
    return (
        LivedExperienceFinding(
            finding_id="panel-resting-finding",
            subject_id=(
                "chew-service-funnel"
                if rural
                else "bath-interchange-key-route"
            ),
            theme="rest-opportunities",
            summary="Redacted panel theme identifies insufficient resting places.",
            accessibility_needs=(
                AccessibilityNeed.MOBILITY_AID,
                AccessibilityNeed.RESTING,
            ),
            evidence_ids=("panel-evidence",),
            material=True,
            personal_data="removed",
        ),
    )


def review_gate(*, rural: bool = False) -> WalkingReviewGate:
    return WalkingReviewGate(
        gate_id="walking-review-gate",
        officer_name="Accountable B&NES officer",
        accessibility_representative="B&NES access-panel representative",
        verified_zone_ids=(
            ("chew-magna-cwz",) if rural else ("bath-centre-cwz",)
        ),
        verified_audit_limitation_ids=(),
        verified_lived_experience_ids=("panel-resting-finding",),
        rationale="Zone selection and material privacy-safe themes reviewed.",
    )


def config(
    output: Path,
    *,
    evidence_snapshot: Path,
    gate: WalkingReviewGate | None = None,
) -> WalkingPlanningConfig:
    profile = guidance_profile()
    return WalkingPlanningConfig(
        analysis_id="banes-walking-plan",
        council_id="bath-and-north-east-somerset",
        guidance_profile=profile,
        guidance_profile_id=profile.profile_id,
        guidance_profile_fingerprint=profile.fingerprint,
        evidence_snapshot=evidence_snapshot,
        output_dir=output,
        transformation_version="walking-planning-1.0",
        maximum_route_endpoint_offset_m=25,
        audit_profile=audit_profile(),
        review_gate=gate,
    )


def build_fixture(
    tmp_path: Path,
    *,
    rural: bool = False,
    complete_site: bool = False,
    deficient_continuity: bool = False,
    gate: WalkingReviewGate | None = None,
) -> Path:
    evidence = walking_evidence_snapshot(tmp_path)
    return build_walking_plan(
        config(tmp_path / "output", evidence_snapshot=evidence, gate=gate),
        attractors=attractors(rural=rural),
        catchments=(catchment(rural=rural),),
        zones=(zone(rural=rural),),
        route_specifications=route_specs(rural=rural),
        audit_observations=observations(
            rural=rural,
            complete_site=complete_site,
            deficient_continuity=deficient_continuity,
        ),
        lived_experience_findings=lived_experience(rural=rural),
        routing_boundary=FixtureWalkingRouter(),
    )


def test_urban_plan_is_reproducible_spatial_and_independent_of_cycling_geometry(
    tmp_path: Path,
) -> None:
    first = build_fixture(tmp_path / "first")
    second = build_fixture(tmp_path / "second")
    first_manifest = validate_walking_bundle(first)
    second_manifest = validate_walking_bundle(second)

    assert first_manifest.analysis_fingerprint == second_manifest.analysis_fingerprint
    assert {item.kind for item in first_manifest.routes} == {
        WalkingRouteKind.KEY,
        WalkingRouteKind.FUNNEL,
    }
    assert first_manifest.catchments[0].inside_attractor_ids == (
        "bath-centre",
        "bath-interchange",
        "bath-school",
    )
    payload = json.loads((first / "walking-network.geojson").read_text())
    assert payload["type"] == "FeatureCollection"
    assert {feature["properties"]["feature_type"] for feature in payload["features"]} >= {
        "walking-attractor",
        "core-walking-zone",
        "walking-route",
    }
    manifest_text = (first / "walking-manifest.json").read_text().lower()
    assert "cycling_geometry" not in manifest_text
    assert "satn" not in manifest_text
    implementation = (PROJECT / "src" / "lcwip" / "walking.py").read_text()
    assert "from lcwip.demand" not in implementation
    assert "from satn" not in implementation


def test_rural_service_access_fixture_keeps_selection_logic_and_uncertainty(
    tmp_path: Path,
) -> None:
    manifest = validate_walking_bundle(build_fixture(tmp_path, rural=True))
    assert manifest.zones[0].zone_id == "chew-magna-cwz"
    assert manifest.routes[0].kind is WalkingRouteKind.FUNNEL
    assert "service-access" in manifest.routes[0].selection_logic
    assert manifest.attractors[1].uncertainties
    assert manifest.zones[0].uncertainties


def test_missing_mandatory_site_evidence_creates_requests_and_blocks_full_audit(
    tmp_path: Path,
) -> None:
    manifest = validate_walking_bundle(build_fixture(tmp_path))
    assert manifest.evidence_requests
    seating_requests = [
        request
        for request in manifest.evidence_requests
        if request.item is AuditItem.SEATING_REST
    ]
    assert seating_requests
    assert all(
        audit.status is WalkingAuditStatus.EVIDENCE_INCOMPLETE
        for audit in manifest.audits
        if audit.subject_id in {request.subject_id for request in seating_requests}
    )
    assert all(request.required_source == "site-survey" for request in seating_requests)


def test_audits_preserve_modelled_and_unknown_conditions_without_conflation(
    tmp_path: Path,
) -> None:
    evidence = walking_evidence_snapshot(tmp_path)
    supplied = []
    removed = False
    modelled = False
    for observation in observations():
        if (
            not removed
            and observation.subject_id == "bath-interchange-key-route"
            and observation.item is AuditItem.SEVERANCE
        ):
            removed = True
            continue
        if not modelled and observation.item is AuditItem.GRADIENT:
            observation = observation.model_copy(
                update={
                    "provenance": AuditProvenance.MODELLED,
                    "evidence_mode": AuditEvidenceMode.DESKTOP,
                    "evidence_ids": ("modelled-evidence",),
                    "site_surveyed_on": None,
                }
            )
            modelled = True
        supplied.append(observation)
    bundle = build_walking_plan(
        config(tmp_path / "output", evidence_snapshot=evidence),
        attractors=attractors(),
        catchments=(catchment(),),
        zones=(zone(),),
        route_specifications=route_specs(),
        audit_observations=tuple(supplied),
        lived_experience_findings=lived_experience(),
        routing_boundary=FixtureWalkingRouter(),
    )
    manifest = validate_walking_bundle(bundle)
    all_observations = [
        observation
        for audit in manifest.audits
        for observation in audit.observations
    ]
    assert any(
        observation.provenance is AuditProvenance.MODELLED
        for observation in all_observations
    )
    unknown = next(
        observation
        for observation in all_observations
        if observation.subject_id == "bath-interchange-key-route"
        and observation.item is AuditItem.SEVERANCE
    )
    assert unknown.condition is AuditCondition.UNKNOWN
    assert unknown.provenance is AuditProvenance.UNKNOWN
    assert unknown.evidence_mode is AuditEvidenceMode.NONE
    assert any(
        request.subject_id == unknown.subject_id
        and request.item is unknown.item
        and request.required_source == "governed-evidence"
        for request in manifest.evidence_requests
    )


def test_complete_site_evidence_still_requires_accountable_human_gate(
    tmp_path: Path,
) -> None:
    without_gate = validate_walking_bundle(
        build_fixture(tmp_path / "pending", complete_site=True)
    )
    assert all(
        audit.status is WalkingAuditStatus.HUMAN_REVIEW_REQUIRED
        for audit in without_gate.audits
    )
    assert without_gate.human_gate_status == "pending"

    with_gate = validate_walking_bundle(
        build_fixture(
            tmp_path / "verified",
            complete_site=True,
            gate=review_gate(),
        )
    )
    assert all(
        audit.status is WalkingAuditStatus.FULLY_AUDITED
        for audit in with_gate.audits
    )
    assert with_gate.human_gate_status == "verified"


def test_wheelchair_continuity_and_severance_are_explicit_intervention_inputs(
    tmp_path: Path,
) -> None:
    manifest = validate_walking_bundle(
        build_fixture(
            tmp_path,
            complete_site=True,
            deficient_continuity=True,
            gate=review_gate(),
        )
    )
    deficiencies = [
        item
        for item in manifest.deficiencies
        if item.item is AuditItem.FOOTWAY_CONTINUITY
    ]
    assert deficiencies
    assert all(AccessibilityNeed.WHEELCHAIR in item.accessibility_needs for item in deficiencies)
    assert all(AccessibilityNeed.MOBILITY_AID in item.accessibility_needs for item in deficiencies)
    assert all(item.feeds_intervention for item in deficiencies)
    assert any(
        observation.item is AuditItem.SEVERANCE
        for audit in manifest.audits
        for observation in audit.observations
    )


def test_lived_experience_is_typed_privacy_safe_and_requires_stakeholder_evidence(
    tmp_path: Path,
) -> None:
    manifest = validate_walking_bundle(build_fixture(tmp_path))
    assert manifest.lived_experience_findings[0].personal_data == "removed"
    engagement = json.loads(
        (
            tmp_path
            / "output"
            / "banes-walking-plan"
            / "engagement-input.json"
        ).read_text()
    )
    assert "Private person" not in json.dumps(engagement)
    assert engagement["findings"][0]["finding_id"] == "panel-resting-finding"

    with pytest.raises(ValidationError):
        LivedExperienceFinding(
            finding_id="unsafe",
            subject_id="bath-centre-cwz",
            theme="crossing",
            summary="Contains prohibited identity field through extra data.",
            accessibility_needs=(AccessibilityNeed.WHEELCHAIR,),
            evidence_ids=("panel-evidence",),
            material=True,
            personal_data="removed",
            person_name="Must not serialize",
        )

    evidence = walking_evidence_snapshot(tmp_path / "invalid-role")
    invalid_finding = lived_experience()[0].model_copy(
        update={"evidence_ids": ("site-evidence",)}
    )
    with pytest.raises(ValueError, match="stakeholder evidence"):
        build_walking_plan(
            config(tmp_path / "invalid-output", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=observations(),
            lived_experience_findings=(invalid_finding,),
            routing_boundary=FixtureWalkingRouter(),
        )

    invalid_audit = tuple(
        observation.model_copy(
            update={
                "evidence_mode": AuditEvidenceMode.LIVED_EXPERIENCE,
                "evidence_ids": ("site-evidence",),
            }
        )
        if observation.item is AuditItem.WAYFINDING
        else observation
        for observation in observations()
    )
    with pytest.raises(ValueError, match="stakeholder evidence"):
        build_walking_plan(
            config(tmp_path / "invalid-audit-output", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=invalid_audit,
            lived_experience_findings=lived_experience(),
            routing_boundary=FixtureWalkingRouter(),
        )


def test_personal_safety_cannot_be_claimed_from_desktop_or_modelled_evidence(
    tmp_path: Path,
) -> None:
    evidence = walking_evidence_snapshot(tmp_path)
    unsafe = tuple(
        observation.model_copy(
            update={
                "provenance": AuditProvenance.INFERRED,
                "evidence_mode": AuditEvidenceMode.DESKTOP,
                "site_surveyed_on": None,
            }
        )
        if observation.item is AuditItem.LIGHTING_PERSONAL_SAFETY
        else observation
        for observation in observations(complete_site=True)
    )
    with pytest.raises(ValueError, match="personal-safety condition"):
        build_walking_plan(
            config(tmp_path / "output", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=unsafe,
            lived_experience_findings=lived_experience(),
            routing_boundary=FixtureWalkingRouter(),
        )


def test_route_geometry_and_zone_catchment_contracts_are_enforced(tmp_path: Path) -> None:
    evidence = walking_evidence_snapshot(tmp_path)

    class DetachedRouter(FixtureWalkingRouter):
        def route(self, request: WalkingRouteRequest) -> WalkingRoutePath:
            return super().route(request).model_copy(
                update={"coordinates": ((-1.0, 50.0), (-1.1, 50.1))}
            )

    with pytest.raises(ValueError, match="endpoint offset"):
        build_walking_plan(
            config(tmp_path / "detached", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=observations(),
            lived_experience_findings=lived_experience(),
            routing_boundary=DetachedRouter(),
        )

    invalid_zone = zone().model_copy(
        update={"selected_attractor_ids": ("not-in-catchment",)}
    )
    with pytest.raises(ValueError, match="catchment"):
        build_walking_plan(
            config(tmp_path / "invalid-zone", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(invalid_zone,),
            route_specifications=route_specs(),
            audit_observations=observations(),
            lived_experience_findings=lived_experience(),
            routing_boundary=FixtureWalkingRouter(),
        )


def test_existing_bundle_rejects_changed_routing_under_the_same_boundary_version(
    tmp_path: Path,
) -> None:
    evidence = walking_evidence_snapshot(tmp_path)
    analysis_config = config(tmp_path / "output", evidence_snapshot=evidence)
    arguments = {
        "attractors": attractors(),
        "catchments": (catchment(),),
        "zones": (zone(),),
        "route_specifications": route_specs(),
        "audit_observations": observations(),
        "lived_experience_findings": lived_experience(),
    }
    build_walking_plan(
        analysis_config,
        **arguments,
        routing_boundary=FixtureWalkingRouter(),
    )

    class ChangedRouter(FixtureWalkingRouter):
        def route(self, request: WalkingRouteRequest) -> WalkingRoutePath:
            path = super().route(request)
            changed_midpoint = (
                path.coordinates[1][0],
                round(path.coordinates[1][1] + 0.0003, 6),
            )
            return path.model_copy(
                update={
                    "coordinates": (
                        path.coordinates[0],
                        changed_midpoint,
                        path.coordinates[-1],
                    )
                }
            )

    with pytest.raises(ValueError, match="not reproducible"):
        build_walking_plan(
            analysis_config,
            **arguments,
            routing_boundary=ChangedRouter(),
        )


def test_audit_observations_have_one_provenance_and_no_duplicate_subject_item(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="site_surveyed_on"):
        WalkingAuditObservation(
            observation_id="invalid-site-date",
            subject_id="bath-centre-cwz",
            item=AuditItem.SEVERANCE,
            condition=AuditCondition.COMPLIANT,
            provenance=AuditProvenance.OBSERVED,
            evidence_mode=AuditEvidenceMode.SITE_SURVEY,
            evidence_ids=("site-evidence",),
            rationale="Missing survey date.",
        )

    evidence = walking_evidence_snapshot(tmp_path)
    duplicate = observations()[0].model_copy(
        update={"observation_id": "duplicate-observation"}
    )
    with pytest.raises(ValueError, match="one observation per subject and audit item"):
        build_walking_plan(
            config(tmp_path / "duplicate", evidence_snapshot=evidence),
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=(*observations(), duplicate),
            lived_experience_findings=lived_experience(),
            routing_boundary=FixtureWalkingRouter(),
        )


def test_bundle_integrity_cli_and_workflow_links_are_cross_validated(
    tmp_path: Path,
) -> None:
    bundle = build_fixture(tmp_path)
    manifest = validate_walking_bundle(bundle)
    assert {item.kind for item in manifest.conformance_artifacts} == {
        "engagement",
        "intervention-input",
        "walking-network-plan",
        "walking-route-area-audit",
    }
    assert load_walking_conformance_artifacts(bundle) == manifest.conformance_artifacts
    result = CliRunner().invoke(app, ["walking", "validate", str(bundle)])
    assert result.exit_code == 0, result.output
    assert manifest.analysis_fingerprint in result.output

    audit_path = bundle / "walking-audits.json"
    audit_path.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="content hash"):
        validate_walking_bundle(bundle)


def test_guidance_profile_and_human_gate_cannot_be_detached_from_outputs(
    tmp_path: Path,
) -> None:
    evidence = walking_evidence_snapshot(tmp_path)
    invalid_profile = config(
        tmp_path / "profile",
        evidence_snapshot=evidence,
    ).model_copy(update={"guidance_profile_fingerprint": "0" * 64})
    with pytest.raises(ValidationError, match="Guidance Profile fingerprint"):
        build_walking_plan(
            invalid_profile,
            attractors=attractors(),
            catchments=(catchment(),),
            zones=(zone(),),
            route_specifications=route_specs(),
            audit_observations=observations(),
            lived_experience_findings=lived_experience(),
            routing_boundary=FixtureWalkingRouter(),
        )

    incomplete_gate = review_gate().model_copy(
        update={"verified_lived_experience_ids": ()}
    )
    with pytest.raises(ValueError, match="material lived-experience"):
        build_fixture(
            tmp_path / "gate",
            complete_site=True,
            gate=incomplete_gate,
        )

    valid_bundle = build_fixture(
        tmp_path / "valid-gate",
        complete_site=True,
        gate=review_gate(),
    )
    payload = validate_walking_bundle(valid_bundle).model_dump()
    payload["review_gate"] = review_gate().model_copy(
        update={"verified_lived_experience_ids": ()}
    ).model_dump()
    with pytest.raises(
        ValidationError,
        match="manifest human gate must verify material lived-experience findings",
    ):
        WalkingPlanningManifest.model_validate(payload)


@pytest.mark.browser
def test_walking_review_map_is_spatial_tabular_and_exposes_audit_limits(
    tmp_path: Path,
) -> None:
    bundle = build_fixture(tmp_path)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto((bundle / "review-map.html").as_uri())
        assert page.get_by_role("heading", name="Walking and wheeling review map").is_visible()
        assert page.locator("svg [data-feature-id='bath-centre-cwz']").is_visible()
        assert page.locator("svg [data-feature-id='bath-interchange-key-route']").is_visible()
        assert page.get_by_role("table", name="Walking and wheeling audit table").is_visible()
        assert page.get_by_text("Site evidence request", exact=False).count() > 0
        assert page.get_by_text("not cycling geometry", exact=False).is_visible()
        browser.close()
