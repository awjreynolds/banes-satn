"""Versioned, public LCWIP domain contracts.

The models are intentionally geometry-free.  Spatial and network artefacts are
linked by stable public identifiers rather than copied from SATN internals.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from satn import PublishedArtifactReference, PublishedNetworkFeatureReference

NonBlankContractText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HumanDecisionText = NonBlankContractText
ExternalDecisionIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]
Sha256ContractText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
]


_PERCENT_ENCODED_OCTET = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED_URI_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _remove_uri_dot_segments(path: str) -> str:
    """Remove RFC 3986 dot segments without collapsing other path separators."""
    input_buffer = path
    output = ""
    while input_buffer:
        if input_buffer.startswith("../") or input_buffer.startswith("./"):
            input_buffer = input_buffer.partition("/")[2]
        elif input_buffer.startswith("/./"):
            input_buffer = "/" + input_buffer[3:]
        elif input_buffer == "/.":
            input_buffer = "/"
        elif input_buffer.startswith("/../"):
            input_buffer = "/" + input_buffer[4:]
            output = output.rpartition("/")[0]
        elif input_buffer == "/..":
            input_buffer = "/"
            output = output.rpartition("/")[0]
        elif input_buffer in {".", ".."}:
            input_buffer = ""
        else:
            segment_end = input_buffer.find("/", 1)
            if segment_end == -1:
                output += input_buffer
                input_buffer = ""
            else:
                output += input_buffer[:segment_end]
                input_buffer = input_buffer[segment_end:]
    return output


def _normalize_uri_path_percent_encoding(path: str) -> str:
    """Canonicalize percent triplets while retaining reserved path semantics."""

    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        if character in _UNRESERVED_URI_CHARACTERS:
            return character
        return f"%{match.group(1).upper()}"

    return _PERCENT_ENCODED_OCTET.sub(replace, path)


def _canonical_resource_identity(uri: str) -> tuple[str, str, str, str]:
    """Return the URI parts that identify a resource for evidence comparison."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    path = _remove_uri_dot_segments(_normalize_uri_path_percent_encoding(parts.path))
    query = _normalize_uri_path_percent_encoding(parts.query)
    if scheme in {"http", "https"} and not path:
        path = "/"
    host = parts.hostname
    if host is None:
        return (scheme, parts.netloc, path, query)

    try:
        port = parts.port
    except ValueError:
        # URI syntax is intentionally not a separate contract concern here.
        # Retain an unparseable authority rather than rejecting it incidentally.
        return (scheme, parts.netloc, path, query)

    userinfo, separator, _ = parts.netloc.rpartition("@")
    authority = f"{userinfo}{separator}" if separator else ""
    normalized_host = host.lower()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    authority += normalized_host
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        authority += f":{port}"
    return (scheme, authority, path, query)


