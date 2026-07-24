"""Evidence-bound infrastructure concepts for strategic LCWIP appraisal."""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import tempfile
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

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


class InterventionContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0"] = "1.0"


class SourceWorkflow(StrEnum):
    CYCLING = "cycling"
    WALKING_WHEELING = "walking-wheeling"
    SATN = "satn"
    OTHER_GOVERNED = "other-governed"


class ProgrammeMode(StrEnum):
    CYCLING = "cycling"
    WALKING = "walking"
    WHEELING = "wheeling"


class ProgrammeUser(StrEnum):
    CYCLIST = "cyclist"
    PEDESTRIAN = "pedestrian"
    WHEELCHAIR_USER = "wheelchair-user"
    MOBILITY_AID_USER = "mobility-aid-user"
    VISUALLY_IMPAIRED_USER = "visually-impaired-user"
    CHILD = "child"


class InterventionFamily(StrEnum):
    ROUTE_SECTION = "route-section"
    JUNCTION = "junction"
    CROSSING = "crossing"
    AREA_MEASURE = "area-measure"
    SUPPORTING_INFRASTRUCTURE = "supporting-infrastructure"
    WAYFINDING = "wayfinding"
    MAINTENANCE = "maintenance"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConstraintTopic(StrEnum):
    LAND_HIGHWAY_RIGHTS = "land-highway-rights"
    ENVIRONMENT_HERITAGE = "environment-heritage"
    UTILITIES = "utilities"
    TRAFFIC = "traffic"
    DEPENDENCIES = "dependencies"
    MAINTENANCE = "maintenance"
    SURVEY_DESIGN = "survey-design"


class ConstraintState(StrEnum):
    KNOWN_CLEAR = "known-clear"
    KNOWN_CONSTRAINT = "known-constraint"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


class InterventionStatus(StrEnum):
    STRATEGIC_OPTION = "strategic-option"
    CONCEPT = "concept"
    FEASIBLE = "feasible"
    DESIGNED = "designed"


class HumanVerification(InterventionContract):
    verification_id: StableIdentifier
    authority_name: NonBlankText
    authority_role: NonBlankText
    verified_on: date
    rationale: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def canonical_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "human-verification evidence IDs")


class CatalogueEntry(InterventionContract):
    catalogue_item_id: StableIdentifier
    version: NonBlankText
    family: InterventionFamily
    title: NonBlankText
    permitted_geometry_types: tuple[Literal["point", "line", "polygon"], ...] = Field(
        min_length=1
    )
    supported_modes: tuple[ProgrammeMode, ...] = Field(min_length=1)
    supported_users: tuple[ProgrammeUser, ...] = Field(min_length=1)
    strategic_scope: NonBlankText
    excluded_detailed_scope: tuple[NonBlankText, ...] = Field(min_length=1)

    @field_validator(
        "permitted_geometry_types",
        "supported_modes",
        "supported_users",
        "excluded_detailed_scope",
    )
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return _canonical_unique(value, "catalogue entry values")


class InterventionCatalogue(InterventionContract):
    catalogue_id: StableIdentifier
    version: NonBlankText
    entries: tuple[CatalogueEntry, ...] = Field(min_length=1)

    @field_validator("entries")
    @classmethod
    def canonical_entries(
        cls, value: tuple[CatalogueEntry, ...]
    ) -> tuple[CatalogueEntry, ...]:
        keys = tuple((entry.catalogue_item_id, entry.version) for entry in value)
        if len(keys) != len(set(keys)):
            raise ValueError("intervention catalogue entries must be unique")
        return tuple(sorted(value, key=lambda item: (item.catalogue_item_id, item.version)))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))


class DeficiencyReference(InterventionContract):
    deficiency_id: StableIdentifier
    source_workflow: SourceWorkflow
    source_artifact: ArtifactLink
    source_fingerprint: Sha256Hex
    source_record_id: StableIdentifier
    subject_id: StableIdentifier
    description: NonBlankText
    modes: tuple[ProgrammeMode, ...] = Field(min_length=1)
    users_served: tuple[ProgrammeUser, ...] = Field(min_length=1)
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    accepted_by: HumanVerification

    @field_validator("modes", "users_served", "evidence_ids")
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return _canonical_unique(value, "deficiency-reference values")


class DesiredOutcome(InterventionContract):
    outcome_id: StableIdentifier
    statement: NonBlankText
    success_measure: NonBlankText
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    assumptions: tuple[NonBlankText, ...] = Field(min_length=1)
    unknowns: tuple[NonBlankText, ...]

    @field_validator("evidence_ids", "assumptions", "unknowns")
    @classmethod
    def canonical_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "desired-outcome values")


