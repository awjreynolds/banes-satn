"""Immutable LCWIP delivery monitoring and governed review releases."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import date, timedelta
from enum import StrEnum
from html import escape
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lcwip.conformance import evaluate_conformance
from lcwip.models import (
    ConformanceResult,
    GuidanceProfile,
    LifecycleState,
    RequirementAssessment,
    RequirementStatus,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class MonitoringContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
    schema_version: Literal["1.0"] = "1.0"


class UpdateConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VerificationState(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"


class MonitoringSource(MonitoringContract):
    source_id: Identifier
    uri: Text
    sha256: Sha256
    public_summary: Text
    contains_personal_data: bool

    @field_validator("uri")
    @classmethod
    def https_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("public monitoring URI must use https")
        return value

    @model_validator(mode="after")
    def privacy_safe(self) -> Self:
        if self.contains_personal_data:
            raise ValueError("public monitoring source cannot contain personal data")
        return self


class HistoricalReleaseReference(MonitoringContract):
    release_id: Identifier
    lifecycle_state: LifecycleState
    release_fingerprint: Sha256
    evidence_fingerprint: Sha256
    configuration_fingerprint: Sha256
    publication_manifest_path: Path
    publication_manifest_sha256: Sha256
    guidance_profile: GuidanceProfile
    conformance: ConformanceResult
    source_fingerprints: dict[Identifier, Sha256] = Field(min_length=1)

    @model_validator(mode="after")
    def governed_release(self) -> Self:
        if self.lifecycle_state not in {
            LifecycleState.ADOPTED,
            LifecycleState.SUPERSEDED,
        }:
            raise ValueError("monitoring requires an adopted or superseded release")
        if self.conformance.profile.fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("historical conformance Guidance Profile must resolve")
        return self


class EvidenceSnapshotReference(MonitoringContract):
    snapshot_id: Identifier
    snapshot_fingerprint: Sha256
    reference_date: date
    manifest_path: Path
    manifest_sha256: Sha256
    item_fingerprints: dict[Identifier, Sha256] = Field(min_length=1)


class DesignState(StrEnum):
    NOT_STARTED = "not-started"
    CONCEPT = "concept"
    PRELIMINARY = "preliminary"
    DETAILED = "detailed"
    APPROVED = "approved"


class FundingState(StrEnum):
    UNALLOCATED = "unallocated"
    BID_PREPARATION = "bid-preparation"
    BID_SUBMITTED = "bid-submitted"
    PARTIALLY_SECURED = "partially-secured"
    SECURED = "secured"


class ConstructionState(StrEnum):
    NOT_STARTED = "not-started"
    PROCUREMENT = "procurement"
    UNDERWAY = "underway"
    PAUSED = "paused"
    COMPLETE = "complete"


class CompletionState(StrEnum):
    NOT_COMPLETE = "not-complete"
    REPORTED_COMPLETE = "reported-complete"
    VERIFIED_COMPLETE = "verified-complete"


class OutcomeState(StrEnum):
    NOT_DUE = "not-due"
    DATA_DUE = "data-due"
    OBSERVED_NO_EVALUATION = "observed-no-evaluation"
    EVALUATED_NO_CAUSAL_CLAIM = "evaluated-no-causal-claim"


class StatusDimension(StrEnum):
    DESIGN = "design"
    FUNDING = "funding"
    CONSTRUCTION = "construction"
    COMPLETION = "completion"
    OUTCOME = "outcome"


class StatusUpdateBase(MonitoringContract):
    update_id: Identifier
    source_id: Identifier
    observer_authority: Text
    observed_on: date
    recorded_on: date
    confidence: UpdateConfidence
    verification: VerificationState
    scope_fingerprint: Sha256

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.recorded_on < self.observed_on:
            raise ValueError("status recorded date cannot predate observation")
        return self


class DesignStatusUpdate(StatusUpdateBase):
    dimension: Literal[StatusDimension.DESIGN] = StatusDimension.DESIGN
    state: DesignState


class FundingStatusUpdate(StatusUpdateBase):
    dimension: Literal[StatusDimension.FUNDING] = StatusDimension.FUNDING
    state: FundingState


class ConstructionStatusUpdate(StatusUpdateBase):
    dimension: Literal[StatusDimension.CONSTRUCTION] = StatusDimension.CONSTRUCTION
    state: ConstructionState


class CompletionStatusUpdate(StatusUpdateBase):
    dimension: Literal[StatusDimension.COMPLETION] = StatusDimension.COMPLETION
    state: CompletionState


class OutcomeStatusUpdate(StatusUpdateBase):
    dimension: Literal[StatusDimension.OUTCOME] = StatusDimension.OUTCOME
    state: OutcomeState


ProgrammeStatusUpdate = Annotated[
    DesignStatusUpdate
    | FundingStatusUpdate
    | ConstructionStatusUpdate
    | CompletionStatusUpdate
    | OutcomeStatusUpdate,
    Field(discriminator="dimension"),
]


class DeliveryMilestone(MonitoringContract):
    milestone_id: Identifier
    title: Text
    due_on: date
    completion_update_id: Identifier | None
    blocked_reason: Text | None
    blocked_update_id: Identifier | None

    @model_validator(mode="after")
    def block_provenance(self) -> Self:
        if (self.blocked_reason is None) != (self.blocked_update_id is None):
            raise ValueError("blocked milestone requires reason and source update")
        return self


class ScopeDeviation(MonitoringContract):
    deviation_id: Identifier
    previous_scope_fingerprint: Sha256
    updated_scope_fingerprint: Sha256
    rationale: Text
    source_id: Identifier
    authority: Text
    recorded_on: date
    confidence: UpdateConfidence
    verification: VerificationState

    @model_validator(mode="after")
    def actual_change(self) -> Self:
        if self.previous_scope_fingerprint == self.updated_scope_fingerprint:
            raise ValueError("scope deviation must record a changed fingerprint")
        return self


_ORDERED_STATES: dict[StatusDimension, dict[StrEnum, int]] = {
    StatusDimension.DESIGN: {
        state: index for index, state in enumerate(DesignState)
    },
    StatusDimension.FUNDING: {
        state: index for index, state in enumerate(FundingState)
    },
    StatusDimension.COMPLETION: {
        state: index for index, state in enumerate(CompletionState)
    },
    StatusDimension.OUTCOME: {
        state: index for index, state in enumerate(OutcomeState)
    },
}


class ProgrammeDeliveryRecord(MonitoringContract):
    programme_entry_id: Identifier
    intervention_id: Identifier
    responsible_owner: Text
    planned_scope: Text
    planned_scope_fingerprint: Sha256
    milestones: tuple[DeliveryMilestone, ...] = Field(min_length=1)
    updates: tuple[ProgrammeStatusUpdate, ...] = Field(min_length=1)
    deviations: tuple[ScopeDeviation, ...]

    @model_validator(mode="after")
    def coherent_history(self) -> Self:
        _unique(self.milestones, "milestone_id", "milestone")
        update_ids = _unique(self.updates, "update_id", "status update")
        _unique(self.deviations, "deviation_id", "scope deviation")
        if len({item.updated_scope_fingerprint for item in self.deviations}) != len(
            self.deviations
        ):
            raise ValueError("scope deviation target fingerprints must be unique")
        reachable_scopes = {self.planned_scope_fingerprint}
        remaining = list(self.deviations)
        while remaining:
            resolved = [
                item
                for item in remaining
                if item.previous_scope_fingerprint in reachable_scopes
            ]
            if not resolved:
                raise ValueError("scope deviation lineage must start from planned scope")
            for item in resolved:
                reachable_scopes.add(item.updated_scope_fingerprint)
                remaining.remove(item)
        source_changes = {
            deviation.updated_scope_fingerprint for deviation in self.deviations
        }
        for update in self.updates:
            if (
                update.scope_fingerprint != self.planned_scope_fingerprint
                and update.scope_fingerprint not in source_changes
            ):
                raise ValueError(
                    "changed update scope requires a matching governed scope deviation"
                )
            if (
                update.verification is VerificationState.VERIFIED
                and update.scope_fingerprint != self.planned_scope_fingerprint
                and not any(
                    deviation.updated_scope_fingerprint == update.scope_fingerprint
                    and deviation.verification is VerificationState.VERIFIED
                    and deviation.recorded_on <= update.observed_on
                    for deviation in self.deviations
                )
            ):
                raise ValueError(
                    "verified changed-scope update requires a prior verified scope deviation"
                )
        for milestone in self.milestones:
            if (
                milestone.blocked_update_id is not None
                and milestone.blocked_update_id not in update_ids
            ):
                raise ValueError("blocked milestone source update must resolve")
            if milestone.completion_update_id is None:
                continue
            if milestone.completion_update_id not in update_ids:
                raise ValueError("milestone completion update must resolve")
            completion = next(
                item
                for item in self.updates
                if item.update_id == milestone.completion_update_id
            )
            if not (
                isinstance(completion, CompletionStatusUpdate)
                and completion.state is CompletionState.VERIFIED_COMPLETE
                and completion.verification is VerificationState.VERIFIED
            ):
                raise ValueError(
                    "milestone completion requires a verified completion update"
                )
        for dimension in StatusDimension:
            history = sorted(
                (
                    item
                    for item in self.updates
                    if item.dimension is dimension
                    and item.verification is VerificationState.VERIFIED
                ),
                key=lambda item: (item.observed_on, item.recorded_on, item.update_id),
            )
            if dimension is StatusDimension.CONSTRUCTION:
                _validate_construction_transitions(history)
                continue
            ranks = _ORDERED_STATES.get(dimension)
            if ranks is None:
                continue
            previous = -1
            for update in history:
                rank = ranks[update.state]
                if rank < previous:
                    raise ValueError(f"{dimension.value} status cannot regress")
                previous = rank
        verified_completion = any(
            isinstance(item, CompletionStatusUpdate)
            and item.state is CompletionState.VERIFIED_COMPLETE
            and item.verification is VerificationState.VERIFIED
            for item in self.updates
        )
        verified_construction = any(
            isinstance(item, ConstructionStatusUpdate)
            and item.state is ConstructionState.COMPLETE
            and item.verification is VerificationState.VERIFIED
            for item in self.updates
        )
        if verified_completion and not verified_construction:
            raise ValueError(
                "verified completion requires verified construction complete"
            )
        return self


def _validate_construction_transitions(
    history: list[ProgrammeStatusUpdate],
) -> None:
    permitted: dict[ConstructionState, set[ConstructionState]] = {
        ConstructionState.NOT_STARTED: {
            ConstructionState.NOT_STARTED,
            ConstructionState.PROCUREMENT,
        },
        ConstructionState.PROCUREMENT: {
            ConstructionState.PROCUREMENT,
            ConstructionState.UNDERWAY,
        },
        ConstructionState.UNDERWAY: {
            ConstructionState.UNDERWAY,
            ConstructionState.PAUSED,
            ConstructionState.COMPLETE,
        },
        ConstructionState.PAUSED: {
            ConstructionState.PAUSED,
            ConstructionState.UNDERWAY,
            ConstructionState.COMPLETE,
        },
        ConstructionState.COMPLETE: {ConstructionState.COMPLETE},
    }
    previous: ConstructionState | None = None
    for update in history:
        state = update.state
        if not isinstance(state, ConstructionState):
            raise TypeError("construction history contains another status dimension")
        if previous is not None and state not in permitted[previous]:
            raise ValueError("construction status cannot regress")
        previous = state


class IndicatorKind(StrEnum):
    ACTIVITY = "activity"
    OUTCOME = "outcome"


class ObservationKind(StrEnum):
    BASELINE = "baseline"
    MONITORING = "monitoring"


class TargetDirection(StrEnum):
    AT_LEAST = "at-least"
    AT_MOST = "at-most"


class IndicatorDefinition(MonitoringContract):
    indicator_id: Identifier
    kind: IndicatorKind
    name: Text
    unit: Text
    methodology: Text
    baseline_observation_id: Identifier
    target_value: float
    target_direction: TargetDirection
    target_date: date
    reporting_frequency_days: int = Field(gt=0)
    responsible_owner: Text


class IndicatorObservation(MonitoringContract):
    observation_id: Identifier
    indicator_id: Identifier
    kind: ObservationKind
    value: float
    unit: Text
    period_start: date
    period_end: date
    due_on: date
    observed_on: date
    recorded_on: date
    source_id: Identifier
    observer_authority: Text
    confidence: UpdateConfidence
    verification: VerificationState
    coverage: Text
    uncertainty: Text
    contradicts_observation_id: Identifier | None = None

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("observation period end cannot predate start")
        if self.observed_on < self.period_end:
            raise ValueError("observation date cannot predate its observation period")
        if self.recorded_on < self.observed_on:
            raise ValueError("observation recorded date cannot predate observation")
        if self.due_on < self.period_end:
            raise ValueError("observation due date cannot predate its period end")
        if self.contradicts_observation_id == self.observation_id:
            raise ValueError("observation cannot contradict itself")
        return self


class ReviewTriggerKind(StrEnum):
    SCHEDULED_REVIEW = "scheduled-review"
    MATERIAL_DEVELOPMENT = "material-development"
    NETWORK_DELIVERY = "network-delivery"
    GUIDANCE_CHANGE = "guidance-change"
    EVIDENCE_EXPIRY = "evidence-expiry"
    UNDERPERFORMANCE = "underperformance"


class ReviewTrigger(MonitoringContract):
    trigger_id: Identifier
    kind: ReviewTriggerKind
    detected_on: date
    source_id: Identifier
    authority: Text
    rationale: Text
    affected_requirement_ids: tuple[Identifier, ...]
    affected_analysis_ids: tuple[Identifier, ...]
    affected_programme_entry_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def affected_work(self) -> Self:
        if not (
            self.affected_requirement_ids
            or self.affected_analysis_ids
            or self.affected_programme_entry_ids
        ):
            raise ValueError("review trigger must identify affected governed work")
        return self


class RequirementImpactMapping(MonitoringContract):
    requirement_id: Identifier
    analysis_ids: tuple[Identifier, ...] = Field(min_length=1)
    programme_entry_ids: tuple[Identifier, ...] = Field(min_length=1)
    action: Text


class EvidenceImpactMapping(MonitoringContract):
    evidence_id: Identifier
    analysis_ids: tuple[Identifier, ...] = Field(min_length=1)
    programme_entry_ids: tuple[Identifier, ...] = Field(min_length=1)
    action: Text


class SupersedingReleaseProposal(MonitoringContract):
    release_id: Identifier
    predecessor_release_id: Identifier
    predecessor_release_fingerprint: Sha256
    evidence_snapshot_id: Identifier
    evidence_snapshot_fingerprint: Sha256
    guidance_profile_fingerprint: Sha256
    triggered_by: tuple[Identifier, ...] = Field(min_length=1)
    prepared_by: Text
    prepared_on: date
    lifecycle_state: Literal[
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
    ]


class MonitoringConfig(MonitoringContract):
    output_dir: Path
    cycle_id: Identifier
    as_of: date
    historical_release: HistoricalReleaseReference
    evidence_snapshot: EvidenceSnapshotReference
    sources: tuple[MonitoringSource, ...] = Field(min_length=1)
    programme: tuple[ProgrammeDeliveryRecord, ...] = Field(min_length=1)
    indicators: tuple[IndicatorDefinition, ...] = Field(min_length=1)
    observations: tuple[IndicatorObservation, ...] = Field(min_length=1)
    review_triggers: tuple[ReviewTrigger, ...] = ()
    current_guidance_profile: GuidanceProfile
    current_requirement_assessments: tuple[RequirementAssessment, ...]
    requirement_impacts: tuple[RequirementImpactMapping, ...]
    evidence_impacts: tuple[EvidenceImpactMapping, ...]
    superseding_release: SupersedingReleaseProposal | None = None


class HistoricalReleaseSeal(MonitoringContract):
    release_id: Identifier
    lifecycle_state: LifecycleState
    release_fingerprint: Sha256
    evidence_fingerprint: Sha256
    configuration_fingerprint: Sha256
    publication_manifest_sha256: Sha256
    guidance_profile_fingerprint: Sha256
    conformance_fingerprint: Sha256
    guidance_profile: GuidanceProfile
    conformance: ConformanceResult
    source_fingerprints: dict[Identifier, Sha256]


class EvidenceSnapshotSeal(MonitoringContract):
    snapshot_id: Identifier
    snapshot_fingerprint: Sha256
    reference_date: date
    manifest_sha256: Sha256
    item_fingerprints: dict[Identifier, Sha256]


class MonitoringWatermark(MonitoringContract):
    cycle_id: Identifier
    as_of: date
    historical_release_id: Identifier
    historical_release_fingerprint: Sha256
    evidence_snapshot_id: Identifier
    evidence_snapshot_fingerprint: Sha256
    guidance_profile_fingerprint: Sha256


class MonitoringSourceSeal(MonitoringContract):
    source_id: Identifier
    sha256: Sha256
    public_summary: Text


class EffectiveProgrammeStatus(MonitoringContract):
    design: DesignState | None
    funding: FundingState | None
    construction: ConstructionState | None
    completion: CompletionState | None
    outcome: OutcomeState | None


class ProgrammeStatusView(MonitoringContract):
    programme_entry_id: Identifier
    intervention_id: Identifier
    responsible_owner: Text
    planned_scope: Text
    planned_scope_fingerprint: Sha256
    effective_status: EffectiveProgrammeStatus
    overdue_milestone_ids: tuple[Identifier, ...]
    blocked_milestone_ids: tuple[Identifier, ...]
    unverified_update_ids: tuple[Identifier, ...]
    contradicted_update_ids: tuple[Identifier, ...]
    scope_deviation_ids: tuple[Identifier, ...]
    updates: tuple[ProgrammeStatusUpdate, ...]
    milestones: tuple[DeliveryMilestone, ...]
    deviations: tuple[ScopeDeviation, ...]


class TargetStatus(StrEnum):
    NOT_DUE = "not-due"
    MET = "met"
    NOT_MET = "not-met"
    MISSING_DATA = "missing-data"
    UNVERIFIED_DATA = "unverified-data"
    CONTRADICTORY_DATA = "contradictory-data"


class IndicatorStatusView(MonitoringContract):
    indicator_id: Identifier
    kind: IndicatorKind
    definition: IndicatorDefinition
    target_status: TargetStatus
    baseline_observation_id: Identifier
    latest_verified_observation_id: Identifier | None
    next_observation_due_on: date
    late_observation_ids: tuple[Identifier, ...]
    unverified_observation_ids: tuple[Identifier, ...]
    contradicted_observation_ids: tuple[Identifier, ...]
    observations: tuple[IndicatorObservation, ...]


class ReviewTaskState(StrEnum):
    OPEN = "open"
    SUPERSEDING_RELEASE_PREPARED = "superseding-release-prepared"


class GovernedReviewTask(MonitoringContract):
    task_id: Identifier
    trigger_id: Identifier
    trigger_kind: ReviewTriggerKind
    created_on: date
    state: ReviewTaskState
    source_id: Identifier
    authority: Text
    rationale: Text
    affected_requirement_ids: tuple[Identifier, ...]
    affected_analysis_ids: tuple[Identifier, ...]
    affected_programme_entry_ids: tuple[Identifier, ...]


class RequirementChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class GuidanceMigrationEntry(MonitoringContract):
    requirement_id: Identifier
    change: RequirementChangeKind
    previous_status: RequirementStatus | None
    current_status: RequirementStatus | None
    analysis_ids: tuple[Identifier, ...]
    programme_entry_ids: tuple[Identifier, ...]
    action: Text


class EvidenceChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class EvidenceMigrationEntry(MonitoringContract):
    evidence_id: Identifier
    change: EvidenceChangeKind
    previous_fingerprint: Sha256 | None
    current_fingerprint: Sha256 | None
    analysis_ids: tuple[Identifier, ...]
    programme_entry_ids: tuple[Identifier, ...]
    action: Text


class MonitoringArtifact(MonitoringContract):
    path: Text
    sha256: Sha256
    size_bytes: int = Field(gt=0)

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("monitoring artifact must remain inside release")
        return value


ARTIFACTS = (
    "monitoring-status.json",
    "review-tasks.json",
    "migration-report.json",
    "release-comparison.json",
    "monitoring-dashboard.html",
)


class MonitoringManifest(MonitoringContract):
    cycle_id: Identifier
    as_of: date
    watermark: MonitoringWatermark
    historical_release: HistoricalReleaseSeal
    evidence_snapshot: EvidenceSnapshotSeal
    sources: tuple[MonitoringSourceSeal, ...]
    conformance: ConformanceResult
    programme: tuple[ProgrammeStatusView, ...]
    indicators: tuple[IndicatorStatusView, ...]
    review_tasks: tuple[GovernedReviewTask, ...]
    guidance_changes: tuple[GuidanceMigrationEntry, ...]
    evidence_changes: tuple[EvidenceMigrationEntry, ...]
    superseding_release: SupersedingReleaseProposal | None
    artifacts: tuple[MonitoringArtifact, ...]
    monitoring_fingerprint: Sha256
    manifest_fingerprint: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        paths = tuple(item.path for item in self.artifacts)
        if len(paths) != len(set(paths)) or set(paths) != set(ARTIFACTS):
            raise ValueError("monitoring artifact set is incomplete")
        expected_monitoring = _fingerprint(_monitoring_payload(self))
        if self.monitoring_fingerprint != expected_monitoring:
            raise ValueError("monitoring fingerprint does not match contents")
        expected_manifest = _fingerprint(
            self.model_dump(mode="json", exclude={"manifest_fingerprint"})
        )
        if self.manifest_fingerprint != expected_manifest:
            raise ValueError("monitoring manifest fingerprint does not match")
        _validate_manifest_content(self)
        return self


def build_monitoring_release(config: MonitoringConfig) -> Path:
    """Build one immutable, atomic delivery-monitoring and review release."""
    config = MonitoringConfig.model_validate(config.model_dump())
    conformance = evaluate_conformance(
        config.current_guidance_profile,
        config.current_requirement_assessments,
    )
    _validate_config(config, conformance)
    historical = _historical_seal(config.historical_release)
    evidence = _evidence_seal(config.evidence_snapshot)
    sources = tuple(
        MonitoringSourceSeal(
            source_id=item.source_id,
            sha256=item.sha256,
            public_summary=item.public_summary,
        )
        for item in sorted(config.sources, key=lambda item: item.source_id)
    )
    watermark = MonitoringWatermark(
        cycle_id=config.cycle_id,
        as_of=config.as_of,
        historical_release_id=historical.release_id,
        historical_release_fingerprint=historical.release_fingerprint,
        evidence_snapshot_id=evidence.snapshot_id,
        evidence_snapshot_fingerprint=evidence.snapshot_fingerprint,
        guidance_profile_fingerprint=config.current_guidance_profile.fingerprint,
    )
    programme = tuple(
        _programme_status(item, config.as_of) for item in config.programme
    )
    indicators = tuple(
        _indicator_status(item, config.observations, config.as_of)
        for item in config.indicators
    )
    tasks = _review_tasks(config)
    guidance_changes = _guidance_changes(config, conformance)
    evidence_changes = _evidence_changes(config)
    content = {
        "cycle_id": config.cycle_id,
        "as_of": config.as_of,
        "watermark": watermark,
        "historical_release": historical,
        "evidence_snapshot": evidence,
        "sources": sources,
        "conformance": conformance,
        "programme": programme,
        "indicators": indicators,
        "review_tasks": tasks,
        "guidance_changes": guidance_changes,
        "evidence_changes": evidence_changes,
        "superseding_release": config.superseding_release,
    }
    monitoring_fingerprint = _fingerprint(content)
    destination = config.output_dir / config.cycle_id
    if destination.exists():
        existing = validate_monitoring_release(destination)
        if existing.monitoring_fingerprint != monitoring_fingerprint:
            raise ValueError("monitoring release ID is immutable and content changed")
        return destination
    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.cycle_id}-", dir=config.output_dir)
    )
    try:
        _write_release(
            temporary,
            config,
            watermark,
            historical,
            evidence,
            sources,
            conformance,
            programme,
            indicators,
            tasks,
            guidance_changes,
            evidence_changes,
            monitoring_fingerprint,
        )
        artifacts = tuple(
            MonitoringArtifact(
                path=filename,
                sha256=_file_hash(temporary / filename),
                size_bytes=(temporary / filename).stat().st_size,
            )
            for filename in ARTIFACTS
        )
        manifest_payload = {
            "schema_version": "1.0",
            **content,
            "artifacts": artifacts,
            "monitoring_fingerprint": monitoring_fingerprint,
        }
        manifest = MonitoringManifest(
            **manifest_payload,
            manifest_fingerprint=_fingerprint(manifest_payload),
        )
        _write_json(temporary / "monitoring-manifest.json", manifest)
        validate_monitoring_release(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_monitoring_release(path: Path) -> MonitoringManifest:
    """Validate manifest, hashes and all human/machine monitoring views."""
    path = Path(path)
    try:
        manifest = MonitoringManifest.model_validate_json(
            (path / "monitoring-manifest.json").read_text()
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid monitoring release: {error}") from error
    expected_files = {"monitoring-manifest.json", *ARTIFACTS}
    actual_files = {
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("invalid monitoring release: file set mismatch")
    for artifact in manifest.artifacts:
        artifact_path = path / artifact.path
        if (
            not artifact_path.is_file()
            or _file_hash(artifact_path) != artifact.sha256
            or artifact_path.stat().st_size != artifact.size_bytes
        ):
            raise ValueError(
                f"invalid monitoring release: {artifact.path} hash mismatch"
            )
    expected = _artifact_payloads(manifest)
    for filename, value in expected.items():
        if json.loads((path / filename).read_text()) != _json(value):
            raise ValueError(f"invalid monitoring release: {filename} mismatch")
    html = (path / "monitoring-dashboard.html").read_text()
    required = (
        '<html lang="en">',
        'href="#main-content"',
        "<nav",
        "<table",
        "No causal claim is made",
        manifest.cycle_id,
        manifest.monitoring_fingerprint,
    )
    if any(value not in html for value in required):
        raise ValueError("invalid monitoring release: dashboard contract mismatch")
    return manifest


def _validate_config(
    config: MonitoringConfig,
    conformance: ConformanceResult,
) -> None:
    _validate_historical_manifest(config.historical_release)
    _validate_evidence_manifest(config.evidence_snapshot)
    if config.evidence_snapshot.reference_date > config.as_of:
        raise ValueError("evidence snapshot cannot postdate monitoring as-of date")
    if (
        config.evidence_snapshot.snapshot_fingerprint
        == config.historical_release.evidence_fingerprint
    ):
        raise ValueError("monitoring updates require a new evidence snapshot")
    source_ids = _unique(config.sources, "source_id", "monitoring source")
    programme_ids = _unique(
        config.programme,
        "programme_entry_id",
        "programme entry",
    )
    update_ids: set[str] = set()
    for programme in config.programme:
        for update in programme.updates:
            if update.update_id in update_ids:
                raise ValueError("status update IDs must be unique across programme")
            update_ids.add(update.update_id)
            if update.source_id not in source_ids:
                raise ValueError("status update source must resolve")
            if update.recorded_on > config.as_of:
                raise ValueError("status update cannot postdate monitoring as-of date")
        for deviation in programme.deviations:
            if deviation.source_id not in source_ids:
                raise ValueError("scope deviation source must resolve")
            if deviation.recorded_on > config.as_of:
                raise ValueError("scope deviation cannot postdate monitoring as-of date")
    indicator_ids = _unique(config.indicators, "indicator_id", "indicator")
    observation_ids = _unique(
        config.observations,
        "observation_id",
        "indicator observation",
    )
    observations_by_indicator: dict[str, list[IndicatorObservation]] = {
        indicator_id: [] for indicator_id in indicator_ids
    }
    for observation in config.observations:
        if observation.indicator_id not in indicator_ids:
            raise ValueError("observation indicator must resolve")
        if observation.source_id not in source_ids:
            raise ValueError("observation source must resolve")
        if observation.recorded_on > config.as_of:
            raise ValueError("observation cannot postdate monitoring as-of date")
        if (
            observation.contradicts_observation_id is not None
            and observation.contradicts_observation_id not in observation_ids
        ):
            raise ValueError("contradicted observation must resolve")
        observations_by_indicator[observation.indicator_id].append(observation)
    _validate_observation_links(list(config.observations))
    for indicator in config.indicators:
        observations = observations_by_indicator[indicator.indicator_id]
        baselines = tuple(
            item
            for item in observations
            if item.kind is ObservationKind.BASELINE
            and item.observation_id == indicator.baseline_observation_id
        )
        if len(baselines) != 1:
            raise ValueError("indicator baseline observation must resolve exactly once")
        if any(item.unit != indicator.unit for item in observations):
            raise ValueError("indicator observation unit must match definition")
        _validate_observation_conflicts(observations)
    trigger_ids = _unique(config.review_triggers, "trigger_id", "review trigger")
    for trigger in config.review_triggers:
        if trigger.source_id not in source_ids:
            raise ValueError("review trigger source must resolve")
        if not set(trigger.affected_programme_entry_ids).issubset(programme_ids):
            raise ValueError("review trigger programme entry must resolve")
        requirement_ids = {
            item.requirement_id
            for item in (
                *config.historical_release.guidance_profile.requirements,
                *config.current_guidance_profile.requirements,
            )
        }
        if not set(trigger.affected_requirement_ids).issubset(requirement_ids):
            raise ValueError("review trigger requirement must resolve")
        if trigger.detected_on > config.as_of:
            raise ValueError("review trigger cannot postdate monitoring as-of date")
    proposal = config.superseding_release
    if proposal is not None:
        if (
            proposal.predecessor_release_id != config.historical_release.release_id
            or proposal.predecessor_release_fingerprint
            != config.historical_release.release_fingerprint
        ):
            raise ValueError(
                "superseding release predecessor must match historical release"
            )
        if (
            proposal.evidence_snapshot_id != config.evidence_snapshot.snapshot_id
            or proposal.evidence_snapshot_fingerprint
            != config.evidence_snapshot.snapshot_fingerprint
        ):
            raise ValueError("superseding release evidence snapshot must match")
        if (
            proposal.guidance_profile_fingerprint
            != config.current_guidance_profile.fingerprint
        ):
            raise ValueError("superseding release Guidance Profile must match")
        if proposal.release_id == config.historical_release.release_id:
            raise ValueError("superseding release requires a new release ID")
        if not set(proposal.triggered_by).issubset(trigger_ids):
            raise ValueError("superseding release review triggers must resolve")
        if proposal.prepared_on > config.as_of:
            raise ValueError(
                "superseding release preparation cannot postdate as-of date"
            )
    if conformance.profile.fingerprint != config.current_guidance_profile.fingerprint:
        raise ValueError("current conformance Guidance Profile must resolve")
    affected_requirements = _changed_requirement_ids(config, conformance)
    mapped_requirements = _unique(
        config.requirement_impacts,
        "requirement_id",
        "requirement impact",
    )
    if mapped_requirements != affected_requirements:
        raise ValueError(
            "requirement impact mappings must cover exactly the changed requirements"
        )
    if any(
        not set(item.programme_entry_ids).issubset(programme_ids)
        for item in config.requirement_impacts
    ):
        raise ValueError("requirement impact programme entry must resolve")
    affected_evidence = _changed_evidence_ids(config)
    mapped_evidence = _unique(
        config.evidence_impacts,
        "evidence_id",
        "evidence impact",
    )
    if mapped_evidence != affected_evidence:
        raise ValueError(
            "evidence impact mappings must cover exactly the changed evidence"
        )
    if any(
        not set(item.programme_entry_ids).issubset(programme_ids)
        for item in config.evidence_impacts
    ):
        raise ValueError("evidence impact programme entry must resolve")


def _validate_observation_conflicts(
    observations: list[IndicatorObservation],
) -> None:
    for index, left in enumerate(observations):
        for right in observations[index + 1 :]:
            same_period = (
                left.kind is right.kind
                and left.period_start == right.period_start
                and left.period_end == right.period_end
            )
            if not same_period or left.value == right.value:
                continue
            explicitly_linked = (
                left.contradicts_observation_id == right.observation_id
                or right.contradicts_observation_id == left.observation_id
            )
            if not explicitly_linked:
                raise ValueError(
                    "contradictory observation values require an explicit link"
                )


def _validate_observation_links(
    observations: list[IndicatorObservation],
) -> None:
    by_id = {item.observation_id: item for item in observations}
    for observation in observations:
        if observation.contradicts_observation_id is None:
            continue
        contradicted = by_id.get(observation.contradicts_observation_id)
        if contradicted is None:
            raise ValueError("contradicted observation must resolve")
        if (
            contradicted.indicator_id != observation.indicator_id
            or contradicted.kind is not observation.kind
            or contradicted.period_start != observation.period_start
            or contradicted.period_end != observation.period_end
            or contradicted.value == observation.value
        ):
            raise ValueError(
                "contradiction link must identify a different value for the same "
                "indicator, observation kind and period"
            )


def _validate_historical_manifest(reference: HistoricalReleaseReference) -> None:
    path = reference.publication_manifest_path
    if not path.is_file() or _file_hash(path) != reference.publication_manifest_sha256:
        raise ValueError("historical publication manifest hash mismatch")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError("historical publication manifest is invalid JSON") from error
    expected = {
        "release_id": reference.release_id,
        "release_fingerprint": reference.release_fingerprint,
        "evidence_fingerprint": reference.evidence_fingerprint,
        "configuration_fingerprint": reference.configuration_fingerprint,
        "lifecycle_state": reference.lifecycle_state.value,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("historical publication manifest identity mismatch")
    conformance = payload.get("conformance", {})
    if (
        conformance.get("profile_fingerprint")
        != reference.guidance_profile.fingerprint
        or conformance.get("conformance_fingerprint")
        != reference.conformance.conformance_fingerprint
    ):
        raise ValueError("historical publication conformance seal mismatch")


def _validate_evidence_manifest(reference: EvidenceSnapshotReference) -> None:
    path = reference.manifest_path
    if not path.is_file() or _file_hash(path) != reference.manifest_sha256:
        raise ValueError("evidence snapshot manifest hash mismatch")
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError("evidence snapshot manifest is invalid JSON") from error
    if (
        payload.get("snapshot_id") != reference.snapshot_id
        or payload.get("snapshot_fingerprint") != reference.snapshot_fingerprint
        or payload.get("reference_date") != reference.reference_date.isoformat()
    ):
        raise ValueError("evidence snapshot manifest identity mismatch")
    items = payload.get("items")
    if isinstance(items, list):
        try:
            item_fingerprints = {
                str(item["evidence_id"]): str(item["sha256"]) for item in items
            }
        except (KeyError, TypeError) as error:
            raise ValueError("evidence snapshot item seal is invalid") from error
    elif isinstance(items, dict):
        item_fingerprints = items
    else:
        raise ValueError("evidence snapshot item seal is missing")
    if item_fingerprints != reference.item_fingerprints:
        raise ValueError("evidence snapshot item fingerprints differ")


def _historical_seal(
    reference: HistoricalReleaseReference,
) -> HistoricalReleaseSeal:
    return HistoricalReleaseSeal(
        release_id=reference.release_id,
        lifecycle_state=reference.lifecycle_state,
        release_fingerprint=reference.release_fingerprint,
        evidence_fingerprint=reference.evidence_fingerprint,
        configuration_fingerprint=reference.configuration_fingerprint,
        publication_manifest_sha256=reference.publication_manifest_sha256,
        guidance_profile_fingerprint=reference.guidance_profile.fingerprint,
        conformance_fingerprint=reference.conformance.conformance_fingerprint,
        guidance_profile=reference.guidance_profile,
        conformance=reference.conformance,
        source_fingerprints=dict(sorted(reference.source_fingerprints.items())),
    )


def _evidence_seal(
    reference: EvidenceSnapshotReference,
) -> EvidenceSnapshotSeal:
    return EvidenceSnapshotSeal(
        snapshot_id=reference.snapshot_id,
        snapshot_fingerprint=reference.snapshot_fingerprint,
        reference_date=reference.reference_date,
        manifest_sha256=reference.manifest_sha256,
        item_fingerprints=dict(sorted(reference.item_fingerprints.items())),
    )


def _programme_status(
    record: ProgrammeDeliveryRecord,
    as_of: date,
) -> ProgrammeStatusView:
    effective: dict[StatusDimension, StrEnum | None] = {
        dimension: None for dimension in StatusDimension
    }
    for update in sorted(
        record.updates,
        key=lambda item: (item.observed_on, item.recorded_on, item.update_id),
    ):
        if update.verification is VerificationState.VERIFIED:
            effective[update.dimension] = update.state
    completed_update_ids = {
        update.update_id
        for update in record.updates
        if update.verification is VerificationState.VERIFIED
        and (
            isinstance(update, CompletionStatusUpdate)
            and update.state is CompletionState.VERIFIED_COMPLETE
        )
    }
    overdue = tuple(
        milestone.milestone_id
        for milestone in record.milestones
        if milestone.due_on < as_of
        and (
            milestone.completion_update_id is None
            or milestone.completion_update_id not in completed_update_ids
        )
    )
    blocked = tuple(
        milestone.milestone_id
        for milestone in record.milestones
        if milestone.blocked_reason is not None
    )
    return ProgrammeStatusView(
        programme_entry_id=record.programme_entry_id,
        intervention_id=record.intervention_id,
        responsible_owner=record.responsible_owner,
        planned_scope=record.planned_scope,
        planned_scope_fingerprint=record.planned_scope_fingerprint,
        effective_status=EffectiveProgrammeStatus(
            design=effective[StatusDimension.DESIGN],
            funding=effective[StatusDimension.FUNDING],
            construction=effective[StatusDimension.CONSTRUCTION],
            completion=effective[StatusDimension.COMPLETION],
            outcome=effective[StatusDimension.OUTCOME],
        ),
        overdue_milestone_ids=overdue,
        blocked_milestone_ids=blocked,
        unverified_update_ids=tuple(
            item.update_id
            for item in record.updates
            if item.verification is VerificationState.UNVERIFIED
        ),
        contradicted_update_ids=tuple(
            item.update_id
            for item in record.updates
            if item.verification is VerificationState.CONTRADICTED
        ),
        scope_deviation_ids=tuple(item.deviation_id for item in record.deviations),
        updates=record.updates,
        milestones=record.milestones,
        deviations=record.deviations,
    )


def _indicator_status(
    indicator: IndicatorDefinition,
    all_observations: tuple[IndicatorObservation, ...],
    as_of: date,
) -> IndicatorStatusView:
    observations = tuple(
        item
        for item in all_observations
        if item.indicator_id == indicator.indicator_id
    )
    monitoring = tuple(
        item for item in observations if item.kind is ObservationKind.MONITORING
    )
    verified = tuple(
        item
        for item in monitoring
        if item.verification is VerificationState.VERIFIED
    )
    contradicted = tuple(
        item
        for item in monitoring
        if item.verification is VerificationState.CONTRADICTED
        or item.contradicts_observation_id is not None
    )
    unverified = tuple(
        item
        for item in monitoring
        if item.verification is VerificationState.UNVERIFIED
    )
    latest = max(
        verified,
        key=lambda item: (item.period_end, item.recorded_on, item.observation_id),
        default=None,
    )
    latest_recorded = max(
        observations,
        key=lambda item: (item.due_on, item.recorded_on, item.observation_id),
    )
    next_observation_due_on = latest_recorded.due_on + timedelta(
        days=indicator.reporting_frequency_days
    )
    if contradicted:
        status = TargetStatus.CONTRADICTORY_DATA
    elif unverified and latest is None:
        status = TargetStatus.UNVERIFIED_DATA
    elif as_of > next_observation_due_on:
        status = TargetStatus.MISSING_DATA
    elif latest is None:
        status = (
            TargetStatus.NOT_DUE
            if as_of < indicator.target_date
            else TargetStatus.MISSING_DATA
        )
    else:
        achieved = (
            latest.value >= indicator.target_value
            if indicator.target_direction is TargetDirection.AT_LEAST
            else latest.value <= indicator.target_value
        )
        status = TargetStatus.MET if achieved else TargetStatus.NOT_MET
    return IndicatorStatusView(
        indicator_id=indicator.indicator_id,
        kind=indicator.kind,
        definition=indicator,
        target_status=status,
        baseline_observation_id=indicator.baseline_observation_id,
        latest_verified_observation_id=(
            latest.observation_id if latest is not None else None
        ),
        next_observation_due_on=next_observation_due_on,
        late_observation_ids=tuple(
            item.observation_id
            for item in observations
            if item.recorded_on > item.due_on
        ),
        unverified_observation_ids=tuple(
            item.observation_id
            for item in observations
            if item.verification is VerificationState.UNVERIFIED
        ),
        contradicted_observation_ids=tuple(
            item.observation_id for item in contradicted
        ),
        observations=observations,
    )


def _review_tasks(config: MonitoringConfig) -> tuple[GovernedReviewTask, ...]:
    prepared = (
        set(config.superseding_release.triggered_by)
        if config.superseding_release is not None
        else set()
    )
    return tuple(
        GovernedReviewTask(
            task_id=f"review-{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            trigger_kind=trigger.kind,
            created_on=trigger.detected_on,
            state=(
                ReviewTaskState.SUPERSEDING_RELEASE_PREPARED
                if trigger.trigger_id in prepared
                else ReviewTaskState.OPEN
            ),
            source_id=trigger.source_id,
            authority=trigger.authority,
            rationale=trigger.rationale,
            affected_requirement_ids=trigger.affected_requirement_ids,
            affected_analysis_ids=trigger.affected_analysis_ids,
            affected_programme_entry_ids=trigger.affected_programme_entry_ids,
        )
        for trigger in sorted(
            config.review_triggers,
            key=lambda item: (item.detected_on, item.trigger_id),
        )
    )


def _changed_requirement_ids(
    config: MonitoringConfig,
    current_conformance: ConformanceResult,
) -> set[str]:
    previous_requirements = {
        item.requirement_id: item
        for item in config.historical_release.guidance_profile.requirements
    }
    current_requirements = {
        item.requirement_id: item
        for item in config.current_guidance_profile.requirements
    }
    previous_statuses = {
        item.requirement_id: item.status
        for item in config.historical_release.conformance.requirements
    }
    current_statuses = {
        item.requirement_id: item.status
        for item in current_conformance.requirements
    }
    changed = set(previous_requirements) ^ set(current_requirements)
    for requirement_id in set(previous_requirements) & set(current_requirements):
        if (
            _fingerprint(previous_requirements[requirement_id])
            != _fingerprint(current_requirements[requirement_id])
            or previous_statuses[requirement_id] != current_statuses[requirement_id]
        ):
            changed.add(requirement_id)
    return changed


def _guidance_changes(
    config: MonitoringConfig,
    current_conformance: ConformanceResult,
) -> tuple[GuidanceMigrationEntry, ...]:
    previous_requirements = {
        item.requirement_id: item
        for item in config.historical_release.guidance_profile.requirements
    }
    current_requirements = {
        item.requirement_id: item
        for item in config.current_guidance_profile.requirements
    }
    previous_statuses = {
        item.requirement_id: item.status
        for item in config.historical_release.conformance.requirements
    }
    current_statuses = {
        item.requirement_id: item.status
        for item in current_conformance.requirements
    }
    mappings = {
        item.requirement_id: item for item in config.requirement_impacts
    }
    entries = []
    for requirement_id in sorted(_changed_requirement_ids(config, current_conformance)):
        if requirement_id not in previous_requirements:
            change = RequirementChangeKind.ADDED
        elif requirement_id not in current_requirements:
            change = RequirementChangeKind.REMOVED
        else:
            change = RequirementChangeKind.CHANGED
        mapping = mappings[requirement_id]
        entries.append(
            GuidanceMigrationEntry(
                requirement_id=requirement_id,
                change=change,
                previous_status=previous_statuses.get(requirement_id),
                current_status=current_statuses.get(requirement_id),
                analysis_ids=tuple(sorted(set(mapping.analysis_ids))),
                programme_entry_ids=tuple(
                    sorted(set(mapping.programme_entry_ids))
                ),
                action=mapping.action,
            )
        )
    return tuple(entries)


def _changed_evidence_ids(config: MonitoringConfig) -> set[str]:
    previous = config.historical_release.source_fingerprints
    current = config.evidence_snapshot.item_fingerprints
    changed = set(previous) ^ set(current)
    changed.update(
        evidence_id
        for evidence_id in set(previous) & set(current)
        if previous[evidence_id] != current[evidence_id]
    )
    return changed


def _evidence_changes(
    config: MonitoringConfig,
) -> tuple[EvidenceMigrationEntry, ...]:
    previous = config.historical_release.source_fingerprints
    current = config.evidence_snapshot.item_fingerprints
    mappings = {item.evidence_id: item for item in config.evidence_impacts}
    entries = []
    for evidence_id in sorted(_changed_evidence_ids(config)):
        if evidence_id not in previous:
            change = EvidenceChangeKind.ADDED
        elif evidence_id not in current:
            change = EvidenceChangeKind.REMOVED
        else:
            change = EvidenceChangeKind.CHANGED
        mapping = mappings[evidence_id]
        entries.append(
            EvidenceMigrationEntry(
                evidence_id=evidence_id,
                change=change,
                previous_fingerprint=previous.get(evidence_id),
                current_fingerprint=current.get(evidence_id),
                analysis_ids=tuple(sorted(set(mapping.analysis_ids))),
                programme_entry_ids=tuple(
                    sorted(set(mapping.programme_entry_ids))
                ),
                action=mapping.action,
            )
        )
    return tuple(entries)


def _write_release(
    path: Path,
    config: MonitoringConfig,
    watermark: MonitoringWatermark,
    historical: HistoricalReleaseSeal,
    evidence: EvidenceSnapshotSeal,
    sources: tuple[MonitoringSourceSeal, ...],
    conformance: ConformanceResult,
    programme: tuple[ProgrammeStatusView, ...],
    indicators: tuple[IndicatorStatusView, ...],
    tasks: tuple[GovernedReviewTask, ...],
    guidance_changes: tuple[GuidanceMigrationEntry, ...],
    evidence_changes: tuple[EvidenceMigrationEntry, ...],
    monitoring_fingerprint: str,
) -> None:
    _write_json(
        path / "monitoring-status.json",
        {
            "watermark": watermark,
            "programme": programme,
            "indicators": indicators,
            "sources": sources,
        },
    )
    _write_json(
        path / "review-tasks.json",
        {"watermark": watermark, "tasks": tasks},
    )
    _write_json(
        path / "migration-report.json",
        {
            "watermark": watermark,
            "conformance": conformance,
            "guidance_changes": guidance_changes,
            "evidence_changes": evidence_changes,
        },
    )
    _write_json(
        path / "release-comparison.json",
        {
            "watermark": watermark,
            "historical_release": historical,
            "evidence_snapshot": evidence,
            "superseding_release": config.superseding_release,
        },
    )
    (path / "monitoring-dashboard.html").write_text(
        _dashboard_html(
            config,
            watermark,
            programme,
            indicators,
            tasks,
            guidance_changes,
            evidence_changes,
            monitoring_fingerprint,
        )
    )


def _dashboard_html(
    config: MonitoringConfig,
    watermark: MonitoringWatermark,
    programme: tuple[ProgrammeStatusView, ...],
    indicators: tuple[IndicatorStatusView, ...],
    tasks: tuple[GovernedReviewTask, ...],
    guidance_changes: tuple[GuidanceMigrationEntry, ...],
    evidence_changes: tuple[EvidenceMigrationEntry, ...],
    monitoring_fingerprint: str,
) -> str:
    successor = (
        "No superseding release proposal has been prepared."
        if config.superseding_release is None
        else (
            f"Proposed successor {escape(config.superseding_release.release_id)} "
            f"remains {escape(config.superseding_release.lifecycle_state.value)}."
        )
    )
    programme_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(item.programme_entry_id)}</th>'
        f"<td>{escape(item.responsible_owner)}</td>"
        f"<td>{escape(_status_summary(item.effective_status))}</td>"
        f"<td>{escape(', '.join(item.overdue_milestone_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.blocked_milestone_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.unverified_update_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.contradicted_update_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.scope_deviation_ids) or 'None')}</td>"
        "</tr>"
        for item in programme
    )
    indicator_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(item.indicator_id)}</th>'
        f"<td>{escape(item.kind.value)}</td>"
        f"<td>{escape(item.target_status.value)}</td>"
        f"<td>{escape(', '.join(item.late_observation_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.unverified_observation_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.contradicted_observation_ids) or 'None')}</td>"
        "</tr>"
        for item in indicators
    )
    task_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(item.task_id)}</th>'
        f"<td>{escape(item.trigger_kind.value)}</td>"
        f"<td>{escape(item.state.value)}</td>"
        f"<td>{escape(item.authority)}</td>"
        f"<td>{escape(item.rationale)}</td>"
        "</tr>"
        for item in tasks
    ) or '<tr><td colspan="5">No governed review tasks for this cycle.</td></tr>'
    migration_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(item.requirement_id)}</th>'
        f"<td>{escape(item.change.value)}</td>"
        f"<td>{escape(', '.join(item.analysis_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.programme_entry_ids) or 'None')}</td>"
        f"<td>{escape(item.action)}</td>"
        "</tr>"
        for item in guidance_changes
    ) or '<tr><td colspan="5">No Guidance Profile changes.</td></tr>'
    evidence_rows = "".join(
        "<tr>"
        f'<th scope="row">{escape(item.evidence_id)}</th>'
        f"<td>{escape(item.change.value)}</td>"
        f"<td>{escape(', '.join(item.analysis_ids) or 'None')}</td>"
        f"<td>{escape(', '.join(item.programme_entry_ids) or 'None')}</td>"
        f"<td>{escape(item.action)}</td>"
        "</tr>"
        for item in evidence_changes
    ) or '<tr><td colspan="5">No evidence snapshot item changes.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="monitoring-cycle-id" content="{escape(config.cycle_id)}">
  <meta name="monitoring-fingerprint" content="{monitoring_fingerprint}">
  <title>LCWIP delivery monitoring - {escape(config.cycle_id)}</title>
  <style>
    :root {{ --ink:#17212b; --blue:#123b52; --pale:#eaf4f8; --amber:#ffdf85;
      --red:#a61b1b; }} * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); font:18px/1.5 system-ui,sans-serif; }}
    header,main,footer {{ max-width:86rem; margin:auto; padding:1.5rem; }}
    header {{ border-top:1rem solid var(--blue); }} nav ul {{ display:flex;
      flex-wrap:wrap; gap:.5rem 1.25rem; }} a {{ color:#004f7c; }}
    a:focus-visible {{ outline:4px solid #ffbf47; outline-offset:3px; }}
    .skip {{ position:absolute; left:-9999px; }} .skip:focus {{ left:1rem;
      top:1rem; background:white; padding:.75rem; z-index:2; }}
    .notice {{ border-left:.6rem solid var(--amber); background:#fff8df;
      padding:1rem; }} table {{ border-collapse:collapse; width:100%;
      margin:1rem 0 2.5rem; }} caption {{ text-align:left; font-weight:800; }}
    .table-scroll {{ max-width:100%; overflow-x:auto; }}
    .table-scroll:focus-visible {{ outline:4px solid #ffbf47;
      outline-offset:3px; }}
    th,td {{ border:1px solid #50606e; padding:.6rem; text-align:left;
      vertical-align:top; }} th {{ background:var(--pale); }}
    footer {{ border-top:2px solid var(--blue); font-size:.85em;
      overflow-wrap:anywhere; }}
  </style>
</head>
<body>
<a class="skip" href="#main-content">Skip to main content</a>
<header>
  <h1>LCWIP delivery monitoring</h1>
  <p>Cycle {escape(config.cycle_id)} at {config.as_of.isoformat()}.</p>
  <p>Historical release {escape(config.historical_release.release_id)} remains
  immutable. {successor}</p>
  <nav aria-label="Dashboard sections"><ul>
    <li><a href="#programme">Programme</a></li>
    <li><a href="#indicators">Indicators</a></li>
    <li><a href="#review">Review tasks</a></li>
    <li><a href="#migration">Migration</a></li>
  </ul></nav>
</header>
<main id="main-content">
  <aside class="notice"><strong>Evidence boundary:</strong> activity and delivery
  status are distinct from observed outcomes. No causal claim is made.</aside>
  <section id="programme"><h2>Programme delivery</h2>
    <div class="table-scroll" role="region" aria-label="Programme delivery table"
    tabindex="0"><table><caption>Overdue, blocked, unverified, contradicted and
    changed scope remain explicit</caption>
    <thead><tr><th scope="col">Programme entry</th><th scope="col">Owner</th>
    <th scope="col">Verified status by dimension</th><th scope="col">Overdue</th>
    <th scope="col">Blocked</th><th scope="col">Unverified</th>
    <th scope="col">Contradicted</th><th scope="col">Scope changes</th></tr></thead>
    <tbody>{programme_rows}</tbody></table></div></section>
  <section id="indicators"><h2>Monitoring indicators</h2>
    <div class="table-scroll" role="region" aria-label="Monitoring indicators table"
    tabindex="0"><table><caption>Baselines, observations and target status</caption><thead><tr>
    <th scope="col">Indicator</th><th scope="col">Kind</th>
    <th scope="col">Target status</th><th scope="col">Late data</th>
    <th scope="col">Unverified data</th><th scope="col">Contradicted data</th>
    </tr></thead>
    <tbody>{indicator_rows}</tbody></table></div></section>
  <section id="review"><h2>Governed review tasks</h2>
    <div class="table-scroll" role="region" aria-label="Governed review tasks table"
    tabindex="0"><table><caption>Triggers create work; they do not silently
    change the plan</caption>
    <thead><tr><th scope="col">Task</th><th scope="col">Trigger</th>
    <th scope="col">State</th><th scope="col">Authority</th>
    <th scope="col">Rationale</th></tr></thead>
    <tbody>{task_rows}</tbody></table></div></section>
  <section id="migration"><h2>Guidance and evidence migration</h2>
    <div class="table-scroll" role="region" aria-label="Guidance migration table"
    tabindex="0"><table><caption>Changed Guidance Profile requirements</caption><thead><tr>
    <th scope="col">Requirement</th><th scope="col">Change</th>
    <th scope="col">Analyses</th><th scope="col">Programme entries</th>
    <th scope="col">Required action</th></tr></thead>
    <tbody>{migration_rows}</tbody></table></div>
    <div class="table-scroll" role="region" aria-label="Evidence migration table"
    tabindex="0"><table><caption>Changed evidence snapshot items</caption><thead><tr>
    <th scope="col">Evidence</th><th scope="col">Change</th>
    <th scope="col">Analyses</th><th scope="col">Programme entries</th>
    <th scope="col">Required action</th></tr></thead>
    <tbody>{evidence_rows}</tbody></table></div></section>
</main>
<footer><p>{escape(config.cycle_id)} | historical
{watermark.historical_release_fingerprint} | evidence
{watermark.evidence_snapshot_fingerprint} | monitoring {monitoring_fingerprint}</p></footer>
</body>
</html>
"""