class ContractModel(BaseModel):
    """Closed, immutable stable contract model with explicit schema versioning."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    schema_version: Literal["1.0"] = "1.0"


class Obligation(StrEnum):
    MANDATORY = "mandatory"
    RECOMMENDED = "recommended"
    LOCALLY_SELECTED = "locally-selected"


class RequirementStatus(StrEnum):
    SATISFIED = "satisfied"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"
    WAIVED = "waived"
    FAILED = "failed"


class AuditFindingStatus(StrEnum):
    UNKNOWN = "unknown"
    SATISFACTORY = "satisfactory"
    DEFICIENCY = "deficiency"
    NOT_APPLICABLE = "not-applicable"


class EqualityFindingStatus(StrEnum):
    UNKNOWN = "unknown"
    ADVERSE_IMPACT = "adverse-impact"
    MITIGATED = "mitigated"
    NO_ADVERSE_IMPACT = "no-adverse-impact"


class LifecycleState(StrEnum):
    EXPLORATORY = "exploratory"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    ANALYSIS_DRAFT = "analysis_draft"
    CONSULTATION_DRAFT = "consultation_draft"
    ADOPTION_CANDIDATE = "adoption_candidate"
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"


class ArtifactLink(ContractModel):
    artifact_id: NonBlankContractText
    uri: NonBlankContractText
    kind: NonBlankContractText


# Compatibility spelling for clients which previously imported this reference
# from LCWIP. SATN owns the public publication contract.
SatnArtifactReference = PublishedArtifactReference
SatnFeatureReference = PublishedNetworkFeatureReference


class Requirement(ContractModel):
    requirement_id: Annotated[
        NonBlankContractText, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    ]
    obligation: Obligation
    expected_artifacts: tuple[NonBlankContractText, ...] = Field(min_length=1)
    description: str = ""

    @field_validator("expected_artifacts")
    @classmethod
    def canonical_expected_artifacts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_identifiers(value, "requirement expected artifacts")


class GuidanceProfile(ContractModel):
    profile_id: Annotated[
        NonBlankContractText, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    ]
    issuer: NonBlankContractText
    document: NonBlankContractText
    version: NonBlankContractText
    effective_date: date
    applicability: NonBlankContractText
    requirements: tuple[Requirement, ...] = Field(min_length=1)

    @field_validator("requirements")
    @classmethod
    def unique_requirement_ids(
        cls, requirements: tuple[Requirement, ...]
    ) -> tuple[Requirement, ...]:
        identifiers = [requirement.requirement_id for requirement in requirements]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Guidance Profile requirement IDs must be unique")
        return tuple(sorted(requirements, key=lambda requirement: requirement.requirement_id))

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(canonical).hexdigest()


class RequirementAssessment(ContractModel):
    requirement_id: NonBlankContractText
    status: RequirementStatus
    evidence: tuple[ArtifactLink, ...] = ()
    rationale: str = ""
    waiver: Waiver | None = None

    @field_validator("evidence")
    @classmethod
    def canonical_evidence(cls, evidence: tuple[ArtifactLink, ...]) -> tuple[ArtifactLink, ...]:
        keys = [(link.kind, link.artifact_id, link.uri) for link in evidence]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement evidence links must be unique")
        return tuple(sorted(evidence, key=lambda link: (link.kind, link.artifact_id, link.uri)))

    def model_post_init(self, __context: object) -> None:
        if self.status is RequirementStatus.WAIVED and self.waiver is None:
            raise ValueError("a waived requirement needs a named human authority and rationale")
        if self.status is not RequirementStatus.WAIVED and self.waiver is not None:
            raise ValueError("a waiver is only permitted when requirement status is waived")


class Waiver(ContractModel):
    """A human-authorised exception; it is never produced by an agent."""

    authority_name: HumanDecisionText
    rationale: HumanDecisionText


class ConformanceResult(ContractModel):
    profile: GuidanceProfile
    profile_id: NonBlankContractText
    profile_fingerprint: NonBlankContractText
    requirements: tuple[RequirementAssessment, ...]
    unresolved_mandatory_requirement_ids: tuple[NonBlankContractText, ...]
    conformance_fingerprint: NonBlankContractText

    def model_post_init(self, __context: object) -> None:
        if self.profile_id != self.profile.profile_id:
            raise ValueError("profile_id does not match the embedded profile")
        if self.profile_fingerprint != self.profile.fingerprint:
            raise ValueError("profile_fingerprint does not match the embedded profile")

        profile_requirement_ids = tuple(
            requirement.requirement_id for requirement in self.profile.requirements
        )
        assessment_ids = tuple(assessment.requirement_id for assessment in self.requirements)
        if assessment_ids != profile_requirement_ids:
            raise ValueError(
                "requirements must be complete, unique, and in profile requirement order"
            )
        for requirement, assessment in zip(
            self.profile.requirements, self.requirements, strict=True
        ):
            if assessment.status is RequirementStatus.SATISFIED:
                evidence_kinds = {evidence.kind for evidence in assessment.evidence}
                missing = set(requirement.expected_artifacts) - evidence_kinds
                if missing:
                    raise ValueError(
                        f"satisfied requirement {requirement.requirement_id} is missing expected "
                        f"artifact kinds: {', '.join(sorted(missing))}"
                    )
        unresolved = tuple(
            requirement.requirement_id
            for requirement, assessment in zip(
                self.profile.requirements, self.requirements, strict=True
            )
            if requirement.obligation is Obligation.MANDATORY
            and not (
                assessment.status is RequirementStatus.SATISFIED
                or (assessment.status is RequirementStatus.WAIVED and assessment.waiver is not None)
            )
        )
        if self.unresolved_mandatory_requirement_ids != unresolved:
            raise ValueError(
                "unresolved mandatory requirement IDs do not match the embedded profile"
            )
        fingerprint = self._derived_fingerprint()
        if self.conformance_fingerprint != fingerprint:
            raise ValueError("conformance fingerprint does not match the evaluated result")

    @classmethod
    def from_evaluation(
        cls,
        profile: GuidanceProfile,
        assessments: Iterable[RequirementAssessment],
    ) -> ConformanceResult:
        """Derive a canonical result from one immutable profile and its assessments.

        This is the only construction path for evaluated results. It never trusts
        a caller to supply result ordering or mandatory gaps. The SHA-256 value
        detects accidental or unauthorised payload changes; it is not an
        authenticated signature.
        """
        supplied: dict[str, RequirementAssessment] = {}
        profile_requirement_ids = {
            requirement.requirement_id for requirement in profile.requirements
        }
        for assessment in assessments:
            if assessment.requirement_id not in profile_requirement_ids:
                raise ValueError(f"unknown requirement {assessment.requirement_id}")
            if assessment.requirement_id in supplied:
                raise ValueError(f"duplicate assessment for {assessment.requirement_id}")
            supplied[assessment.requirement_id] = assessment

        requirements = tuple(
            supplied.get(
                requirement.requirement_id,
                RequirementAssessment(
                    requirement_id=requirement.requirement_id,
                    status=RequirementStatus.UNKNOWN,
                    rationale="No assessment has been supplied.",
                ),
            )
            for requirement in profile.requirements
        )
        for requirement, assessment in zip(profile.requirements, requirements, strict=True):
            if assessment.status is RequirementStatus.SATISFIED:
                evidence_kinds = {evidence.kind for evidence in assessment.evidence}
                missing = set(requirement.expected_artifacts) - evidence_kinds
                if missing:
                    raise ValueError(
                        f"satisfied requirement {requirement.requirement_id} is missing expected "
                        f"artifact kinds: {', '.join(sorted(missing))}"
                    )

        unresolved_mandatory_requirement_ids = tuple(
            requirement.requirement_id
            for requirement, assessment in zip(profile.requirements, requirements, strict=True)
            if requirement.obligation is Obligation.MANDATORY
            and not (
                assessment.status is RequirementStatus.SATISFIED
                or (assessment.status is RequirementStatus.WAIVED and assessment.waiver is not None)
            )
        )
        payload = {
            "schema_version": "1.0",
            "profile": profile,
            "profile_id": profile.profile_id,
            "profile_fingerprint": profile.fingerprint,
            "requirements": requirements,
            "unresolved_mandatory_requirement_ids": unresolved_mandatory_requirement_ids,
        }
        return cls(
            **payload,
            conformance_fingerprint=cls._fingerprint_for_payload(payload),
        )

    def _derived_fingerprint(self) -> str:
        return self._fingerprint_for_payload(
            self.model_dump(mode="json", exclude={"conformance_fingerprint"})
        )

    @staticmethod
    def _fingerprint_for_payload(payload: object) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.model_dump(mode="json"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()


class TransitionGate(ContractModel):
    """Named human confirmation of one lifecycle transition."""

    authority_name: HumanDecisionText
    rationale: HumanDecisionText


class LifecycleTransition(ContractModel):
    """One accountable transition in a release's lifecycle history."""

    from_state: LifecycleState
    to_state: LifecycleState
    gate: TransitionGate


