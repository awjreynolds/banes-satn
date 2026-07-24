"""Governed, immutable evidence registry for LCWIP baseline analysis.

The registry snapshots configured evidence into a deterministic public bundle.
It does not acquire live data, infer missing evidence, mutate raw inputs, or
publish controlled/personal source material.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import date
from enum import StrEnum
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


class EvidenceContract(BaseModel):
    """Closed immutable contract used at every evidence-registry boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Annotated[str, StringConstraints(pattern=r"^1\.0$")] = "1.0"


class EvidenceRole(StrEnum):
    RAW = "raw"
    OBSERVED = "observed"
    MODELLED = "modelled"
    DERIVED = "derived"
    POLICY = "policy"
    STAKEHOLDER = "stakeholder"
    EXPERT_JUDGEMENT = "expert-judgement"


class EvidenceFamily(StrEnum):
    DEMOGRAPHICS = "demographics"
    EQUITY_CONTEXT = "equity-context"
    DEMAND = "demand"
    SAFETY_TRAFFIC = "safety-traffic"
    PUBLIC_TRANSPORT_ATTRACTORS = "public-transport-attractors"
    DEVELOPMENT_POLICY = "development-policy"
    RIGHTS_OF_WAY_INFRASTRUCTURE = "rights-of-way-infrastructure"
    LOCAL_EVIDENCE = "local-evidence"


class AdapterKind(StrEnum):
    CENSUS_POPULATION = "census-population"
    DEPRIVATION_CHARACTERISTICS = "deprivation-characteristics"
    ORIGIN_DESTINATION = "origin-destination"
    PROPENSITY_TO_CYCLE = "propensity-to-cycle"
    COLLISIONS_TRAFFIC = "collisions-traffic"
    PUBLIC_TRANSPORT_ATTRACTORS = "public-transport-attractors"
    DEVELOPMENT_POLICY = "development-policy"
    RIGHTS_OF_WAY_INFRASTRUCTURE = "rights-of-way-infrastructure"
    CONTROLLED_LOCAL_IMPORT = "controlled-local-import"


ADAPTER_FAMILIES = {
    AdapterKind.CENSUS_POPULATION: EvidenceFamily.DEMOGRAPHICS,
    AdapterKind.DEPRIVATION_CHARACTERISTICS: EvidenceFamily.EQUITY_CONTEXT,
    AdapterKind.ORIGIN_DESTINATION: EvidenceFamily.DEMAND,
    AdapterKind.PROPENSITY_TO_CYCLE: EvidenceFamily.DEMAND,
    AdapterKind.COLLISIONS_TRAFFIC: EvidenceFamily.SAFETY_TRAFFIC,
    AdapterKind.PUBLIC_TRANSPORT_ATTRACTORS: (
        EvidenceFamily.PUBLIC_TRANSPORT_ATTRACTORS
    ),
    AdapterKind.DEVELOPMENT_POLICY: EvidenceFamily.DEVELOPMENT_POLICY,
    AdapterKind.RIGHTS_OF_WAY_INFRASTRUCTURE: (
        EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE
    ),
    AdapterKind.CONTROLLED_LOCAL_IMPORT: EvidenceFamily.LOCAL_EVIDENCE,
}


class EvidenceQuality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


QUALITY_RANK = {
    EvidenceQuality.LOW: 0,
    EvidenceQuality.MEDIUM: 1,
    EvidenceQuality.HIGH: 2,
}


class AccessLevel(StrEnum):
    PUBLIC = "public"
    CONTROLLED = "controlled"
    PERSONAL = "personal"


class PublicDisposition(StrEnum):
    INCLUDE = "include"
    REDACTED = "redacted"
    EXCLUDE = "exclude"


class EvidenceAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class EvidenceIssue(StrEnum):
    MISSING = "missing"
    STALE = "stale"
    LOW_QUALITY = "low-quality"
    SPATIALLY_INCOMPLETE = "spatially-incomplete"
    LICENCE_RESTRICTED = "licence-restricted"
    NON_REPRODUCIBLE = "non-reproducible"


ISSUE_ORDER = tuple(EvidenceIssue)


