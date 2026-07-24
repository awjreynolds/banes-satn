"""Flow-led LCWIP cycling planning outside the SATN Wayfinding Pass.

This module consumes governed evidence and immutable public SATN references. It
does not import SATN routing/compiler internals and cannot mutate the SATN
network hypothesis. A caller supplies a bounded deterministic routing adapter.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import shutil
import tempfile
from collections.abc import Iterable
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Protocol, Self
from urllib.parse import unquote, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lcwip.evidence import (
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSnapshotManifest,
    validate_evidence_snapshot,
)
from lcwip.models import ArtifactLink, GuidanceProfile
from satn import PublishedArtifactReference, PublishedNetworkFeatureReference

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


# Public contracts


class DemandContract(BaseModel):
    """Closed immutable contract for demand-planning boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0"] = "1.0"


class DemandScale(StrEnum):
    LOCAL = "local"
    STRATEGIC = "strategic"


class RouteCondition(StrEnum):
    CURRENT = "current-condition"
    POTENTIAL = "potential-design-outcome"


class RouteCriterion(StrEnum):
    DIRECTNESS = "directness"
    GRADIENT = "gradient"
    SAFETY = "safety"
    COMFORT = "comfort"
    ATTRACTIVENESS = "attractiveness"
    COHESION = "cohesion"


class RouteNetworkSource(StrEnum):
    SATN = "satn"
    LOCAL = "local"
    EXTERNAL = "external"


class DecisionSource(StrEnum):
    DETERMINISTIC = "deterministic"
    HUMAN = "human"
    AGENT = "agent"


class AlternativeDisposition(StrEnum):
    CANDIDATE = "candidate"
    PREFERRED = "preferred"
    REJECTED = "rejected"


class DemandPoint(DemandContract):
    point_id: StableIdentifier
    name: NonBlankText
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    inside_study_area: bool
    equality_relevant: bool = False
    source_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("source_evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "point evidence IDs")


class DemandScenario(DemandContract):
    scenario_id: StableIdentifier
    name: NonBlankText
    evidence_role: EvidenceRole
    assumptions: tuple[NonBlankText, ...] = Field(min_length=1)
    source_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("assumptions", "source_evidence_ids")
    @classmethod
    def canonical_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "scenario values")

    @field_validator("evidence_role")
    @classmethod
    def planning_evidence_role(cls, value: EvidenceRole) -> EvidenceRole:
        if value not in {
            EvidenceRole.OBSERVED,
            EvidenceRole.MODELLED,
            EvidenceRole.DERIVED,
        }:
            raise ValueError(
                "demand scenarios must be observed, modelled, or derived"
            )
        return value