class ConceptGeometry(InterventionContract):
    geometry_type: Literal["point", "line", "polygon"]
    coordinates: tuple[Coordinate, ...]

    @model_validator(mode="after")
    def geometry_shape(self) -> Self:
        if self.geometry_type == "point" and len(self.coordinates) != 1:
            raise ValueError("point concept geometry requires exactly one coordinate")
        if self.geometry_type == "line" and len(self.coordinates) < 2:
            raise ValueError("line concept geometry requires at least two coordinates")
        if self.geometry_type == "polygon":
            if len(self.coordinates) < 4 or self.coordinates[0] != self.coordinates[-1]:
                raise ValueError("polygon concept geometry must be a closed ring")
            area = abs(
                sum(
                    left[0] * right[1] - right[0] * left[1]
                    for left, right in pairwise(self.coordinates)
                )
            )
            if area == 0:
                raise ValueError("polygon concept geometry must have non-zero area")
        return self


class StageVerification(InterventionContract):
    stage: Literal[InterventionStatus.FEASIBLE, InterventionStatus.DESIGNED]
    verification: HumanVerification


class InterventionConcept(InterventionContract):
    intervention_id: StableIdentifier
    catalogue_item_id: StableIdentifier
    catalogue_item_version: NonBlankText
    title: NonBlankText
    deficiency_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    outcome_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    geometry: ConceptGeometry
    modes: tuple[ProgrammeMode, ...] = Field(min_length=1)
    users_served: tuple[ProgrammeUser, ...] = Field(min_length=1)
    evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    assumptions: tuple[NonBlankText, ...] = Field(min_length=1)
    alternative_intervention_ids: tuple[StableIdentifier, ...] = ()
    depends_on_intervention_ids: tuple[StableIdentifier, ...] = ()
    mutually_exclusive_intervention_ids: tuple[StableIdentifier, ...] = ()
    residual_deficiency_ids: tuple[StableIdentifier, ...] = ()
    cost_range_id: StableIdentifier | None = None
    status: InterventionStatus
    stage_verifications: tuple[StageVerification, ...] = ()
    detailed_design_in_scope: Literal[False] = False

    @field_validator(
        "deficiency_ids",
        "outcome_ids",
        "modes",
        "users_served",
        "evidence_ids",
        "assumptions",
        "alternative_intervention_ids",
        "depends_on_intervention_ids",
        "mutually_exclusive_intervention_ids",
        "residual_deficiency_ids",
    )
    @classmethod
    def canonical_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        return _canonical_unique(value, "intervention-concept values")

    @field_validator("stage_verifications")
    @classmethod
    def canonical_stage_verifications(
        cls, value: tuple[StageVerification, ...]
    ) -> tuple[StageVerification, ...]:
        stages = tuple(item.stage for item in value)
        if len(stages) != len(set(stages)):
            raise ValueError("stage verifications must be unique")
        return tuple(sorted(value, key=lambda item: item.stage))


class CostRange(InterventionContract):
    cost_range_id: StableIdentifier
    intervention_id: StableIdentifier
    currency: Literal["GBP"]
    lower_bound: int = Field(gt=0)
    upper_bound: int = Field(gt=0)
    rounding_increment: int = Field(gt=0)
    price_base_year: int = Field(ge=2000, le=2100)
    basis: NonBlankText
    confidence: ConfidenceLevel
    included_scope: tuple[NonBlankText, ...] = Field(min_length=1)
    excluded_scope: tuple[NonBlankText, ...] = Field(min_length=1)
    quantity_assumptions: tuple[NonBlankText, ...] = Field(min_length=1)
    unknowns: tuple[NonBlankText, ...] = Field(min_length=1)
    source_evidence_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    verified_by: HumanVerification | None

    @field_validator(
        "included_scope",
        "excluded_scope",
        "quantity_assumptions",
        "unknowns",
        "source_evidence_ids",
    )
    @classmethod
    def canonical_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "cost-range values")

    @model_validator(mode="after")
    def honest_range(self) -> Self:
        if self.upper_bound <= self.lower_bound:
            raise ValueError("cost range upper bound must exceed its lower bound")
        if (
            self.lower_bound % self.rounding_increment
            or self.upper_bound % self.rounding_increment
            or self.upper_bound - self.lower_bound < self.rounding_increment
        ):
            raise ValueError(
                "cost range must use its disclosed rounding increment without "
                "false precision"
            )
        return self


class ConstraintAssessment(InterventionContract):
    assessment_id: StableIdentifier
    intervention_id: StableIdentifier
    topic: ConstraintTopic
    state: ConstraintState
    material: bool
    evidence_ids: tuple[StableIdentifier, ...]
    assumptions: tuple[NonBlankText, ...] = Field(min_length=1)
    unknowns: tuple[NonBlankText, ...]
    verified_by: HumanVerification | None

    @field_validator("evidence_ids", "assumptions", "unknowns")
    @classmethod
    def canonical_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "constraint-assessment values")

    @model_validator(mode="after")
    def evidence_state(self) -> Self:
        if self.state is ConstraintState.UNKNOWN:
            if not self.unknowns:
                raise ValueError("unknown constraints require explicit unknowns")
            if self.verified_by is not None:
                raise ValueError("unknown constraints cannot claim human verification")
        elif not self.evidence_ids:
            raise ValueError("known constraint judgements require evidence")
        if (
            self.material
            and self.state is not ConstraintState.UNKNOWN
            and self.verified_by is None
        ):
            raise ValueError(
                "material constraint judgements require human verification"
            )
        return self