PERMITTED_LIFECYCLE_TRANSITIONS = {
    LifecycleState.EXPLORATORY: {
        LifecycleState.EVIDENCE_INCOMPLETE,
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.SUPERSEDED,
    },
    LifecycleState.EVIDENCE_INCOMPLETE: {
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.SUPERSEDED,
    },
    LifecycleState.ANALYSIS_DRAFT: {
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.SUPERSEDED,
    },
    LifecycleState.CONSULTATION_DRAFT: {
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.SUPERSEDED,
    },
    LifecycleState.ADOPTION_CANDIDATE: {LifecycleState.ADOPTED, LifecycleState.SUPERSEDED},
    LifecycleState.ADOPTED: {LifecycleState.SUPERSEDED},
    LifecycleState.SUPERSEDED: set(),
}


class ExternalDecisionRecord(ContractModel):
    """An externally recorded decision with independently governed verification.

    Verification provenance is accountable human evidence, not a cryptographic signature.
    """

    decision_id: ExternalDecisionIdentifier
    authority_name: HumanDecisionText
    uri: HumanDecisionText
    verification: ExternalDecisionVerification

    def model_post_init(self, __context: object) -> None:
        # ``model_construct`` bypasses field validation but still calls this hook.
        # Leave malformed constructed values for the public revalidation boundaries.
        verification = getattr(self, "verification", None)
        if not isinstance(verification, ExternalDecisionVerification):
            return
        if verification.decision_id != self.decision_id:
            raise ValueError("verification decision_id must match the external decision record")
        if verification.evidence.artifact_id == self.decision_id:
            raise ValueError("verification evidence must be distinct from the decision record ID")
        if (
            isinstance(verification.evidence.uri, str)
            and isinstance(self.uri, str)
            and _canonical_resource_identity(verification.evidence.uri)
            == _canonical_resource_identity(self.uri)
        ):
            raise ValueError("verification evidence must be distinct from the decision record URI")


