"""Typed contracts shared by the four compiler modules."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


class TrafficLight(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    GREY = "grey"


class NetworkScope(StrEnum):
    RURAL = "rural"
    URBAN = "urban"
    UNRESOLVED = "unresolved"


class OfficialRoadClassification(StrEnum):
    A_ROAD = "a-road"
    B_ROAD = "b-road"
    CLASSIFIED_UNNUMBERED = "classified-unnumbered"
    UNCLASSIFIED = "unclassified"
    UNKNOWN = "unknown"


class UrbanClassificationStatus(StrEnum):
    GOVERNED_OFFICIAL = "governed-official"
    EXPLICIT_UNKNOWN = "explicit-unknown"


class TopographyComparisonStatus(StrEnum):
    EVIDENCE_UNAVAILABLE = "evidence-unavailable"
    NOT_TRIGGERED = "not-triggered"
    EASIER_ALTERNATIVE_SELECTED = "easier-alternative-selected"
    ORIGINAL_RETAINED = "original-retained-no-easier-option"
    STRATEGIC_SPINE_RETAINED = "strategic-spine-retained"
    GATE_REVISED_SELECTION = "gate-revised-selection"
    GATE_REJECTED_SELECTION = "gate-rejected-selection"


class AccessPointStatus(StrEnum):
    MAPPED = "mapped"
    INFERRED = "inferred"
    UNRESOLVED = "unresolved"


class AccessServiceStatus(StrEnum):
    SERVED = "served"
    SERVED_PROVISIONAL = "served-provisional"
    NETWORK_GAP = "network-gap"


ACCESS_OBLIGATION_COLUMNS = [
    "obligation_id",
    "obligation_kind",
    "place_id",
    "community_id",
    "school_id",
    "school_kind",
    "name",
    "network_role",
    "network_scope",
    "service_status",
    "service_rationale",
    "access_point_status",
    "access_point_source_id",
    "access_point_rationale",
    "criterion_access_point",
    "criterion_continuity",
    "access_connection_id",
    "root_spine_id",
    "branch_id",
    "low_traffic_area_id",
    "low_traffic_area_name",
    "portal_id",
    "portal_name",
    "urban_spine_id",
    "fabric_source_ids",
    "supporting_evidence",
    "finding",
    "geometry_semantics",
    "provenance",
    "geometry",
]


class GovernedSpatialSourceConfig(BaseModel):
    path: Path
    source_id: str = Field(min_length=1)
    effective_date: date
    licence: str = Field(min_length=1)


class OfficialRoadClassificationConfig(GovernedSpatialSourceConfig):
    pass


class ObservedThroughTrafficConfig(GovernedSpatialSourceConfig):
    pass


class NationalElevationConfig(BaseModel):
    provider: Literal["local-geojson", "remote-geojson"]
    source_id: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    effective_date: date | None = None
    path: Path | None = None
    url: str | None = None
    elevation_field: str = "elevation_m"
    identifier_field: str = "evidence_id"
    timeout_seconds: int = Field(default=90, ge=1, le=600)

    @model_validator(mode="after")
    def validate_provider_location(self) -> NationalElevationConfig:
        if self.provider == "local-geojson" and self.path is None:
            raise ValueError("local national Elevation Evidence requires path")
        if self.provider == "remote-geojson" and not self.url:
            raise ValueError("remote national Elevation Evidence requires url")
        return self


class UrbanSettlementFormConfig(BaseModel):
    """Council-governed evidence thresholds for village circulation planning."""

    eligible_place_classes: list[str] = Field(default_factory=lambda: ["village"])
    assessment_radius_km: float = Field(default=1.0, gt=0)
    maximum_component_association_m: float = Field(default=250.0, gt=0)
    component_association_tolerance_m: float = Field(default=10.0, ge=0)
    minimum_minor_street_length_km: float = Field(default=15.0, gt=0)
    minimum_junction_count: int = Field(default=100, ge=1)


class SourceConfig(BaseModel):
    kind: Literal["fixture", "osm"] = "fixture"
    fixture_dir: Path | None = None
    snapshot_dir: Path
    snapshot_id: str = "current"
    osm_place_query: str | None = None
    ncn_feature_service_url: str | None = None
    network_type: str = "bike"
    overpass_url: str = "https://overpass-api.de/api"
    osm_timeout_seconds: int = Field(default=180, ge=30, le=1800)
    external_buffer_km: float = 15.0
    internal_portal_threshold_km: float = 1.0
    community_place_types: list[str] = Field(
        default_factory=lambda: ["town", "village", "suburb", "quarter", "neighbourhood"]
    )
    urban_place_types: list[str] = Field(
        default_factory=lambda: ["city", "town", "suburb", "quarter", "neighbourhood"]
    )
    urban_place_source_ids: list[str] = Field(default_factory=list)
    urban_settlement_form: UrbanSettlementFormConfig = Field(
        default_factory=UrbanSettlementFormConfig
    )
    urban_scope_buffer_km: float = Field(default=2.0, gt=0)
    strategic_destination_source_ids: list[str] = Field(default_factory=list)
    official_road_classification: OfficialRoadClassificationConfig | None = None
    observed_through_traffic: ObservedThroughTrafficConfig | None = None
    national_elevation: NationalElevationConfig | None = None


class AgentReviewAudit(BaseModel):
    governing_status: TrafficLight
    review_policy: tuple[TrafficLight, ...]
    review_required: bool

    @field_validator("review_policy")
    @classmethod
    def canonicalise_review_policy(
        cls, value: tuple[TrafficLight, ...]
    ) -> tuple[TrafficLight, ...]:
        selected = set(value)
        return tuple(status for status in TrafficLight if status in selected)

    @model_validator(mode="after")
    def validate_review_requirement(self) -> AgentReviewAudit:
        required_by_policy = self.governing_status in self.review_policy
        if self.review_required != required_by_policy:
            raise ValueError("review_required must match governing_status membership in policy")
        return self


class AgentReviewDecision(AgentReviewAudit):
    model_config = ConfigDict(frozen=True)


class AgentConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    provider: str = "fake"
    model: str | None = None
    review_statuses: tuple[TrafficLight, ...] = (
        TrafficLight.AMBER,
        TrafficLight.RED,
    )
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_requests: int = Field(default=12, ge=1)
    max_tokens: int = Field(default=4000, ge=100)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_enabled(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "enabled" not in value:
            return value
        migrated = dict(value)
        enabled = TypeAdapter(bool).validate_python(migrated.pop("enabled"))
        if not enabled:
            configured = migrated.get("review_statuses")
            if configured:
                raise ValueError("enabled: false conflicts with non-empty review_statuses")
            migrated["review_statuses"] = ()
        return migrated

    @field_validator("review_statuses")
    @classmethod
    def canonicalise_review_statuses(
        cls, value: tuple[TrafficLight, ...]
    ) -> tuple[TrafficLight, ...]:
        selected = set(value)
        return tuple(status for status in TrafficLight if status in selected)

    def review_decision(self, governing_status: TrafficLight) -> AgentReviewDecision:
        return AgentReviewDecision(
            governing_status=governing_status,
            review_policy=self.review_statuses,
            review_required=governing_status in self.review_statuses,
        )


class TopographyConfig(BaseModel):
    """Governed trial settings for Topography Profile calculation."""

    gentle_max_pct: float = Field(default=3.0, gt=0)
    noticeable_max_pct: float = Field(default=5.0, gt=0)
    steep_max_pct: float = Field(default=8.0, gt=0)
    very_steep_max_pct: float = Field(default=12.5, gt=0)
    maximum_sample_spacing_m: float = Field(default=250.0, gt=0)
    minimum_sustained_spacing_m: float = Field(default=10.0, gt=0)
    steep_trigger_length_m: float = Field(default=100.0, gt=0)
    very_steep_trigger_length_m: float = Field(default=50.0, gt=0)
    severe_trigger_length_m: float = Field(default=30.0, gt=0)
    repeated_climb_count: int = Field(default=2, ge=2)
    cumulative_ascent_trigger_m: float = Field(default=40.0, gt=0)
    maximum_alternative_detour_ratio: float = Field(default=1.5, ge=1)
    material_ascent_reduction_m: float = Field(default=20.0, gt=0)
    material_ascent_reduction_ratio: float = Field(default=0.25, gt=0, le=1)

    @model_validator(mode="after")
    def validate_gradient_bands(self) -> TopographyConfig:
        thresholds = (
            self.gentle_max_pct,
            self.noticeable_max_pct,
            self.steep_max_pct,
            self.very_steep_max_pct,
        )
        if tuple(sorted(thresholds)) != thresholds or len(set(thresholds)) != len(thresholds):
            raise ValueError("Topography gradient thresholds must be strictly increasing")
        return self


class PublicationConfig(BaseModel):
    output_dir: Path
    comparison_reference: Path | None = None
    title: str
    pdf_page_size: str = "A3"
    audience: Literal["public", "local"] = "public"


class CompilationConfig(BaseModel):
    max_connection_km: float = 15.0
    full: bool = False
    criteria_version: str = "1"
    agent: AgentConfig = Field(default_factory=AgentConfig)
    topography: TopographyConfig = Field(default_factory=TopographyConfig)


class ATMConfig(BaseModel):
    enabled: bool = False
    mode: Literal["blind", "seeded"] = "blind"
    path: Path | None = None
    redistribution_permitted: bool = False
    match_buffer_m: float = 100.0


class CouncilConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    council_id: str
    council_name: str
    source: SourceConfig
    compilation: CompilationConfig = Field(default_factory=CompilationConfig)
    atm: ATMConfig = Field(default_factory=ATMConfig)
    publication: PublicationConfig

    @model_validator(mode="after")
    def resolve_paths(self) -> CouncilConfig:
        root = self.config_path.parent
        if self.source.fixture_dir is not None and not self.source.fixture_dir.is_absolute():
            self.source.fixture_dir = (root / self.source.fixture_dir).resolve()
        if not self.source.snapshot_dir.is_absolute():
            self.source.snapshot_dir = (root / self.source.snapshot_dir).resolve()
        classification = self.source.official_road_classification
        if classification is not None and not classification.path.is_absolute():
            classification.path = (root / classification.path).resolve()
        observed_traffic = self.source.observed_through_traffic
        if observed_traffic is not None and not observed_traffic.path.is_absolute():
            observed_traffic.path = (root / observed_traffic.path).resolve()
        national_elevation = self.source.national_elevation
        if (
            national_elevation is not None
            and national_elevation.path is not None
            and not national_elevation.path.is_absolute()
        ):
            national_elevation.path = (root / national_elevation.path).resolve()
        if not self.publication.output_dir.is_absolute():
            self.publication.output_dir = (root / self.publication.output_dir).resolve()
        if (
            self.publication.comparison_reference is not None
            and not self.publication.comparison_reference.is_absolute()
        ):
            self.publication.comparison_reference = (
                root / self.publication.comparison_reference
            ).resolve()
        if self.atm.path is not None and not self.atm.path.is_absolute():
            self.atm.path = (root / self.atm.path).resolve()
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> CouncilConfig:
        config_path = Path(path).resolve()
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return cls(config_path=config_path, **raw)


class PublishedFeatureReference(BaseModel):
    feature_id: str
    network_role: str


class AgentFinding(BaseModel):
    code: str
    severity: Literal["blocking", "revision-required", "advisory"]
    message: str
    evidence_ids: list[str] = Field(default_factory=list)


class AgentProposal(BaseModel):
    selected_role: str | None
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class AgentCritique(BaseModel):
    summary: str
    findings: list[AgentFinding] = Field(default_factory=list)


class AgentSynthesis(BaseModel):
    decision: Literal["accept", "revise", "gap"]
    selected_role: str | None
    rationale: str


class AgentAttempt(BaseModel):
    attempt: int = Field(ge=1)
    proposal: AgentProposal | None = None
    critique: AgentCritique | None = None
    red_team: AgentCritique | None = None
    synthesis: AgentSynthesis | None = None
    deterministic_findings: list[AgentFinding] = Field(default_factory=list)
    findings: list[AgentFinding] = Field(default_factory=list)
    selected_role: str | None = None
    decision: Literal["retry"] | None = None


class AgentDecisionAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "select-network-role",
        "reject-candidate",
        "retain-network-gap",
        "retain-atm-comparison",
        "terminate",
    ]
    network_role: str | None = None
    comparison_status: Literal["match", "omission", "deviation", "addition"] | None = None

    @model_validator(mode="after")
    def validate_action_parameters(self) -> AgentDecisionAction:
        if self.kind == "select-network-role" and (
            not self.network_role or self.comparison_status is not None
        ):
            raise ValueError("select-network-role requires only network_role")
        if self.kind == "retain-atm-comparison" and (
            not self.comparison_status or self.network_role is not None
        ):
            raise ValueError("retain-atm-comparison requires only comparison_status")
        if self.kind in {"reject-candidate", "retain-network-gap", "terminate"} and (
            self.network_role or self.comparison_status
        ):
            raise ValueError(f"{self.kind} cannot contain action parameters")
        return self


class AgentDecisionChoice(BaseModel):
    model_config = ConfigDict(frozen=True)

    choice_id: str = Field(pattern=r"^(?:[1-9][0-9]*|terminate)$")
    label: str = Field(min_length=1)
    compiler_action: AgentDecisionAction
    expected_consequence: str = Field(min_length=1)
    mandatory_constraints: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reserved_terminate_action(self) -> AgentDecisionChoice:
        identifier_is_terminate = self.choice_id == "terminate"
        action_is_terminate = self.compiler_action.kind == "terminate"
        if identifier_is_terminate != action_is_terminate:
            raise ValueError("only the reserved terminate choice may terminate compilation")
        return self


class AgentDecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    dependency_fingerprint: str
    decision_contract: Literal["agent-decision-menu/v1"] = "agent-decision-menu/v1"
    compilation_scope: str
    affected_identifiers: tuple[str, ...]
    criterion: str
    question: str
    status: TrafficLight
    governed_evidence_references: tuple[str, ...]
    deterministic_findings: tuple[AgentFinding, ...]
    choices: tuple[AgentDecisionChoice, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounded_choices(self) -> AgentDecisionRequest:
        identifiers = [choice.choice_id for choice in self.choices]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("decision choice identifiers must be unique")
        return self


class AgentDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    choice_id: str = Field(pattern=r"^(?:[1-9][0-9]*|terminate)$")


class AgentDecisionLedger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_contract: Literal["agent-decision-menu/v1"] = "agent-decision-menu/v1"
    responses: tuple[AgentDecisionResponse, ...] = ()

    @field_validator("responses")
    @classmethod
    def canonicalise_responses(
        cls,
        value: tuple[AgentDecisionResponse, ...],
    ) -> tuple[AgentDecisionResponse, ...]:
        return tuple(sorted(value, key=lambda response: response.request_id))

    @model_validator(mode="after")
    def validate_unique_requests(self) -> AgentDecisionLedger:
        request_ids = [response.request_id for response in self.responses]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("a decision ledger can answer each request only once")
        return self


class AgentRecord(AgentReviewAudit):
    connection_id: str
    governing_criterion: str
    network_role: str | None = None
    runtime: str
    model: str
    proposal: AgentProposal | None = None
    critique: AgentCritique | None = None
    revision: AgentSynthesis | None = None
    decision: Literal["accept", "reject", "gap", "superseded"]
    selected_role: str | None = None
    outcome_reason: str = ""
    attempts: list[AgentAttempt] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    derived_features: list[PublishedFeatureReference] = Field(default_factory=list)
    decision_request: AgentDecisionRequest | None = None
    selected_choice_id: str | None = None
    mapped_action: AgentDecisionAction | None = None
    responder_mode: Literal["caller", "direct-runtime"] | None = None
    choice_validation: Literal["accepted"] | None = None
    affected_feature_identifiers: tuple[str, ...] = ()
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_review_execution(self) -> AgentRecord:
        requests = self.usage.get("requests", 0)
        tokens = self.usage.get("tokens", 0)
        caller_response = self.responder_mode == "caller"
        if self.review_required and caller_response:
            if (
                self.runtime != "caller"
                or self.decision_request is None
                or self.selected_choice_id is None
                or self.mapped_action is None
                or self.choice_validation != "accepted"
            ):
                raise ValueError("caller review must record the complete accepted choice")
            if (
                self.attempts
                or self.proposal is not None
                or self.critique is not None
                or self.revision is not None
                or requests
                or tokens
            ):
                raise ValueError("caller review cannot contain direct-runtime activity")
            selected = next(
                (
                    choice
                    for choice in self.decision_request.choices
                    if choice.choice_id == self.selected_choice_id
                ),
                None,
            )
            if (
                selected is None
                or selected.compiler_action != self.mapped_action
                or self.affected_feature_identifiers
                != self.decision_request.affected_identifiers
            ):
                raise ValueError("caller review choice must match the offered request action")
        elif self.review_required and (
            self.runtime == "not-invoked" or not self.attempts
        ):
            raise ValueError("required review must record an invoked runtime and attempt")
        if not self.review_required and (
            self.runtime != "not-invoked" or requests or tokens or self.attempts
        ):
            raise ValueError("skipped review must have no runtime, usage, or attempts")
        return self


class DivergenceRecord(AgentReviewAudit):
    connection_id: str
    status: Literal["match", "omission", "deviation", "addition"]
    atm_feature_ids: list[str] = Field(default_factory=list)
    overlap_ratio: float = Field(ge=0, le=1)
    explanation: str
    resolution_attempts: list[dict[str, Any]] = Field(default_factory=list)
    resolved: bool = False
    decision_request: AgentDecisionRequest | None = None
    selected_choice_id: str | None = None
    mapped_action: AgentDecisionAction | None = None
    responder_mode: Literal["caller", "direct-runtime"] | None = None
    choice_validation: Literal["accepted"] | None = None
    affected_feature_identifiers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_review_execution(self) -> DivergenceRecord:
        caller_response = self.responder_mode == "caller"
        if self.review_required and caller_response:
            if (
                self.decision_request is None
                or self.selected_choice_id is None
                or self.mapped_action is None
                or self.choice_validation != "accepted"
            ):
                raise ValueError("caller review must record the complete accepted choice")
            if self.resolution_attempts:
                raise ValueError("caller review cannot contain direct-runtime attempts")
            selected = next(
                (
                    choice
                    for choice in self.decision_request.choices
                    if choice.choice_id == self.selected_choice_id
                ),
                None,
            )
            if (
                selected is None
                or selected.compiler_action != self.mapped_action
                or self.affected_feature_identifiers
                != self.decision_request.affected_identifiers
            ):
                raise ValueError("caller review choice must match the offered request action")
        elif self.review_required and not self.resolution_attempts:
            raise ValueError("required divergence review must record an attempt")
        if not self.review_required and self.resolution_attempts:
            raise ValueError("skipped divergence review cannot contain resolution attempts")
        return self


class HumanInterventionRequest(BaseModel):
    request_id: str
    connection_id: str
    reason: str
    attempted_revisions: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_findings: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)
    smallest_human_input: str


class CompilationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    status: Literal["reviewable", "complete", "decision-required", "terminated"]
    output_dir: Path
    connections: int
    gaps: int
    artifacts: dict[str, Path]
    criteria: dict[str, dict[str, TrafficLight]]
    agent_records: list[AgentRecord]
    divergence_records: list[DivergenceRecord] = Field(default_factory=list)
    decision_requests: list[AgentDecisionRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
