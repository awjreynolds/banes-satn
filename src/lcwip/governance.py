"""Human-authority, engagement, equality and policy governance for LCWIP."""

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

from lcwip.evidence import AccessLevel, PublicDisposition
from lcwip.models import (
    PERMITTED_LIFECYCLE_TRANSITIONS,
    GuidanceProfile,
    LifecycleState,
    Objective,
    Target,
    _canonical_resource_identity,
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


class GovernanceContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )
    schema_version: Literal["1.0"] = "1.0"


class AuthorityRoleKind(StrEnum):
    SPONSOR = "sponsor"
    SRO = "sro"
    PROJECT_BOARD = "project-board"
    SCOPE_AUTHORITY = "scope-authority"
    EVIDENCE_AUTHORITY = "evidence-authority"
    PRIORITISATION_AUTHORITY = "prioritisation-authority"
    CONSULTATION_AUTHORITY = "consultation-authority"
    REPRESENTATION_AUTHORITY = "representation-authority"
    EQUALITY_AUTHORITY = "equality-authority"
    ADOPTION_CANDIDATE_AUTHORITY = "adoption-candidate-authority"
    EXTERNAL_ADOPTION_AUTHORITY = "external-adoption-authority"
    INDEPENDENT_VERIFIER = "independent-verifier"
    SUPERSESSION_AUTHORITY = "supersession-authority"


class GateKind(StrEnum):
    SCOPE = "scope"
    EVIDENCE_LIMITATIONS = "evidence-limitations"
    PRIORITISATION_RULES = "prioritisation-rules"
    CONSULTATION_RELEASE = "consultation-release"
    REPRESENTATION_DISPOSITION = "representation-disposition"
    EQUALITY_DISPOSITION = "equality-disposition"
    ADOPTION_CANDIDATE = "adoption-candidate"
    EXTERNAL_ADOPTION = "external-adoption"
    SUPERSESSION = "supersession"


GATE_ROLE = {
    GateKind.SCOPE: AuthorityRoleKind.SCOPE_AUTHORITY,
    GateKind.EVIDENCE_LIMITATIONS: AuthorityRoleKind.EVIDENCE_AUTHORITY,
    GateKind.PRIORITISATION_RULES: AuthorityRoleKind.PRIORITISATION_AUTHORITY,
    GateKind.CONSULTATION_RELEASE: AuthorityRoleKind.CONSULTATION_AUTHORITY,
    GateKind.REPRESENTATION_DISPOSITION: AuthorityRoleKind.REPRESENTATION_AUTHORITY,
    GateKind.EQUALITY_DISPOSITION: AuthorityRoleKind.EQUALITY_AUTHORITY,
    GateKind.ADOPTION_CANDIDATE: AuthorityRoleKind.ADOPTION_CANDIDATE_AUTHORITY,
    GateKind.EXTERNAL_ADOPTION: AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY,
    GateKind.SUPERSESSION: AuthorityRoleKind.SUPERSESSION_AUTHORITY,
}


REQUIRED_GATES = {
    LifecycleState.EVIDENCE_INCOMPLETE: {GateKind.EVIDENCE_LIMITATIONS},
    LifecycleState.ANALYSIS_DRAFT: {
        GateKind.SCOPE,
        GateKind.EVIDENCE_LIMITATIONS,
        GateKind.PRIORITISATION_RULES,
    },
    LifecycleState.CONSULTATION_DRAFT: {
        GateKind.CONSULTATION_RELEASE,
        GateKind.REPRESENTATION_DISPOSITION,
        GateKind.EQUALITY_DISPOSITION,
    },
    LifecycleState.ADOPTION_CANDIDATE: {GateKind.ADOPTION_CANDIDATE},
    LifecycleState.ADOPTED: {GateKind.EXTERNAL_ADOPTION},
    LifecycleState.SUPERSEDED: {GateKind.SUPERSESSION},
}

CUMULATIVE_GATES = {
    LifecycleState.ANALYSIS_DRAFT: REQUIRED_GATES[LifecycleState.ANALYSIS_DRAFT],
    LifecycleState.CONSULTATION_DRAFT: (
        REQUIRED_GATES[LifecycleState.ANALYSIS_DRAFT]
        | REQUIRED_GATES[LifecycleState.CONSULTATION_DRAFT]
    ),
    LifecycleState.ADOPTION_CANDIDATE: (
        REQUIRED_GATES[LifecycleState.ANALYSIS_DRAFT]
        | REQUIRED_GATES[LifecycleState.CONSULTATION_DRAFT]
        | REQUIRED_GATES[LifecycleState.ADOPTION_CANDIDATE]
    ),
    LifecycleState.ADOPTED: (
        REQUIRED_GATES[LifecycleState.ANALYSIS_DRAFT]
        | REQUIRED_GATES[LifecycleState.CONSULTATION_DRAFT]
        | REQUIRED_GATES[LifecycleState.ADOPTION_CANDIDATE]
        | REQUIRED_GATES[LifecycleState.ADOPTED]
    ),
}