class ExternalDecisionVerificationMethod(StrEnum):
    """Governed, human methods permitted for decision-verification evidence."""

    HUMAN_RECORD_REVIEW = "human-record-review"
    INDEPENDENT_EVIDENCE_REVIEW = "independent-evidence-review"


class ExternalDecisionVerification(ContractModel):
    """Named human verification of one external decision using distinct evidence.

    This preserves governed verification provenance; it is not a cryptographic signature.
    """

    decision_id: ExternalDecisionIdentifier
    verifier_name: HumanDecisionText
    verified_on: date
    method: ExternalDecisionVerificationMethod
    evidence: ArtifactLink


class PlanRelease(ContractModel):
    """A release is a historical record bound to one immutable Guidance Profile."""

    release_id: NonBlankContractText
    profile_id: NonBlankContractText
    profile_fingerprint: Sha256ContractText
    lifecycle_state: LifecycleState = LifecycleState.EXPLORATORY
    claims: tuple[NonBlankContractText, ...] = ("exploratory",)
    transition_history: tuple[LifecycleTransition, ...] = ()
    external_decision: ExternalDecisionRecord | None = None

    @field_validator("claims")
    @classmethod
    def validate_claims(cls, claims: tuple[str, ...]) -> tuple[str, ...]:
        if not claims:
            raise ValueError("a release must state its lifecycle claim")
        return tuple(sorted(set(claims)))

    @field_validator("external_decision")
    @classmethod
    def external_decision_is_external(
        cls, decision: ExternalDecisionRecord | None
    ) -> ExternalDecisionRecord | None:
        if decision is None:
            return None
        return ExternalDecisionRecord.model_validate(decision)

    def model_post_init(self, __context: object) -> None:
        permitted = {self.lifecycle_state.value}
        if not set(self.claims).issubset(permitted):
            raise ValueError(
                f"claims {self.claims!r} are not permitted for {self.lifecycle_state.value}"
            )
        adoption_reached = self.lifecycle_state is LifecycleState.ADOPTED or any(
            transition.to_state is LifecycleState.ADOPTED
            for transition in self.transition_history
        )
        if adoption_reached != (self.external_decision is not None):
            raise ValueError(
                "an external decision record is required exactly when adoption is reached"
            )
        if self.lifecycle_state is LifecycleState.EXPLORATORY:
            if self.transition_history:
                raise ValueError("exploratory releases cannot have a transition history")
            return
        if not self.transition_history:
            raise ValueError("non-exploratory releases require a complete transition history")
        if self.transition_history[0].from_state is not LifecycleState.EXPLORATORY:
            raise ValueError("transition history must start at exploratory")
        previous = LifecycleState.EXPLORATORY
        for transition in self.transition_history:
            if transition.from_state is not previous:
                raise ValueError("transition history must be contiguous")
            if transition.to_state not in PERMITTED_LIFECYCLE_TRANSITIONS[transition.from_state]:
                raise ValueError("transition history contains a transition that is not permitted")
            previous = transition.to_state
        if previous is not self.lifecycle_state:
            raise ValueError("transition history must end at the release lifecycle state")


class StudyArea(ContractModel):
    area_id: NonBlankContractText
    name: NonBlankContractText
    boundary: ArtifactLink


class PlanHorizon(ContractModel):
    start_year: int = Field(ge=2000, le=3000)
    end_year: int = Field(ge=2000, le=3000)

    def model_post_init(self, __context: object) -> None:
        if self.end_year <= self.start_year:
            raise ValueError("plan horizon end year must be after its start year")


class Objective(ContractModel):
    objective_id: NonBlankContractText
    statement: NonBlankContractText


class Target(ContractModel):
    target_id: NonBlankContractText
    objective_id: NonBlankContractText
    measure: NonBlankContractText
    value: float
    unit: NonBlankContractText


class GovernanceDirective(ContractModel):
    directive_id: NonBlankContractText
    authority_name: NonBlankContractText
    directive: NonBlankContractText


