"""Independent walking and wheeling network planning for LCWIP.

The pass consumes governed evidence and walking-specific spatial inputs. It
does not import cycling or SATN geometry and cannot use either as a proxy for
footway, crossing, accessibility or lived-experience conditions.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import shutil
import tempfile
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lcwip.evidence import (
    AccessLevel,
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSnapshotManifest,
    PublicDisposition,
    validate_evidence_snapshot,
)
from lcwip.models import ArtifactLink, GuidanceProfile

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StableIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
]
Coordinate = tuple[
    Annotated[float, Field(ge=-180, le=180)],
    Annotated[float, Field(ge=-90, le=90)],
]


class WalkingContract(BaseModel):
    """Closed immutable contract for walking-planning boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0"] = "1.0"


class WalkingAttractorKind(StrEnum):
    LOCAL_CENTRE = "local-centre"
    INTERCHANGE = "interchange"
    SCHOOL = "school"
    SERVICE = "service"
    DEVELOPMENT = "development"
    EMPLOYMENT = "employment"


class WalkingRouteKind(StrEnum):
    KEY = "key-route"
    FUNNEL = "funnel-route"


class AuditSubjectKind(StrEnum):
    ZONE = "zone"
    ROUTE = "route"


class AuditItem(StrEnum):
    FOOTWAY_CONTINUITY = "footway-continuity"
    FOOTWAY_WIDTH = "footway-width"
    SURFACE = "surface"
    CROSSINGS = "crossings"
    GRADIENT = "gradient"
    SEVERANCE = "severance"
    LIGHTING_PERSONAL_SAFETY = "lighting-personal-safety"
    SEATING_REST = "seating-rest"
    WAYFINDING = "wayfinding"


class AuditCondition(StrEnum):
    COMPLIANT = "compliant"
    DEFICIENT = "deficient"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