class AuthorityRole(GovernanceContract):
    role_id: Identifier
    person_name: Text
    organisation: Text
    kind: AuthorityRoleKind
    responsibilities: tuple[Text, ...] = Field(min_length=1)
    conflict_of_interest: Text

    @field_validator("responsibilities")
    @classmethod
    def canonical_responsibilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "authority responsibilities")


class GovernanceStructure(GovernanceContract):
    plan_sponsor_role_id: Identifier
    sro_role_id: Identifier
    project_board_role_ids: tuple[Identifier, ...] = Field(min_length=1)
    roles: tuple[AuthorityRole, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def resolve_roles(self) -> Self:
        by_id = {role.role_id: role for role in self.roles}
        if len(by_id) != len(self.roles):
            raise ValueError("governance role IDs must be unique")
        if self.plan_sponsor_role_id == self.sro_role_id:
            raise ValueError("plan sponsor and SRO roles must be separated")
        if by_id.get(self.plan_sponsor_role_id) is None or (
            by_id[self.plan_sponsor_role_id].kind is not AuthorityRoleKind.SPONSOR
        ):
            raise ValueError("plan sponsor role must resolve to a sponsor")
        if by_id.get(self.sro_role_id) is None or (
            by_id[self.sro_role_id].kind is not AuthorityRoleKind.SRO
        ):
            raise ValueError("SRO role must resolve to an SRO")
        if not set(self.project_board_role_ids).issubset(by_id):
            raise ValueError("project board roles must resolve")
        if any(
            by_id[role_id].kind is not AuthorityRoleKind.PROJECT_BOARD
            for role_id in self.project_board_role_ids
        ):
            raise ValueError("project board role IDs must identify board members")
        kinds = {role.kind for role in self.roles}
        if not set(GATE_ROLE.values()).issubset(kinds):
            raise ValueError("governance roles must cover every human gate authority")
        if AuthorityRoleKind.INDEPENDENT_VERIFIER not in kinds:
            raise ValueError("governance requires an independent verifier")
        return self


class TimetableMilestone(GovernanceContract):
    milestone_id: Identifier
    name: Text
    target_date: date
    accountable_role_id: Identifier


class GovernanceDirectiveRecord(GovernanceContract):
    directive_id: Identifier
    authority_role_id: Identifier
    issued_on: date
    directive: Text
    evidence_uri: Text


class StakeholderRecord(GovernanceContract):
    stakeholder_id: Identifier
    group_name: Text
    relationship: Text
    contact_access: Literal["controlled", "none"]
    accessibility_adjustments: tuple[Text, ...]


class EngagementStrategy(GovernanceContract):
    strategy_id: Identifier
    purpose: Text
    lawful_basis: Text
    privacy_notice_uri: Text
    stakeholder_ids: tuple[Identifier, ...]
    planned_methods: tuple[Text, ...] = Field(min_length=1)
    representativeness_limits: tuple[Text, ...] = Field(min_length=1)
    groups_not_reached: tuple[Text, ...] = Field(min_length=1)


class EngagementActivity(GovernanceContract):
    activity_id: Identifier
    strategy_id: Identifier
    activity_type: Text
    occurred_on: date
    stakeholder_ids: tuple[Identifier, ...]
    attendance_count: int = Field(ge=0)
    limitations: tuple[Text, ...] = Field(min_length=1)


class RepresentationRecord(GovernanceContract):
    representation_id: Identifier
    source_reference_id: Identifier
    source_sha256: Sha256
    received_on: date
    access_level: AccessLevel
    public_disposition: PublicDisposition
    redacted_summary: Text | None
    personal_data: Literal["removed", "not-collected"]
    themes: tuple[Identifier, ...] = Field(min_length=1)
    position: Literal["support", "object", "mixed", "neutral"]
    supersedes_representation_id: Identifier | None = None
    contradicts_representation_ids: tuple[Identifier, ...] = ()
    lineage_note: Text | None = None

    @model_validator(mode="after")
    def privacy_boundary(self) -> Self:
        if self.representation_id == self.supersedes_representation_id:
            raise ValueError("a representation cannot supersede itself")
        if self.representation_id in self.contradicts_representation_ids:
            raise ValueError("a representation cannot contradict itself")
        if len(self.contradicts_representation_ids) != len(
            set(self.contradicts_representation_ids)
        ):
            raise ValueError("contradictory representation IDs must be unique")
        if (
            self.supersedes_representation_id is not None
            or self.contradicts_representation_ids
        ) and self.lineage_note is None:
            raise ValueError("representation lineage requires an explanatory note")
        if self.access_level is AccessLevel.PUBLIC:
            if self.public_disposition is not PublicDisposition.INCLUDE:
                raise ValueError("public representations must be included")
        elif self.access_level is AccessLevel.CONTROLLED:
            if (
                self.public_disposition is not PublicDisposition.REDACTED
                or self.redacted_summary is None
                or self.personal_data != "removed"
            ):
                raise ValueError(
                    "controlled representations require privacy-safe redaction"
                )
        elif (
            self.public_disposition is not PublicDisposition.EXCLUDE
            or self.redacted_summary is not None
        ):
            raise ValueError("personal representations must remain excluded")
        return self


class HumanRecord(GovernanceContract):
    record_id: Identifier
    authority_role_id: Identifier
    recorded_on: date
    rationale: Text
    evidence_uri: Text


class AgentRepresentationSummary(GovernanceContract):
    summary_id: Identifier
    included_representation_ids: tuple[Identifier, ...] = Field(min_length=1)
    summary: Text
    classifications: tuple[Identifier, ...] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    covered_count: int = Field(ge=1)
    available_count: int = Field(ge=1)
    methodology_version: Text
    human_verification: HumanRecord

    @model_validator(mode="after")
    def coverage_matches(self) -> Self:
        if self.covered_count != len(self.included_representation_ids):
            raise ValueError("summary coverage must match its cited representations")
        if self.covered_count > self.available_count:
            raise ValueError("summary coverage cannot exceed available representations")
        return self


class RepresentationDisposition(GovernanceContract):
    disposition_id: Identifier
    representation_id: Identifier
    decision: Literal["accepted", "partially-accepted", "rejected", "out-of-scope"]
    rationale: Text
    human_record: HumanRecord


class EqualityImpactStatus(StrEnum):
    UNKNOWN = "unknown"
    ADVERSE_UNRESOLVED = "adverse-unresolved"
    MITIGATED = "mitigated"
    NO_ADVERSE_IMPACT = "no-adverse-impact"


class EqualityImpactFinding(GovernanceContract):
    finding_id: Identifier
    affected_users: tuple[Text, ...] = Field(min_length=1)
    evidence_references: tuple[Text, ...] = Field(min_length=1)
    impact: Text
    mitigations: tuple[Text, ...]
    owner_role_id: Identifier
    status: EqualityImpactStatus
    eqia_process_uri: Text
    officer_record: HumanRecord

    @model_validator(mode="after")
    def mitigation_matches_status(self) -> Self:
        if self.status is EqualityImpactStatus.MITIGATED and not self.mitigations:
            raise ValueError("mitigated equality findings require mitigations")
        if (
            self.status is EqualityImpactStatus.ADVERSE_UNRESOLVED
            and self.mitigations
        ):
            raise ValueError("unresolved adverse impact cannot claim mitigation")
        return self


class PolicyReference(GovernanceContract):
    policy_reference_id: Identifier
    title: Text
    source_uri: Text
    source_sha256: Sha256
    clause_pointer: Text
    clause_excerpt: Text


class PolicyAlignment(GovernanceContract):
    alignment_id: Identifier
    policy_reference_id: Identifier
    subject_kind: Literal["objective", "network", "intervention"]
    subject_id: Identifier
    alignment_claim: Text
    basis: Literal["clause-evidence", "officer-judgement"]
    subject_evidence_uri: Text
    subject_evidence_sha256: Sha256
    officer_record: HumanRecord


class HumanGate(GovernanceContract):
    gate_id: Identifier
    kind: GateKind
    authority_role_id: Identifier
    decided_on: date
    rationale: Text
    evidence_uri: Text


class GovernanceTransition(GovernanceContract):
    from_state: LifecycleState
    to_state: LifecycleState
    gates: tuple[HumanGate, ...] = Field(min_length=1)


class ExternalAdoptionRecord(GovernanceContract):
    decision_identifier: Identifier
    authority_name: Text
    decision_date: date
    decision_uri: Text
    release_fingerprint: Sha256
    decision_authority_role_id: Identifier
    verifier_role_id: Identifier
    verification_date: date
    verification_evidence_uri: Text

    @model_validator(mode="after")
    def separation(self) -> Self:
        if self.decision_authority_role_id == self.verifier_role_id:
            raise ValueError("adoption decision authority and verifier must be separate")
        if self.verification_date < self.decision_date:
            raise ValueError("adoption verification cannot predate the decision")
        if _canonical_resource_identity(
            self.decision_uri
        ) == _canonical_resource_identity(self.verification_evidence_uri):
            raise ValueError("adoption verification requires separate evidence")
        return self


class AmendmentRecord(GovernanceContract):
    amendment_id: Identifier
    previous_release_fingerprint: Sha256
    amended_release_fingerprint: Sha256
    amended_on: date
    author_role_id: Identifier
    rationale: Text
    trigger_record_ids: tuple[Identifier, ...] = Field(min_length=1)


class GovernanceConfig(GovernanceContract):
    release_id: Identifier
    release_version: Text
    guidance_profile: GuidanceProfile
    guidance_profile_id: Identifier
    guidance_profile_fingerprint: Sha256
    output_dir: Path
    structure: GovernanceStructure
    objectives: tuple[Objective, ...]
    targets: tuple[Target, ...]
    timetable: tuple[TimetableMilestone, ...]
    directives: tuple[GovernanceDirectiveRecord, ...]
    stakeholders: tuple[StakeholderRecord, ...]
    engagement_strategy: EngagementStrategy
    activities: tuple[EngagementActivity, ...]
    representations: tuple[RepresentationRecord, ...]
    summaries: tuple[AgentRepresentationSummary, ...]
    dispositions: tuple[RepresentationDisposition, ...]
    equality_findings: tuple[EqualityImpactFinding, ...]
    policy_references: tuple[PolicyReference, ...]
    policy_alignments: tuple[PolicyAlignment, ...]
    transitions: tuple[GovernanceTransition, ...]
    external_adoption: ExternalAdoptionRecord | None = None
    amendments: tuple[AmendmentRecord, ...] = ()

    @model_validator(mode="after")
    def profile_binding(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("Guidance Profile ID does not match")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("Guidance Profile fingerprint does not match")
        return self


class GovernanceArtifact(GovernanceContract):
    path: Text
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("governance artifact path must remain inside bundle")
        return value


ARTIFACTS = (
    "decision-provenance.json",
    "engagement-record.json",
    "equality-and-policy.json",
    "governance-record.json",
)


class GovernanceManifest(GovernanceContract):
    release_id: Identifier
    release_version: Text
    guidance_profile: GuidanceProfile
    guidance_profile_id: Identifier
    guidance_profile_fingerprint: Sha256
    lifecycle_state: LifecycleState
    release_fingerprint: Sha256
    structure: GovernanceStructure
    objectives: tuple[Objective, ...]
    targets: tuple[Target, ...]
    timetable: tuple[TimetableMilestone, ...]
    directives: tuple[GovernanceDirectiveRecord, ...]
    stakeholders: tuple[StakeholderRecord, ...]
    engagement_strategy: EngagementStrategy
    activities: tuple[EngagementActivity, ...]
    representations: tuple[RepresentationRecord, ...]
    summaries: tuple[AgentRepresentationSummary, ...]
    dispositions: tuple[RepresentationDisposition, ...]
    equality_findings: tuple[EqualityImpactFinding, ...]
    policy_references: tuple[PolicyReference, ...]
    policy_alignments: tuple[PolicyAlignment, ...]
    transitions: tuple[GovernanceTransition, ...]
    external_adoption: ExternalAdoptionRecord | None
    amendments: tuple[AmendmentRecord, ...]
    participation_statement: Text
    artifacts: tuple[GovernanceArtifact, ...]
    input_fingerprint: Sha256
    analysis_fingerprint: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.guidance_profile_id != self.guidance_profile.profile_id:
            raise ValueError("Guidance Profile ID does not match")
        if self.guidance_profile_fingerprint != self.guidance_profile.fingerprint:
            raise ValueError("Guidance Profile fingerprint does not match")
        _validate_governance_content(self)
        paths = tuple(artifact.path for artifact in self.artifacts)
        if len(paths) != len(set(paths)) or set(paths) != set(ARTIFACTS):
            raise ValueError("governance artifact set is incomplete")
        if self.release_fingerprint != _release_fingerprint(self):
            raise ValueError("governance release fingerprint does not match")
        expected_input = _fingerprint(
            self.model_dump(
                mode="json",
                exclude={"artifacts", "input_fingerprint", "analysis_fingerprint"},
            )
        )
        if self.input_fingerprint != expected_input:
            raise ValueError("governance input fingerprint does not match")
        expected = _fingerprint(
            self.model_dump(mode="json", exclude={"analysis_fingerprint"})
        )
        if self.analysis_fingerprint != expected:
            raise ValueError("governance analysis fingerprint does not match")
        return self


def build_governance_record(config: GovernanceConfig) -> Path:
    """Build one immutable, human-gated governance and engagement record."""
    config = GovernanceConfig.model_validate(config.model_dump())
    lifecycle_state = _validate_transitions(config.transitions)
    release_payload = _release_payload(config)
    release_fingerprint = _fingerprint(release_payload)
    payload = {
        "schema_version": "1.0",
        **release_payload,
        "lifecycle_state": lifecycle_state,
        "release_fingerprint": release_fingerprint,
        "transitions": config.transitions,
        "external_adoption": config.external_adoption,
        "amendments": config.amendments,
        "participation_statement": (
            "Participation evidence is limited by: "
            + "; ".join(config.engagement_strategy.representativeness_limits)
            + ". Groups not reached: "
            + "; ".join(config.engagement_strategy.groups_not_reached)
            + ". Silence is not support."
        ),
    }
    _validate_governance_content(
        GovernanceManifest.model_construct(
            **payload,
            artifacts=(),
            input_fingerprint="0" * 64,
            analysis_fingerprint="0" * 64,
        )
    )
    destination = config.output_dir / config.release_id
    if destination.exists():
        existing = validate_governance_bundle(destination)
        candidate_input_fingerprint = _fingerprint(payload)
        if (
            existing.release_fingerprint != release_fingerprint
            or existing.input_fingerprint != candidate_input_fingerprint
        ):
            raise ValueError("governance release is immutable and content changed")
        return destination
    config.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{config.release_id}-", dir=config.output_dir)
    )
    try:
        public_representations = tuple(
            representation
            for representation in config.representations
            if representation.public_disposition is not PublicDisposition.EXCLUDE
        )
        public_representation_ids = {
            representation.representation_id
            for representation in public_representations
        }
        public_summaries = tuple(
            summary
            for summary in config.summaries
            if set(summary.included_representation_ids).issubset(
                public_representation_ids
            )
        )
        public_dispositions = tuple(
            disposition
            for disposition in config.dispositions
            if disposition.representation_id in public_representation_ids
        )
        files = {
            "governance-record.json": {
                "structure": config.structure,
                "objectives": config.objectives,
                "targets": config.targets,
                "timetable": config.timetable,
                "directives": config.directives,
            },
            "engagement-record.json": {
                "strategy": config.engagement_strategy,
                "activities": config.activities,
                "representations": public_representations,
                "summaries": public_summaries,
                "dispositions": public_dispositions,
                "participation_statement": payload["participation_statement"],
            },
            "equality-and-policy.json": {
                "equality_findings": config.equality_findings,
                "policy_references": config.policy_references,
                "policy_alignments": config.policy_alignments,
            },
            "decision-provenance.json": {
                "transitions": config.transitions,
                "external_adoption": config.external_adoption,
                "amendments": config.amendments,
            },
        }
        for filename, contents in files.items():
            _write(temporary / filename, contents)
        artifacts = tuple(
            GovernanceArtifact(
                path=filename,
                sha256=hashlib.sha256((temporary / filename).read_bytes()).hexdigest(),
            )
            for filename in ARTIFACTS
        )
        manifest_payload = {
            **payload,
            "artifacts": artifacts,
            "input_fingerprint": _fingerprint(payload),
        }
        manifest = GovernanceManifest(
            **manifest_payload,
            analysis_fingerprint=_fingerprint(manifest_payload),
        )
        _write(temporary / "governance-manifest.json", manifest)
        validate_governance_bundle(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def governance_release_fingerprint(config: GovernanceConfig) -> str:
    """Fingerprint the substantive release before binding an adoption decision."""
    validated = GovernanceConfig.model_validate(config.model_dump())
    return _release_fingerprint(validated)


def validate_governance_bundle(path: Path) -> GovernanceManifest:
    path = Path(path)
    try:
        manifest = GovernanceManifest.model_validate_json(
            (path / "governance-manifest.json").read_text()
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid governance bundle: {error}") from error
    expected_files = {"governance-manifest.json"}
    for artifact in manifest.artifacts:
        expected_files.add(artifact.path)
        artifact_path = path / artifact.path
        if not artifact_path.is_file():
            raise ValueError(f"invalid governance bundle: missing {artifact.path}")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError(
                f"invalid governance bundle: {artifact.path} content hash mismatch"
            )
    actual_files = {
        item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("invalid governance bundle: file set mismatch")
    public_representations = tuple(
        representation
        for representation in manifest.representations
        if representation.public_disposition is not PublicDisposition.EXCLUDE
    )
    public_representation_ids = {
        representation.representation_id for representation in public_representations
    }
    public_summaries = tuple(
        summary
        for summary in manifest.summaries
        if set(summary.included_representation_ids).issubset(public_representation_ids)
    )
    public_dispositions = tuple(
        disposition
        for disposition in manifest.dispositions
        if disposition.representation_id in public_representation_ids
    )
    expected = {
        "governance-record.json": {
            "structure": manifest.structure,
            "objectives": manifest.objectives,
            "targets": manifest.targets,
            "timetable": manifest.timetable,
            "directives": manifest.directives,
        },
        "engagement-record.json": {
            "strategy": manifest.engagement_strategy,
            "activities": manifest.activities,
            "representations": public_representations,
            "summaries": public_summaries,
            "dispositions": public_dispositions,
            "participation_statement": manifest.participation_statement,
        },
        "equality-and-policy.json": {
            "equality_findings": manifest.equality_findings,
            "policy_references": manifest.policy_references,
            "policy_alignments": manifest.policy_alignments,
        },
        "decision-provenance.json": {
            "transitions": manifest.transitions,
            "external_adoption": manifest.external_adoption,
            "amendments": manifest.amendments,
        },
    }
    for filename, contents in expected.items():
        if json.loads((path / filename).read_text()) != _json(contents):
            raise ValueError(f"invalid governance bundle: {filename} mismatch")
    return manifest


def _validate_transitions(
    transitions: tuple[GovernanceTransition, ...],
) -> LifecycleState:
    state = LifecycleState.EXPLORATORY
    supplied_cumulatively: set[GateKind] = set()
    gate_ids: set[str] = set()
    previous_date: date | None = None
    visited = {state}
    for transition in transitions:
        if transition.from_state is not state:
            raise ValueError("governance transition history must be contiguous")
        if transition.to_state not in PERMITTED_LIFECYCLE_TRANSITIONS[state]:
            raise ValueError("governance lifecycle transition is not permitted")
        supplied = {gate.kind for gate in transition.gates}
        if len(supplied) != len(transition.gates):
            raise ValueError("a transition may provide each named human gate once")
        for gate in transition.gates:
            if gate.gate_id in gate_ids:
                raise ValueError("human gate IDs must be unique")
            if previous_date is not None and gate.decided_on < previous_date:
                raise ValueError("human gate decisions must be chronologically ordered")
            gate_ids.add(gate.gate_id)
            previous_date = gate.decided_on
        required = REQUIRED_GATES.get(transition.to_state, set())
        if supplied != required:
            raise ValueError(
                f"transition to {transition.to_state.value} requires named human "
                f"gates: {', '.join(sorted(item.value for item in required))}"
            )
        supplied_cumulatively.update(supplied)
        state = transition.to_state
        visited.add(state)
    if state in {
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    } and LifecycleState.CONSULTATION_DRAFT not in visited:
        raise ValueError("adoption lifecycle cannot bypass consultation draft")
    cumulative_required = CUMULATIVE_GATES.get(state)
    if cumulative_required is not None and not cumulative_required.issubset(
        supplied_cumulatively
    ):
        raise ValueError("lifecycle history is missing required cumulative human gates")
    return state


def _validate_governance_content(record: Any) -> None:
    derived_state = _validate_transitions(record.transitions)
    if derived_state is not record.lifecycle_state:
        raise ValueError("lifecycle state must be derived from transition history")
    roles = {role.role_id: role for role in record.structure.roles}
    if record.lifecycle_state in {
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    } and not all(
        (
            record.objectives,
            record.targets,
            record.timetable,
            record.directives,
        )
    ):
        raise ValueError(
            "analysis draft requires objectives, targets, timetable and directives"
        )
    if record.lifecycle_state in {
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    } and not all(
        (
            record.stakeholders,
            record.activities,
            record.representations,
            record.summaries,
            record.equality_findings,
            record.policy_references,
            record.policy_alignments,
        )
    ):
        raise ValueError(
            "consultation requires engagement, representation, equality and policy records"
        )
    all_human_records = [
        *(summary.human_verification for summary in record.summaries),
        *(item.human_record for item in record.dispositions),
        *(item.officer_record for item in record.equality_findings),
        *(item.officer_record for item in record.policy_alignments),
    ]
    for human_record in all_human_records:
        if human_record.authority_role_id not in roles:
            raise ValueError("human record authority role must resolve")
    _ids(tuple(all_human_records), "record_id", "human record")
    for transition in record.transitions:
        for gate in transition.gates:
            role = roles.get(gate.authority_role_id)
            if role is None or role.kind is not GATE_ROLE[gate.kind]:
                raise ValueError("human gate authority does not hold the required role")
    objective_ids = _ids(record.objectives, "objective_id", "objective")
    for target in record.targets:
        if target.objective_id not in objective_ids:
            raise ValueError("target objective must resolve")
    role_ids = set(roles)
    for milestone in record.timetable:
        if milestone.accountable_role_id not in role_ids:
            raise ValueError("timetable accountable role must resolve")
    for directive in record.directives:
        if directive.authority_role_id not in role_ids:
            raise ValueError("directive authority role must resolve")
    stakeholder_ids = _ids(record.stakeholders, "stakeholder_id", "stakeholder")
    if set(record.engagement_strategy.stakeholder_ids) != stakeholder_ids:
        raise ValueError("engagement strategy must cover the stakeholder register")
    for activity in record.activities:
        if activity.strategy_id != record.engagement_strategy.strategy_id:
            raise ValueError("engagement activity strategy must resolve")
        if not set(activity.stakeholder_ids).issubset(stakeholder_ids):
            raise ValueError("engagement activity stakeholders must resolve")
    representation_ids = _ids(
        record.representations, "representation_id", "representation"
    )
    source_keys = [
        (item.source_reference_id, item.source_sha256)
        for item in record.representations
    ]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("duplicate source representations are not permitted")
    if len({item.source_reference_id for item in record.representations}) != len(
        record.representations
    ) or len({item.source_sha256 for item in record.representations}) != len(
        record.representations
    ):
        raise ValueError("duplicate representation references or content are not permitted")
    representations_by_id = {
        item.representation_id: item for item in record.representations
    }
    for representation in record.representations:
        if (
            representation.supersedes_representation_id is not None
            and representation.supersedes_representation_id not in representation_ids
        ):
            raise ValueError("superseded representation must resolve")
        if representation.supersedes_representation_id is not None:
            superseded = representations_by_id[
                representation.supersedes_representation_id
            ]
            if representation.received_on < superseded.received_on:
                raise ValueError("a superseding representation cannot predate its source")
        if not set(representation.contradicts_representation_ids).issubset(
            representation_ids
        ):
            raise ValueError("contradictory representations must resolve")
    for summary in record.summaries:
        if not set(summary.included_representation_ids).issubset(representation_ids):
            raise ValueError("agent summary citations must resolve")
        if any(
            representations_by_id[item].public_disposition
            is PublicDisposition.EXCLUDE
            for item in summary.included_representation_ids
        ):
            raise ValueError(
                "public agent summaries cannot cite excluded personal representations"
            )
        publishable_count = sum(
            item.public_disposition is not PublicDisposition.EXCLUDE
            for item in record.representations
        )
        if summary.available_count != publishable_count:
            raise ValueError(
                "summary available count must equal publishable representations"
            )
        if summary.human_verification.recorded_on < max(
            representations_by_id[item].received_on
            for item in summary.included_representation_ids
        ):
            raise ValueError("summary verification cannot predate its representations")
    covered_representation_ids = {
        representation_id
        for summary in record.summaries
        for representation_id in summary.included_representation_ids
    }
    publishable_representation_ids = {
        item.representation_id
        for item in record.representations
        if item.public_disposition is not PublicDisposition.EXCLUDE
    }
    if record.summaries and covered_representation_ids != publishable_representation_ids:
        raise ValueError("agent summaries must disclose complete publishable coverage")
    disposition_ids = [
        disposition.representation_id for disposition in record.dispositions
    ]
    if len(disposition_ids) != len(set(disposition_ids)):
        raise ValueError("representations may have only one disposition")
    if set(disposition_ids) != representation_ids:
        raise ValueError("every representation requires a human disposition")
    for disposition in record.dispositions:
        if (
            disposition.human_record.recorded_on
            < representations_by_id[disposition.representation_id].received_on
        ):
            raise ValueError("representation disposition cannot predate its source")
    for finding in record.equality_findings:
        if finding.owner_role_id not in role_ids:
            raise ValueError("equality finding owner must resolve")
    if record.lifecycle_state in {
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    } and any(
        finding.status
        in {
            EqualityImpactStatus.UNKNOWN,
            EqualityImpactStatus.ADVERSE_UNRESOLVED,
        }
        for finding in record.equality_findings
    ):
        raise ValueError(
            "consultation/adoption is blocked by unresolved equality impacts"
        )
    policy_ids = _ids(
        record.policy_references, "policy_reference_id", "policy reference"
    )
    for alignment in record.policy_alignments:
        if alignment.policy_reference_id not in policy_ids:
            raise ValueError("policy alignment reference must resolve")
        if (
            alignment.subject_kind == "objective"
            and alignment.subject_id not in objective_ids
        ):
            raise ValueError("policy alignment objective must resolve")
    if record.lifecycle_state in {
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    } and {alignment.subject_kind for alignment in record.policy_alignments} != {
        "objective",
        "network",
        "intervention",
    }:
        raise ValueError(
            "consultation policy mapping must cover objectives, networks and interventions"
        )
    _ids(record.policy_alignments, "alignment_id", "policy alignment")
    gate_dates = {
        gate.kind: gate.decided_on
        for transition in record.transitions
        for gate in transition.gates
    }
    if GateKind.REPRESENTATION_DISPOSITION in gate_dates and any(
        record_date > gate_dates[GateKind.REPRESENTATION_DISPOSITION]
        for record_date in (
            *(item.human_record.recorded_on for item in record.dispositions),
            *(item.human_verification.recorded_on for item in record.summaries),
        )
    ):
        raise ValueError(
            "representation disposition gate cannot predate its human records"
        )
    if GateKind.EQUALITY_DISPOSITION in gate_dates and any(
        item.officer_record.recorded_on > gate_dates[GateKind.EQUALITY_DISPOSITION]
        for item in record.equality_findings
    ):
        raise ValueError("equality disposition gate cannot predate its findings")
    if record.lifecycle_state is LifecycleState.ADOPTED:
        adoption = record.external_adoption
        if adoption is None:
            raise ValueError("adopted requires a verified external authority record")
        if adoption.release_fingerprint != record.release_fingerprint:
            raise ValueError("adoption record release fingerprint mismatch")
        decision_role = roles.get(adoption.decision_authority_role_id)
        verifier_role = roles.get(adoption.verifier_role_id)
        if (
            decision_role is None
            or decision_role.kind is not AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY
            or verifier_role is None
            or verifier_role.kind is not AuthorityRoleKind.INDEPENDENT_VERIFIER
        ):
            raise ValueError("adoption authority and verifier roles are invalid")
        if decision_role.person_name.casefold() == verifier_role.person_name.casefold():
            raise ValueError("adoption authority and verifier must be different people")
    elif record.external_adoption is not None:
        raise ValueError("external adoption record is only valid for adopted")
    previous = None
    amendment_ids = _ids(record.amendments, "amendment_id", "amendment")
    trigger_ids = (
        representation_ids
        | {item.directive_id for item in record.directives}
        | {
            gate.gate_id
            for transition in record.transitions
            for gate in transition.gates
        }
        | amendment_ids
    )
    if record.external_adoption is not None:
        trigger_ids.add(record.external_adoption.decision_identifier)
    consultation_dates = [
        gate.decided_on
        for transition in record.transitions
        for gate in transition.gates
        if gate.kind is GateKind.CONSULTATION_RELEASE
    ]
    for amendment in record.amendments:
        if amendment.author_role_id not in role_ids:
            raise ValueError("amendment author role must resolve")
        if previous is not None and amendment.previous_release_fingerprint != previous:
            raise ValueError("amendment history must be fingerprint-contiguous")
        if not set(amendment.trigger_record_ids).issubset(trigger_ids):
            raise ValueError("amendment trigger records must resolve")
        if not consultation_dates or amendment.amended_on < min(consultation_dates):
            raise ValueError("amendments must be auditable after consultation release")
        previous = amendment.amended_release_fingerprint
    if previous is not None and previous != record.release_fingerprint:
        raise ValueError("amendment history must end at the current release fingerprint")


def _ids(records: tuple[Any, ...], field: str, label: str) -> set[str]:
    values = tuple(getattr(item, field) for item in records)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} IDs must be unique")
    return set(values)


def _unique(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(value))


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, StrEnum):
        return value.value
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _release_payload(record: Any) -> dict[str, Any]:
    return {
        "release_id": record.release_id,
        "release_version": record.release_version,
        "guidance_profile": record.guidance_profile,
        "guidance_profile_id": record.guidance_profile_id,
        "guidance_profile_fingerprint": record.guidance_profile_fingerprint,
        "structure": record.structure,
        "objectives": record.objectives,
        "targets": record.targets,
        "timetable": record.timetable,
        "directives": record.directives,
        "stakeholders": record.stakeholders,
        "engagement_strategy": record.engagement_strategy,
        "activities": record.activities,
        "representations": record.representations,
        "summaries": record.summaries,
        "dispositions": record.dispositions,
        "equality_findings": record.equality_findings,
        "policy_references": record.policy_references,
        "policy_alignments": record.policy_alignments,
    }


def _release_fingerprint(record: Any) -> str:
    return _fingerprint(_release_payload(record))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json(value), indent=2, sort_keys=True) + "\n")