class DemandFlow(DemandContract):
    flow_id: StableIdentifier
    scenario_id: StableIdentifier
    origin_id: StableIdentifier
    destination_id: StableIdentifier
    trips: float = Field(ge=0)
    unit: NonBlankText
    source_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("source_evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "flow evidence IDs")

    @model_validator(mode="after")
    def distinct_endpoints(self) -> Self:
        if self.origin_id == self.destination_id:
            raise ValueError("a demand flow requires distinct origin and destination")
        return self


class ScaleFilter(DemandContract):
    scale: DemandScale
    minimum_distance_km: float = Field(ge=0)
    maximum_distance_km: float = Field(gt=0)
    minimum_trips: float = Field(ge=0)
    protect_equality_access: bool = False

    @model_validator(mode="after")
    def ordered_distance_range(self) -> Self:
        if self.maximum_distance_km <= self.minimum_distance_km:
            raise ValueError("scale maximum distance must exceed its minimum distance")
        return self


class SensitivityCase(DemandContract):
    case_id: StableIdentifier
    scale: DemandScale
    minimum_distance_km: float = Field(ge=0)
    maximum_distance_km: float = Field(gt=0)
    minimum_trips: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered_distance_range(self) -> Self:
        if self.maximum_distance_km <= self.minimum_distance_km:
            raise ValueError("sensitivity maximum distance must exceed its minimum distance")
        return self


class CriterionAssessment(DemandContract):
    criterion: RouteCriterion
    score: int | None = Field(default=None, ge=0, le=5)
    evidence_ids: tuple[StableIdentifier, ...] = ()
    rationale: NonBlankText

    @field_validator("evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "criterion evidence IDs")

    @model_validator(mode="after")
    def evidence_for_known_score(self) -> Self:
        if self.score is not None and not self.evidence_ids:
            raise ValueError("a scored route criterion requires governed evidence")
        return self


class RouteQualityAssessment(DemandContract):
    condition: RouteCondition
    criteria: tuple[CriterionAssessment, ...]

    @field_validator("criteria")
    @classmethod
    def complete_criteria(
        cls, value: tuple[CriterionAssessment, ...]
    ) -> tuple[CriterionAssessment, ...]:
        by_criterion = {assessment.criterion: assessment for assessment in value}
        if len(by_criterion) != len(value):
            raise ValueError("route quality criteria must be unique")
        if set(by_criterion) != set(RouteCriterion):
            raise ValueError("route quality criteria must include every governed criterion")
        return tuple(by_criterion[criterion] for criterion in RouteCriterion)

    @property
    def explicit_unknowns(self) -> tuple[RouteCriterion, ...]:
        return tuple(item.criterion for item in self.criteria if item.score is None)


class RoutedAlternative(DemandContract):
    """One finite geometry-bearing result returned by a routing boundary."""

    alternative_id: StableIdentifier
    network_source: RouteNetworkSource
    coordinates: tuple[Coordinate, ...] = Field(min_length=2)
    length_km: float = Field(gt=0)
    satn_feature_references: tuple[PublishedNetworkFeatureReference, ...] = ()
    external_or_local_network_ids: tuple[StableIdentifier, ...] = ()
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    current_quality: RouteQualityAssessment
    potential_quality: RouteQualityAssessment

    @field_validator(
        "satn_feature_references",
        "external_or_local_network_ids",
        "evidence_ids",
    )
    @classmethod
    def canonical_references(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if value and isinstance(value[0], PublishedNetworkFeatureReference):
            keys = tuple(item.public_identifier for item in value)
            if len(keys) != len(set(keys)):
                raise ValueError("SATN feature references must be unique")
            return tuple(sorted(value, key=lambda item: item.public_identifier))
        if len(value) != len(set(value)):
            raise ValueError("route alternative references must be unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_network_and_quality_states(self) -> Self:
        if self.network_source is RouteNetworkSource.SATN:
            if not self.satn_feature_references:
                raise ValueError("a SATN route alternative requires SATN feature references")
            if self.external_or_local_network_ids:
                raise ValueError("a SATN route cannot claim local or external network IDs")
        else:
            if self.satn_feature_references:
                raise ValueError("a local or external route cannot claim SATN features")
            if not self.external_or_local_network_ids:
                raise ValueError("a local or external route requires governed network IDs")
        if self.current_quality.condition is not RouteCondition.CURRENT:
            raise ValueError("current_quality must assess current-condition evidence")
        if self.potential_quality.condition is not RouteCondition.POTENTIAL:
            raise ValueError(
                "potential_quality must assess the potential-design-outcome"
            )
        return self


class SatnNetworkHypothesis(DemandContract):
    """The immutable SATN publication treated as one network hypothesis."""

    artifact: PublishedArtifactReference
    features: tuple[PublishedNetworkFeatureReference, ...] = Field(min_length=1)

    @field_validator("features")
    @classmethod
    def canonical_features(
        cls, value: tuple[PublishedNetworkFeatureReference, ...]
    ) -> tuple[PublishedNetworkFeatureReference, ...]:
        identifiers = tuple(feature.public_identifier for feature in value)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("SATN hypothesis feature references must be unique")
        return tuple(sorted(value, key=lambda feature: feature.public_identifier))

    @model_validator(mode="after")
    def features_belong_to_artifact(self) -> Self:
        for feature in self.features:
            if (
                feature.run_id != self.artifact.run_id
                or feature.artifact_key != self.artifact.artifact_key
                or feature.source_artifact_uri != self.artifact.uri
                or feature.source_artifact_sha256 != self.artifact.sha256
            ):
                raise ValueError(
                    "SATN feature references must belong to the hypothesis artifact"
                )
        return self


class RoutingRequest(DemandContract):
    desire_line_id: StableIdentifier
    scale: DemandScale
    origin: DemandPoint
    destination: DemandPoint
    maximum_alternatives: int = Field(ge=1, le=10)
    satn: SatnNetworkHypothesis


class DemandRoutingBoundary(Protocol):
    boundary_id: str
    boundary_version: str

    def route_alternatives(
        self, request: RoutingRequest
    ) -> tuple[RoutedAlternative, ...]: ...


class RouteSelectionProfile(DemandContract):
    profile_id: StableIdentifier
    guidance_profile_id: StableIdentifier
    version: NonBlankText
    selection_condition: RouteCondition
    criterion_order: tuple[RouteCriterion, ...]
    allow_unknown: bool = False

    @field_validator("criterion_order")
    @classmethod
    def complete_order(
        cls, value: tuple[RouteCriterion, ...]
    ) -> tuple[RouteCriterion, ...]:
        if len(value) != len(set(value)) or set(value) != set(RouteCriterion):
            raise ValueError("route-selection criterion order must contain every criterion")
        return value


class RouteSelectionDecision(DemandContract):
    decision_id: StableIdentifier
    desire_line_id: StableIdentifier
    source: DecisionSource
    selected_alternative_id: StableIdentifier
    candidate_alternative_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    candidate_fingerprint: Sha256Hex
    authority_or_agent: NonBlankText
    rationale: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("candidate_alternative_ids", "evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "decision evidence IDs")


class DemandAnalysisConfig(DemandContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot: Path
    output_dir: Path
    transformation_version: NonBlankText
    scales: tuple[ScaleFilter, ...] = Field(min_length=1)
    sensitivity_cases: tuple[SensitivityCase, ...] = ()
    maximum_route_alternatives: int = Field(ge=1, le=10)
    minimum_route_alternatives: int = Field(ge=1, le=10)
    maximum_route_endpoint_offset_m: float = Field(ge=0)
    route_selection_profile: RouteSelectionProfile
    decisions: tuple[RouteSelectionDecision, ...] = ()

    @field_validator("scales")
    @classmethod
    def canonical_scales(cls, value: tuple[ScaleFilter, ...]) -> tuple[ScaleFilter, ...]:
        scales = tuple(item.scale for item in value)
        if len(scales) != len(set(scales)):
            raise ValueError("demand scale filters must be unique")
        return tuple(sorted(value, key=lambda item: item.scale))

    @field_validator("sensitivity_cases")
    @classmethod
    def canonical_sensitivity(
        cls, value: tuple[SensitivityCase, ...]
    ) -> tuple[SensitivityCase, ...]:
        identifiers = tuple(item.case_id for item in value)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("sensitivity case IDs must be unique")
        return tuple(sorted(value, key=lambda item: item.case_id))

    @field_validator("decisions")
    @classmethod
    def canonical_decisions(
        cls, value: tuple[RouteSelectionDecision, ...]
    ) -> tuple[RouteSelectionDecision, ...]:
        decision_ids = tuple(item.decision_id for item in value)
        desire_ids = tuple(item.desire_line_id for item in value)
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("route-selection decision IDs must be unique")
        if len(desire_ids) != len(set(desire_ids)):
            raise ValueError("only one supplied decision is permitted per desire line")
        return tuple(sorted(value, key=lambda item: item.desire_line_id))

    @model_validator(mode="after")
    def validate_selection_boundary(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError(
                "Guidance Profile ID does not match the embedded profile"
            )
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError(
                "Guidance Profile fingerprint does not match the embedded profile"
            )
        if self.minimum_route_alternatives > self.maximum_route_alternatives:
            raise ValueError(
                "minimum_route_alternatives cannot exceed maximum_route_alternatives"
            )
        if (
            self.route_selection_profile.guidance_profile_id
            != self.guidance_profile_id
        ):
            raise ValueError(
                "route-selection profile must match the active Guidance Profile"
            )
        for decision in self.decisions:
            if decision.source is DecisionSource.DETERMINISTIC:
                raise ValueError(
                    "caller-supplied decisions must identify a human or bounded agent"
                )
        return self


class FilterOutcome(DemandContract):
    desire_line_id: StableIdentifier
    rule: Literal[
        "minimum-distance-km",
        "maximum-distance-km",
        "minimum-trips",
    ]
    configured_value: float
    observed_value: float
    passed: bool
    overridden_by_equality_access: bool = False


class DesireLineRecord(DemandContract):
    desire_line_id: StableIdentifier
    scenario_id: StableIdentifier
    scale: DemandScale
    origin_id: StableIdentifier
    destination_id: StableIdentifier
    trips: float = Field(ge=0)
    unit: NonBlankText
    straight_line_distance_km: float = Field(ge=0)
    flow_lineage: tuple[StableIdentifier, ...] = Field(min_length=1)
    source_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    transformation_version: NonBlankText
    retained: bool
    retention_reasons: tuple[NonBlankText, ...]


class SensitivityResult(DemandContract):
    case_id: StableIdentifier
    scale: DemandScale
    retained_desire_line_ids: tuple[StableIdentifier, ...]
    changed_from_base_ids: tuple[StableIdentifier, ...]


class PlannedRouteAlternative(RoutedAlternative):
    desire_line_id: StableIdentifier
    route_feature_id: StableIdentifier
    disposition: AlternativeDisposition
    rejection_reason: NonBlankText | None = None
    explicit_unknowns: tuple[RouteCriterion, ...] = ()

    @model_validator(mode="after")
    def reason_matches_disposition(self) -> Self:
        if self.disposition is AlternativeDisposition.REJECTED:
            if self.rejection_reason is None:
                raise ValueError("a rejected route alternative requires a reason")
        elif self.rejection_reason is not None:
            raise ValueError("only rejected route alternatives may have a rejection reason")
        return self


class RouteSelectionRecord(DemandContract):
    desire_line_id: StableIdentifier
    alternative_ids: tuple[StableIdentifier, ...]
    preferred_alternative_id: StableIdentifier | None
    audit_status: Literal["preferred", "unresolved"]
    explicit_unknowns: tuple[RouteCriterion, ...] = ()
    decision: RouteSelectionDecision | None = None


class NetworkReconciliation(DemandContract):
    desire_line_id: StableIdentifier
    alternative_id: StableIdentifier
    relationship: Literal[
        "strategic-spine",
        "access-branch",
        "cross-spine-connector",
        "network-gap",
        "local-network",
        "external-network",
        "unmatched-satn",
    ]
    satn_feature_ids: tuple[StableIdentifier, ...] = ()
    divergence_reported: bool
    rationale: NonBlankText


class NetworkCoverageGap(DemandContract):
    gap_id: StableIdentifier
    point_id: StableIdentifier
    reason: Literal[
        "no-governed-flow-evidence",
        "demand-filtered",
        "no-route-alternatives",
        "route-selection-unresolved",
    ]
    equality_relevant: bool
    evidence_ids: tuple[StableIdentifier, ...]


class NetworkDensityRecord(DemandContract):
    density_id: StableIdentifier
    scenario_id: StableIdentifier
    scale: DemandScale
    retained_desire_line_count: int = Field(ge=0)
    preferred_route_count: int = Field(ge=0)
    covered_point_count: int = Field(ge=0)
    total_point_count: int = Field(ge=0)
    coverage_ratio: float = Field(ge=0, le=1)
    preferred_route_length_km: float = Field(ge=0)
    gap_point_ids: tuple[StableIdentifier, ...]


class BundleArtifact(DemandContract):
    path: NonBlankText
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("demand bundle artifact paths must stay inside the bundle")
        return value


class DemandAnalysisManifest(DemandContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot_id: StableIdentifier
    evidence_snapshot_fingerprint: Sha256Hex
    satn: SatnNetworkHypothesis
    routing_boundary_id: StableIdentifier
    routing_boundary_version: NonBlankText
    transformation_version: NonBlankText
    scale_filters: tuple[ScaleFilter, ...]
    sensitivity_cases: tuple[SensitivityCase, ...]
    maximum_route_alternatives: int = Field(ge=1, le=10)
    minimum_route_alternatives: int = Field(ge=1, le=10)
    maximum_route_endpoint_offset_m: float = Field(ge=0)
    route_selection_profile: RouteSelectionProfile
    input_fingerprint: Sha256Hex
    points: tuple[DemandPoint, ...]
    scenarios: tuple[DemandScenario, ...]
    flows: tuple[DemandFlow, ...]
    desire_lines: tuple[DesireLineRecord, ...]
    filter_outcomes: tuple[FilterOutcome, ...]
    sensitivity_results: tuple[SensitivityResult, ...]
    route_alternatives: tuple[PlannedRouteAlternative, ...]
    route_selections: tuple[RouteSelectionRecord, ...]
    network_reconciliations: tuple[NetworkReconciliation, ...]
    coverage_gaps: tuple[NetworkCoverageGap, ...]
    network_density: tuple[NetworkDensityRecord, ...]
    conformance_artifacts: tuple[ArtifactLink, ...]
    artifacts: tuple[BundleArtifact, ...]
    analysis_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_relational_integrity(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError(
                "manifest Guidance Profile ID does not match the embedded profile"
            )
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError(
                "manifest Guidance Profile fingerprint does not match its contents"
            )
        if (
            self.route_selection_profile.guidance_profile_id
            != self.guidance_profile_id
        ):
            raise ValueError(
                "manifest route-selection profile must match the Guidance Profile"
            )
        if self.minimum_route_alternatives > self.maximum_route_alternatives:
            raise ValueError("manifest route alternative bounds are inconsistent")
        configured_scales = tuple(item.scale for item in self.scale_filters)
        if len(configured_scales) != len(set(configured_scales)):
            raise ValueError("manifest demand scale filters must be unique")
        point_ids = _unique_record_ids(self.points, "point_id", "manifest point")
        scenario_ids = _unique_record_ids(
            self.scenarios, "scenario_id", "manifest scenario"
        )
        flow_ids = _unique_record_ids(self.flows, "flow_id", "manifest flow")
        desire_ids = _unique_record_ids(
            self.desire_lines, "desire_line_id", "manifest desire line"
        )
        _unique_record_ids(
            self.route_alternatives,
            "route_feature_id",
            "manifest route feature",
        )
        _unique_record_ids(self.route_selections, "desire_line_id", "route selection")
        _unique_record_ids(self.coverage_gaps, "gap_id", "coverage gap")
        _unique_record_ids(self.network_density, "density_id", "network density")
        _unique_record_ids(self.artifacts, "path", "bundle artifact")

        for flow in self.flows:
            if flow.origin_id not in point_ids or flow.destination_id not in point_ids:
                raise ValueError("manifest flow endpoints must resolve to points")
            if flow.scenario_id not in scenario_ids:
                raise ValueError("manifest flow scenario must resolve")
        for desire_line in self.desire_lines:
            if (
                desire_line.origin_id not in point_ids
                or desire_line.destination_id not in point_ids
            ):
                raise ValueError("manifest desire-line endpoints must resolve to points")
            if desire_line.scenario_id not in scenario_ids:
                raise ValueError("manifest desire-line scenario must resolve")
            if not set(desire_line.flow_lineage).issubset(flow_ids):
                raise ValueError("manifest desire-line flow lineage must be complete")

        alternatives_by_desire: dict[str, set[str]] = {}
        alternative_keys: set[tuple[str, str]] = set()
        for alternative in self.route_alternatives:
            if alternative.desire_line_id not in desire_ids:
                raise ValueError("manifest route alternative must resolve to a desire line")
            key = (alternative.desire_line_id, alternative.alternative_id)
            if key in alternative_keys:
                raise ValueError(
                    "route alternative IDs must be unique within each desire line"
                )
            alternative_keys.add(key)
            alternatives_by_desire.setdefault(
                alternative.desire_line_id, set()
            ).add(alternative.alternative_id)

        retained_ids = {
            line.desire_line_id for line in self.desire_lines if line.retained
        }
        selection_ids = {
            selection.desire_line_id for selection in self.route_selections
        }
        if selection_ids != retained_ids:
            raise ValueError(
                "route selections must account for every retained desire line exactly"
            )
        for selection in self.route_selections:
            available = alternatives_by_desire.get(selection.desire_line_id, set())
            if set(selection.alternative_ids) != available:
                raise ValueError(
                    "route selection alternatives must match the finite route menu"
                )
            if (
                selection.preferred_alternative_id is not None
                and selection.preferred_alternative_id not in available
            ):
                raise ValueError("preferred route must resolve to a finite alternative")
            if selection.decision is not None and (
                selection.decision.desire_line_id != selection.desire_line_id
                or set(selection.decision.candidate_alternative_ids) != available
            ):
                raise ValueError(
                    "route decision must remain bound to its finite alternative menu"
                )
            if selection.decision is not None:
                menu = tuple(
                    _base_route_alternative(alternative)
                    for alternative in self.route_alternatives
                    if alternative.desire_line_id == selection.desire_line_id
                )
                if (
                    selection.decision.candidate_fingerprint
                    != route_candidate_fingerprint(menu)
                ):
                    raise ValueError(
                        "route decision candidate fingerprint must match its "
                        "finite alternative menu"
                    )
        for reconciliation in self.network_reconciliations:
            if (
                reconciliation.desire_line_id,
                reconciliation.alternative_id,
            ) not in alternative_keys:
                raise ValueError(
                    "network reconciliation must resolve to a route alternative"
                )
        for gap in self.coverage_gaps:
            if gap.point_id not in point_ids:
                raise ValueError("coverage gap point must resolve")
        for density in self.network_density:
            if density.scenario_id not in scenario_ids:
                raise ValueError("network density scenario must resolve")
            if not set(density.gap_point_ids).issubset(point_ids):
                raise ValueError("network density gap points must resolve")
        if {artifact.kind for artifact in self.conformance_artifacts} != {
            "baseline-evidence",
            "cycling-network-plan",
        }:
            raise ValueError(
                "demand conformance artifacts must cover baseline and cycling plan"
            )
        if {artifact.path for artifact in self.artifacts} != {
            "conformance-artifacts.json",
            "demand-network.geojson",
            "review-map.html",
            "route-selection.json",
            "sensitivity.json",
        }:
            raise ValueError("demand bundle manifest artifact set is incomplete")
        return self

    @model_validator(mode="after")
    def fingerprint_matches_contents(self) -> Self:
        expected = _fingerprint(
            self.model_dump(mode="json", exclude={"analysis_fingerprint"})
        )
        if self.analysis_fingerprint != expected:
            raise ValueError("demand analysis fingerprint does not match its contents")
        return self


# Deep-module interface


def route_candidate_fingerprint(
    alternatives: Iterable[RoutedAlternative],
) -> str:
    """Fingerprint one complete finite routing menu for a bounded decision."""
    validated = tuple(
        sorted(
            (
                RoutedAlternative.model_validate(alternative)
                for alternative in alternatives
            ),
            key=lambda item: item.alternative_id,
        )
    )
    identifiers = tuple(item.alternative_id for item in validated)
    if not validated or len(identifiers) != len(set(identifiers)):
        raise ValueError("route candidate menu must be non-empty and unique")
    return _fingerprint({"route_alternatives": validated})


def build_demand_analysis(
    config: DemandAnalysisConfig,
    *,
    points: Iterable[DemandPoint],
    scenarios: Iterable[DemandScenario],
    flows: Iterable[DemandFlow],
    satn: SatnNetworkHypothesis,
    routing_boundary: DemandRoutingBoundary,
) -> Path:
    """Build one deterministic immutable demand-analysis review bundle."""
    config = DemandAnalysisConfig.model_validate(config.model_dump())
    satn = SatnNetworkHypothesis.model_validate(satn.model_dump())
    _validate_local_satn_artifact(satn)
    evidence = validate_evidence_snapshot(config.evidence_snapshot)
    _validate_analysis_scope(config, evidence)
    canonical_points = _canonical_records(
        points, DemandPoint, "point_id", "demand point"
    )
    canonical_scenarios = _canonical_records(
        scenarios, DemandScenario, "scenario_id", "demand scenario"
    )
    canonical_flows = _canonical_records(
        flows, DemandFlow, "flow_id", "demand flow"
    )
    governed_evidence = {
        item.evidence_id: item
        for item in evidence.items
        if item.availability is EvidenceAvailability.AVAILABLE
    }
    _validate_inputs(
        canonical_points,
        canonical_scenarios,
        canonical_flows,
        config,
        governed_evidence,
    )
    boundary_id = _stable_boundary_identifier(routing_boundary.boundary_id)
    boundary_version = _nonblank_boundary_value(
        routing_boundary.boundary_version, "routing boundary version"
    )
    (
        desire_lines,
        filter_outcomes,
        sensitivity_results,
    ) = _derive_desire_lines(
        canonical_points,
        canonical_flows,
        config,
    )
    (
        route_alternatives,
        route_selections,
        reconciliations,
        coverage_gaps,
    ) = _route_and_reconcile(
        config,
        canonical_points,
        desire_lines,
        satn,
        routing_boundary,
        governed_evidence,
    )
    network_density = _derive_network_density(
        canonical_points,
        canonical_scenarios,
        config.scales,
        desire_lines,
        route_alternatives,
        route_selections,
    )
    input_fingerprint = _fingerprint(
        {
            "analysis_id": config.analysis_id,
            "council_id": config.council_id,
            "guidance_profile": config.guidance_profile,
            "guidance_profile_id": config.guidance_profile_id,
            "guidance_profile_fingerprint": config.guidance_profile_fingerprint,
            "evidence_snapshot_fingerprint": evidence.snapshot_fingerprint,
            "satn": satn,
            "routing_boundary_id": boundary_id,
            "routing_boundary_version": boundary_version,
            "transformation_version": config.transformation_version,
            "scales": config.scales,
            "sensitivity_cases": config.sensitivity_cases,
            "maximum_route_alternatives": config.maximum_route_alternatives,
            "minimum_route_alternatives": config.minimum_route_alternatives,
            "maximum_route_endpoint_offset_m": (
                config.maximum_route_endpoint_offset_m
            ),
            "route_selection_profile": config.route_selection_profile,
            "decisions": config.decisions,
            "points": canonical_points,
            "scenarios": canonical_scenarios,
            "flows": canonical_flows,
        }
    )
    destination = config.output_dir / config.analysis_id
    if destination.exists():
        existing = validate_demand_bundle(destination)
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError(
                f"demand analysis {config.analysis_id!r} is immutable and inputs changed"
            )
        expected_outputs = (
            desire_lines,
            filter_outcomes,
            sensitivity_results,
            route_alternatives,
            route_selections,
            reconciliations,
            coverage_gaps,
            network_density,
        )
        existing_outputs = (
            existing.desire_lines,
            existing.filter_outcomes,
            existing.sensitivity_results,
            existing.route_alternatives,
            existing.route_selections,
            existing.network_reconciliations,
            existing.coverage_gaps,
            existing.network_density,
        )
        if existing_outputs != expected_outputs:
            raise ValueError(
                "routing boundary output is not reproducible under its declared version"
            )
        return destination

    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.analysis_id}-", dir=config.output_dir)
    )
    try:
        conformance_artifacts = _conformance_artifacts(config.analysis_id)
        _write_json(
            temporary / "demand-network.geojson",
            _network_geojson(
                canonical_points,
                desire_lines,
                route_alternatives,
                coverage_gaps,
            ),
        )
        _write_json(
            temporary / "route-selection.json",
            {
                "route_alternatives": route_alternatives,
                "route_selections": route_selections,
                "network_reconciliations": reconciliations,
                "coverage_gaps": coverage_gaps,
                "network_density": network_density,
                "route_selection_profile": config.route_selection_profile,
            },
        )
        _write_json(
            temporary / "sensitivity.json",
            {
                "scale_filters": config.scales,
                "sensitivity_cases": config.sensitivity_cases,
                "filter_outcomes": filter_outcomes,
                "sensitivity_results": sensitivity_results,
            },
        )
        _write_json(
            temporary / "conformance-artifacts.json",
            {"artifacts": conformance_artifacts},
        )
        (temporary / "review-map.html").write_text(
            _review_map_html(
                config.analysis_id,
                canonical_points,
                desire_lines,
                route_alternatives,
                coverage_gaps,
            ),
            encoding="utf-8",
        )
        artifact_paths = (
            "conformance-artifacts.json",
            "demand-network.geojson",
            "review-map.html",
            "route-selection.json",
            "sensitivity.json",
        )
        artifacts = tuple(
            BundleArtifact(
                path=path,
                sha256=hashlib.sha256((temporary / path).read_bytes()).hexdigest(),
            )
            for path in artifact_paths
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
            "satn": satn,
            "routing_boundary_id": boundary_id,
            "routing_boundary_version": boundary_version,
            "transformation_version": config.transformation_version,
            "scale_filters": config.scales,
            "sensitivity_cases": config.sensitivity_cases,
            "maximum_route_alternatives": config.maximum_route_alternatives,
            "minimum_route_alternatives": config.minimum_route_alternatives,
            "maximum_route_endpoint_offset_m": (
                config.maximum_route_endpoint_offset_m
            ),
            "route_selection_profile": config.route_selection_profile,
            "input_fingerprint": input_fingerprint,
            "points": canonical_points,
            "scenarios": canonical_scenarios,
            "flows": canonical_flows,
            "desire_lines": desire_lines,
            "filter_outcomes": filter_outcomes,
            "sensitivity_results": sensitivity_results,
            "route_alternatives": route_alternatives,
            "route_selections": route_selections,
            "network_reconciliations": reconciliations,
            "coverage_gaps": coverage_gaps,
            "network_density": network_density,
            "conformance_artifacts": conformance_artifacts,
            "artifacts": artifacts,
        }
        manifest = DemandAnalysisManifest(
            **payload,
            analysis_fingerprint=_fingerprint(payload),
        )
        _write_json(
            temporary / "demand-manifest.json",
            manifest.model_dump(mode="json"),
        )
        validate_demand_bundle(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_demand_bundle(path: Path) -> DemandAnalysisManifest:
    """Cross-validate one demand bundle, including all derived review artifacts."""
    manifest_path = path / "demand-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("invalid demand bundle: missing demand-manifest.json")
    manifest = DemandAnalysisManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    expected_files = {"demand-manifest.json"}
    for artifact in manifest.artifacts:
        expected_files.add(artifact.path)
        artifact_path = path / artifact.path
        if not artifact_path.is_file():
            raise ValueError(f"invalid demand bundle: missing {artifact.path}")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact.sha256:
            raise ValueError(f"invalid demand bundle: {artifact.path} content hash mismatch")
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("invalid demand bundle file set")

    expected_network = _network_geojson(
        manifest.points,
        manifest.desire_lines,
        manifest.route_alternatives,
        manifest.coverage_gaps,
    )
    if json.loads((path / "demand-network.geojson").read_text()) != _json_payload(
        expected_network
    ):
        raise ValueError("demand network GeoJSON does not match the manifest")
    selection_payload = json.loads((path / "route-selection.json").read_text())
    if selection_payload != _json_payload(
        {
            "route_alternatives": manifest.route_alternatives,
            "route_selections": manifest.route_selections,
            "network_reconciliations": manifest.network_reconciliations,
            "coverage_gaps": manifest.coverage_gaps,
            "network_density": manifest.network_density,
            "route_selection_profile": manifest.route_selection_profile,
        }
    ):
        raise ValueError("route-selection artifact does not match the manifest")
    sensitivity_payload = json.loads((path / "sensitivity.json").read_text())
    if sensitivity_payload != _json_payload(
        {
            "scale_filters": manifest.scale_filters,
            "sensitivity_cases": manifest.sensitivity_cases,
            "filter_outcomes": manifest.filter_outcomes,
            "sensitivity_results": manifest.sensitivity_results,
        }
    ):
        raise ValueError("sensitivity artifact does not match the manifest")
    conformance_payload = json.loads(
        (path / "conformance-artifacts.json").read_text()
    )
    if conformance_payload != _json_payload(
        {"artifacts": manifest.conformance_artifacts}
    ):
        raise ValueError("conformance artifacts do not match the manifest")
    expected_html = _review_map_html(
        manifest.analysis_id,
        manifest.points,
        manifest.desire_lines,
        manifest.route_alternatives,
        manifest.coverage_gaps,
    )
    if (path / "review-map.html").read_text(encoding="utf-8") != expected_html:
        raise ValueError("demand review map does not match the manifest")
    return manifest


def load_demand_conformance_artifacts(path: Path) -> tuple[ArtifactLink, ...]:
    """Load profile-compatible artifact links after validating the entire bundle."""
    return validate_demand_bundle(path).conformance_artifacts


# Planning implementation


def _validate_analysis_scope(
    config: DemandAnalysisConfig, evidence: EvidenceSnapshotManifest
) -> None:
    if evidence.council_id != config.council_id:
        raise ValueError("demand analysis council does not match the Evidence Registry")
    if evidence.profile_id != config.guidance_profile_id:
        raise ValueError(
            "demand analysis Guidance Profile does not match the Evidence Registry"
        )


def _validate_local_satn_artifact(satn: SatnNetworkHypothesis) -> None:
    parsed = urlsplit(satn.artifact.uri)
    if parsed.scheme != "file":
        return
    artifact_path = Path(unquote(parsed.path))
    if not artifact_path.is_file():
        raise ValueError("local SATN hypothesis artifact is not a file")
    payload_bytes = artifact_path.read_bytes()
    if hashlib.sha256(payload_bytes).hexdigest() != satn.artifact.sha256:
        raise ValueError("local SATN hypothesis artifact content hash mismatch")
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(
            "local SATN hypothesis artifact is not readable public GeoJSON"
        ) from error
    if (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or not isinstance(payload.get("features"), list)
    ):
        raise ValueError(
            "local SATN hypothesis artifact is not a GeoJSON FeatureCollection"
        )
    features: dict[str, dict[str, Any]] = {}
    for feature in payload["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("local SATN public GeoJSON contains an invalid feature")
        feature_id = feature.get("id")
        if isinstance(feature_id, bool) or not isinstance(feature_id, (str, int)):
            raise ValueError("local SATN public GeoJSON feature has no stable ID")
        normalized_id = str(feature_id).strip()
        if not normalized_id or normalized_id in features:
            raise ValueError(
                "local SATN public GeoJSON feature IDs must be nonblank and unique"
            )
        features[normalized_id] = feature
    for reference in satn.features:
        feature = features.get(reference.feature_id)
        if feature is None:
            raise ValueError(
                f"local SATN artifact has no referenced feature "
                f"{reference.feature_id!r}"
            )
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(
                f"local SATN feature {reference.feature_id!r} has no properties"
            )
        if properties.get("feature_type") != reference.feature_type:
            raise ValueError(
                f"local SATN feature {reference.feature_id!r} type does not "
                "match its public reference"
            )
        if properties.get("network_role") != reference.network_role:
            raise ValueError(
                f"local SATN feature {reference.feature_id!r} network role does "
                "not match its public reference"
            )


def _canonical_records(
    records: Iterable[Any],
    model: type[DemandContract],
    identifier_field: str,
    label: str,
) -> tuple[Any, ...]:
    validated = tuple(model.model_validate(record) for record in records)
    identifiers = tuple(getattr(record, identifier_field) for record in validated)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return tuple(sorted(validated, key=lambda record: getattr(record, identifier_field)))


def _validate_inputs(
    points: tuple[DemandPoint, ...],
    scenarios: tuple[DemandScenario, ...],
    flows: tuple[DemandFlow, ...],
    config: DemandAnalysisConfig,
    governed_evidence: dict[str, Any],
) -> None:
    point_ids = {point.point_id for point in points}
    scenario_ids = {scenario.scenario_id for scenario in scenarios}
    flow_units: dict[tuple[str, str, str], set[str]] = {}
    all_records: tuple[Any, ...] = (*points, *scenarios, *flows, *config.decisions)
    for record in all_records:
        evidence_ids = getattr(record, "source_evidence_ids", None)
        if evidence_ids is None:
            evidence_ids = getattr(record, "evidence_ids", ())
        for evidence_id in evidence_ids:
            if evidence_id not in governed_evidence:
                raise ValueError(
                    f"evidence {evidence_id!r} is not present in the Evidence Registry"
                )
    for flow in flows:
        if flow.origin_id not in point_ids or flow.destination_id not in point_ids:
            raise ValueError("demand flow endpoints must resolve to configured OD points")
        if flow.scenario_id not in scenario_ids:
            raise ValueError("demand flow scenario must resolve to a configured scenario")
        key = (flow.scenario_id, flow.origin_id, flow.destination_id)
        flow_units.setdefault(key, set()).add(flow.unit)
    if any(len(units) > 1 for units in flow_units.values()):
        raise ValueError(
            "conflicting demand-flow units cannot be aggregated for one "
            "scenario and OD pair"
        )


def _derive_desire_lines(
    points: tuple[DemandPoint, ...],
    flows: tuple[DemandFlow, ...],
    config: DemandAnalysisConfig,
) -> tuple[
    tuple[DesireLineRecord, ...],
    tuple[FilterOutcome, ...],
    tuple[SensitivityResult, ...],
]:
    point_by_id = {point.point_id: point for point in points}
    grouped: dict[tuple[str, str, str, str], list[DemandFlow]] = {}
    for flow in flows:
        key = (flow.scenario_id, flow.origin_id, flow.destination_id, flow.unit)
        grouped.setdefault(key, []).append(flow)
    desire_lines: list[DesireLineRecord] = []
    outcomes: list[FilterOutcome] = []
    for (scenario_id, origin_id, destination_id, unit), grouped_flows in sorted(
        grouped.items()
    ):
        origin = point_by_id[origin_id]
        destination = point_by_id[destination_id]
        distance = _haversine_km(origin, destination)
        trips = sum(flow.trips for flow in grouped_flows)
        flow_ids = tuple(sorted(flow.flow_id for flow in grouped_flows))
        evidence_ids = tuple(
            sorted(
                {
                    evidence_id
                    for flow in grouped_flows
                    for evidence_id in flow.source_evidence_ids
                }
            )
        )
        for scale_filter in config.scales:
            desire_id = (
                f"desire-{scenario_id}-{scale_filter.scale}-{origin_id}-{destination_id}"
            )
            equality_override = (
                scale_filter.protect_equality_access
                and (origin.equality_relevant or destination.equality_relevant)
            )
            line_outcomes = _filter_outcomes(
                desire_id,
                distance,
                trips,
                scale_filter.minimum_distance_km,
                scale_filter.maximum_distance_km,
                scale_filter.minimum_trips,
                equality_override,
            )
            retained = all(
                outcome.passed or outcome.overridden_by_equality_access
                for outcome in line_outcomes
            )
            if retained and not any(
                item.overridden_by_equality_access for item in line_outcomes
            ):
                retention_reasons = (
                    "Retained by configured scale and trip filters.",
                )
            elif retained:
                retention_reasons = (
                    "Retained to protect equality-relevant access from a "
                    "single demand threshold.",
                )
            else:
                retention_reasons = (
                    "Retained in the unsimplified long list but filtered "
                    "from base routing by configured assumptions.",
                )
            desire_lines.append(
                DesireLineRecord(
                    desire_line_id=desire_id,
                    scenario_id=scenario_id,
                    scale=scale_filter.scale,
                    origin_id=origin_id,
                    destination_id=destination_id,
                    trips=trips,
                    unit=unit,
                    straight_line_distance_km=round(distance, 6),
                    flow_lineage=flow_ids,
                    source_evidence_ids=evidence_ids,
                    transformation_version=config.transformation_version,
                    retained=retained,
                    retention_reasons=retention_reasons,
                )
            )
            outcomes.extend(line_outcomes)
    canonical_lines = tuple(sorted(desire_lines, key=lambda item: item.desire_line_id))
    sensitivity: list[SensitivityResult] = []
    for case in config.sensitivity_cases:
        base_retained = {
            line.desire_line_id
            for line in canonical_lines
            if line.scale is case.scale and line.retained
        }
        retained_ids: list[str] = []
        for line in canonical_lines:
            if line.scale is not case.scale:
                continue
            origin = point_by_id[line.origin_id]
            destination = point_by_id[line.destination_id]
            protects_equality = next(
                scale.protect_equality_access
                for scale in config.scales
                if scale.scale is case.scale
            ) and (origin.equality_relevant or destination.equality_relevant)
            case_outcomes = _filter_outcomes(
                line.desire_line_id,
                line.straight_line_distance_km,
                line.trips,
                case.minimum_distance_km,
                case.maximum_distance_km,
                case.minimum_trips,
                protects_equality,
            )
            if all(
                item.passed or item.overridden_by_equality_access
                for item in case_outcomes
            ):
                retained_ids.append(line.desire_line_id)
        retained_set = set(retained_ids)
        sensitivity.append(
            SensitivityResult(
                case_id=case.case_id,
                scale=case.scale,
                retained_desire_line_ids=tuple(sorted(retained_set)),
                changed_from_base_ids=tuple(
                    sorted(retained_set.symmetric_difference(base_retained))
                ),
            )
        )
    return (
        canonical_lines,
        tuple(sorted(outcomes, key=lambda item: (item.desire_line_id, item.rule))),
        tuple(sensitivity),
    )


def _filter_outcomes(
    desire_line_id: str,
    distance: float,
    trips: float,
    minimum_distance: float,
    maximum_distance: float,
    minimum_trips: float,
    equality_override: bool,
) -> tuple[FilterOutcome, ...]:
    return (
        FilterOutcome(
            desire_line_id=desire_line_id,
            rule="minimum-distance-km",
            configured_value=minimum_distance,
            observed_value=distance,
            passed=distance >= minimum_distance,
        ),
        FilterOutcome(
            desire_line_id=desire_line_id,
            rule="maximum-distance-km",
            configured_value=maximum_distance,
            observed_value=distance,
            passed=distance <= maximum_distance,
        ),
        FilterOutcome(
            desire_line_id=desire_line_id,
            rule="minimum-trips",
            configured_value=minimum_trips,
            observed_value=trips,
            passed=trips >= minimum_trips,
            overridden_by_equality_access=(
                equality_override and trips < minimum_trips
            ),
        ),
    )


def _route_and_reconcile(
    config: DemandAnalysisConfig,
    points: tuple[DemandPoint, ...],
    desire_lines: tuple[DesireLineRecord, ...],
    satn: SatnNetworkHypothesis,
    routing_boundary: DemandRoutingBoundary,
    governed_evidence: dict[str, Any],
) -> tuple[
    tuple[PlannedRouteAlternative, ...],
    tuple[RouteSelectionRecord, ...],
    tuple[NetworkReconciliation, ...],
    tuple[NetworkCoverageGap, ...],
]:
    point_by_id = {point.point_id: point for point in points}
    decisions = {decision.desire_line_id: decision for decision in config.decisions}
    known_satn_features = {
        feature.public_identifier: feature for feature in satn.features
    }
    planned: list[PlannedRouteAlternative] = []
    selections: list[RouteSelectionRecord] = []
    reconciliations: list[NetworkReconciliation] = []
    point_status: dict[str, str] = {}
    routed_desire_ids: set[str] = set()
    for desire_line in desire_lines:
        if not desire_line.retained:
            point_status.setdefault(desire_line.origin_id, "demand-filtered")
            point_status.setdefault(desire_line.destination_id, "demand-filtered")
            continue
        routed_desire_ids.add(desire_line.desire_line_id)
        request = RoutingRequest(
            desire_line_id=desire_line.desire_line_id,
            scale=desire_line.scale,
            origin=point_by_id[desire_line.origin_id],
            destination=point_by_id[desire_line.destination_id],
            maximum_alternatives=config.maximum_route_alternatives,
            satn=satn,
        )
        supplied = tuple(
            RoutedAlternative.model_validate(item)
            for item in routing_boundary.route_alternatives(request)
        )
        if len(supplied) > config.maximum_route_alternatives:
            raise ValueError(
                "routing boundary exceeded maximum_route_alternatives"
            )
        alternative_ids = tuple(item.alternative_id for item in supplied)
        if len(alternative_ids) != len(set(alternative_ids)):
            raise ValueError("routing boundary alternative IDs must be unique")
        geometries = tuple(item.coordinates for item in supplied)
        if len(geometries) != len(set(geometries)):
            raise ValueError(
                "finite route alternatives must be geometrically distinct"
            )
        for alternative in supplied:
            _validate_route_endpoints(
                alternative,
                request,
                config.maximum_route_endpoint_offset_m,
            )
            if alternative.length_km + 0.001 < _polyline_length_km(
                alternative.coordinates
            ):
                raise ValueError(
                    f"route alternative {alternative.alternative_id!r} length "
                    "is shorter than its geometry"
                )
            for evidence_id in _route_evidence_ids(alternative):
                if evidence_id not in governed_evidence:
                    raise ValueError(
                        f"route evidence {evidence_id!r} is not present in "
                        "the Evidence Registry"
                    )
            for feature in alternative.satn_feature_references:
                expected_feature = known_satn_features.get(feature.public_identifier)
                if expected_feature is None or feature != expected_feature:
                    raise ValueError(
                        f"SATN feature {feature.feature_id!r} is not in the "
                        "SATN hypothesis"
                    )
        preferred_id, decision, selection_unknowns = _select_route(
            desire_line,
            supplied,
            decisions.get(desire_line.desire_line_id),
            config,
        )
        if preferred_id is not None:
            _record_point_status(point_status, desire_line.origin_id, "covered")
            _record_point_status(point_status, desire_line.destination_id, "covered")
        else:
            reason = (
                "no-route-alternatives"
                if not supplied
                else "route-selection-unresolved"
            )
            _record_point_status(point_status, desire_line.origin_id, reason)
            _record_point_status(point_status, desire_line.destination_id, reason)
        planned_for_line: list[PlannedRouteAlternative] = []
        for alternative in supplied:
            unknowns = _selection_unknowns(
                alternative, config.route_selection_profile.selection_condition
            )
            if preferred_id is None:
                disposition = AlternativeDisposition.CANDIDATE
                rejection_reason = None
            elif alternative.alternative_id == preferred_id:
                disposition = AlternativeDisposition.PREFERRED
                rejection_reason = None
            else:
                disposition = AlternativeDisposition.REJECTED
                rejection_reason = (
                    "Potential route quality remains unknown for: "
                    + ", ".join(unknowns)
                    if unknowns and not config.route_selection_profile.allow_unknown
                    else f"Not selected by decision {decision.decision_id}."
                )
            planned_item = PlannedRouteAlternative(
                **alternative.model_dump(),
                desire_line_id=desire_line.desire_line_id,
                route_feature_id=(
                    f"route-{desire_line.desire_line_id}-{alternative.alternative_id}"
                ),
                disposition=disposition,
                rejection_reason=rejection_reason,
                explicit_unknowns=unknowns,
            )
            planned.append(planned_item)
            planned_for_line.append(planned_item)
            reconciliations.extend(
                _reconcile_alternative(desire_line, planned_item)
            )
        selections.append(
            RouteSelectionRecord(
                desire_line_id=desire_line.desire_line_id,
                alternative_ids=tuple(sorted(alternative_ids)),
                preferred_alternative_id=preferred_id,
                audit_status=("preferred" if preferred_id is not None else "unresolved"),
                explicit_unknowns=selection_unknowns,
                decision=decision,
            )
        )
    unused_decisions = set(decisions) - routed_desire_ids
    if unused_decisions:
        raise ValueError(
            "route-selection decisions do not resolve to retained desire lines: "
            + ", ".join(sorted(unused_decisions))
        )

    flow_point_ids = {
        point_id
        for line in desire_lines
        for point_id in (line.origin_id, line.destination_id)
    }
    gaps: list[NetworkCoverageGap] = []
    for point in points:
        if point.point_id not in flow_point_ids:
            reason = "no-governed-flow-evidence"
        else:
            reason = point_status.get(point.point_id, "route-selection-unresolved")
        if reason == "covered":
            continue
        gaps.append(
            NetworkCoverageGap(
                gap_id=f"demand-gap-{point.point_id}",
                point_id=point.point_id,
                reason=reason,
                equality_relevant=point.equality_relevant,
                evidence_ids=point.source_evidence_ids,
            )
        )
    return (
        tuple(sorted(planned, key=lambda item: (item.desire_line_id, item.alternative_id))),
        tuple(sorted(selections, key=lambda item: item.desire_line_id)),
        tuple(
            sorted(
                reconciliations,
                key=lambda item: (
                    item.desire_line_id,
                    item.alternative_id,
                    item.relationship,
                ),
            )
        ),
        tuple(sorted(gaps, key=lambda item: item.gap_id)),
    )


def _record_point_status(
    statuses: dict[str, str],
    point_id: str,
    status: str,
) -> None:
    if statuses.get(point_id) == "covered":
        return
    statuses[point_id] = status


def _select_route(
    desire_line: DesireLineRecord,
    alternatives: tuple[RoutedAlternative, ...],
    supplied_decision: RouteSelectionDecision | None,
    config: DemandAnalysisConfig,
) -> tuple[str | None, RouteSelectionDecision | None, tuple[RouteCriterion, ...]]:
    profile = config.route_selection_profile
    unknowns = tuple(
        criterion
        for criterion in RouteCriterion
        if any(
            criterion
            in _selection_unknowns(alternative, profile.selection_condition)
            for alternative in alternatives
        )
    )
    if len(alternatives) < config.minimum_route_alternatives:
        if supplied_decision is not None:
            raise ValueError(
                "a route decision requires the configured minimum finite alternatives"
            )
        return None, None, unknowns
    by_id = {alternative.alternative_id: alternative for alternative in alternatives}
    eligible = tuple(
        alternative
        for alternative in alternatives
        if profile.allow_unknown
        or not _selection_unknowns(alternative, profile.selection_condition)
    )
    if supplied_decision is not None:
        if supplied_decision.candidate_alternative_ids != tuple(sorted(by_id)):
            raise ValueError(
                "route-selection decision candidate alternatives do not match "
                "the finite routing menu"
            )
        if supplied_decision.candidate_fingerprint != route_candidate_fingerprint(
            alternatives
        ):
            raise ValueError(
                "route-selection decision candidate fingerprint does not match "
                "the finite routing menu"
            )
        if supplied_decision.selected_alternative_id not in by_id:
            raise ValueError("route-selection decision selected an unoffered alternative")
        selected = by_id[supplied_decision.selected_alternative_id]
        if selected not in eligible:
            raise ValueError(
                "route-selection decision cannot conceal unknown route-quality evidence"
            )
        return selected.alternative_id, supplied_decision, unknowns
    if not eligible:
        return None, None, unknowns
    selected = sorted(
        eligible,
        key=lambda alternative: (
            tuple(
                -_criterion_score(
                    alternative, profile.selection_condition, criterion
                )
                for criterion in profile.criterion_order
            ),
            alternative.length_km,
            alternative.alternative_id,
        ),
    )[0]
    decision = RouteSelectionDecision(
        decision_id=f"deterministic-{desire_line.desire_line_id}",
        desire_line_id=desire_line.desire_line_id,
        source=DecisionSource.DETERMINISTIC,
        selected_alternative_id=selected.alternative_id,
        candidate_alternative_ids=tuple(sorted(by_id)),
        candidate_fingerprint=route_candidate_fingerprint(alternatives),
        authority_or_agent="deterministic-demand-planner",
        rationale=(
            f"Selected by route-selection profile {profile.profile_id} "
            f"{profile.version} using its explicit criterion order."
        ),
        evidence_ids=tuple(
            sorted(
                set(selected.evidence_ids)
                | {
                    evidence_id
                    for assessment in _quality_for(
                        selected, profile.selection_condition
                    ).criteria
                    for evidence_id in assessment.evidence_ids
                }
            )
        ),
    )
    return selected.alternative_id, decision, unknowns


def _quality_for(
    alternative: RoutedAlternative, condition: RouteCondition
) -> RouteQualityAssessment:
    return (
        alternative.current_quality
        if condition is RouteCondition.CURRENT
        else alternative.potential_quality
    )


def _base_route_alternative(
    alternative: PlannedRouteAlternative,
) -> RoutedAlternative:
    return RoutedAlternative.model_validate(
        alternative.model_dump(
            include=set(RoutedAlternative.model_fields),
        )
    )


def _selection_unknowns(
    alternative: RoutedAlternative, condition: RouteCondition
) -> tuple[RouteCriterion, ...]:
    return _quality_for(alternative, condition).explicit_unknowns


def _criterion_score(
    alternative: RoutedAlternative,
    condition: RouteCondition,
    criterion: RouteCriterion,
) -> int:
    assessment = next(
        item
        for item in _quality_for(alternative, condition).criteria
        if item.criterion is criterion
    )
    return assessment.score if assessment.score is not None else -1


def _validate_route_endpoints(
    alternative: RoutedAlternative,
    request: RoutingRequest,
    maximum_offset_m: float,
) -> None:
    origin_offset = (
        _coordinate_distance_km(
            (request.origin.longitude, request.origin.latitude),
            alternative.coordinates[0],
        )
        * 1000
    )
    destination_offset = (
        _coordinate_distance_km(
            (request.destination.longitude, request.destination.latitude),
            alternative.coordinates[-1],
        )
        * 1000
    )
    if origin_offset > maximum_offset_m or destination_offset > maximum_offset_m:
        raise ValueError(
            f"route alternative {alternative.alternative_id!r} endpoint offset "
            "exceeds maximum_route_endpoint_offset_m"
        )


def _route_evidence_ids(alternative: RoutedAlternative) -> set[str]:
    identifiers = set(alternative.evidence_ids)
    for quality in (alternative.current_quality, alternative.potential_quality):
        for criterion in quality.criteria:
            identifiers.update(criterion.evidence_ids)
    return identifiers


def _derive_network_density(
    points: tuple[DemandPoint, ...],
    scenarios: tuple[DemandScenario, ...],
    scale_filters: tuple[ScaleFilter, ...],
    desire_lines: tuple[DesireLineRecord, ...],
    alternatives: tuple[PlannedRouteAlternative, ...],
    selections: tuple[RouteSelectionRecord, ...],
) -> tuple[NetworkDensityRecord, ...]:
    selected_by_desire = {
        selection.desire_line_id: selection.preferred_alternative_id
        for selection in selections
        if selection.preferred_alternative_id is not None
    }
    alternative_by_key = {
        (item.desire_line_id, item.alternative_id): item for item in alternatives
    }
    records: list[NetworkDensityRecord] = []
    scales = tuple(item.scale for item in scale_filters)
    point_ids = {point.point_id for point in points}
    for scenario in scenarios:
        for scale in scales:
            retained = tuple(
                line
                for line in desire_lines
                if line.scenario_id == scenario.scenario_id
                and line.scale is scale
                and line.retained
            )
            selected_lines = tuple(
                line for line in retained if line.desire_line_id in selected_by_desire
            )
            covered_ids = {
                point_id
                for line in selected_lines
                for point_id in (line.origin_id, line.destination_id)
            }
            preferred_length = sum(
                alternative_by_key[
                    (
                        line.desire_line_id,
                        selected_by_desire[line.desire_line_id],
                    )
                ].length_km
                for line in selected_lines
            )
            records.append(
                NetworkDensityRecord(
                    density_id=f"density-{scenario.scenario_id}-{scale}",
                    scenario_id=scenario.scenario_id,
                    scale=scale,
                    retained_desire_line_count=len(retained),
                    preferred_route_count=len(selected_lines),
                    covered_point_count=len(covered_ids),
                    total_point_count=len(point_ids),
                    coverage_ratio=(
                        round(len(covered_ids) / len(point_ids), 6)
                        if point_ids
                        else 0
                    ),
                    preferred_route_length_km=round(preferred_length, 6),
                    gap_point_ids=tuple(sorted(point_ids - covered_ids)),
                )
            )
    return tuple(records)


def _reconcile_alternative(
    desire_line: DesireLineRecord,
    alternative: PlannedRouteAlternative,
) -> tuple[NetworkReconciliation, ...]:
    if alternative.network_source is RouteNetworkSource.LOCAL:
        return (
            NetworkReconciliation(
                desire_line_id=desire_line.desire_line_id,
                alternative_id=alternative.alternative_id,
                relationship="local-network",
                divergence_reported=True,
                rationale=(
                    "A governed local-network alternative diverges from the SATN "
                    "hypothesis and is retained for review."
                ),
            ),
        )
    if alternative.network_source is RouteNetworkSource.EXTERNAL:
        return (
            NetworkReconciliation(
                desire_line_id=desire_line.desire_line_id,
                alternative_id=alternative.alternative_id,
                relationship="external-network",
                divergence_reported=True,
                rationale=(
                    "A governed external-network alternative is reported alongside "
                    "the SATN hypothesis."
                ),
            ),
        )
    relationships: dict[str, list[str]] = {}
    for feature in alternative.satn_feature_references:
        relationship = _satn_relationship(feature)
        relationships.setdefault(relationship, []).append(feature.feature_id)
    return tuple(
        NetworkReconciliation(
            desire_line_id=desire_line.desire_line_id,
            alternative_id=alternative.alternative_id,
            relationship=relationship,
            satn_feature_ids=tuple(sorted(feature_ids)),
            divergence_reported=relationship in {"network-gap", "unmatched-satn"},
            rationale=(
                "Demand-led routing encounters a published SATN Network Gap; "
                "the divergence remains visible."
                if relationship == "network-gap"
                else (
                    "Demand-led routing uses the governed SATN hypothesis."
                    if relationship
                    in {
                        "strategic-spine",
                        "access-branch",
                        "cross-spine-connector",
                    }
                    else "The SATN feature role is unmatched and requires review."
                )
            ),
        )
        for relationship, feature_ids in sorted(relationships.items())
    )


def _satn_relationship(feature: PublishedNetworkFeatureReference) -> str:
    values = {
        (feature.feature_type or "").lower(),
        (feature.network_role or "").lower(),
    }
    joined = " ".join(values)
    if "network-gap" in joined or joined.strip() == "gap":
        return "network-gap"
    if "cross-spine" in joined or "branch-meeting" in joined:
        return "cross-spine-connector"
    if "access" in joined or "branch" in joined:
        return "access-branch"
    if "spine" in joined:
        return "strategic-spine"
    return "unmatched-satn"


# Publication and verification


def _network_geojson(
    points: tuple[DemandPoint, ...],
    desire_lines: tuple[DesireLineRecord, ...],
    alternatives: tuple[PlannedRouteAlternative, ...],
    gaps: tuple[NetworkCoverageGap, ...],
) -> dict[str, Any]:
    point_by_id = {point.point_id: point for point in points}
    features: list[dict[str, Any]] = []
    for point in points:
        features.append(
            {
                "type": "Feature",
                "id": f"demand-point-{point.point_id}",
                "properties": {
                    "feature_type": "demand-point",
                    "point_id": point.point_id,
                    "name": point.name,
                    "inside_study_area": point.inside_study_area,
                    "equality_relevant": point.equality_relevant,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [point.longitude, point.latitude],
                },
            }
        )
    for line in desire_lines:
        origin = point_by_id[line.origin_id]
        destination = point_by_id[line.destination_id]
        features.append(
            {
                "type": "Feature",
                "id": line.desire_line_id,
                "properties": {
                    "feature_type": "cycling-desire-line",
                    "scenario_id": line.scenario_id,
                    "scale": line.scale,
                    "trips": line.trips,
                    "unit": line.unit,
                    "retained": line.retained,
                    "flow_lineage": list(line.flow_lineage),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [origin.longitude, origin.latitude],
                        [destination.longitude, destination.latitude],
                    ],
                },
            }
        )
    for alternative in alternatives:
        features.append(
            {
                "type": "Feature",
                "id": alternative.route_feature_id,
                "properties": {
                    "feature_type": "route-alternative",
                    "desire_line_id": alternative.desire_line_id,
                    "alternative_id": alternative.alternative_id,
                    "network_source": alternative.network_source,
                    "disposition": alternative.disposition,
                    "explicit_unknowns": list(alternative.explicit_unknowns),
                    "satn_feature_ids": [
                        feature.feature_id
                        for feature in alternative.satn_feature_references
                    ],
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(coordinate) for coordinate in alternative.coordinates],
                },
            }
        )
    for gap in gaps:
        point = point_by_id[gap.point_id]
        features.append(
            {
                "type": "Feature",
                "id": gap.gap_id,
                "properties": {
                    "feature_type": "demand-coverage-gap",
                    "point_id": gap.point_id,
                    "reason": gap.reason,
                    "equality_relevant": gap.equality_relevant,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [point.longitude, point.latitude],
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": sorted(features, key=lambda feature: feature["id"]),
    }


def _review_map_html(
    analysis_id: str,
    points: tuple[DemandPoint, ...],
    desire_lines: tuple[DesireLineRecord, ...],
    alternatives: tuple[PlannedRouteAlternative, ...],
    gaps: tuple[NetworkCoverageGap, ...],
) -> str:
    all_coordinates = [
        (point.longitude, point.latitude) for point in points
    ] + [
        coordinate
        for alternative in alternatives
        for coordinate in alternative.coordinates
    ]
    if not all_coordinates:
        all_coordinates = [(0.0, 0.0), (1.0, 1.0)]
    min_x = min(item[0] for item in all_coordinates)
    max_x = max(item[0] for item in all_coordinates)
    min_y = min(item[1] for item in all_coordinates)
    max_y = max(item[1] for item in all_coordinates)
    span_x = max(max_x - min_x, 0.001)
    span_y = max(max_y - min_y, 0.001)

    def project(coordinate: Coordinate) -> tuple[float, float]:
        x = 20 + ((coordinate[0] - min_x) / span_x) * 760
        y = 20 + ((max_y - coordinate[1]) / span_y) * 460
        return (round(x, 2), round(y, 2))

    point_by_id = {point.point_id: point for point in points}
    svg_lines: list[str] = []
    for line in desire_lines:
        origin = point_by_id[line.origin_id]
        destination = point_by_id[line.destination_id]
        left = project((origin.longitude, origin.latitude))
        right = project((destination.longitude, destination.latitude))
        css = "desire retained" if line.retained else "desire filtered"
        svg_lines.append(
            f'<line class="{css}" x1="{left[0]}" y1="{left[1]}" '
            f'x2="{right[0]}" y2="{right[1]}"><title>'
            f"{html.escape(line.desire_line_id)}</title></line>"
        )
    for alternative in alternatives:
        coordinates = " ".join(
            f"{x},{y}" for x, y in (project(item) for item in alternative.coordinates)
        )
        svg_lines.append(
            f'<polyline class="route {alternative.disposition}" points="{coordinates}">'
            f"<title>{html.escape(alternative.alternative_id)} "
            f"({alternative.disposition})</title></polyline>"
        )
    for point in points:
        x, y = project((point.longitude, point.latitude))
        svg_lines.append(
            f'<circle class="point" cx="{x}" cy="{y}" r="5"><title>'
            f"{html.escape(point.name)}</title></circle>"
        )
    rows = []
    for line in desire_lines:
        rows.append(
            (
                line.desire_line_id,
                "desire line",
                "retained" if line.retained else "filtered",
            )
        )
    for alternative in alternatives:
        rows.append(
            (
                alternative.route_feature_id,
                "route alternative",
                str(alternative.disposition),
            )
        )
    for gap in gaps:
        rows.append((gap.gap_id, "coverage gap", gap.reason))
    table_rows = "\n".join(
        "<tr>"
        f"<th scope=\"row\"><code>{html.escape(identifier)}</code></th>"
        f"<td>{html.escape(kind)}</td><td>{html.escape(status)}</td>"
        "</tr>"
        for identifier, kind, status in sorted(rows)
    )
    svg = "\n".join(svg_lines)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LCWIP demand review map — {html.escape(analysis_id)}</title>
<style>
body{{font:16px system-ui;margin:0;color:#17202a;background:#f8fafc}}
main{{max-width:1100px;margin:auto;padding:1rem}}
svg{{width:100%;border:1px solid #64748b;background:#fff}}
.desire{{stroke:#64748b;stroke-width:2;stroke-dasharray:7 5}}.filtered{{opacity:.35}}
.route{{fill:none;stroke-width:5}}.preferred{{stroke:#0f766e}}.rejected{{stroke:#b91c1c;opacity:.65}}
.candidate{{stroke:#a16207}}.point{{fill:#1d4ed8;stroke:#fff;stroke-width:2}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #cbd5e1;padding:.4rem;text-align:left}}
</style>
</head>
<body><main>
<h1>LCWIP demand review map</h1>
<p><strong>Analysis:</strong> <code>{html.escape(analysis_id)}</code></p>
<p>SATN divergence is reported, never silently resolved. Current-condition and
potential-design-outcome assessments remain separate. This is planning evidence,
not detailed design, feasibility, priority or adoption.</p>
<svg role="img" aria-label="Demand points, desire lines and route alternatives"
viewBox="0 0 800 500">{svg}</svg>
<h2>Inspectable feature register</h2>
<table><thead><tr><th>Stable ID</th><th>Kind</th><th>Status</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p><a href="demand-network.geojson">Download demand network GeoJSON</a></p>
</main></body></html>
"""


def _conformance_artifacts(analysis_id: str) -> tuple[ArtifactLink, ...]:
    return (
        ArtifactLink(
            artifact_id=f"{analysis_id}-baseline-evidence",
            uri=f"bundle://{analysis_id}/demand-manifest.json",
            kind="baseline-evidence",
        ),
        ArtifactLink(
            artifact_id=f"{analysis_id}-cycling-network-plan",
            uri=f"bundle://{analysis_id}/review-map.html",
            kind="cycling-network-plan",
        ),
    )


# Canonicalization and geometry utilities


def _haversine_km(origin: DemandPoint, destination: DemandPoint) -> float:
    return _coordinate_distance_km(
        (origin.longitude, origin.latitude),
        (destination.longitude, destination.latitude),
    )


def _polyline_length_km(coordinates: tuple[Coordinate, ...]) -> float:
    return sum(
        _coordinate_distance_km(left, right)
        for left, right in pairwise(coordinates)
    )


def _coordinate_distance_km(
    origin: Coordinate,
    destination: Coordinate,
) -> float:
    radius_km = 6371.0088
    latitude_1 = math.radians(origin[1])
    latitude_2 = math.radians(destination[1])
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(destination[0] - origin[0])
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_1)
        * math.cos(latitude_2)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(haversine))


def _stable_boundary_identifier(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("routing boundary ID must be a stable identifier")
    value = value.strip()
    if (
        not value
        or not value[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in value)
    ):
        raise ValueError("routing boundary ID must be a stable identifier")
    return value


def _nonblank_boundary_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank")
    return value.strip()


def _canonical_unique(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(value))


def _unique_record_ids(
    records: tuple[Any, ...],
    attribute: str,
    label: str,
) -> set[str]:
    identifiers = tuple(getattr(record, attribute) for record in records)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return set(identifiers)


def _json_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_payload(item) for item in value]
    if isinstance(value, StrEnum):
        return str(value)
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
        json.dumps(_json_payload(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