def _artifact_payloads(manifest: MonitoringManifest) -> dict[str, Any]:
    return {
        "monitoring-status.json": {
            "watermark": manifest.watermark,
            "programme": manifest.programme,
            "indicators": manifest.indicators,
            "sources": manifest.sources,
        },
        "review-tasks.json": {
            "watermark": manifest.watermark,
            "tasks": manifest.review_tasks,
        },
        "migration-report.json": {
            "watermark": manifest.watermark,
            "conformance": manifest.conformance,
            "guidance_changes": manifest.guidance_changes,
            "evidence_changes": manifest.evidence_changes,
        },
        "release-comparison.json": {
            "watermark": manifest.watermark,
            "historical_release": manifest.historical_release,
            "evidence_snapshot": manifest.evidence_snapshot,
            "superseding_release": manifest.superseding_release,
        },
    }


def _validate_manifest_content(manifest: MonitoringManifest) -> None:
    if manifest.watermark.cycle_id != manifest.cycle_id:
        raise ValueError("monitoring watermark cycle does not match")
    if manifest.watermark.as_of != manifest.as_of:
        raise ValueError("monitoring watermark date does not match")
    if (
        manifest.watermark.historical_release_id
        != manifest.historical_release.release_id
        or manifest.watermark.historical_release_fingerprint
        != manifest.historical_release.release_fingerprint
    ):
        raise ValueError("monitoring historical release seal does not match")
    if (
        manifest.historical_release.guidance_profile.fingerprint
        != manifest.historical_release.guidance_profile_fingerprint
        or manifest.historical_release.conformance.conformance_fingerprint
        != manifest.historical_release.conformance_fingerprint
        or manifest.historical_release.conformance.profile.fingerprint
        != manifest.historical_release.guidance_profile.fingerprint
    ):
        raise ValueError("historical Guidance Profile and conformance seal differ")
    if (
        manifest.watermark.evidence_snapshot_id
        != manifest.evidence_snapshot.snapshot_id
        or manifest.watermark.evidence_snapshot_fingerprint
        != manifest.evidence_snapshot.snapshot_fingerprint
    ):
        raise ValueError("monitoring evidence snapshot seal does not match")
    if manifest.superseding_release is not None and (
        manifest.superseding_release.predecessor_release_fingerprint
        != manifest.historical_release.release_fingerprint
        or manifest.superseding_release.evidence_snapshot_fingerprint
        != manifest.evidence_snapshot.snapshot_fingerprint
        or manifest.superseding_release.guidance_profile_fingerprint
        != manifest.conformance.profile.fingerprint
    ):
        raise ValueError(
            "superseding release proposal does not match monitoring seals"
        )
    source_ids = _unique(manifest.sources, "source_id", "monitoring source")
    update_ids: set[str] = set()
    for view in manifest.programme:
        record = ProgrammeDeliveryRecord(
            programme_entry_id=view.programme_entry_id,
            intervention_id=view.intervention_id,
            responsible_owner=view.responsible_owner,
            planned_scope=view.planned_scope,
            planned_scope_fingerprint=view.planned_scope_fingerprint,
            milestones=view.milestones,
            updates=view.updates,
            deviations=view.deviations,
        )
        if _programme_status(record, manifest.as_of) != view:
            raise ValueError("programme status view does not match governed updates")
        for update in view.updates:
            if update.update_id in update_ids:
                raise ValueError("manifest status update IDs must be unique")
            update_ids.add(update.update_id)
            if update.source_id not in source_ids:
                raise ValueError("manifest status update source must resolve")
        if any(item.source_id not in source_ids for item in view.deviations):
            raise ValueError("manifest scope deviation source must resolve")
    observations: list[IndicatorObservation] = []
    for view in manifest.indicators:
        if view.definition.indicator_id != view.indicator_id:
            raise ValueError("indicator status definition does not match")
        observations.extend(view.observations)
        _validate_observation_conflicts(list(view.observations))
        if any(item.source_id not in source_ids for item in view.observations):
            raise ValueError("manifest observation source must resolve")
        if (
            _indicator_status(
                view.definition,
                view.observations,
                manifest.as_of,
            )
            != view
        ):
            raise ValueError("indicator status view does not match observations")
    _unique(tuple(observations), "observation_id", "manifest observation")
    _validate_observation_links(observations)
    trigger_ids = {task.trigger_id for task in manifest.review_tasks}
    if (
        manifest.superseding_release is not None
        and not set(manifest.superseding_release.triggered_by).issubset(trigger_ids)
    ):
        raise ValueError("superseding release review tasks do not resolve")
    programme_ids = {item.programme_entry_id for item in manifest.programme}
    for task in manifest.review_tasks:
        if task.source_id not in source_ids:
            raise ValueError("review task source must resolve")
        if not set(task.affected_programme_entry_ids).issubset(programme_ids):
            raise ValueError("review task programme entry does not resolve")
    previous_requirements = {
        item.requirement_id: item
        for item in manifest.historical_release.guidance_profile.requirements
    }
    current_requirements = {
        item.requirement_id: item
        for item in manifest.conformance.profile.requirements
    }
    previous_statuses = {
        item.requirement_id: item.status
        for item in manifest.historical_release.conformance.requirements
    }
    current_statuses = {
        item.requirement_id: item.status
        for item in manifest.conformance.requirements
    }
    expected_requirement_changes = set(previous_requirements) ^ set(
        current_requirements
    )
    expected_requirement_changes.update(
        requirement_id
        for requirement_id in set(previous_requirements) & set(current_requirements)
        if (
            _fingerprint(previous_requirements[requirement_id])
            != _fingerprint(current_requirements[requirement_id])
            or previous_statuses[requirement_id] != current_statuses[requirement_id]
        )
    )
    if {item.requirement_id for item in manifest.guidance_changes} != (
        expected_requirement_changes
    ):
        raise ValueError("guidance migration set does not match sealed profiles")
    for item in manifest.guidance_changes:
        expected_change = (
            RequirementChangeKind.ADDED
            if item.requirement_id not in previous_requirements
            else (
                RequirementChangeKind.REMOVED
                if item.requirement_id not in current_requirements
                else RequirementChangeKind.CHANGED
            )
        )
        if (
            item.change is not expected_change
            or item.previous_status != previous_statuses.get(item.requirement_id)
            or item.current_status != current_statuses.get(item.requirement_id)
        ):
            raise ValueError("guidance migration entry does not match sealed profiles")
    previous_evidence = manifest.historical_release.source_fingerprints
    current_evidence = manifest.evidence_snapshot.item_fingerprints
    expected_evidence_changes = set(previous_evidence) ^ set(current_evidence)
    expected_evidence_changes.update(
        evidence_id
        for evidence_id in set(previous_evidence) & set(current_evidence)
        if previous_evidence[evidence_id] != current_evidence[evidence_id]
    )
    if {item.evidence_id for item in manifest.evidence_changes} != (
        expected_evidence_changes
    ):
        raise ValueError("evidence migration set does not match sealed snapshots")
    for item in manifest.evidence_changes:
        expected_change = (
            EvidenceChangeKind.ADDED
            if item.evidence_id not in previous_evidence
            else (
                EvidenceChangeKind.REMOVED
                if item.evidence_id not in current_evidence
                else EvidenceChangeKind.CHANGED
            )
        )
        if (
            item.change is not expected_change
            or item.previous_fingerprint
            != previous_evidence.get(item.evidence_id)
            or item.current_fingerprint != current_evidence.get(item.evidence_id)
        ):
            raise ValueError("evidence migration entry does not match sealed snapshots")