class EvidenceItem(ContractModel):
    evidence_id: NonBlankContractText
    item: ArtifactLink


class EvidenceRequest(ContractModel):
    request_id: NonBlankContractText
    purpose: NonBlankContractText


class CyclingDesireLine(ContractModel):
    desire_line_id: NonBlankContractText
    origin_id: NonBlankContractText
    destination_id: NonBlankContractText
    evidence: tuple[ArtifactLink, ...] = ()

    def model_post_init(self, __context: object) -> None:
        if self.origin_id == self.destination_id:
            raise ValueError("a Cycling Desire Line requires distinct origin and destination")


class WalkingZone(ContractModel):
    zone_id: NonBlankContractText
    name: NonBlankContractText
    evidence: tuple[ArtifactLink, ...] = ()


class WalkingRoute(ContractModel):
    route_id: NonBlankContractText
    zone_id: NonBlankContractText
    name: NonBlankContractText
    evidence: tuple[ArtifactLink, ...] = ()


class AuditFinding(ContractModel):
    finding_id: NonBlankContractText
    subject_id: NonBlankContractText
    status: AuditFindingStatus
    evidence: tuple[ArtifactLink, ...] = ()

    @field_validator("status", mode="before")
    @classmethod
    def reject_requirement_status(cls, value: object) -> object:
        if isinstance(value, RequirementStatus):
            raise ValueError("audit findings use AuditFindingStatus, not RequirementStatus")
        return value


class Deficiency(ContractModel):
    deficiency_id: NonBlankContractText
    finding_id: NonBlankContractText
    description: NonBlankContractText


class Intervention(ContractModel):
    intervention_id: NonBlankContractText
    deficiency_ids: tuple[NonBlankContractText, ...] = Field(min_length=1)
    description: NonBlankContractText

    @field_validator("deficiency_ids")
    @classmethod
    def unique_deficiencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_identifiers(value, "intervention deficiency IDs")


class ProgrammeScenario(ContractModel):
    scenario_id: NonBlankContractText
    name: NonBlankContractText


class ProgrammeEntry(ContractModel):
    entry_id: NonBlankContractText
    scenario_id: NonBlankContractText
    intervention_ids: tuple[NonBlankContractText, ...] = Field(min_length=1)
    phase: NonBlankContractText

    @field_validator("intervention_ids")
    @classmethod
    def unique_interventions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_identifiers(value, "programme entry intervention IDs")


class Representation(ContractModel):
    representation_id: NonBlankContractText
    source: NonBlankContractText
    evidence: tuple[ArtifactLink, ...] = ()


class Disposition(ContractModel):
    disposition_id: NonBlankContractText
    representation_id: NonBlankContractText
    decision: NonBlankContractText
    rationale: NonBlankContractText


class EqualityFinding(ContractModel):
    equality_finding_id: NonBlankContractText
    topic: NonBlankContractText
    status: EqualityFindingStatus
    evidence: tuple[ArtifactLink, ...] = ()

    @field_validator("status", mode="before")
    @classmethod
    def reject_requirement_status(cls, value: object) -> object:
        if isinstance(value, RequirementStatus):
            raise ValueError("equality findings use EqualityFindingStatus, not RequirementStatus")
        return value


class PolicyLink(ContractModel):
    policy_link_id: NonBlankContractText
    policy: ArtifactLink
    outcome: NonBlankContractText


class MonitoringIndicator(ContractModel):
    indicator_id: NonBlankContractText
    measure: NonBlankContractText
    unit: NonBlankContractText