class AuditProvenance(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    MODELLED = "modelled"
    UNKNOWN = "unknown"


class AuditEvidenceMode(StrEnum):
    DESKTOP = "desktop"
    SITE_SURVEY = "site-survey"
    LIVED_EXPERIENCE = "lived-experience"
    NONE = "none"


class AccessibilityNeed(StrEnum):
    WHEELCHAIR = "wheelchair"
    MOBILITY_AID = "mobility-aid"
    VISUAL = "visual"
    HEARING = "hearing"
    COGNITIVE_NEURODIVERGENT = "cognitive-neurodivergent"
    RESTING = "resting"
    PERSONAL_SAFETY = "personal-safety"


class WalkingAuditStatus(StrEnum):
    FULLY_AUDITED = "fully-audited"
    EVIDENCE_INCOMPLETE = "evidence-incomplete"
    HUMAN_REVIEW_REQUIRED = "human-review-required"


class WalkingAttractor(WalkingContract):
    attractor_id: StableIdentifier
    name: NonBlankText
    kind: WalkingAttractorKind
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    inside_study_area: bool
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    uncertainties: tuple[NonBlankText, ...] = ()

    @field_validator("evidence_ids", "uncertainties")
    @classmethod
    def canonical_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking-attractor values")


class WalkingCatchment(WalkingContract):
    catchment_id: StableIdentifier
    centre_attractor_id: StableIdentifier
    radius_m: float = Field(gt=0)
    method: NonBlankText
    selection_logic: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    uncertainties: tuple[NonBlankText, ...] = Field(min_length=1)

    @field_validator("evidence_ids", "uncertainties")
    @classmethod
    def canonical_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking-catchment values")


class WalkingCatchmentRecord(WalkingCatchment):
    inside_attractor_ids: tuple[StableIdentifier, ...]
    outside_attractor_ids: tuple[StableIdentifier, ...]

    @field_validator("inside_attractor_ids", "outside_attractor_ids")
    @classmethod
    def canonical_membership(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking catchment membership")


class CoreWalkingZoneProposal(WalkingContract):
    zone_id: StableIdentifier
    name: NonBlankText
    catchment_id: StableIdentifier
    coordinates: tuple[Coordinate, ...] = Field(min_length=4)
    selected_attractor_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    selection_rationale: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    uncertainties: tuple[NonBlankText, ...] = Field(min_length=1)

    @field_validator(
        "selected_attractor_ids",
        "evidence_ids",
        "uncertainties",
    )
    @classmethod
    def canonical_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "Core Walking Zone values")

    @model_validator(mode="after")
    def closed_polygon(self) -> Self:
        if self.coordinates[0] != self.coordinates[-1]:
            raise ValueError("Core Walking Zone polygon must be closed")
        if len(set(self.coordinates[:-1])) < 3 or _polygon_area(self.coordinates) == 0:
            raise ValueError("Core Walking Zone polygon must have non-zero area")
        return self


class WalkingRouteSpecification(WalkingContract):
    route_id: StableIdentifier
    zone_id: StableIdentifier
    kind: WalkingRouteKind
    origin_attractor_id: StableIdentifier
    destination_attractor_id: StableIdentifier
    selection_logic: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    uncertainties: tuple[NonBlankText, ...] = Field(min_length=1)

    @field_validator("evidence_ids", "uncertainties")
    @classmethod
    def canonical_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking-route values")

    @model_validator(mode="after")
    def distinct_endpoints(self) -> Self:
        if self.origin_attractor_id == self.destination_attractor_id:
            raise ValueError("a walking route requires distinct attractors")
        return self


class WalkingRoutePath(WalkingContract):
    route_id: StableIdentifier
    coordinates: tuple[Coordinate, ...] = Field(min_length=2)
    length_km: float = Field(gt=0)
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking-route evidence IDs")


class WalkingRouteRecord(WalkingRouteSpecification):
    coordinates: tuple[Coordinate, ...] = Field(min_length=2)
    length_km: float = Field(gt=0)
    path_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    routing_boundary_id: StableIdentifier
    routing_boundary_version: NonBlankText

    @field_validator("path_evidence_ids")
    @classmethod
    def canonical_path_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking route path evidence IDs")


class WalkingRouteRequest(WalkingContract):
    specification: WalkingRouteSpecification
    origin: WalkingAttractor
    destination: WalkingAttractor
    maximum_endpoint_offset_m: float = Field(ge=0)


class WalkingRoutingBoundary(Protocol):
    boundary_id: str
    boundary_version: str

    def route(self, request: WalkingRouteRequest) -> WalkingRoutePath: ...


class WalkingAuditRequirement(WalkingContract):
    item: AuditItem
    applies_to: tuple[AuditSubjectKind, ...] = Field(min_length=1)
    mandatory: bool
    site_evidence_required: bool
    accessibility_needs: tuple[AccessibilityNeed, ...] = ()

    @field_validator("applies_to", "accessibility_needs")
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(value) != len(set(value)):
            raise ValueError("walking audit requirement values must be unique")
        return tuple(sorted(value))


class WalkingAuditProfile(WalkingContract):
    profile_id: StableIdentifier
    guidance_profile_id: StableIdentifier
    version: NonBlankText
    requirements: tuple[WalkingAuditRequirement, ...] = Field(min_length=1)

    @field_validator("requirements")
    @classmethod
    def complete_unique_items(
        cls,
        value: tuple[WalkingAuditRequirement, ...],
    ) -> tuple[WalkingAuditRequirement, ...]:
        items = tuple(requirement.item for requirement in value)
        if len(items) != len(set(items)):
            raise ValueError("walking audit item requirements must be unique")
        if set(items) != set(AuditItem):
            raise ValueError("walking audit profile must cover every governed audit item")
        by_item = {requirement.item: requirement for requirement in value}
        continuity = by_item[AuditItem.FOOTWAY_CONTINUITY]
        if not {
            AccessibilityNeed.WHEELCHAIR,
            AccessibilityNeed.MOBILITY_AID,
        }.issubset(continuity.accessibility_needs):
            raise ValueError(
                "footway continuity must explicitly cover wheelchair and "
                "mobility-aid needs"
            )
        personal_safety = by_item[AuditItem.LIGHTING_PERSONAL_SAFETY]
        if (
            not personal_safety.site_evidence_required
            or AccessibilityNeed.PERSONAL_SAFETY
            not in personal_safety.accessibility_needs
        ):
            raise ValueError(
                "lighting and personal safety requires site evidence and an "
                "explicit accessibility need"
            )
        return tuple(by_item[item] for item in AuditItem)


class WalkingAuditObservation(WalkingContract):
    observation_id: StableIdentifier
    subject_id: StableIdentifier
    item: AuditItem
    condition: AuditCondition
    provenance: AuditProvenance
    evidence_mode: AuditEvidenceMode
    evidence_ids: tuple[StableIdentifier, ...] = ()
    rationale: NonBlankText
    accessibility_needs: tuple[AccessibilityNeed, ...] = ()
    site_surveyed_on: date | None = None

    @field_validator("evidence_ids", "accessibility_needs")
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(value) != len(set(value)):
            raise ValueError("walking audit observation values must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def evidence_state_is_coherent(self) -> Self:
        if self.evidence_mode is AuditEvidenceMode.SITE_SURVEY:
            if self.site_surveyed_on is None:
                raise ValueError("site_surveyed_on is required for site-survey evidence")
            if self.provenance is not AuditProvenance.OBSERVED:
                raise ValueError("site-survey conditions must use observed provenance")
        elif self.site_surveyed_on is not None:
            raise ValueError("site_surveyed_on is only valid for site-survey evidence")
        if self.condition is AuditCondition.UNKNOWN:
            if self.provenance is not AuditProvenance.UNKNOWN:
                raise ValueError("unknown conditions must use unknown provenance")
        elif self.provenance is AuditProvenance.UNKNOWN:
            raise ValueError("known conditions cannot use unknown provenance")
        if (
            self.condition
            not in {AuditCondition.UNKNOWN, AuditCondition.NOT_APPLICABLE}
            and not self.evidence_ids
        ):
            raise ValueError("known audit conditions require governed evidence")
        if (
            self.evidence_mode is AuditEvidenceMode.NONE
            and self.condition is not AuditCondition.UNKNOWN
        ):
            raise ValueError("no-evidence audit mode is only valid for unknown conditions")
        return self


class LivedExperienceFinding(WalkingContract):
    finding_id: StableIdentifier
    subject_id: StableIdentifier
    theme: StableIdentifier
    summary: NonBlankText
    accessibility_needs: tuple[AccessibilityNeed, ...] = Field(min_length=1)
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    material: bool
    personal_data: Literal["removed"]

    @field_validator("accessibility_needs", "evidence_ids")
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(value) != len(set(value)):
            raise ValueError("lived-experience finding values must be unique")
        return tuple(sorted(value))


class WalkingReviewGate(WalkingContract):
    gate_id: StableIdentifier
    officer_name: NonBlankText
    accessibility_representative: NonBlankText
    verified_zone_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    verified_audit_limitation_ids: tuple[StableIdentifier, ...] = ()
    verified_lived_experience_ids: tuple[StableIdentifier, ...] = ()
    rationale: NonBlankText

    @field_validator(
        "verified_zone_ids",
        "verified_audit_limitation_ids",
        "verified_lived_experience_ids",
    )
    @classmethod
    def canonical_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "walking human-gate values")


class WalkingPlanningConfig(WalkingContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot: Path
    output_dir: Path
    transformation_version: NonBlankText
    maximum_route_endpoint_offset_m: float = Field(ge=0)
    audit_profile: WalkingAuditProfile
    review_gate: WalkingReviewGate | None = None

    @model_validator(mode="after")
    def profile_binding(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("Guidance Profile ID does not match the embedded profile")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError(
                "Guidance Profile fingerprint does not match the embedded profile"
            )
        if self.audit_profile.guidance_profile_id != self.guidance_profile_id:
            raise ValueError(
                "walking audit profile must match the active Guidance Profile"
            )
        requirement = next(
            (
                item
                for item in self.guidance_profile.requirements
                if item.requirement_id == "dft-2017.walking-network-planning"
            ),
            None,
        )
        if requirement is None or "walking-network-plan" not in requirement.expected_artifacts:
            raise ValueError(
                "Guidance Profile does not define the walking-network-plan artifact"
            )
        return self


class WalkingEvidenceRequest(WalkingContract):
    request_id: StableIdentifier
    subject_id: StableIdentifier
    item: AuditItem
    purpose: NonBlankText
    required_source: Literal["site-survey", "governed-evidence"]
    accessibility_needs: tuple[AccessibilityNeed, ...] = ()

    @field_validator("accessibility_needs")
    @classmethod
    def canonical_needs(
        cls, value: tuple[AccessibilityNeed, ...]
    ) -> tuple[AccessibilityNeed, ...]:
        return _canonical_unique(value, "walking evidence-request accessibility needs")


class WalkingAuditRecord(WalkingContract):
    subject_id: StableIdentifier
    subject_kind: AuditSubjectKind
    observations: tuple[WalkingAuditObservation, ...]
    status: WalkingAuditStatus
    evidence_request_ids: tuple[StableIdentifier, ...] = ()
    explicit_unknown_items: tuple[AuditItem, ...] = ()

    @field_validator("evidence_request_ids", "explicit_unknown_items")
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return _canonical_unique(value, "walking audit record values")

    @model_validator(mode="after")
    def observations_match_subject(self) -> Self:
        items = tuple(observation.item for observation in self.observations)
        if len(items) != len(set(items)):
            raise ValueError("walking audit observations must contain unique items")
        if any(
            observation.subject_id != self.subject_id
            for observation in self.observations
        ):
            raise ValueError("walking audit observations must match their subject")
        if (
            self.status is WalkingAuditStatus.FULLY_AUDITED
            and self.evidence_request_ids
        ):
            raise ValueError("a fully audited subject cannot retain evidence requests")
        return self


class WalkingDeficiency(WalkingContract):
    deficiency_id: StableIdentifier
    subject_id: StableIdentifier
    item: AuditItem
    condition: AuditCondition
    description: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = ()
    evidence_request_ids: tuple[StableIdentifier, ...] = ()
    accessibility_needs: tuple[AccessibilityNeed, ...] = ()
    feeds_intervention: Literal[True] = True

    @field_validator(
        "evidence_ids",
        "evidence_request_ids",
        "accessibility_needs",
    )
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return _canonical_unique(value, "walking deficiency values")


class WalkingBundleArtifact(WalkingContract):
    path: NonBlankText
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("walking bundle artifact paths must stay inside the bundle")
        return value


WALKING_ARTIFACT_PATHS = (
    "conformance-artifacts.json",
    "engagement-input.json",
    "review-map.html",
    "walking-audits.json",
    "walking-deficiencies.json",
    "walking-evidence-requests.json",
    "walking-network.geojson",
)


class WalkingPlanningManifest(WalkingContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot_id: StableIdentifier
    evidence_snapshot_fingerprint: Sha256Hex
    transformation_version: NonBlankText
    routing_boundary_id: StableIdentifier
    routing_boundary_version: NonBlankText
    maximum_route_endpoint_offset_m: float = Field(ge=0)
    audit_profile: WalkingAuditProfile
    review_gate: WalkingReviewGate | None
    human_gate_status: Literal["pending", "verified"]
    input_fingerprint: Sha256Hex
    attractors: tuple[WalkingAttractor, ...]
    catchments: tuple[WalkingCatchmentRecord, ...]
    zones: tuple[CoreWalkingZoneProposal, ...]
    routes: tuple[WalkingRouteRecord, ...]
    audits: tuple[WalkingAuditRecord, ...]
    evidence_requests: tuple[WalkingEvidenceRequest, ...]
    deficiencies: tuple[WalkingDeficiency, ...]
    lived_experience_findings: tuple[LivedExperienceFinding, ...]
    conformance_artifacts: tuple[ArtifactLink, ...]
    artifacts: tuple[WalkingBundleArtifact, ...]
    analysis_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def relational_integrity(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("manifest Guidance Profile ID does not match")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("manifest Guidance Profile fingerprint does not match")
        if self.audit_profile.guidance_profile_id != self.guidance_profile_id:
            raise ValueError("manifest walking audit profile does not match")
        attractor_ids = _unique_ids(
            self.attractors, "attractor_id", "walking attractor"
        )
        catchment_ids = _unique_ids(
            self.catchments, "catchment_id", "walking catchment"
        )
        zone_ids = _unique_ids(self.zones, "zone_id", "Core Walking Zone")
        route_ids = _unique_ids(self.routes, "route_id", "walking route")
        subject_ids = zone_ids | route_ids
        _unique_ids(self.audits, "subject_id", "walking audit")
        request_ids = _unique_ids(
            self.evidence_requests, "request_id", "walking evidence request"
        )
        _unique_ids(self.deficiencies, "deficiency_id", "walking deficiency")
        _unique_ids(
            self.lived_experience_findings,
            "finding_id",
            "lived-experience finding",
        )
        _unique_ids(self.artifacts, "path", "walking bundle artifact")
        for catchment in self.catchments:
            if catchment.centre_attractor_id not in attractor_ids:
                raise ValueError("walking catchment centre must resolve")
            if set(catchment.inside_attractor_ids) | set(
                catchment.outside_attractor_ids
            ) != attractor_ids:
                raise ValueError("walking catchment membership must cover all attractors")
            if set(catchment.inside_attractor_ids) & set(
                catchment.outside_attractor_ids
            ):
                raise ValueError("walking catchment membership cannot overlap")
        for zone in self.zones:
            if zone.catchment_id not in catchment_ids:
                raise ValueError("Core Walking Zone catchment must resolve")
            catchment = next(
                item for item in self.catchments if item.catchment_id == zone.catchment_id
            )
            if not set(zone.selected_attractor_ids).issubset(
                catchment.inside_attractor_ids
            ):
                raise ValueError("Core Walking Zone attractors must resolve to its catchment")
        for route in self.routes:
            if route.zone_id not in zone_ids:
                raise ValueError("walking route zone must resolve")
            if (
                route.origin_attractor_id not in attractor_ids
                or route.destination_attractor_id not in attractor_ids
            ):
                raise ValueError("walking route attractors must resolve")
        if {audit.subject_id for audit in self.audits} != subject_ids:
            raise ValueError("walking audits must cover every zone and route")
        expected_items = {
            subject_kind: {
                requirement.item
                for requirement in self.audit_profile.requirements
                if subject_kind in requirement.applies_to
            }
            for subject_kind in AuditSubjectKind
        }
        referenced_request_ids: set[str] = set()
        for audit in self.audits:
            if {item.item for item in audit.observations} != expected_items[
                audit.subject_kind
            ]:
                raise ValueError(
                    "walking audit must contain every applicable profile item"
                )
            for request_id in audit.evidence_request_ids:
                if request_id not in request_ids:
                    raise ValueError("walking audit evidence request must resolve")
                referenced_request_ids.add(request_id)
            expected_status = (
                WalkingAuditStatus.EVIDENCE_INCOMPLETE
                if audit.evidence_request_ids
                else (
                    WalkingAuditStatus.FULLY_AUDITED
                    if self.human_gate_status == "verified"
                    else WalkingAuditStatus.HUMAN_REVIEW_REQUIRED
                )
            )
            if audit.status is not expected_status:
                raise ValueError(
                    "walking audit status does not match evidence and human review"
                )
        if referenced_request_ids != request_ids:
            raise ValueError("every walking evidence request must belong to an audit")
        for request in self.evidence_requests:
            if request.subject_id not in subject_ids:
                raise ValueError("walking evidence request subject must resolve")
            audit = next(
                item for item in self.audits if item.subject_id == request.subject_id
            )
            if request.item not in {item.item for item in audit.observations}:
                raise ValueError("walking evidence request item must resolve")
        deficiency_keys = {
            (deficiency.subject_id, deficiency.item)
            for deficiency in self.deficiencies
        }
        if len(deficiency_keys) != len(self.deficiencies):
            raise ValueError("walking deficiencies must be unique by subject and item")
        for deficiency in self.deficiencies:
            if deficiency.subject_id not in subject_ids:
                raise ValueError("walking deficiency subject must resolve")
            if not set(deficiency.evidence_request_ids).issubset(request_ids):
                raise ValueError("walking deficiency evidence requests must resolve")
        for finding in self.lived_experience_findings:
            if finding.subject_id not in subject_ids:
                raise ValueError("lived-experience finding subject must resolve")
        if (self.review_gate is None) != (self.human_gate_status == "pending"):
            raise ValueError("walking human-gate status does not match its record")
        if self.review_gate is not None:
            if set(self.review_gate.verified_zone_ids) != zone_ids:
                raise ValueError("manifest human gate must verify every walking zone")
            if (
                set(self.review_gate.verified_audit_limitation_ids)
                != request_ids
            ):
                raise ValueError(
                    "manifest human gate must verify every audit limitation"
                )
            material_ids = {
                finding.finding_id
                for finding in self.lived_experience_findings
                if finding.material
            }
            if (
                set(self.review_gate.verified_lived_experience_ids)
                != material_ids
            ):
                raise ValueError(
                    "manifest human gate must verify material lived-experience findings"
                )
        if {item.kind for item in self.conformance_artifacts} != {
            "engagement",
            "intervention-input",
            "walking-network-plan",
            "walking-route-area-audit",
        }:
            raise ValueError("walking workflow artifact links are incomplete")
        if {item.path for item in self.artifacts} != set(WALKING_ARTIFACT_PATHS):
            raise ValueError("walking bundle artifact set is incomplete")
        return self

    @model_validator(mode="after")
    def fingerprint_matches(self) -> Self:
        expected = _fingerprint(
            self.model_dump(mode="json", exclude={"analysis_fingerprint"})
        )
        if self.analysis_fingerprint != expected:
            raise ValueError("walking analysis fingerprint does not match its contents")
        return self


def build_walking_plan(
    config: WalkingPlanningConfig,
    *,
    attractors: Iterable[WalkingAttractor],
    catchments: Iterable[WalkingCatchment],
    zones: Iterable[CoreWalkingZoneProposal],
    route_specifications: Iterable[WalkingRouteSpecification],
    audit_observations: Iterable[WalkingAuditObservation],
    lived_experience_findings: Iterable[LivedExperienceFinding],
    routing_boundary: WalkingRoutingBoundary,
) -> Path:
    """Build one deterministic immutable walking/wheeling review bundle."""
    config = WalkingPlanningConfig.model_validate(config.model_dump())
    evidence = validate_evidence_snapshot(config.evidence_snapshot)
    _validate_scope(config, evidence)
    canonical_attractors = _canonical_records(
        attractors, WalkingAttractor, "attractor_id", "walking attractor"
    )
    canonical_catchments = _canonical_records(
        catchments, WalkingCatchment, "catchment_id", "walking catchment"
    )
    canonical_zones = _canonical_records(
        zones, CoreWalkingZoneProposal, "zone_id", "Core Walking Zone"
    )
    canonical_specs = _canonical_records(
        route_specifications,
        WalkingRouteSpecification,
        "route_id",
        "walking route",
    )
    canonical_observations = _canonical_records(
        audit_observations,
        WalkingAuditObservation,
        "observation_id",
        "walking audit observation",
    )
    canonical_lived = _canonical_records(
        lived_experience_findings,
        LivedExperienceFinding,
        "finding_id",
        "lived-experience finding",
    )
    governed_evidence = {
        item.evidence_id: item
        for item in evidence.items
        if item.availability is EvidenceAvailability.AVAILABLE
        and item.public_disposition is not PublicDisposition.EXCLUDE
        and item.access_level is not AccessLevel.PERSONAL
    }
    _validate_references(
        canonical_attractors,
        canonical_catchments,
        canonical_zones,
        canonical_specs,
        canonical_observations,
        canonical_lived,
        governed_evidence,
    )
    catchment_records = _derive_catchments(
        canonical_attractors, canonical_catchments
    )
    _validate_zones(canonical_zones, catchment_records, canonical_attractors)
    boundary_id = _stable_boundary_identifier(routing_boundary.boundary_id)
    boundary_version = _nonblank_boundary_value(
        routing_boundary.boundary_version, "walking routing boundary version"
    )
    routes = _route_walking_network(
        canonical_specs,
        canonical_attractors,
        canonical_zones,
        config,
        routing_boundary,
        boundary_id,
        boundary_version,
        governed_evidence,
    )
    (
        audits,
        evidence_requests,
        deficiencies,
    ) = _compile_audits(
        canonical_zones,
        routes,
        canonical_observations,
        config.audit_profile,
        governed_evidence,
    )
    _validate_lived_experience(
        canonical_lived,
        {zone.zone_id for zone in canonical_zones}
        | {route.route_id for route in routes},
        governed_evidence,
    )
    human_gate_status = _validate_human_gate(
        config.review_gate,
        canonical_zones,
        evidence_requests,
        canonical_lived,
    )
    if human_gate_status == "verified":
        audits = tuple(
            audit.model_copy(
                update={
                    "status": (
                        WalkingAuditStatus.EVIDENCE_INCOMPLETE
                        if audit.evidence_request_ids
                        else WalkingAuditStatus.FULLY_AUDITED
                    )
                }
            )
            for audit in audits
        )
    conformance_artifacts = _conformance_artifacts(config.analysis_id)
    input_fingerprint = _fingerprint(
        {
            "analysis_id": config.analysis_id,
            "council_id": config.council_id,
            "guidance_profile": config.guidance_profile,
            "guidance_profile_id": config.guidance_profile_id,
            "guidance_profile_fingerprint": config.guidance_profile_fingerprint,
            "evidence_snapshot_fingerprint": evidence.snapshot_fingerprint,
            "transformation_version": config.transformation_version,
            "maximum_route_endpoint_offset_m": (
                config.maximum_route_endpoint_offset_m
            ),
            "audit_profile": config.audit_profile,
            "review_gate": config.review_gate,
            "routing_boundary_id": boundary_id,
            "routing_boundary_version": boundary_version,
            "attractors": canonical_attractors,
            "catchments": canonical_catchments,
            "zones": canonical_zones,
            "route_specifications": canonical_specs,
            "audit_observations": canonical_observations,
            "lived_experience_findings": canonical_lived,
        }
    )
    outputs = (
        catchment_records,
        routes,
        audits,
        evidence_requests,
        deficiencies,
        human_gate_status,
    )
    destination = config.output_dir / config.analysis_id
    if destination.exists():
        existing = validate_walking_bundle(destination)
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError(
                f"walking analysis {config.analysis_id!r} is immutable and inputs changed"
            )
        existing_outputs = (
            existing.catchments,
            existing.routes,
            existing.audits,
            existing.evidence_requests,
            existing.deficiencies,
            existing.human_gate_status,
        )
        if existing_outputs != outputs:
            raise ValueError(
                "walking routing boundary output is not reproducible under "
                "its declared version"
            )
        return destination
    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.analysis_id}-", dir=config.output_dir)
    )
    try:
        network_payload = _network_geojson(
            canonical_attractors,
            canonical_zones,
            routes,
            deficiencies,
        )
        audit_payload = {
            "audit_profile": config.audit_profile,
            "audits": audits,
            "review_gate": config.review_gate,
            "human_gate_status": human_gate_status,
        }
        request_payload = {"evidence_requests": evidence_requests}
        deficiency_payload = {"deficiencies": deficiencies}
        engagement_payload = {"findings": canonical_lived}
        conformance_payload = {"artifacts": conformance_artifacts}
        _write_json(temporary / "walking-network.geojson", network_payload)
        _write_json(temporary / "walking-audits.json", audit_payload)
        _write_json(temporary / "walking-evidence-requests.json", request_payload)
        _write_json(temporary / "walking-deficiencies.json", deficiency_payload)
        _write_json(temporary / "engagement-input.json", engagement_payload)
        _write_json(temporary / "conformance-artifacts.json", conformance_payload)
        (temporary / "review-map.html").write_text(
            _review_map_html(
                config.analysis_id,
                canonical_attractors,
                canonical_zones,
                routes,
                audits,
                evidence_requests,
            ),
            encoding="utf-8",
        )
        artifacts = tuple(
            WalkingBundleArtifact(
                path=path,
                sha256=hashlib.sha256((temporary / path).read_bytes()).hexdigest(),
            )
            for path in WALKING_ARTIFACT_PATHS
        )
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "analysis_id": config.analysis_id,
            "council_id": config.council_id,
            "guidance_profile": config.guidance_profile,
            "guidance_profile_id": config.guidance_profile_id,
            "guidance_profile_fingerprint": config.guidance_profile_fingerprint,
            "evidence_snapshot_id": evidence.snapshot_id,
            "evidence_snapshot_fingerprint": evidence.snapshot_fingerprint,
            "transformation_version": config.transformation_version,
            "routing_boundary_id": boundary_id,
            "routing_boundary_version": boundary_version,
            "maximum_route_endpoint_offset_m": (
                config.maximum_route_endpoint_offset_m
            ),
            "audit_profile": config.audit_profile,
            "review_gate": config.review_gate,
            "human_gate_status": human_gate_status,
            "input_fingerprint": input_fingerprint,
            "attractors": canonical_attractors,
            "catchments": catchment_records,
            "zones": canonical_zones,
            "routes": routes,
            "audits": audits,
            "evidence_requests": evidence_requests,
            "deficiencies": deficiencies,
            "lived_experience_findings": canonical_lived,
            "conformance_artifacts": conformance_artifacts,
            "artifacts": artifacts,
        }
        manifest = WalkingPlanningManifest(
            **payload,
            analysis_fingerprint=_fingerprint(payload),
        )
        _write_json(
            temporary / "walking-manifest.json",
            manifest.model_dump(mode="json"),
        )
        validate_walking_bundle(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_walking_bundle(path: Path) -> WalkingPlanningManifest:
    """Cross-validate a walking/wheeling bundle and its derived review files."""
    path = Path(path)
    manifest_path = path / "walking-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("invalid walking bundle: missing walking-manifest.json")
    try:
        manifest = WalkingPlanningManifest.model_validate_json(
            manifest_path.read_text()
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid walking bundle: {error}") from error
    expected_files = {"walking-manifest.json"}
    for artifact in manifest.artifacts:
        expected_files.add(artifact.path)
        artifact_path = path / artifact.path
        if not artifact_path.is_file():
            raise ValueError(f"invalid walking bundle: missing {artifact.path}")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact.sha256:
            raise ValueError(
                f"invalid walking bundle: {artifact.path} content hash mismatch"
            )
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("invalid walking bundle: file set does not match manifest")
    expected_payloads = {
        "walking-network.geojson": _network_geojson(
            manifest.attractors,
            manifest.zones,
            manifest.routes,
            manifest.deficiencies,
        ),
        "walking-audits.json": {
            "audit_profile": manifest.audit_profile,
            "audits": manifest.audits,
            "review_gate": manifest.review_gate,
            "human_gate_status": manifest.human_gate_status,
        },
        "walking-evidence-requests.json": {
            "evidence_requests": manifest.evidence_requests
        },
        "walking-deficiencies.json": {"deficiencies": manifest.deficiencies},
        "engagement-input.json": {
            "findings": manifest.lived_experience_findings
        },
        "conformance-artifacts.json": {
            "artifacts": manifest.conformance_artifacts
        },
    }
    for filename, expected in expected_payloads.items():
        actual = json.loads((path / filename).read_text())
        if actual != _json_payload(expected):
            raise ValueError(
                f"invalid walking bundle: {filename} does not match manifest"
            )
    expected_html = _review_map_html(
        manifest.analysis_id,
        manifest.attractors,
        manifest.zones,
        manifest.routes,
        manifest.audits,
        manifest.evidence_requests,
    )
    if (path / "review-map.html").read_text() != expected_html:
        raise ValueError("invalid walking bundle: review map does not match manifest")
    return manifest


def load_walking_conformance_artifacts(path: Path) -> tuple[ArtifactLink, ...]:
    """Return workflow links only after validating the complete bundle."""
    return validate_walking_bundle(path).conformance_artifacts


def _validate_scope(
    config: WalkingPlanningConfig,
    evidence: EvidenceSnapshotManifest,
) -> None:
    if evidence.council_id != config.council_id:
        raise ValueError("walking analysis council does not match Evidence Registry")
    if evidence.profile_id != config.guidance_profile_id:
        raise ValueError(
            "walking analysis Guidance Profile does not match Evidence Registry"
        )


def _canonical_records(
    records: Iterable[Any],
    model: type[WalkingContract],
    identifier_field: str,
    label: str,
) -> tuple[Any, ...]:
    validated = tuple(model.model_validate(record) for record in records)
    identifiers = tuple(getattr(record, identifier_field) for record in validated)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return tuple(sorted(validated, key=lambda record: getattr(record, identifier_field)))


def _validate_references(
    attractors: tuple[WalkingAttractor, ...],
    catchments: tuple[WalkingCatchment, ...],
    zones: tuple[CoreWalkingZoneProposal, ...],
    specs: tuple[WalkingRouteSpecification, ...],
    observations: tuple[WalkingAuditObservation, ...],
    lived: tuple[LivedExperienceFinding, ...],
    governed_evidence: dict[str, Any],
) -> None:
    records: tuple[Any, ...] = (
        *attractors,
        *catchments,
        *zones,
        *specs,
        *observations,
        *lived,
    )
    for record in records:
        for evidence_id in getattr(record, "evidence_ids", ()):
            if evidence_id not in governed_evidence:
                raise ValueError(
                    f"evidence {evidence_id!r} is not publishable governed evidence"
                )
    for observation in observations:
        if (
            observation.evidence_mode is AuditEvidenceMode.SITE_SURVEY
            and any(
                governed_evidence[evidence_id].role is not EvidenceRole.OBSERVED
                for evidence_id in observation.evidence_ids
            )
        ):
            raise ValueError("site-survey observations require observed evidence")
        if (
            observation.provenance is AuditProvenance.MODELLED
            and any(
                governed_evidence[evidence_id].role is not EvidenceRole.MODELLED
                for evidence_id in observation.evidence_ids
            )
        ):
            raise ValueError("modelled audit conditions require modelled evidence")
        if (
            observation.evidence_mode is AuditEvidenceMode.LIVED_EXPERIENCE
            and any(
                governed_evidence[evidence_id].role is not EvidenceRole.STAKEHOLDER
                for evidence_id in observation.evidence_ids
            )
        ):
            raise ValueError(
                "lived-experience audit conditions require stakeholder evidence"
            )
        if (
            observation.item is AuditItem.LIGHTING_PERSONAL_SAFETY
            and observation.condition is AuditCondition.COMPLIANT
            and observation.evidence_mode
            not in {
                AuditEvidenceMode.SITE_SURVEY,
                AuditEvidenceMode.LIVED_EXPERIENCE,
            }
        ):
            raise ValueError(
                "a compliant personal-safety condition requires positive site "
                "or lived-experience evidence"
            )


def _derive_catchments(
    attractors: tuple[WalkingAttractor, ...],
    catchments: tuple[WalkingCatchment, ...],
) -> tuple[WalkingCatchmentRecord, ...]:
    by_id = {item.attractor_id: item for item in attractors}
    records = []
    for catchment in catchments:
        centre = by_id.get(catchment.centre_attractor_id)
        if centre is None:
            raise ValueError("walking catchment centre attractor must resolve")
        inside = tuple(
            sorted(
                attractor.attractor_id
                for attractor in attractors
                if _coordinate_distance_km(
                    (centre.longitude, centre.latitude),
                    (attractor.longitude, attractor.latitude),
                )
                * 1000
                <= catchment.radius_m
            )
        )
        outside = tuple(
            sorted(
                attractor.attractor_id
                for attractor in attractors
                if attractor.attractor_id not in inside
            )
        )
        records.append(
            WalkingCatchmentRecord(
                **catchment.model_dump(),
                inside_attractor_ids=inside,
                outside_attractor_ids=outside,
            )
        )
    return tuple(records)


def _validate_zones(
    zones: tuple[CoreWalkingZoneProposal, ...],
    catchments: tuple[WalkingCatchmentRecord, ...],
    attractors: tuple[WalkingAttractor, ...],
) -> None:
    catchment_by_id = {item.catchment_id: item for item in catchments}
    attractor_by_id = {item.attractor_id: item for item in attractors}
    for zone in zones:
        catchment = catchment_by_id.get(zone.catchment_id)
        if catchment is None:
            raise ValueError("Core Walking Zone catchment must resolve")
        if not set(zone.selected_attractor_ids).issubset(
            catchment.inside_attractor_ids
        ):
            raise ValueError(
                "Core Walking Zone selected attractors must resolve inside its catchment"
            )
        centre = attractor_by_id[catchment.centre_attractor_id]
        if not _point_in_polygon(
            (centre.longitude, centre.latitude), zone.coordinates
        ):
            raise ValueError("Core Walking Zone must contain its local centre")


def _route_walking_network(
    specs: tuple[WalkingRouteSpecification, ...],
    attractors: tuple[WalkingAttractor, ...],
    zones: tuple[CoreWalkingZoneProposal, ...],
    config: WalkingPlanningConfig,
    routing_boundary: WalkingRoutingBoundary,
    boundary_id: str,
    boundary_version: str,
    governed_evidence: dict[str, Any],
) -> tuple[WalkingRouteRecord, ...]:
    attractor_by_id = {item.attractor_id: item for item in attractors}
    zone_ids = {item.zone_id for item in zones}
    routes = []
    geometries: set[tuple[Coordinate, ...]] = set()
    for spec in specs:
        if spec.zone_id not in zone_ids:
            raise ValueError("walking route Core Walking Zone must resolve")
        try:
            origin = attractor_by_id[spec.origin_attractor_id]
            destination = attractor_by_id[spec.destination_attractor_id]
        except KeyError as error:
            raise ValueError("walking route attractors must resolve") from error
        request = WalkingRouteRequest(
            specification=spec,
            origin=origin,
            destination=destination,
            maximum_endpoint_offset_m=config.maximum_route_endpoint_offset_m,
        )
        path = WalkingRoutePath.model_validate(routing_boundary.route(request))
        if path.route_id != spec.route_id:
            raise ValueError("walking routing boundary returned a different route ID")
        _validate_route_endpoints(
            path,
            origin,
            destination,
            config.maximum_route_endpoint_offset_m,
        )
        if path.length_km + 0.001 < _polyline_length_km(path.coordinates):
            raise ValueError("walking route length is shorter than its geometry")
        if path.coordinates in geometries:
            raise ValueError("walking route geometries must be distinct")
        geometries.add(path.coordinates)
        for evidence_id in path.evidence_ids:
            if evidence_id not in governed_evidence:
                raise ValueError(
                    "walking routing boundary returned ungoverned path evidence"
                )
        routes.append(
            WalkingRouteRecord(
                **spec.model_dump(),
                coordinates=path.coordinates,
                length_km=path.length_km,
                path_evidence_ids=path.evidence_ids,
                routing_boundary_id=boundary_id,
                routing_boundary_version=boundary_version,
            )
        )
    return tuple(routes)


def _compile_audits(
    zones: tuple[CoreWalkingZoneProposal, ...],
    routes: tuple[WalkingRouteRecord, ...],
    supplied: tuple[WalkingAuditObservation, ...],
    profile: WalkingAuditProfile,
    governed_evidence: dict[str, Any],
) -> tuple[
    tuple[WalkingAuditRecord, ...],
    tuple[WalkingEvidenceRequest, ...],
    tuple[WalkingDeficiency, ...],
]:
    subjects = (
        *((zone.zone_id, AuditSubjectKind.ZONE) for zone in zones),
        *((route.route_id, AuditSubjectKind.ROUTE) for route in routes),
    )
    subject_kinds = dict(subjects)
    by_key: dict[tuple[str, AuditItem], WalkingAuditObservation] = {}
    for observation in supplied:
        if observation.subject_id not in subject_kinds:
            raise ValueError("walking audit observation subject must resolve")
        key = (observation.subject_id, observation.item)
        if key in by_key:
            raise ValueError("only one observation per subject and audit item is allowed")
        by_key[key] = observation
    audits: list[WalkingAuditRecord] = []
    requests: list[WalkingEvidenceRequest] = []
    deficiencies: list[WalkingDeficiency] = []
    consumed: set[tuple[str, AuditItem]] = set()
    for subject_id, subject_kind in subjects:
        audit_observations: list[WalkingAuditObservation] = []
        audit_request_ids: list[str] = []
        unknown_items: list[AuditItem] = []
        for requirement in profile.requirements:
            if subject_kind not in requirement.applies_to:
                continue
            key = (subject_id, requirement.item)
            observation = by_key.get(key)
            if observation is None:
                observation = WalkingAuditObservation(
                    observation_id=f"unknown-{subject_id}-{requirement.item}",
                    subject_id=subject_id,
                    item=requirement.item,
                    condition=AuditCondition.UNKNOWN,
                    provenance=AuditProvenance.UNKNOWN,
                    evidence_mode=AuditEvidenceMode.NONE,
                    rationale="No governed audit observation was supplied.",
                    accessibility_needs=requirement.accessibility_needs,
                )
            else:
                consumed.add(key)
                if not set(requirement.accessibility_needs).issubset(
                    observation.accessibility_needs
                ):
                    raise ValueError(
                        f"audit observation {observation.observation_id!r} omits "
                        "required accessibility needs"
                    )
            audit_observations.append(observation)
            needs_request = False
            required_source: Literal["site-survey", "governed-evidence"]
            if observation.condition is AuditCondition.UNKNOWN:
                needs_request = requirement.mandatory
                required_source = (
                    "site-survey"
                    if requirement.site_evidence_required
                    else "governed-evidence"
                )
                unknown_items.append(requirement.item)
            elif (
                requirement.mandatory
                and requirement.site_evidence_required
                and observation.evidence_mode is not AuditEvidenceMode.SITE_SURVEY
            ):
                needs_request = True
                required_source = "site-survey"
            else:
                required_source = "governed-evidence"
            request_ids: tuple[str, ...] = ()
            if needs_request:
                request_id = f"request-{subject_id}-{requirement.item}"
                request = WalkingEvidenceRequest(
                    request_id=request_id,
                    subject_id=subject_id,
                    item=requirement.item,
                    purpose=(
                        f"Site evidence request: resolve mandatory "
                        f"{requirement.item.value} condition."
                        if required_source == "site-survey"
                        else (
                            f"Governed evidence request: resolve mandatory "
                            f"{requirement.item.value} condition."
                        )
                    ),
                    required_source=required_source,
                    accessibility_needs=requirement.accessibility_needs,
                )
                requests.append(request)
                audit_request_ids.append(request_id)
                request_ids = (request_id,)
            if observation.condition in {
                AuditCondition.DEFICIENT,
                AuditCondition.UNKNOWN,
            }:
                deficiencies.append(
                    WalkingDeficiency(
                        deficiency_id=f"deficiency-{subject_id}-{requirement.item}",
                        subject_id=subject_id,
                        item=requirement.item,
                        condition=observation.condition,
                        description=(
                            observation.rationale
                            if observation.condition is AuditCondition.DEFICIENT
                            else (
                                f"Mandatory {requirement.item.value} condition "
                                "is unresolved."
                            )
                        ),
                        evidence_ids=observation.evidence_ids,
                        evidence_request_ids=request_ids,
                        accessibility_needs=tuple(
                            sorted(
                                set(requirement.accessibility_needs)
                                | set(observation.accessibility_needs)
                            )
                        ),
                    )
                )
        status = (
            WalkingAuditStatus.EVIDENCE_INCOMPLETE
            if audit_request_ids
            else WalkingAuditStatus.HUMAN_REVIEW_REQUIRED
        )
        audits.append(
            WalkingAuditRecord(
                subject_id=subject_id,
                subject_kind=subject_kind,
                observations=tuple(audit_observations),
                status=status,
                evidence_request_ids=tuple(sorted(audit_request_ids)),
                explicit_unknown_items=tuple(sorted(unknown_items)),
            )
        )
    unused = set(by_key) - consumed
    if unused:
        raise ValueError(
            "walking audit observations include items not applicable to their subject"
        )
    return (
        tuple(sorted(audits, key=lambda item: item.subject_id)),
        tuple(sorted(requests, key=lambda item: item.request_id)),
        tuple(sorted(deficiencies, key=lambda item: item.deficiency_id)),
    )


def _validate_lived_experience(
    findings: tuple[LivedExperienceFinding, ...],
    subject_ids: set[str],
    governed_evidence: dict[str, Any],
) -> None:
    for finding in findings:
        if finding.subject_id not in subject_ids:
            raise ValueError("lived-experience finding subject must resolve")
        for evidence_id in finding.evidence_ids:
            item = governed_evidence[evidence_id]
            if (
                item.role is not EvidenceRole.STAKEHOLDER
                or item.access_level is AccessLevel.PERSONAL
                or item.public_disposition is PublicDisposition.EXCLUDE
            ):
                raise ValueError(
                    "lived-experience findings require privacy-safe stakeholder evidence"
                )


def _validate_human_gate(
    gate: WalkingReviewGate | None,
    zones: tuple[CoreWalkingZoneProposal, ...],
    requests: tuple[WalkingEvidenceRequest, ...],
    findings: tuple[LivedExperienceFinding, ...],
) -> Literal["pending", "verified"]:
    if gate is None:
        return "pending"
    zone_ids = {zone.zone_id for zone in zones}
    if set(gate.verified_zone_ids) != zone_ids:
        raise ValueError("human gate must verify every Core Walking Zone selection")
    request_ids = {request.request_id for request in requests}
    if set(gate.verified_audit_limitation_ids) != request_ids:
        raise ValueError("human gate must verify every material audit limitation")
    material_ids = {finding.finding_id for finding in findings if finding.material}
    if set(gate.verified_lived_experience_ids) != material_ids:
        raise ValueError(
            "human gate must verify every material lived-experience finding"
        )
    return "verified"


def _validate_route_endpoints(
    path: WalkingRoutePath,
    origin: WalkingAttractor,
    destination: WalkingAttractor,
    maximum_offset_m: float,
) -> None:
    origin_offset = (
        _coordinate_distance_km(
            (origin.longitude, origin.latitude),
            path.coordinates[0],
        )
        * 1000
    )
    destination_offset = (
        _coordinate_distance_km(
            (destination.longitude, destination.latitude),
            path.coordinates[-1],
        )
        * 1000
    )
    if origin_offset > maximum_offset_m or destination_offset > maximum_offset_m:
        raise ValueError(
            f"walking route {path.route_id!r} endpoint offset exceeds "
            "maximum_route_endpoint_offset_m"
        )


def _network_geojson(
    attractors: tuple[WalkingAttractor, ...],
    zones: tuple[CoreWalkingZoneProposal, ...],
    routes: tuple[WalkingRouteRecord, ...],
    deficiencies: tuple[WalkingDeficiency, ...],
) -> dict[str, Any]:
    deficiency_counts: dict[str, int] = {}
    for deficiency in deficiencies:
        deficiency_counts[deficiency.subject_id] = (
            deficiency_counts.get(deficiency.subject_id, 0) + 1
        )
    features: list[dict[str, Any]] = []
    for attractor in attractors:
        features.append(
            {
                "type": "Feature",
                "id": attractor.attractor_id,
                "properties": {
                    "feature_type": "walking-attractor",
                    "name": attractor.name,
                    "attractor_kind": attractor.kind,
                    "inside_study_area": attractor.inside_study_area,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [attractor.longitude, attractor.latitude],
                },
            }
        )
    for zone in zones:
        features.append(
            {
                "type": "Feature",
                "id": zone.zone_id,
                "properties": {
                    "feature_type": "core-walking-zone",
                    "name": zone.name,
                    "catchment_id": zone.catchment_id,
                    "selected_attractor_ids": list(zone.selected_attractor_ids),
                    "deficiency_count": deficiency_counts.get(zone.zone_id, 0),
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[list(coordinate) for coordinate in zone.coordinates]],
                },
            }
        )
    for route in routes:
        features.append(
            {
                "type": "Feature",
                "id": route.route_id,
                "properties": {
                    "feature_type": "walking-route",
                    "route_kind": route.kind,
                    "zone_id": route.zone_id,
                    "deficiency_count": deficiency_counts.get(route.route_id, 0),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(coordinate) for coordinate in route.coordinates],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": sorted(features, key=lambda feature: feature["id"]),
    }


def _review_map_html(
    analysis_id: str,
    attractors: tuple[WalkingAttractor, ...],
    zones: tuple[CoreWalkingZoneProposal, ...],
    routes: tuple[WalkingRouteRecord, ...],
    audits: tuple[WalkingAuditRecord, ...],
    requests: tuple[WalkingEvidenceRequest, ...],
) -> str:
    all_coordinates = [
        (attractor.longitude, attractor.latitude) for attractor in attractors
    ]
    all_coordinates.extend(
        coordinate for zone in zones for coordinate in zone.coordinates
    )
    all_coordinates.extend(
        coordinate for route in routes for coordinate in route.coordinates
    )
    longitudes = [coordinate[0] for coordinate in all_coordinates] or [0.0]
    latitudes = [coordinate[1] for coordinate in all_coordinates] or [0.0]
    min_lon, max_lon = min(longitudes), max(longitudes)
    min_lat, max_lat = min(latitudes), max(latitudes)
    lon_span = max(max_lon - min_lon, 0.001)
    lat_span = max(max_lat - min_lat, 0.001)

    def project(coordinate: Coordinate) -> tuple[float, float]:
        x = 30 + ((coordinate[0] - min_lon) / lon_span) * 740
        y = 470 - ((coordinate[1] - min_lat) / lat_span) * 440
        return round(x, 2), round(y, 2)

    zone_shapes = "".join(
        (
            f'<polygon data-feature-id="{html.escape(zone.zone_id)}" '
            f'points="{" ".join(f"{x},{y}" for x, y in map(project, zone.coordinates))}" '
            'fill="#d8f3dc" stroke="#1b4332" stroke-width="2"/>'
        )
        for zone in zones
    )
    route_shapes = "".join(
        (
            f'<polyline data-feature-id="{html.escape(route.route_id)}" '
            f'points="{" ".join(f"{x},{y}" for x, y in map(project, route.coordinates))}" '
            f'fill="none" stroke="'
            f'{"#6a4c93" if route.kind is WalkingRouteKind.KEY else "#1982c4"}" '
            'stroke-width="5" stroke-linecap="round"/>'
        )
        for route in routes
    )
    attractor_shapes = "".join(
        (
            f'<circle data-feature-id="{html.escape(attractor.attractor_id)}" '
            f'cx="{project((attractor.longitude, attractor.latitude))[0]}" '
            f'cy="{project((attractor.longitude, attractor.latitude))[1]}" '
            'r="6" fill="#ffca3a" stroke="#333"/>'
        )
        for attractor in attractors
    )
    def audit_row(audit: WalkingAuditRecord) -> str:
        unknowns = ", ".join(
            item.value for item in audit.explicit_unknown_items
        ) or "None"
        return (
            "<tr>"
            f"<td>{html.escape(audit.subject_id)}</td>"
            f"<td>{html.escape(audit.subject_kind.value)}</td>"
            f"<td>{html.escape(audit.status.value)}</td>"
            f"<td>{html.escape(unknowns)}</td>"
            f"<td>{len(audit.evidence_request_ids)}</td>"
            "</tr>"
        )

    audit_rows = "".join(audit_row(audit) for audit in audits)
    request_rows = "".join(
        (
            "<li>"
            f"<strong>Site evidence request</strong> "
            f"{html.escape(request.subject_id)} / {html.escape(request.item.value)}: "
            f"{html.escape(request.purpose)}"
            "</li>"
        )
        for request in requests
    ) or "<li>No unresolved mandatory evidence requests.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Walking and wheeling review map — {html.escape(analysis_id)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; color: #17202a; background: #f7f9f9; }}
main {{ max-width: 1100px; margin: auto; padding: 1rem; }}
.notice {{ border-left: 5px solid #6a4c93; background: white; padding: .8rem; }}
svg {{ width: 100%; height: auto; background: #eef5f1; border: 1px solid #9aa; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ border: 1px solid #bbb; padding: .45rem; text-align: left; }}
th {{ background: #1b4332; color: white; }}
</style>
</head>
<body><main>
<h1>Walking and wheeling review map</h1>
<p class="notice">This is walking/wheeling evidence and not cycling geometry.
Browser accessibility is not a substitute for mobility-aid continuity, crossings,
personal safety, rest opportunities or access-panel review.</p>
<svg viewBox="0 0 800 500" role="img" aria-label="Walking zones, routes and attractors">
{zone_shapes}{route_shapes}{attractor_shapes}
</svg>
<h2>Audit status</h2>
<table aria-label="Walking and wheeling audit table">
<thead><tr><th>Subject</th><th>Kind</th><th>Status</th><th>Unknowns</th><th>Requests</th></tr></thead>
<tbody>{audit_rows}</tbody>
</table>
<h2>Evidence limitations</h2><ul>{request_rows}</ul>
</main></body></html>
"""


def _conformance_artifacts(analysis_id: str) -> tuple[ArtifactLink, ...]:
    return tuple(
        ArtifactLink(
            artifact_id=f"{analysis_id}-{kind}",
            uri=f"walking-manifest.json#{fragment}",
            kind=kind,
        )
        for kind, fragment in (
            ("engagement", "lived_experience_findings"),
            ("intervention-input", "deficiencies"),
            ("walking-network-plan", "zones"),
            ("walking-route-area-audit", "audits"),
        )
    )


def _polygon_area(coordinates: tuple[Coordinate, ...]) -> float:
    return abs(
        sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in pairwise(coordinates)
        )
        / 2
    )


def _point_in_polygon(point: Coordinate, polygon: tuple[Coordinate, ...]) -> bool:
    x, y = point
    inside = False
    for left, right in pairwise(polygon):
        x1, y1 = left
        x2, y2 = right
        if ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1) + x1
        ):
            inside = not inside
    return inside


def _polyline_length_km(coordinates: tuple[Coordinate, ...]) -> float:
    return sum(
        _coordinate_distance_km(left, right)
        for left, right in pairwise(coordinates)
    )


def _coordinate_distance_km(left: Coordinate, right: Coordinate) -> float:
    radius_km = 6371.0088
    lat1, lat2 = math.radians(left[1]), math.radians(right[1])
    delta_lat = math.radians(right[1] - left[1])
    delta_lon = math.radians(right[0] - left[0])
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return radius_km * 2 * math.atan2(
        math.sqrt(haversine), math.sqrt(1 - haversine)
    )


def _stable_boundary_identifier(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("walking routing boundary ID must be a string")
    normalized = value.strip()
    if (
        not normalized
        or not normalized[0].isalnum()
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in normalized
        )
    ):
        raise ValueError("walking routing boundary ID must be a stable identifier")
    return normalized


def _nonblank_boundary_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonblank string")
    return value.strip()


def _canonical_unique(value: tuple[Any, ...], label: str) -> tuple[Any, ...]:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(value))


def _unique_ids(
    records: tuple[Any, ...],
    field: str,
    label: str,
) -> set[str]:
    identifiers = tuple(getattr(record, field) for record in records)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return set(identifiers)


def _json_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json_payload(item) for item in value]
    if isinstance(value, list):
        return [_json_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_payload(item) for key, item in value.items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        _json_payload(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            _json_payload(payload),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