def _monitoring_payload(record: Any) -> dict[str, Any]:
    return {
        "cycle_id": record.cycle_id,
        "as_of": record.as_of,
        "watermark": record.watermark,
        "historical_release": record.historical_release,
        "evidence_snapshot": record.evidence_snapshot,
        "sources": record.sources,
        "conformance": record.conformance,
        "programme": record.programme,
        "indicators": record.indicators,
        "review_tasks": record.review_tasks,
        "guidance_changes": record.guidance_changes,
        "evidence_changes": record.evidence_changes,
        "superseding_release": record.superseding_release,
    }


def _status_summary(status: EffectiveProgrammeStatus) -> str:
    return "; ".join(
        f"{dimension}: {value.value if value is not None else 'unverified/not reported'}"
        for dimension, value in (
            ("design", status.design),
            ("funding", status.funding),
            ("construction", status.construction),
            ("completion", status.completion),
            ("outcome", status.outcome),
        )
    )


def _unique(
    records: tuple[Any, ...],
    field: str,
    label: str,
) -> set[str]:
    identifiers = [str(getattr(item, field)) for item in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{label} IDs must be unique")
    return set(identifiers)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json(value), indent=2, sort_keys=True) + "\n")


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, (date, Path, StrEnum)):
        return str(value)
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