class Plan(ContractModel):
    """Extensible LCWIP workspace record; analysis remains a later concern."""

    plan_id: NonBlankContractText
    name: NonBlankContractText
    study_area: StudyArea
    horizon: PlanHorizon
    objectives: tuple[Objective, ...] = ()
    targets: tuple[Target, ...] = ()
    governance_directives: tuple[GovernanceDirective, ...] = ()
    evidence_items: tuple[EvidenceItem, ...] = ()
    evidence_requests: tuple[EvidenceRequest, ...] = ()
    cycling_desire_lines: tuple[CyclingDesireLine, ...] = ()
    walking_zones: tuple[WalkingZone, ...] = ()
    walking_routes: tuple[WalkingRoute, ...] = ()
    audit_findings: tuple[AuditFinding, ...] = ()
    deficiencies: tuple[Deficiency, ...] = ()
    interventions: tuple[Intervention, ...] = ()
    programme_scenarios: tuple[ProgrammeScenario, ...] = ()
    programme_entries: tuple[ProgrammeEntry, ...] = ()
    representations: tuple[Representation, ...] = ()
    dispositions: tuple[Disposition, ...] = ()
    equality_findings: tuple[EqualityFinding, ...] = ()
    policy_links: tuple[PolicyLink, ...] = ()
    monitoring_indicators: tuple[MonitoringIndicator, ...] = ()
    satn_artifacts: tuple[SatnArtifactReference, ...] = ()
    satn_features: tuple[PublishedNetworkFeatureReference, ...] = ()

    def model_post_init(self, __context: object) -> None:
        collections = {
            "objective IDs": (self.objectives, "objective_id"),
            "target IDs": (self.targets, "target_id"),
            "governance directive IDs": (self.governance_directives, "directive_id"),
            "evidence item IDs": (self.evidence_items, "evidence_id"),
            "evidence request IDs": (self.evidence_requests, "request_id"),
            "cycling desire line IDs": (self.cycling_desire_lines, "desire_line_id"),
            "walking zone IDs": (self.walking_zones, "zone_id"),
            "walking route IDs": (self.walking_routes, "route_id"),
            "audit finding IDs": (self.audit_findings, "finding_id"),
            "deficiency IDs": (self.deficiencies, "deficiency_id"),
            "intervention IDs": (self.interventions, "intervention_id"),
            "programme scenario IDs": (self.programme_scenarios, "scenario_id"),
            "programme entry IDs": (self.programme_entries, "entry_id"),
            "representation IDs": (self.representations, "representation_id"),
            "disposition IDs": (self.dispositions, "disposition_id"),
            "equality finding IDs": (self.equality_findings, "equality_finding_id"),
            "policy link IDs": (self.policy_links, "policy_link_id"),
            "monitoring indicator IDs": (self.monitoring_indicators, "indicator_id"),
        }
        identifiers: dict[str, set[str]] = {}
        audit_subject_identifiers = [self.study_area.area_id]
        global_identifiers = [self.study_area.area_id]
        for label, (records, attribute) in collections.items():
            values = [getattr(record, attribute) for record in records]
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
            identifiers[attribute] = set(values)
            global_identifiers.extend(values)
            if attribute != "finding_id":
                audit_subject_identifiers.extend(values)
        satn_identifiers = [artifact.public_identifier for artifact in self.satn_artifacts]
        if len(satn_identifiers) != len(set(satn_identifiers)):
            raise ValueError("SATN public identifiers must be unique")
        satn_feature_identifiers = [feature.public_identifier for feature in self.satn_features]
        if len(satn_feature_identifiers) != len(set(satn_feature_identifiers)):
            raise ValueError("SATN feature public identifiers must be unique")
        feature_ids = [feature.feature_id for feature in self.satn_features]
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("SATN feature IDs must be unique")
        audit_subject_identifiers.extend(feature_ids)
        global_identifiers.extend(feature_ids)
        if len(global_identifiers) != len(set(global_identifiers)):
            raise ValueError("audit-referable identifiers must be globally unique")

        def resolve(value: str, values: set[str], field: str) -> None:
            if value not in values:
                raise ValueError(f"{field} must resolve to a record in this plan")

        for target in self.targets:
            resolve(target.objective_id, identifiers["objective_id"], "objective_id")
        for route in self.walking_routes:
            resolve(route.zone_id, identifiers["zone_id"], "zone_id")
        for deficiency in self.deficiencies:
            resolve(deficiency.finding_id, identifiers["finding_id"], "finding_id")
        for intervention in self.interventions:
            for deficiency_id in intervention.deficiency_ids:
                resolve(deficiency_id, identifiers["deficiency_id"], "deficiency_ids")
        for entry in self.programme_entries:
            resolve(entry.scenario_id, identifiers["scenario_id"], "scenario_id")
            for intervention_id in entry.intervention_ids:
                resolve(intervention_id, identifiers["intervention_id"], "intervention_ids")
        for disposition in self.dispositions:
            resolve(
                disposition.representation_id,
                identifiers["representation_id"],
                "representation_id",
            )
        audit_subject_ids = set(audit_subject_identifiers)
        for finding in self.audit_findings:
            resolve(finding.subject_id, audit_subject_ids, "subject_id")


def _canonical_identifiers(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if any(not identifier for identifier in value) or len(value) != len(set(value)):
        raise ValueError(f"{label} must be non-empty and unique")
    return tuple(sorted(value))