class InterventionPackage(InterventionContract):
    package_id: StableIdentifier
    name: NonBlankText
    intervention_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    outcome_ids: tuple[StableIdentifier, ...] = Field(min_length=1)
    depends_on_package_ids: tuple[StableIdentifier, ...] = ()
    mutually_exclusive_package_ids: tuple[StableIdentifier, ...] = ()
    residual_deficiency_ids: tuple[StableIdentifier, ...] = ()
    assumptions: tuple[NonBlankText, ...] = Field(min_length=1)

    @field_validator(
        "intervention_ids",
        "outcome_ids",
        "depends_on_package_ids",
        "mutually_exclusive_package_ids",
        "residual_deficiency_ids",
        "assumptions",
    )
    @classmethod
    def canonical_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_unique(value, "intervention-package values")


class InterventionEvidenceRequest(InterventionContract):
    request_id: StableIdentifier
    intervention_id: StableIdentifier
    kind: Literal["outline-cost", "constraint"]
    topic: ConstraintTopic | None = None
    purpose: NonBlankText

    @model_validator(mode="after")
    def topic_matches_kind(self) -> Self:
        if (self.kind == "constraint") != (self.topic is not None):
            raise ValueError("constraint requests require exactly one topic")
        return self


class InterventionPlanningConfig(InterventionContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot: Path
    output_dir: Path
    transformation_version: NonBlankText
    catalogue: InterventionCatalogue
    catalogue_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def binding(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("Guidance Profile ID does not match its contents")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("Guidance Profile fingerprint does not match its contents")
        if self.catalogue_fingerprint != self.catalogue.fingerprint:
            raise ValueError("intervention catalogue fingerprint does not match")
        return self


class InterventionBundleArtifact(InterventionContract):
    path: NonBlankText
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("intervention bundle paths must remain inside the bundle")
        return value


ARTIFACT_PATHS = (
    "conformance-artifacts.json",
    "costs-and-constraints.json",
    "evidence-requests.json",
    "intervention-concepts.geojson",
    "intervention-packages.json",
    "review-map.html",
)


class InterventionPlanningManifest(InterventionContract):
    analysis_id: StableIdentifier
    council_id: StableIdentifier
    guidance_profile: GuidanceProfile
    guidance_profile_id: StableIdentifier
    guidance_profile_fingerprint: Sha256Hex
    evidence_snapshot_id: StableIdentifier
    evidence_snapshot_fingerprint: Sha256Hex
    transformation_version: NonBlankText
    catalogue: InterventionCatalogue
    catalogue_fingerprint: Sha256Hex
    input_fingerprint: Sha256Hex
    deficiencies: tuple[DeficiencyReference, ...]
    outcomes: tuple[DesiredOutcome, ...]
    concepts: tuple[InterventionConcept, ...]
    costs: tuple[CostRange, ...]
    constraints: tuple[ConstraintAssessment, ...]
    packages: tuple[InterventionPackage, ...]
    evidence_requests: tuple[InterventionEvidenceRequest, ...]
    conformance_artifacts: tuple[ArtifactLink, ...]
    artifacts: tuple[InterventionBundleArtifact, ...]
    analysis_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def relational_integrity(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("manifest Guidance Profile ID does not match")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("manifest Guidance Profile fingerprint does not match")
        if self.catalogue_fingerprint != self.catalogue.fingerprint:
            raise ValueError("manifest catalogue fingerprint does not match")
        deficiency_ids = _unique_ids(
            self.deficiencies, "deficiency_id", "accepted deficiency"
        )
        outcome_ids = _unique_ids(self.outcomes, "outcome_id", "desired outcome")
        concept_ids = _unique_ids(self.concepts, "intervention_id", "intervention")
        cost_ids = _unique_ids(self.costs, "cost_range_id", "cost range")
        _unique_ids(self.packages, "package_id", "package")
        request_ids = _unique_ids(
            self.evidence_requests, "request_id", "intervention evidence request"
        )
        _unique_ids(self.constraints, "assessment_id", "constraint assessment")
        _unique_ids(self.artifacts, "path", "bundle artifact")
        if len({item.intervention_id for item in self.costs}) != len(self.costs):
            raise ValueError("only one cost range is allowed per intervention")
        if set(item.intervention_id for item in self.costs) - concept_ids:
            raise ValueError("cost range intervention must resolve")
        for concept in self.concepts:
            if not set(concept.deficiency_ids).issubset(deficiency_ids):
                raise ValueError("intervention deficiencies must resolve")
            if not set(concept.outcome_ids).issubset(outcome_ids):
                raise ValueError("intervention outcomes must resolve")
            if concept.cost_range_id is not None and concept.cost_range_id not in cost_ids:
                raise ValueError("intervention cost range must resolve")
        if {
            (item.intervention_id, item.topic) for item in self.constraints
        } != {
            (intervention_id, topic)
            for intervention_id in concept_ids
            for topic in ConstraintTopic
        }:
            raise ValueError(
                "constraints must cover every intervention and governed topic"
            )
        for package in self.packages:
            if not set(package.intervention_ids).issubset(concept_ids):
                raise ValueError("package interventions must resolve")
            if not set(package.outcome_ids).issubset(outcome_ids):
                raise ValueError("package outcomes must resolve")
            if not set(package.residual_deficiency_ids).issubset(deficiency_ids):
                raise ValueError("package residual deficiencies must resolve")
        if not concept_ids.issubset(
            {
                intervention_id
                for package in self.packages
                for intervention_id in package.intervention_ids
            }
        ):
            raise ValueError("every intervention concept must belong to a package")
        traced_deficiencies = {
            deficiency_id
            for concept in self.concepts
            for deficiency_id in concept.deficiency_ids
        } | {
            deficiency_id
            for package in self.packages
            for deficiency_id in package.residual_deficiency_ids
        }
        if traced_deficiencies != deficiency_ids:
            raise ValueError("every accepted deficiency must remain traced or residual")
        if set(item.intervention_id for item in self.evidence_requests) - concept_ids:
            raise ValueError("intervention evidence request must resolve")
        if len(request_ids) != len(self.evidence_requests):
            raise ValueError("intervention evidence request IDs must be unique")
        if any(cost.verified_by is None for cost in self.costs):
            raise ValueError("manifest costs require human verification")
        _validate_catalogue(self.catalogue, self.concepts)
        _validate_constraints(self.constraints, self.concepts)
        _validate_relationships(
            self.deficiencies,
            self.outcomes,
            self.concepts,
            self.costs,
            self.constraints,
            self.packages,
        )
        if self.evidence_requests != _evidence_requests(
            self.concepts, self.costs, self.constraints
        ):
            raise ValueError(
                "manifest intervention evidence requests do not match gaps"
            )
        if {item.kind for item in self.conformance_artifacts} != {
            "intervention-packages",
            "programme-appraisal-input",
        }:
            raise ValueError("intervention conformance links are incomplete")
        if {item.path for item in self.artifacts} != set(ARTIFACT_PATHS):
            raise ValueError("intervention bundle artifact set is incomplete")
        return self

    @model_validator(mode="after")
    def fingerprint_matches(self) -> Self:
        expected = _fingerprint(
            self.model_dump(mode="json", exclude={"analysis_fingerprint"})
        )
        if self.analysis_fingerprint != expected:
            raise ValueError("intervention analysis fingerprint does not match")
        return self


def build_intervention_packages(
    config: InterventionPlanningConfig,
    *,
    deficiencies: Iterable[DeficiencyReference],
    outcomes: Iterable[DesiredOutcome],
    concepts: Iterable[InterventionConcept],
    costs: Iterable[CostRange],
    constraints: Iterable[ConstraintAssessment],
    packages: Iterable[InterventionPackage],
) -> Path:
    """Compile accepted deficiencies into immutable strategic concept packages."""
    config = InterventionPlanningConfig.model_validate(config.model_dump())
    evidence = validate_evidence_snapshot(config.evidence_snapshot)
    _validate_scope(config, evidence)
    canonical_deficiencies = _canonical_records(
        deficiencies, DeficiencyReference, "deficiency_id", "accepted deficiency"
    )
    canonical_outcomes = _canonical_records(
        outcomes, DesiredOutcome, "outcome_id", "desired outcome"
    )
    canonical_concepts = _canonical_records(
        concepts, InterventionConcept, "intervention_id", "intervention concept"
    )
    canonical_costs = _canonical_records(
        costs, CostRange, "cost_range_id", "cost range"
    )
    canonical_constraints = _canonical_records(
        constraints,
        ConstraintAssessment,
        "assessment_id",
        "constraint assessment",
    )
    canonical_packages = _canonical_records(
        packages, InterventionPackage, "package_id", "intervention package"
    )
    governed = {
        item.evidence_id: item
        for item in evidence.items
        if item.availability is EvidenceAvailability.AVAILABLE
        and item.public_disposition is not PublicDisposition.EXCLUDE
        and item.access_level is not AccessLevel.PERSONAL
    }
    _validate_evidence_references(
        (
            *canonical_deficiencies,
            *canonical_outcomes,
            *canonical_concepts,
            *canonical_costs,
            *canonical_constraints,
        ),
        governed,
    )
    _validate_catalogue(config.catalogue, canonical_concepts)
    _validate_costs(canonical_costs, canonical_concepts, governed)
    _validate_constraints(canonical_constraints, canonical_concepts)
    _validate_relationships(
        canonical_deficiencies,
        canonical_outcomes,
        canonical_concepts,
        canonical_costs,
        canonical_constraints,
        canonical_packages,
    )
    evidence_requests = _evidence_requests(
        canonical_concepts, canonical_costs, canonical_constraints
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
            "catalogue": config.catalogue,
            "catalogue_fingerprint": config.catalogue_fingerprint,
            "deficiencies": canonical_deficiencies,
            "outcomes": canonical_outcomes,
            "concepts": canonical_concepts,
            "costs": canonical_costs,
            "constraints": canonical_constraints,
            "packages": canonical_packages,
        }
    )
    destination = config.output_dir / config.analysis_id
    if destination.exists():
        existing = validate_intervention_bundle(destination)
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError(
                f"intervention analysis {config.analysis_id!r} is immutable "
                "and inputs changed"
            )
        return destination
    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.analysis_id}-", dir=config.output_dir)
    )
    try:
        _write_json(
            temporary / "intervention-concepts.geojson",
            _concept_geojson(canonical_concepts),
        )
        _write_json(
            temporary / "intervention-packages.json",
            {
                "deficiencies": canonical_deficiencies,
                "outcomes": canonical_outcomes,
                "concepts": canonical_concepts,
                "packages": canonical_packages,
            },
        )
        _write_json(
            temporary / "costs-and-constraints.json",
            {"costs": canonical_costs, "constraints": canonical_constraints},
        )
        _write_json(
            temporary / "evidence-requests.json",
            {"evidence_requests": evidence_requests},
        )
        _write_json(
            temporary / "conformance-artifacts.json",
            {"artifacts": conformance_artifacts},
        )
        (temporary / "review-map.html").write_text(
            _review_html(
                config.analysis_id,
                canonical_deficiencies,
                canonical_concepts,
                canonical_packages,
                evidence_requests,
            ),
            encoding="utf-8",
        )
        artifacts = tuple(
            InterventionBundleArtifact(
                path=path,
                sha256=hashlib.sha256((temporary / path).read_bytes()).hexdigest(),
            )
            for path in ARTIFACT_PATHS
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
            "catalogue": config.catalogue,
            "catalogue_fingerprint": config.catalogue_fingerprint,
            "input_fingerprint": input_fingerprint,
            "deficiencies": canonical_deficiencies,
            "outcomes": canonical_outcomes,
            "concepts": canonical_concepts,
            "costs": canonical_costs,
            "constraints": canonical_constraints,
            "packages": canonical_packages,
            "evidence_requests": evidence_requests,
            "conformance_artifacts": conformance_artifacts,
            "artifacts": artifacts,
        }
        manifest = InterventionPlanningManifest(
            **payload,
            analysis_fingerprint=_fingerprint(payload),
        )
        _write_json(
            temporary / "intervention-manifest.json",
            manifest.model_dump(mode="json"),
        )
        validate_intervention_bundle(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_intervention_bundle(path: Path) -> InterventionPlanningManifest:
    path = Path(path)
    manifest_path = path / "intervention-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("invalid intervention bundle: missing manifest")
    try:
        manifest = InterventionPlanningManifest.model_validate_json(
            manifest_path.read_text()
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid intervention bundle: {error}") from error
    expected_files = {"intervention-manifest.json"}
    for artifact in manifest.artifacts:
        expected_files.add(artifact.path)
        artifact_path = path / artifact.path
        if not artifact_path.is_file():
            raise ValueError(f"invalid intervention bundle: missing {artifact.path}")
        if (
            hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            != artifact.sha256
        ):
            raise ValueError(
                f"invalid intervention bundle: {artifact.path} content hash mismatch"
            )
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("invalid intervention bundle: file set mismatch")
    expected_payloads = {
        "intervention-concepts.geojson": _concept_geojson(manifest.concepts),
        "intervention-packages.json": {
            "deficiencies": manifest.deficiencies,
            "outcomes": manifest.outcomes,
            "concepts": manifest.concepts,
            "packages": manifest.packages,
        },
        "costs-and-constraints.json": {
            "costs": manifest.costs,
            "constraints": manifest.constraints,
        },
        "evidence-requests.json": {
            "evidence_requests": manifest.evidence_requests
        },
        "conformance-artifacts.json": {
            "artifacts": manifest.conformance_artifacts
        },
    }
    for filename, expected in expected_payloads.items():
        if json.loads((path / filename).read_text()) != _json_payload(expected):
            raise ValueError(
                f"invalid intervention bundle: {filename} does not match manifest"
            )
    if (path / "review-map.html").read_text() != _review_html(
        manifest.analysis_id,
        manifest.deficiencies,
        manifest.concepts,
        manifest.packages,
        manifest.evidence_requests,
    ):
        raise ValueError("invalid intervention bundle: review map mismatch")
    return manifest


def _validate_scope(
    config: InterventionPlanningConfig,
    evidence: EvidenceSnapshotManifest,
) -> None:
    if evidence.council_id != config.council_id:
        raise ValueError("intervention council does not match Evidence Registry")
    if evidence.profile_id != config.guidance_profile_id:
        raise ValueError("intervention Guidance Profile does not match Evidence Registry")


def _canonical_records(
    records: Iterable[Any],
    model: type[InterventionContract],
    identifier_field: str,
    label: str,
) -> tuple[Any, ...]:
    validated = tuple(model.model_validate(item) for item in records)
    identifiers = tuple(getattr(item, identifier_field) for item in validated)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return tuple(sorted(validated, key=lambda item: getattr(item, identifier_field)))


def _validate_evidence_references(
    records: tuple[Any, ...],
    governed: dict[str, Any],
) -> None:
    for record in records:
        identifiers = list(getattr(record, "evidence_ids", ()))
        identifiers.extend(getattr(record, "source_evidence_ids", ()))
        verifications = [
            getattr(record, "accepted_by", None),
            getattr(record, "verified_by", None),
        ]
        verifications.extend(
            item.verification
            for item in getattr(record, "stage_verifications", ())
        )
        for verification in verifications:
            if verification is not None:
                identifiers.extend(verification.evidence_ids)
        for evidence_id in identifiers:
            if evidence_id not in governed:
                raise ValueError(
                    f"evidence {evidence_id!r} is not publishable governed evidence"
                )


def _validate_catalogue(
    catalogue: InterventionCatalogue,
    concepts: tuple[InterventionConcept, ...],
) -> None:
    entries = {
        (entry.catalogue_item_id, entry.version): entry
        for entry in catalogue.entries
    }
    for concept in concepts:
        entry = entries.get(
            (concept.catalogue_item_id, concept.catalogue_item_version)
        )
        if entry is None:
            raise ValueError("intervention selected an unsupported catalogue entry")
        if concept.geometry.geometry_type not in entry.permitted_geometry_types:
            raise ValueError("intervention geometry is unsupported by its catalogue entry")
        if not set(concept.modes).issubset(entry.supported_modes):
            raise ValueError("intervention mode is unsupported by its catalogue entry")
        if not set(concept.users_served).issubset(entry.supported_users):
            raise ValueError("intervention users are unsupported by its catalogue entry")


def _validate_costs(
    costs: tuple[CostRange, ...],
    concepts: tuple[InterventionConcept, ...],
    governed: dict[str, Any],
) -> None:
    concept_ids = {item.intervention_id for item in concepts}
    if len({item.intervention_id for item in costs}) != len(costs):
        raise ValueError("only one cost range is allowed per intervention")
    for cost in costs:
        if cost.intervention_id not in concept_ids:
            raise ValueError("cost range intervention must resolve")
        if cost.verified_by is None:
            raise ValueError("outline cost judgements require human verification")
        if any(
            governed[evidence_id].role is not EvidenceRole.EXPERT_JUDGEMENT
            for evidence_id in cost.source_evidence_ids
        ):
            raise ValueError("outline cost evidence must be governed expert cost evidence")


def _validate_constraints(
    constraints: tuple[ConstraintAssessment, ...],
    concepts: tuple[InterventionConcept, ...],
) -> None:
    expected = {
        (concept.intervention_id, topic)
        for concept in concepts
        for topic in ConstraintTopic
    }
    actual = {(item.intervention_id, item.topic) for item in constraints}
    if len(actual) != len(constraints) or actual != expected:
        raise ValueError(
            "constraints must cover every intervention and governed topic exactly"
        )


def _validate_relationships(
    deficiencies: tuple[DeficiencyReference, ...],
    outcomes: tuple[DesiredOutcome, ...],
    concepts: tuple[InterventionConcept, ...],
    costs: tuple[CostRange, ...],
    constraints: tuple[ConstraintAssessment, ...],
    packages: tuple[InterventionPackage, ...],
) -> None:
    deficiency_ids = {item.deficiency_id for item in deficiencies}
    outcome_ids = {item.outcome_id for item in outcomes}
    concept_ids = {item.intervention_id for item in concepts}
    cost_by_id = {item.cost_range_id: item for item in costs}
    constraints_by_intervention: dict[str, tuple[ConstraintAssessment, ...]] = {
        intervention_id: tuple(
            item for item in constraints if item.intervention_id == intervention_id
        )
        for intervention_id in concept_ids
    }
    for concept in concepts:
        if not set(concept.deficiency_ids).issubset(deficiency_ids):
            raise ValueError("intervention deficiencies must resolve")
        if not set(concept.outcome_ids).issubset(outcome_ids):
            raise ValueError("intervention outcomes must resolve")
        relationship_ids = (
            set(concept.alternative_intervention_ids)
            | set(concept.depends_on_intervention_ids)
            | set(concept.mutually_exclusive_intervention_ids)
        )
        if not relationship_ids.issubset(concept_ids - {concept.intervention_id}):
            raise ValueError("intervention relationships must resolve without self-links")
        if not set(concept.residual_deficiency_ids).issubset(deficiency_ids):
            raise ValueError("residual deficiencies must resolve")
        cost = (
            cost_by_id.get(concept.cost_range_id)
            if concept.cost_range_id is not None
            else None
        )
        if cost is not None and cost.intervention_id != concept.intervention_id:
            raise ValueError("intervention cost range belongs to another concept")
        if concept.status is not InterventionStatus.STRATEGIC_OPTION and cost is None:
            raise ValueError("concept or later status requires an outline cost range")
        constraint_items = constraints_by_intervention[concept.intervention_id]
        stages = {item.stage for item in concept.stage_verifications}
        if concept.status in {
            InterventionStatus.STRATEGIC_OPTION,
            InterventionStatus.CONCEPT,
        } and stages:
            raise ValueError("strategic/concept status cannot claim later-stage evidence")
        if concept.status in {
            InterventionStatus.FEASIBLE,
            InterventionStatus.DESIGNED,
        }:
            if InterventionStatus.FEASIBLE not in stages:
                raise ValueError("feasibility status requires external human evidence")
            if any(
                item.state is ConstraintState.UNKNOWN for item in constraint_items
            ):
                raise ValueError("feasibility status requires resolved constraints")
        if (
            concept.status is InterventionStatus.DESIGNED
            and InterventionStatus.DESIGNED not in stages
        ):
            raise ValueError("designed status requires external human evidence")
    _validate_relationship_graphs(concepts, packages)
    package_ids = {item.package_id for item in packages}
    packaged = {
        intervention_id
        for package in packages
        for intervention_id in package.intervention_ids
    }
    if packaged != concept_ids:
        raise ValueError("every concept must belong to at least one package")
    traced = {
        deficiency_id
        for concept in concepts
        for deficiency_id in concept.deficiency_ids
    } | {
        deficiency_id
        for package in packages
        for deficiency_id in package.residual_deficiency_ids
    }
    if traced != deficiency_ids:
        raise ValueError("every accepted deficiency must remain traced or residual")
    for package in packages:
        if not set(package.intervention_ids).issubset(concept_ids):
            raise ValueError("package interventions must resolve")
        included_concepts = tuple(
            concept
            for concept in concepts
            if concept.intervention_id in package.intervention_ids
        )
        expected_outcomes = {
            outcome_id
            for concept in included_concepts
            for outcome_id in concept.outcome_ids
        }
        if set(package.outcome_ids) != expected_outcomes:
            raise ValueError(
                "package outcomes must exactly trace its intervention concepts"
            )
        addressed_deficiencies = {
            deficiency_id
            for concept in included_concepts
            for deficiency_id in concept.deficiency_ids
        }
        if set(package.residual_deficiency_ids) != (
            deficiency_ids - addressed_deficiencies
        ):
            raise ValueError(
                "package residual deficiencies must expose every unaddressed "
                "accepted deficiency"
            )
        relationships = (
            set(package.depends_on_package_ids)
            | set(package.mutually_exclusive_package_ids)
        )
        if not relationships.issubset(package_ids - {package.package_id}):
            raise ValueError("package relationships must resolve without self-links")


def _validate_relationship_graphs(
    concepts: tuple[InterventionConcept, ...],
    packages: tuple[InterventionPackage, ...],
) -> None:
    _assert_acyclic(
        {
            item.intervention_id: set(item.depends_on_intervention_ids)
            for item in concepts
        },
        "intervention dependency",
    )
    _assert_symmetric(
        {
            item.intervention_id: set(item.alternative_intervention_ids)
            for item in concepts
        },
        "intervention alternative",
    )
    _assert_symmetric(
        {
            item.intervention_id: set(item.mutually_exclusive_intervention_ids)
            for item in concepts
        },
        "intervention mutual exclusion",
    )
    _assert_acyclic(
        {
            item.package_id: set(item.depends_on_package_ids)
            for item in packages
        },
        "package dependency",
    )
    _assert_symmetric(
        {
            item.package_id: set(item.mutually_exclusive_package_ids)
            for item in packages
        },
        "package mutual exclusion",
    )
    for concept in concepts:
        if set(concept.depends_on_intervention_ids) & set(
            concept.mutually_exclusive_intervention_ids
        ):
            raise ValueError(
                "an intervention cannot depend on a mutually exclusive intervention"
            )
    for package in packages:
        if set(package.depends_on_package_ids) & set(
            package.mutually_exclusive_package_ids
        ):
            raise ValueError(
                "a package cannot depend on a mutually exclusive package"
            )


def _assert_acyclic(graph: dict[str, set[str]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError(f"{label} graph contains a cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _assert_symmetric(graph: dict[str, set[str]], label: str) -> None:
    for node, peers in graph.items():
        if any(node not in graph[peer] for peer in peers):
            raise ValueError(f"{label} relationships must be symmetric")


def _evidence_requests(
    concepts: tuple[InterventionConcept, ...],
    costs: tuple[CostRange, ...],
    constraints: tuple[ConstraintAssessment, ...],
) -> tuple[InterventionEvidenceRequest, ...]:
    costed = {item.intervention_id for item in costs}
    requests = [
        InterventionEvidenceRequest(
            request_id=f"request-{concept.intervention_id}-outline-cost",
            intervention_id=concept.intervention_id,
            kind="outline-cost",
            purpose=(
                "Acquire a governed, human-verified outline cost range before "
                "advancing beyond strategic option."
            ),
        )
        for concept in concepts
        if concept.intervention_id not in costed
    ]
    requests.extend(
        InterventionEvidenceRequest(
            request_id=f"request-{item.intervention_id}-{item.topic}",
            intervention_id=item.intervention_id,
            kind="constraint",
            topic=item.topic,
            purpose=f"Resolve the unknown {item.topic.value} constraint.",
        )
        for item in constraints
        if item.state is ConstraintState.UNKNOWN
    )
    return tuple(sorted(requests, key=lambda item: item.request_id))


def _concept_geojson(
    concepts: tuple[InterventionConcept, ...],
) -> dict[str, Any]:
    features = []
    for concept in concepts:
        if concept.geometry.geometry_type == "point":
            geometry = {
                "type": "Point",
                "coordinates": list(concept.geometry.coordinates[0]),
            }
        elif concept.geometry.geometry_type == "line":
            geometry = {
                "type": "LineString",
                "coordinates": [
                    list(coordinate) for coordinate in concept.geometry.coordinates
                ],
            }
        else:
            geometry = {
                "type": "Polygon",
                "coordinates": [
                    [list(coordinate) for coordinate in concept.geometry.coordinates]
                ],
            }
        features.append(
            {
                "type": "Feature",
                "id": concept.intervention_id,
                "properties": {
                    "feature_type": "intervention-concept",
                    "catalogue_item_id": concept.catalogue_item_id,
                    "delivery_status": concept.status,
                    "deficiency_ids": list(concept.deficiency_ids),
                    "outcome_ids": list(concept.outcome_ids),
                    "detailed_design_in_scope": concept.detailed_design_in_scope,
                },
                "geometry": geometry,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _review_html(
    analysis_id: str,
    deficiencies: tuple[DeficiencyReference, ...],
    concepts: tuple[InterventionConcept, ...],
    packages: tuple[InterventionPackage, ...],
    requests: tuple[InterventionEvidenceRequest, ...],
) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>{html.escape(item.intervention_id)}</td>"
            f"<td>Intervention concept</td>"
            f"<td>{html.escape(item.status.value)}</td>"
            f"<td>{html.escape(', '.join(item.deficiency_ids))}</td>"
            f"<td>{'Yes' if item.cost_range_id else 'No'}</td>"
            "</tr>"
        )
        for item in concepts
    )
    aspiration_items = "".join(
        f"<li>Network aspiration from {html.escape(item.source_workflow.value)}: "
        f"{html.escape(item.description)}</li>"
        for item in deficiencies
    )
    package_items = "".join(
        f"<li>{html.escape(item.package_id)}: "
        f"{html.escape(', '.join(item.intervention_ids))}</li>"
        for item in packages
    )
    request_items = "".join(
        f"<li>{html.escape(item.purpose)}</li>" for item in requests
    ) or "<li>No unresolved cost or constraint requests.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Infrastructure intervention review — {html.escape(analysis_id)}</title>
<style>
body {{ font-family: system-ui,sans-serif; margin: 0; background: #f5f7f8; color: #18222b; }}
main {{ max-width: 1100px; margin: auto; padding: 1rem; }}
.boundary {{ background: white; border-left: 5px solid #b45309; padding: .8rem; }}
table {{ width: 100%; border-collapse: collapse; background: white; }}
th,td {{ border: 1px solid #bbb; padding: .45rem; text-align: left; }}
th {{ background: #263b50; color: white; }}
</style></head><body><main>
<h1>Infrastructure intervention review</h1>
<p class="boundary">Network aspiration, Intervention concept and delivery status
are separate. Detailed design is out of scope; feasible/designed labels only
record externally verified human evidence.</p>
<h2>Network aspirations and accepted deficiencies</h2><ul>{aspiration_items}</ul>
<h2>Concept packages</h2><ul>{package_items}</ul>
<table aria-label="Intervention delivery status table">
<thead><tr><th>Concept</th><th>Layer</th><th>Delivery status</th>
<th>Deficiencies</th><th>Outline cost</th></tr></thead><tbody>{rows}</tbody>
</table>
<h2>Evidence requests</h2><ul>{request_items}</ul>
</main></body></html>
"""


def _conformance_artifacts(analysis_id: str) -> tuple[ArtifactLink, ...]:
    return (
        ArtifactLink(
            artifact_id=f"{analysis_id}-intervention-packages",
            uri="intervention-manifest.json#packages",
            kind="intervention-packages",
        ),
        ArtifactLink(
            artifact_id=f"{analysis_id}-programme-appraisal-input",
            uri="intervention-manifest.json#concepts",
            kind="programme-appraisal-input",
        ),
    )


def _canonical_unique(value: tuple[Any, ...], label: str) -> tuple[Any, ...]:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(value))


def _unique_ids(records: tuple[Any, ...], field: str, label: str) -> set[str]:
    identifiers = tuple(getattr(item, field) for item in records)
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


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(_json_payload(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