class SpatialCoverage(EvidenceContract):
    expected_units: tuple[NonBlankText, ...] = Field(min_length=1)
    covered_units: tuple[NonBlankText, ...] = ()
    description: NonBlankText

    @field_validator("expected_units", "covered_units")
    @classmethod
    def canonical_units(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("spatial coverage units must be unique")
        return tuple(sorted(value))


class EvidenceSourceSpec(EvidenceContract):
    """Governed source metadata plus a local acquisition contract.

    ``path`` and ``redacted_path`` are acquisition inputs only. They are never
    serialized into the public snapshot manifest.
    """

    evidence_id: StableIdentifier
    adapter: AdapterKind
    family: EvidenceFamily
    role: EvidenceRole
    path: Path | None = None
    redacted_path: Path | None = None
    source_uri: NonBlankText
    publisher: NonBlankText
    licence: NonBlankText
    retrieved_on: date
    observed_from: date
    observed_to: date
    spatial_coverage: SpatialCoverage
    version: NonBlankText
    methodology: NonBlankText
    known_bias: NonBlankText
    quality: EvidenceQuality
    permitted_uses: tuple[NonBlankText, ...] = Field(min_length=1)
    access_level: AccessLevel = AccessLevel.PUBLIC
    public_disposition: PublicDisposition = PublicDisposition.INCLUDE
    lineage: tuple[StableIdentifier, ...] = ()
    transformation_version: NonBlankText | None = None
    non_reproducibility_reason: NonBlankText | None = None

    @field_validator("permitted_uses", "lineage")
    @classmethod
    def canonical_identifiers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("evidence source lists must not contain duplicates")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_governance(self) -> Self:
        if self.observed_to < self.observed_from:
            raise ValueError("observation end must not precede observation start")
        if self.observed_to > self.retrieved_on:
            raise ValueError("observation end must not follow retrieval")
        expected_family = ADAPTER_FAMILIES[self.adapter]
        if self.family is not expected_family:
            raise ValueError(
                f"{self.adapter.value} adapter belongs to {expected_family.value}"
            )
        if self.role is EvidenceRole.DERIVED:
            if not self.lineage:
                raise ValueError("derived evidence requires complete input lineage")
            if self.transformation_version is None:
                raise ValueError("derived evidence requires a transformation version")
        elif self.lineage or self.transformation_version is not None:
            raise ValueError("only derived evidence may declare lineage and transformation version")
        if self.access_level is AccessLevel.PUBLIC:
            if self.public_disposition is not PublicDisposition.INCLUDE:
                raise ValueError("public evidence must use the include disposition")
            if self.redacted_path is not None:
                raise ValueError("public evidence does not use a redacted acquisition path")
        elif self.access_level is AccessLevel.CONTROLLED:
            if self.public_disposition is PublicDisposition.INCLUDE:
                raise ValueError(
                    "controlled evidence cannot be copied directly to public artifacts"
                )
            if (
                self.public_disposition is PublicDisposition.REDACTED
                and self.redacted_path is None
            ):
                raise ValueError("redacted controlled evidence requires a redacted path")
        elif self.public_disposition is not PublicDisposition.EXCLUDE:
            raise ValueError("personal evidence must be excluded from public artifacts")
        if (
            self.public_disposition is PublicDisposition.EXCLUDE
            and self.non_reproducibility_reason is None
        ):
            raise ValueError("excluded evidence requires a non-reproducibility reason")
        if self.path is None and self.non_reproducibility_reason is None:
            raise ValueError("an unavailable source requires a non-reproducibility reason")
        return self


class EvidenceFamilyRequirement(EvidenceContract):
    family: EvidenceFamily
    required_units: tuple[NonBlankText, ...] = Field(min_length=1)
    maximum_age_days: int = Field(ge=0)
    minimum_quality: EvidenceQuality
    required_use: NonBlankText

    @field_validator("required_units")
    @classmethod
    def canonical_units(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("required coverage units must be unique")
        return tuple(sorted(value))


class EvidenceRegistryConfig(EvidenceContract):
    snapshot_id: StableIdentifier
    council_id: StableIdentifier
    profile_id: StableIdentifier
    reference_date: date
    output_dir: Path
    requirements: tuple[EvidenceFamilyRequirement, ...] = Field(min_length=1)
    sources: tuple[EvidenceSourceSpec, ...] = ()

    @field_validator("requirements")
    @classmethod
    def canonical_requirements(
        cls, value: tuple[EvidenceFamilyRequirement, ...]
    ) -> tuple[EvidenceFamilyRequirement, ...]:
        families = [requirement.family for requirement in value]
        if len(families) != len(set(families)):
            raise ValueError("evidence family requirements must be unique")
        return tuple(sorted(value, key=lambda requirement: requirement.family))

    @field_validator("sources")
    @classmethod
    def canonical_sources(
        cls, value: tuple[EvidenceSourceSpec, ...]
    ) -> tuple[EvidenceSourceSpec, ...]:
        identifiers = [source.evidence_id for source in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("evidence source IDs must be unique")
        return tuple(sorted(value, key=lambda source: source.evidence_id))

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        for source in self.sources:
            if source.retrieved_on > self.reference_date:
                raise ValueError(
                    f"evidence source {source.evidence_id!r} was retrieved after "
                    "the registry reference date"
                )
        sources = {source.evidence_id: source for source in self.sources}
        for source in self.sources:
            for input_id in source.lineage:
                if input_id == source.evidence_id:
                    raise ValueError("derived evidence cannot include itself in its lineage")
                if input_id not in sources:
                    raise ValueError(
                        f"derived evidence input {input_id!r} is not configured"
                    )

        def visit(identifier: str, visiting: set[str], visited: set[str]) -> None:
            if identifier in visited:
                return
            if identifier in visiting:
                raise ValueError("derived evidence lineage must be acyclic")
            visiting.add(identifier)
            for dependency in sources[identifier].lineage:
                visit(dependency, visiting, visited)
            visiting.remove(identifier)
            visited.add(identifier)

        visited: set[str] = set()
        for identifier in sources:
            visit(identifier, set(), visited)
        return self

    @classmethod
    def from_json(cls, path: Path) -> EvidenceRegistryConfig:
        """Load a config, resolving acquisition/output paths beside the config file."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        base = path.parent.resolve()
        output = Path(payload["output_dir"])
        if not output.is_absolute():
            payload["output_dir"] = str((base / output).resolve())
        for source in payload.get("sources", []):
            for field in ("path", "redacted_path"):
                configured = source.get(field)
                if configured:
                    candidate = Path(configured)
                    if not candidate.is_absolute():
                        source[field] = str((base / candidate).resolve())
        return cls.model_validate(payload)


class _AdapterPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _CensusPopulationPayload(_AdapterPayload):
    area: NonBlankText
    population: int = Field(ge=0)
    year: int = Field(ge=1800, le=2200)


class _DeprivationCharacteristicsPayload(_AdapterPayload):
    area: NonBlankText
    imd_decile: int = Field(ge=1, le=10)
    protected_characteristics: NonBlankText


class _OriginDestinationPayload(_AdapterPayload):
    origin: NonBlankText
    destination: NonBlankText
    daily_trips: int = Field(ge=0)


class _PropensityToCyclePayload(_AdapterPayload):
    scenario: NonBlankText
    origin: NonBlankText
    destination: NonBlankText
    cycle_trips: int = Field(ge=0)


class _CollisionsTrafficPayload(_AdapterPayload):
    site: NonBlankText
    motor_vehicles: int = Field(ge=0)
    collisions: int = Field(ge=0)


class _PublicTransportAttractorsPayload(_AdapterPayload):
    id: NonBlankText
    kind: NonBlankText
    name: NonBlankText


class _DevelopmentPolicyPayload(_AdapterPayload):
    allocation: NonBlankText
    homes: int = Field(ge=0)
    policy: NonBlankText


class _RightsOfWayInfrastructurePayload(_AdapterPayload):
    reference: NonBlankText
    kind: NonBlankText
    condition: NonBlankText


class _ControlledLocalImportPayload(_AdapterPayload):
    response_id: NonBlankText
    theme: NonBlankText
    personal_data: Literal["removed"]


ADAPTER_PAYLOAD_CONTRACTS: dict[AdapterKind, type[_AdapterPayload]] = {
    AdapterKind.CENSUS_POPULATION: _CensusPopulationPayload,
    AdapterKind.DEPRIVATION_CHARACTERISTICS: _DeprivationCharacteristicsPayload,
    AdapterKind.ORIGIN_DESTINATION: _OriginDestinationPayload,
    AdapterKind.PROPENSITY_TO_CYCLE: _PropensityToCyclePayload,
    AdapterKind.COLLISIONS_TRAFFIC: _CollisionsTrafficPayload,
    AdapterKind.PUBLIC_TRANSPORT_ATTRACTORS: _PublicTransportAttractorsPayload,
    AdapterKind.DEVELOPMENT_POLICY: _DevelopmentPolicyPayload,
    AdapterKind.RIGHTS_OF_WAY_INFRASTRUCTURE: _RightsOfWayInfrastructurePayload,
    AdapterKind.CONTROLLED_LOCAL_IMPORT: _ControlledLocalImportPayload,
}


class EvidenceSnapshotItem(EvidenceContract):
    evidence_id: StableIdentifier
    adapter: AdapterKind
    family: EvidenceFamily
    role: EvidenceRole
    source_uri: NonBlankText
    publisher: NonBlankText
    licence: NonBlankText
    retrieved_on: date
    observed_from: date
    observed_to: date
    spatial_coverage: SpatialCoverage
    version: NonBlankText
    methodology: NonBlankText
    known_bias: NonBlankText
    quality: EvidenceQuality
    permitted_uses: tuple[NonBlankText, ...]
    access_level: AccessLevel
    public_disposition: PublicDisposition
    lineage: tuple[StableIdentifier, ...] = ()
    transformation_version: NonBlankText | None = None
    availability: EvidenceAvailability
    artifact_path: NonBlankText | None = None
    sha256: Sha256Hex | None = None
    non_reproducibility_reason: NonBlankText | None = None

    @field_validator("artifact_path")
    @classmethod
    def safe_artifact_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("snapshot artifact paths must stay inside the snapshot")
        return value

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        if self.observed_to < self.observed_from:
            raise ValueError("observation end must not precede observation start")
        if self.observed_to > self.retrieved_on:
            raise ValueError("observation end must not follow retrieval")
        expected_family = ADAPTER_FAMILIES[self.adapter]
        if self.family is not expected_family:
            raise ValueError(
                f"{self.adapter.value} adapter belongs to {expected_family.value}"
            )
        has_artifact = self.artifact_path is not None and self.sha256 is not None
        if (self.artifact_path is None) != (self.sha256 is None):
            raise ValueError("a copied artifact requires both its path and content hash")
        if self.availability is EvidenceAvailability.UNAVAILABLE and has_artifact:
            raise ValueError("unavailable evidence cannot contain a public artifact")
        if (
            self.availability is EvidenceAvailability.AVAILABLE
            and self.public_disposition is not PublicDisposition.EXCLUDE
            and not has_artifact
        ):
            raise ValueError("available public evidence requires a copied artifact")
        if self.public_disposition is PublicDisposition.EXCLUDE and has_artifact:
            raise ValueError("excluded evidence cannot contain a public artifact")
        if (
            self.public_disposition is PublicDisposition.EXCLUDE
            and self.non_reproducibility_reason is None
        ):
            raise ValueError("excluded evidence requires a non-reproducibility reason")
        if (
            self.availability is EvidenceAvailability.UNAVAILABLE
            and self.non_reproducibility_reason is None
        ):
            raise ValueError("unavailable evidence requires an explicit reason")
        if self.role is EvidenceRole.DERIVED:
            if not self.lineage or self.transformation_version is None:
                raise ValueError(
                    "derived evidence requires complete lineage and transformation version"
                )
        elif self.lineage or self.transformation_version is not None:
            raise ValueError(
                "only derived evidence may declare lineage and transformation version"
            )
        if (
            self.access_level is AccessLevel.PUBLIC
            and self.public_disposition is not PublicDisposition.INCLUDE
        ):
            raise ValueError("public evidence must use the include disposition")
        if (
            self.access_level is AccessLevel.CONTROLLED
            and self.public_disposition is PublicDisposition.INCLUDE
        ):
            raise ValueError("controlled evidence cannot use the include disposition")
        if (
            self.access_level is AccessLevel.PERSONAL
            and self.public_disposition is not PublicDisposition.EXCLUDE
        ):
            raise ValueError("personal evidence must be excluded")
        return self


class RegistryEvidenceRequest(EvidenceContract):
    request_id: StableIdentifier
    family: EvidenceFamily
    council_id: StableIdentifier
    profile_id: StableIdentifier
    reasons: tuple[EvidenceIssue, ...] = Field(min_length=1)
    missing_units: tuple[NonBlankText, ...] = ()
    requested_use: NonBlankText


class EvidenceCoverageEntry(EvidenceContract):
    family: EvidenceFamily
    required_use: NonBlankText
    maximum_age_days: int = Field(ge=0)
    minimum_quality: EvidenceQuality
    evidence_ids: tuple[StableIdentifier, ...] = ()
    licences: tuple[NonBlankText, ...] = ()
    issues: tuple[EvidenceIssue, ...] = ()
    missing_units: tuple[NonBlankText, ...] = ()
    freshest_observation: date | None = None
    best_quality: EvidenceQuality | None = None


class EvidenceCoverageReport(EvidenceContract):
    snapshot_id: StableIdentifier
    snapshot_fingerprint: Sha256Hex
    council_id: StableIdentifier
    profile_id: StableIdentifier
    reference_date: date
    complete: bool
    entries: tuple[EvidenceCoverageEntry, ...]


class EvidenceSnapshotManifest(EvidenceContract):
    snapshot_id: StableIdentifier
    council_id: StableIdentifier
    profile_id: StableIdentifier
    reference_date: date
    input_fingerprint: Sha256Hex
    requirements: tuple[EvidenceFamilyRequirement, ...]
    items: tuple[EvidenceSnapshotItem, ...]
    evidence_requests: tuple[RegistryEvidenceRequest, ...]
    snapshot_fingerprint: Sha256Hex

    @field_validator("requirements")
    @classmethod
    def canonical_manifest_requirements(
        cls, value: tuple[EvidenceFamilyRequirement, ...]
    ) -> tuple[EvidenceFamilyRequirement, ...]:
        families = tuple(requirement.family for requirement in value)
        if len(families) != len(set(families)):
            raise ValueError("manifest requirement families must be unique")
        if families != tuple(sorted(families)):
            raise ValueError("manifest requirements must use canonical family order")
        return value

    @field_validator("items")
    @classmethod
    def canonical_manifest_items(
        cls, value: tuple[EvidenceSnapshotItem, ...]
    ) -> tuple[EvidenceSnapshotItem, ...]:
        identifiers = tuple(item.evidence_id for item in value)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("manifest item IDs must be unique")
        if identifiers != tuple(sorted(identifiers)):
            raise ValueError("manifest items must use canonical evidence ID order")
        return value

    @model_validator(mode="after")
    def validate_manifest_lineage(self) -> Self:
        items = {item.evidence_id: item for item in self.items}
        for item in self.items:
            if item.retrieved_on > self.reference_date:
                raise ValueError(
                    f"evidence item {item.evidence_id!r} was retrieved after "
                    "the snapshot reference date"
                )
            for input_id in item.lineage:
                if input_id == item.evidence_id:
                    raise ValueError("derived evidence cannot include itself in its lineage")
                if input_id not in items:
                    raise ValueError(
                        f"derived evidence input {input_id!r} is not present in the manifest"
                    )

        def visit(identifier: str, visiting: set[str], visited: set[str]) -> None:
            if identifier in visited:
                return
            if identifier in visiting:
                raise ValueError("manifest evidence lineage must be acyclic")
            visiting.add(identifier)
            for dependency in items[identifier].lineage:
                visit(dependency, visiting, visited)
            visiting.remove(identifier)
            visited.add(identifier)

        visited: set[str] = set()
        for identifier in items:
            visit(identifier, set(), visited)
        return self

    @model_validator(mode="after")
    def validate_fingerprint(self) -> Self:
        if self.snapshot_fingerprint != _fingerprint(
            self.model_dump(mode="json", exclude={"snapshot_fingerprint"})
        ):
            raise ValueError("evidence snapshot fingerprint does not match its contents")
        return self

    @classmethod
    def create(
        cls,
        *,
        config: EvidenceRegistryConfig,
        input_fingerprint: str,
        items: tuple[EvidenceSnapshotItem, ...],
        requests: tuple[RegistryEvidenceRequest, ...],
    ) -> EvidenceSnapshotManifest:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "snapshot_id": config.snapshot_id,
            "council_id": config.council_id,
            "profile_id": config.profile_id,
            "reference_date": config.reference_date,
            "input_fingerprint": input_fingerprint,
            "requirements": config.requirements,
            "items": items,
            "evidence_requests": requests,
        }
        fingerprint = _fingerprint(_json_payload(payload))
        return cls(**payload, snapshot_fingerprint=fingerprint)


class _PreparedSource(EvidenceContract):
    source: EvidenceSourceSpec
    availability: EvidenceAvailability
    public_bytes: bytes | None = None
    suffix: NonBlankText | None = None
    non_reproducibility_reason: NonBlankText | None = None


def snapshot_evidence_registry(config: EvidenceRegistryConfig) -> Path:
    """Materialise one deterministic immutable evidence snapshot."""
    config = EvidenceRegistryConfig.model_validate(config.model_dump())
    prepared = tuple(_prepare_source(source) for source in config.sources)
    input_fingerprint = _input_fingerprint(config, prepared)
    destination = config.output_dir / config.snapshot_id
    if destination.exists():
        existing = validate_evidence_snapshot(destination)
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError(
                f"evidence snapshot {config.snapshot_id!r} is immutable and inputs changed"
            )
        return destination

    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.snapshot_id}-", dir=config.output_dir)
    )
    try:
        evidence_dir = temporary / "evidence"
        evidence_dir.mkdir()
        items = tuple(_write_item(item, evidence_dir) for item in prepared)
        report, requests = _evaluate_coverage(config, items)
        manifest = EvidenceSnapshotManifest.create(
            config=config,
            input_fingerprint=input_fingerprint,
            items=items,
            requests=requests,
        )
        report = report.model_copy(
            update={"snapshot_fingerprint": manifest.snapshot_fingerprint}
        )
        _write_json(temporary / "evidence-registry.json", manifest.model_dump(mode="json"))
        _write_json(temporary / "coverage-report.json", report.model_dump(mode="json"))
        (temporary / "coverage-report.md").write_text(
            _render_coverage_report(report), encoding="utf-8"
        )
        validate_evidence_snapshot(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_evidence_snapshot(path: Path) -> EvidenceSnapshotManifest:
    """Validate manifest integrity, copied artifacts and mandatory reports."""
    manifest_path = path / "evidence-registry.json"
    report_path = path / "coverage-report.json"
    human_report_path = path / "coverage-report.md"
    for required in (manifest_path, report_path, human_report_path):
        if not required.is_file():
            raise ValueError(f"invalid evidence snapshot: missing {required.name}")
    manifest = EvidenceSnapshotManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    report = EvidenceCoverageReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    validation_config = EvidenceRegistryConfig(
        snapshot_id=manifest.snapshot_id,
        council_id=manifest.council_id,
        profile_id=manifest.profile_id,
        reference_date=manifest.reference_date,
        output_dir=Path("."),
        requirements=manifest.requirements,
    )
    expected_report, expected_requests = _evaluate_coverage(
        validation_config, manifest.items
    )
    expected_report = expected_report.model_copy(
        update={"snapshot_fingerprint": manifest.snapshot_fingerprint}
    )
    if report != expected_report or manifest.evidence_requests != expected_requests:
        raise ValueError("coverage report does not match the governed evidence snapshot")
    if human_report_path.read_text(encoding="utf-8") != _render_coverage_report(
        expected_report
    ):
        raise ValueError(
            "human coverage report does not match the machine coverage report"
        )
    expected_files = {
        "evidence-registry.json",
        "coverage-report.json",
        "coverage-report.md",
    }
    for item in manifest.items:
        if item.artifact_path is None:
            continue
        artifact = path / item.artifact_path
        expected_files.add(item.artifact_path)
        if not artifact.is_file():
            raise ValueError(f"invalid evidence snapshot: missing {item.artifact_path}")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != item.sha256:
            raise ValueError(
                f"invalid evidence snapshot: {item.artifact_path} content hash mismatch"
            )
    actual_files = {
        file.relative_to(path).as_posix() for file in path.rglob("*") if file.is_file()
    }
    if actual_files != expected_files:
        unexpected = sorted(actual_files - expected_files)
        missing = sorted(expected_files - actual_files)
        raise ValueError(
            "invalid evidence snapshot file set"
            + (f"; unexpected: {', '.join(unexpected)}" if unexpected else "")
            + (f"; missing: {', '.join(missing)}" if missing else "")
        )
    return manifest


def load_evidence_gate(path: Path) -> EvidenceCoverageReport:
    """Load the reports that every later analytical pass must inspect first."""
    validate_evidence_snapshot(path)
    return EvidenceCoverageReport.model_validate_json(
        (path / "coverage-report.json").read_text(encoding="utf-8")
    )


def _prepare_source(source: EvidenceSourceSpec) -> _PreparedSource:
    acquisition_path = source.path
    if source.public_disposition is PublicDisposition.REDACTED:
        acquisition_path = source.redacted_path
    if source.public_disposition is PublicDisposition.EXCLUDE:
        exists = source.path is not None and source.path.is_file()
        return _PreparedSource(
            source=source,
            availability=(
                EvidenceAvailability.AVAILABLE if exists else EvidenceAvailability.UNAVAILABLE
            ),
            non_reproducibility_reason=source.non_reproducibility_reason,
        )
    if acquisition_path is None or not acquisition_path.is_file():
        return _PreparedSource(
            source=source,
            availability=EvidenceAvailability.UNAVAILABLE,
            non_reproducibility_reason=(
                source.non_reproducibility_reason
                or "Configured evidence source was not supplied."
            ),
        )
    payload = acquisition_path.read_bytes()
    if not payload:
        return _PreparedSource(
            source=source,
            availability=EvidenceAvailability.UNAVAILABLE,
            non_reproducibility_reason="Configured evidence source was empty.",
        )
    _validate_adapter_payload(source.adapter, payload)
    suffix = acquisition_path.suffix.lower() or ".bin"
    return _PreparedSource(
        source=source,
        availability=EvidenceAvailability.AVAILABLE,
        public_bytes=payload,
        suffix=suffix,
        non_reproducibility_reason=source.non_reproducibility_reason,
    )


def _validate_adapter_payload(adapter: AdapterKind, payload: bytes) -> None:
    try:
        decoded = json.loads(payload)
        ADAPTER_PAYLOAD_CONTRACTS[adapter].model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(
            f"{adapter.value} adapter contract rejected the configured payload"
        ) from error


def _write_item(prepared: _PreparedSource, evidence_dir: Path) -> EvidenceSnapshotItem:
    source = prepared.source
    artifact_path: str | None = None
    digest: str | None = None
    if prepared.public_bytes is not None:
        filename = f"{source.evidence_id}{prepared.suffix}"
        artifact = evidence_dir / filename
        artifact.write_bytes(prepared.public_bytes)
        artifact_path = f"evidence/{filename}"
        digest = hashlib.sha256(prepared.public_bytes).hexdigest()
    return EvidenceSnapshotItem(
        evidence_id=source.evidence_id,
        adapter=source.adapter,
        family=source.family,
        role=source.role,
        source_uri=source.source_uri,
        publisher=source.publisher,
        licence=source.licence,
        retrieved_on=source.retrieved_on,
        observed_from=source.observed_from,
        observed_to=source.observed_to,
        spatial_coverage=source.spatial_coverage,
        version=source.version,
        methodology=source.methodology,
        known_bias=source.known_bias,
        quality=source.quality,
        permitted_uses=source.permitted_uses,
        access_level=source.access_level,
        public_disposition=source.public_disposition,
        lineage=source.lineage,
        transformation_version=source.transformation_version,
        availability=prepared.availability,
        artifact_path=artifact_path,
        sha256=digest,
        non_reproducibility_reason=prepared.non_reproducibility_reason,
    )


def _evaluate_coverage(
    config: EvidenceRegistryConfig,
    items: tuple[EvidenceSnapshotItem, ...],
) -> tuple[EvidenceCoverageReport, tuple[RegistryEvidenceRequest, ...]]:
    entries: list[EvidenceCoverageEntry] = []
    requests: list[RegistryEvidenceRequest] = []
    for requirement in config.requirements:
        family_items = tuple(item for item in items if item.family is requirement.family)
        available = tuple(
            item
            for item in family_items
            if item.availability is EvidenceAvailability.AVAILABLE
        )
        issues: set[EvidenceIssue] = set()
        if not available:
            issues.add(EvidenceIssue.MISSING)
        if family_items and not any(item.artifact_path for item in family_items):
            issues.add(EvidenceIssue.NON_REPRODUCIBLE)
        freshest = max((item.observed_to for item in available), default=None)
        if freshest is not None:
            age = (config.reference_date - freshest).days
            if age > requirement.maximum_age_days:
                issues.add(EvidenceIssue.STALE)
        best_quality = max(
            (item.quality for item in available),
            key=lambda quality: QUALITY_RANK[quality],
            default=None,
        )
        if (
            best_quality is not None
            and QUALITY_RANK[best_quality] < QUALITY_RANK[requirement.minimum_quality]
        ):
            issues.add(EvidenceIssue.LOW_QUALITY)
        covered_units = {
            unit for item in available for unit in item.spatial_coverage.covered_units
        }
        missing_units = tuple(sorted(set(requirement.required_units) - covered_units))
        if available and missing_units:
            issues.add(EvidenceIssue.SPATIALLY_INCOMPLETE)
        if available and not any(
            requirement.required_use in item.permitted_uses for item in available
        ):
            issues.add(EvidenceIssue.LICENCE_RESTRICTED)
        ordered_issues = tuple(issue for issue in ISSUE_ORDER if issue in issues)
        entries.append(
            EvidenceCoverageEntry(
                family=requirement.family,
                required_use=requirement.required_use,
                maximum_age_days=requirement.maximum_age_days,
                minimum_quality=requirement.minimum_quality,
                evidence_ids=tuple(sorted(item.evidence_id for item in available)),
                licences=tuple(sorted({item.licence for item in available})),
                issues=ordered_issues,
                missing_units=missing_units,
                freshest_observation=freshest,
                best_quality=best_quality,
            )
        )
        if ordered_issues:
            requests.append(
                RegistryEvidenceRequest(
                    request_id=f"evidence-request-{requirement.family}",
                    family=requirement.family,
                    council_id=config.council_id,
                    profile_id=config.profile_id,
                    reasons=ordered_issues,
                    missing_units=missing_units,
                    requested_use=requirement.required_use,
                )
            )
    report = EvidenceCoverageReport(
        snapshot_id=config.snapshot_id,
        snapshot_fingerprint="0" * 64,
        council_id=config.council_id,
        profile_id=config.profile_id,
        reference_date=config.reference_date,
        complete=not requests,
        entries=tuple(entries),
    )
    return report, tuple(requests)


def _input_fingerprint(
    config: EvidenceRegistryConfig, prepared: tuple[_PreparedSource, ...]
) -> str:
    sources: list[dict[str, Any]] = []
    for item in prepared:
        source = item.source.model_dump(
            mode="json", exclude={"path", "redacted_path"}
        )
        source["availability"] = item.availability
        source["public_content_sha256"] = (
            hashlib.sha256(item.public_bytes).hexdigest()
            if item.public_bytes is not None
            else None
        )
        sources.append(source)
    return _fingerprint(
        {
            "snapshot_id": config.snapshot_id,
            "council_id": config.council_id,
            "profile_id": config.profile_id,
            "reference_date": config.reference_date,
            "requirements": config.requirements,
            "sources": sources,
        }
    )


def _render_coverage_report(report: EvidenceCoverageReport) -> str:
    lines = [
        f"# Evidence coverage: {report.snapshot_id}",
        "",
        f"- Council: `{report.council_id}`",
        f"- Guidance Profile: `{report.profile_id}`",
        f"- Reference date: {report.reference_date.isoformat()}",
        f"- Complete: {'yes' if report.complete else 'no'}",
        "",
        (
            "| Evidence family | Evidence | Freshest observation | Best quality "
            "| Licences | Required use | Issues | Missing coverage |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in report.entries:
        lines.append(
            "| "
            + " | ".join(
                (
                    entry.family,
                    ", ".join(entry.evidence_ids) or "None",
                    (
                        entry.freshest_observation.isoformat()
                        if entry.freshest_observation is not None
                        else "None"
                    ),
                    entry.best_quality or "None",
                    ", ".join(entry.licences) or "None",
                    entry.required_use,
                    ", ".join(entry.issues) or "None",
                    ", ".join(entry.missing_units) or "None",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _json_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _json_payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_payload(item) for item in value]
    if isinstance(value, (date, StrEnum, Path)):
        return str(value)
    return value


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        _json_payload(value), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_payload(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
