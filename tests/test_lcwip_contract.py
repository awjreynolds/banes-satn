from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcwip import (
    ArtifactLink,
    AuditFinding,
    AuditFindingStatus,
    ConformanceResult,
    CyclingDesireLine,
    Deficiency,
    Disposition,
    EqualityFinding,
    EqualityFindingStatus,
    EvidenceItem,
    EvidenceRequest,
    ExternalDecisionRecord,
    ExternalDecisionVerification,
    GovernanceDirective,
    GuidanceProfile,
    Intervention,
    LifecycleState,
    LifecycleTransition,
    MonitoringIndicator,
    Objective,
    Obligation,
    Plan,
    PlanHorizon,
    PlanRelease,
    PolicyLink,
    ProgrammeEntry,
    ProgrammeScenario,
    Representation,
    Requirement,
    RequirementAssessment,
    RequirementStatus,
    SatnArtifactReference,
    StudyArea,
    Target,
    TransitionGate,
    Waiver,
    WalkingRoute,
    WalkingZone,
    evaluate_conformance,
    evaluate_release_conformance,
    transition_release,
)
from lcwip.cli import app
from satn import PublishedArtifactReference, PublishedNetworkFeatureReference


def external_decision_payload(**overrides: object) -> dict[str, object]:
    """A decision with distinct, human-reviewed verification evidence."""
    payload: dict[str, object] = {
        "decision_id": "decision-1",
        "authority_name": "Council committee",
        "uri": "https://example.test/decision-1",
        "verification": {
            "decision_id": "decision-1",
            "verifier_name": "Named governance officer",
            "verified_on": "2026-07-24",
            "method": "human-record-review",
            "evidence": {
                "artifact_id": "decision-1-verification",
                "uri": "bundle://governance/decision-1-verification",
                "kind": "verification-record",
            },
        },
    }
    return payload | overrides


def test_guidance_profile_round_trips_and_reports_only_unresolved_mandatory_requirements() -> None:
    profile = GuidanceProfile(
        profile_id="dft-lcwip-2017",
        issuer="Department for Transport",
        document="Local Cycling and Walking Infrastructure Plans technical guidance",
        version="2017",
        effective_date=date(2017, 4, 1),
        applicability="English local authorities preparing an LCWIP",
        requirements=(
            Requirement(
                requirement_id="dft-2017.scope-governance",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("scope-and-governance",),
            ),
            Requirement(
                requirement_id="dft-2017.local-context",
                obligation=Obligation.RECOMMENDED,
                expected_artifacts=("baseline",),
            ),
        ),
    )

    restored = GuidanceProfile.model_validate_json(profile.model_dump_json())
    result = evaluate_conformance(
        restored,
        assessments=(
            RequirementAssessment(
                requirement_id="dft-2017.scope-governance",
                status=RequirementStatus.SATISFIED,
                evidence=(
                    ArtifactLink(
                        artifact_id="scope-1",
                        uri="bundle://scope.json",
                        kind="scope-and-governance",
                    ),
                ),
            ),
        ),
    )

    assert result.profile_fingerprint == restored.fingerprint
    assert [item.requirement_id for item in result.requirements] == [
        "dft-2017.local-context",
        "dft-2017.scope-governance",
    ]
    assert result.unresolved_mandatory_requirement_ids == ()
    assert result.requirements[0].status is RequirementStatus.UNKNOWN
    assert result.requirements[1].evidence[0].uri == "bundle://scope.json"


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (ArtifactLink, "artifact_id", "   "),
        (ArtifactLink, "uri", "\t"),
        (ArtifactLink, "kind", "\n"),
        (GuidanceProfile, "profile_id", "  "),
        (GuidanceProfile, "issuer", "  "),
        (GuidanceProfile, "document", "  "),
        (GuidanceProfile, "version", "  "),
        (GuidanceProfile, "applicability", "  "),
    ],
)
def test_required_contract_strings_reject_whitespace_only_evidence_and_profile_identity(
    model: type[ArtifactLink] | type[GuidanceProfile], field: str, value: str
) -> None:
    if model is ArtifactLink:
        payload = {"artifact_id": "artifact", "uri": "bundle://artifact", "kind": "baseline"}
    else:
        payload = {
            "profile_id": "test-profile",
            "issuer": "Issuer",
            "document": "Guidance",
            "version": "1",
            "effective_date": date(2026, 1, 1),
            "applicability": "Test scope",
            "requirements": (
                Requirement(
                    requirement_id="test.requirement",
                    obligation=Obligation.MANDATORY,
                    expected_artifacts=("baseline",),
                ),
            ),
        }
    payload[field] = value
    with pytest.raises(ValueError):
        model(**payload)


def test_required_expected_artifact_identifier_rejects_whitespace_only_value() -> None:
    with pytest.raises(ValueError):
        Requirement(
            requirement_id="test.requirement",
            obligation=Obligation.MANDATORY,
            expected_artifacts=(" \t ",),
        )


@pytest.mark.parametrize(
    ("model", "field", "payload"),
    [
        (
            PublishedArtifactReference,
            "uri",
            {
                "run_id": "run",
                "artifact_key": "geojson",
                "uri": "file:///network.geojson",
                "sha256": "a" * 64,
            },
        ),
        (
            PublishedNetworkFeatureReference,
            "feature_id",
            {
                "run_id": "run",
                "artifact_key": "geojson",
                "feature_id": "feature",
                "feature_type": "connection",
                "source_artifact_uri": "file:///network.geojson",
                "source_artifact_sha256": "a" * 64,
            },
        ),
    ],
)
def test_public_satn_references_reject_whitespace_only_required_strings(
    model: type[PublishedArtifactReference] | type[PublishedNetworkFeatureReference],
    field: str,
    payload: dict[str, str],
) -> None:
    payload[field] = " \t "
    with pytest.raises(ValueError):
        model(**payload)


@pytest.mark.parametrize("network_role", (" \t ", True, {"role": "spine"}))
def test_published_feature_reference_network_role_is_optional_but_validated_when_present(
    network_role: object,
) -> None:
    payload = {
        "run_id": "run",
        "artifact_key": "geojson",
        "feature_id": "feature",
        "feature_type": "connection",
        "source_artifact_uri": "file:///network.geojson",
        "source_artifact_sha256": "a" * 64,
    }

    reference = PublishedNetworkFeatureReference(**payload)
    assert reference.network_role is None
    assert PublishedNetworkFeatureReference(**(payload | {"network_role": None})) == reference
    role_bearing = PublishedNetworkFeatureReference(**(payload | {"network_role": " spine "}))
    assert role_bearing.network_role == "spine"

    with pytest.raises(ValueError):
        PublishedNetworkFeatureReference(**(payload | {"network_role": network_role}))


def test_lifecycle_rejects_ungated_and_generated_adoption_and_forbidden_claims() -> None:
    release = PlanRelease(
        release_id="release-01",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )

    with pytest.raises(ValueError, match="human transition gate"):
        transition_release(release, LifecycleState.EVIDENCE_INCOMPLETE)
    with pytest.raises(ValueError, match="not permitted"):
        PlanRelease(
            release_id="release-claim",
            profile_id="dft-lcwip-2017",
            profile_fingerprint="a" * 64,
            claims=("adopted",),
        )

    evidence_incomplete = transition_release(
        release,
        LifecycleState.EVIDENCE_INCOMPLETE,
        gate=TransitionGate(authority_name="Named officer", rationale="Evidence review."),
    )
    candidate = transition_release(
        evidence_incomplete,
        LifecycleState.ANALYSIS_DRAFT,
        gate=TransitionGate(authority_name="Named officer", rationale="Analysis reviewed."),
    )
    candidate = transition_release(
        candidate,
        LifecycleState.CONSULTATION_DRAFT,
        gate=TransitionGate(authority_name="Named officer", rationale="Consultation approved."),
    )
    candidate = transition_release(
        candidate,
        LifecycleState.ADOPTION_CANDIDATE,
        gate=TransitionGate(authority_name="Named officer", rationale="Candidate checked."),
    )
    assert [transition.to_state for transition in candidate.transition_history] == [
        LifecycleState.EVIDENCE_INCOMPLETE,
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
    ]

    with pytest.raises(ValueError):
        transition_release(
            candidate,
            LifecycleState.ADOPTED,
            gate=TransitionGate(authority_name="Named officer", rationale="Generated it."),
            external_decision=ExternalDecisionRecord.model_construct(
                decision_id="decision-1",
                authority_name="Council committee",
                uri="https://example.test/decision-1",
                verification=ExternalDecisionVerification.model_construct(
                    decision_id="decision-1",
                    verifier_name="Named governance officer",
                    verified_on=date(2026, 7, 24),
                    method="automatic",
                    evidence=ArtifactLink(
                        artifact_id="decision-1-verification",
                        uri="bundle://governance/decision-1-verification",
                        kind="verification-record",
                    ),
                ),
            ),
        )

    adopted = transition_release(
        candidate,
        LifecycleState.ADOPTED,
        gate=TransitionGate(authority_name="Named officer", rationale="Adoption recorded."),
        external_decision=ExternalDecisionRecord.model_validate(
            external_decision_payload(
                decision_id="decision-2",
                uri="https://example.test/decision-2",
                verification={
                    "decision_id": "decision-2",
                    "verifier_name": "Named governance officer",
                    "verified_on": "2026-07-24",
                    "method": "human-record-review",
                    "evidence": {
                        "artifact_id": "decision-2-verification",
                        "uri": "bundle://governance/decision-2-verification",
                        "kind": "verification-record",
                    },
                },
            )
        ),
    )
    superseded = transition_release(
        adopted,
        LifecycleState.SUPERSEDED,
        gate=TransitionGate(
            authority_name="Named officer", rationale="Superseded by a new release."
        ),
    )
    assert superseded.external_decision == adopted.external_decision


def test_constructed_transition_gate_cannot_bypass_release_or_transition_validation() -> None:
    blank_gate = TransitionGate.model_construct(authority_name=" \t ", rationale="Review.")
    transition = LifecycleTransition.model_construct(
        from_state=LifecycleState.EXPLORATORY,
        to_state=LifecycleState.ANALYSIS_DRAFT,
        gate=blank_gate,
    )

    with pytest.raises(ValueError, match="authority_name"):
        PlanRelease(
            release_id="constructed-history",
            profile_id="dft-lcwip-2017",
            profile_fingerprint="a" * 64,
            lifecycle_state=LifecycleState.ANALYSIS_DRAFT,
            claims=("analysis_draft",),
            transition_history=(transition,),
        )

    release = PlanRelease(
        release_id="constructed-transition",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )
    with pytest.raises(ValueError, match="authority_name"):
        transition_release(release, LifecycleState.ANALYSIS_DRAFT, gate=blank_gate)


@pytest.mark.parametrize(
    ("model", "field", "valid_value"),
    (
        (Waiver, "authority_name", " Director of transport "),
        (Waiver, "rationale", " Approved exception. "),
        (TransitionGate, "authority_name", " Named officer "),
        (TransitionGate, "rationale", " Evidence reviewed. "),
        (ExternalDecisionRecord, "decision_id", " decision-1 "),
        (ExternalDecisionRecord, "authority_name", " Council committee "),
        (ExternalDecisionRecord, "uri", " https://example.test/decision-1 "),
    ),
)
def test_human_decision_fields_reject_whitespace_and_normalize_values(
    model: type[Waiver | TransitionGate | ExternalDecisionRecord],
    field: str,
    valid_value: str,
) -> None:
    values = {
        Waiver: {"authority_name": "Named officer", "rationale": "Approved exception."},
        TransitionGate: {"authority_name": "Named officer", "rationale": "Evidence reviewed."},
        ExternalDecisionRecord: {
            "decision_id": "decision-1",
            "authority_name": "Council committee",
            "uri": "https://example.test/decision-1",
            "verification": external_decision_payload()["verification"],
        },
    }[model]

    with pytest.raises(ValueError):
        model.model_validate(values | {field: " \t\n "})

    normalized = model.model_validate(values | {field: valid_value})
    assert getattr(normalized, field) == valid_value.strip()


def test_external_decision_id_rejects_blank_values_at_validation_and_adoption_seams() -> None:
    decision_payload = external_decision_payload(decision_id=" \t\n ")
    with pytest.raises(ValueError, match="decision_id"):
        ExternalDecisionRecord.model_validate(decision_payload)
    with pytest.raises(ValueError, match="decision_id"):
        ExternalDecisionRecord.model_validate_json(json.dumps(decision_payload))

    release = PlanRelease(
        release_id="adoption-candidate",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )
    for state in (
        LifecycleState.ANALYSIS_DRAFT,
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
    ):
        release = transition_release(
            release,
            state,
            gate=TransitionGate(authority_name="Named officer", rationale="Release reviewed."),
        )
    with pytest.raises(ValueError, match="decision_id"):
        transition_release(
            release,
            LifecycleState.ADOPTED,
            gate=TransitionGate(authority_name="Named officer", rationale="Adoption recorded."),
            external_decision=ExternalDecisionRecord.model_construct(**decision_payload),
        )


@pytest.mark.parametrize(
    "invalid_decision",
    (
        {"verified": True, "generated": False},
        {"verification": None},
        {"verification": {**external_decision_payload()["verification"], "method": "automatic"}},
        {"verification": {**external_decision_payload()["verification"], "decision_id": "other"}},
        {"verification": {**external_decision_payload()["verification"], "verifier_name": " \t "}},
        {
            "verification": {
                **external_decision_payload()["verification"],
                "evidence": {
                    "artifact_id": "decision-1",
                    "uri": "https://example.test/decision-1",
                    "kind": "decision-record",
                },
            }
        },
    ),
)
def test_external_decision_requires_independent_governed_verification(
    invalid_decision: dict[str, object]
) -> None:
    """Verification provenance is governed human evidence, not a cryptographic signature."""
    payload = external_decision_payload(**invalid_decision)

    with pytest.raises(ValueError):
        ExternalDecisionRecord.model_validate(payload)
    with pytest.raises(ValueError):
        ExternalDecisionRecord.model_validate_json(json.dumps(payload))

    release = PlanRelease(
        release_id="adoption-candidate",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )
    gate = TransitionGate(authority_name="Named officer", rationale="Release reviewed.")
    for state in (LifecycleState.ANALYSIS_DRAFT, LifecycleState.ADOPTION_CANDIDATE):
        release = transition_release(release, state, gate=gate)
    constructed_payload = payload
    if "verified" in invalid_decision:
        constructed_payload = {
            "decision_id": payload["decision_id"],
            "authority_name": payload["authority_name"],
            "uri": payload["uri"],
            **invalid_decision,
        }
    with pytest.raises(ValueError):
        transition_release(
            release,
            LifecycleState.ADOPTED,
            gate=gate,
            external_decision=ExternalDecisionRecord.model_construct(**constructed_payload),
        )


@pytest.mark.parametrize(
    "evidence_uri",
    (
        "HTTPS://EXAMPLE.TEST:443/decision-1#verification",
        "http://EXAMPLE.TEST:80/decision-1#verification",
        "file:///governance/decision-1#verification",
    ),
)
def test_external_decision_rejects_verification_evidence_for_the_same_canonical_resource(
    evidence_uri: str,
) -> None:
    """Evidence must not differ from a decision only in URI presentation."""
    decision_uri = {
        "HTTPS://EXAMPLE.TEST:443/decision-1#verification": "https://example.test/decision-1",
        "http://EXAMPLE.TEST:80/decision-1#verification": "HTTP://example.test/decision-1",
        "file:///governance/decision-1#verification": "FILE:///governance/decision-1",
    }[evidence_uri]
    payload = external_decision_payload(
        uri=decision_uri,
        verification={
            **external_decision_payload()["verification"],
            "evidence": {
                "artifact_id": "decision-1-verification",
                "uri": evidence_uri,
                "kind": "verification-record",
            },
        },
    )

    with pytest.raises(ValueError, match="distinct from the decision record URI"):
        ExternalDecisionRecord.model_validate(payload)
    with pytest.raises(ValueError, match="distinct from the decision record URI"):
        ExternalDecisionRecord.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    ("decision_uri", "evidence_uri"),
    (
        ("https://example.test", "HTTPS://EXAMPLE.TEST:443/"),
        (
            "https://example.test/governance/decision-1",
            "https://example.test/governance/current/../decision-1",
        ),
        ("https://example.test/decision-1", "https://example.test/%64ecision-1"),
        (
            "https://example.test/decision-1?view=verification",
            "https://example.test/decision-1?view=%76erification",
        ),
    ),
)
def test_external_decision_rejects_equivalent_http_resource_uri_presentations(
    decision_uri: str, evidence_uri: str
) -> None:
    payload = external_decision_payload(
        uri=decision_uri,
        verification={
            **external_decision_payload()["verification"],
            "evidence": {
                "artifact_id": "decision-1-verification",
                "uri": evidence_uri,
                "kind": "verification-record",
            },
        },
    )

    with pytest.raises(ValueError, match="distinct from the decision record URI"):
        ExternalDecisionRecord.model_validate(payload)


@pytest.mark.parametrize(
    "evidence_uri",
    (
        "https://example.test/Decision-1",
        "https://example.test/decision-1?view=verification",
        "https://example.test/decision-1?view=verification&format=html",
        "https://example.test/governance//decision-1",
        "file:///governance/Decision-1",
    ),
)
def test_external_decision_allows_verification_evidence_at_a_distinct_canonical_resource(
    evidence_uri: str,
) -> None:
    payload = external_decision_payload(
        uri="file:///governance/decision-1"
        if evidence_uri.startswith("file:")
        else "https://example.test/decision-1",
        verification={
            **external_decision_payload()["verification"],
            "evidence": {
                "artifact_id": "decision-1-verification",
                "uri": evidence_uri,
                "kind": "verification-record",
            },
        },
    )

    assert ExternalDecisionRecord.model_validate(payload).verification.evidence.uri == evidence_uri


@pytest.mark.parametrize(
    ("field", "reference", "error"),
    (
        (
            "satn_artifacts",
            PublishedArtifactReference.model_construct(
                run_id=" \t ",
                artifact_key="geojson",
                uri=" \t ",
                sha256="not-a-sha",
            ),
            "run_id|uri|sha256",
        ),
        (
            "satn_features",
            PublishedNetworkFeatureReference.model_construct(
                run_id="run",
                artifact_key="geojson",
                feature_id=" \t ",
                feature_type="connection",
                network_role=" \t ",
                source_artifact_uri=" \t ",
                source_artifact_sha256="not-a-sha",
            ),
            "feature_id|network_role|source_artifact_uri|source_artifact_sha256",
        ),
    ),
)
def test_plan_revalidates_constructed_satn_publication_references(
    field: str,
    reference: PublishedArtifactReference | PublishedNetworkFeatureReference,
    error: str,
) -> None:
    payload: dict[str, object] = {
        "plan_id": "publication-reference-plan",
        "name": "Publication reference plan",
        "study_area": StudyArea(
            area_id="area",
            name="Area",
            boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
        ),
        "horizon": PlanHorizon(start_year=2026, end_year=2027),
        field: (reference,),
    }

    with pytest.raises(ValueError, match=error):
        Plan.model_validate(payload)


def test_external_decision_rejects_a_missing_verification_contract() -> None:
    old_self_assertion = {
        "decision_id": "decision-1",
        "authority_name": "Council committee",
        "uri": "https://example.test/decision-1",
        "verified": True,
        "generated": False,
    }
    with pytest.raises(ValueError):
        ExternalDecisionRecord.model_validate(old_self_assertion)
    with pytest.raises(ValueError):
        ExternalDecisionRecord.model_validate_json(json.dumps(old_self_assertion))


def test_external_decision_verification_round_trips_and_authorizes_adoption() -> None:
    decision = ExternalDecisionRecord.model_validate(external_decision_payload())
    assert ExternalDecisionRecord.model_validate_json(decision.model_dump_json()) == decision
    assert decision.verification.verifier_name == "Named governance officer"

    release = PlanRelease(
        release_id="adoption-candidate",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )
    gate = TransitionGate(authority_name="Named officer", rationale="Release reviewed.")
    for state in (LifecycleState.ANALYSIS_DRAFT, LifecycleState.ADOPTION_CANDIDATE):
        release = transition_release(release, state, gate=gate)
    assert (
        transition_release(
            release, LifecycleState.ADOPTED, gate=gate, external_decision=decision
        ).external_decision
        == decision
    )


@pytest.mark.parametrize(
    ("factory", "field"),
    (
        (
            lambda: Plan(
                plan_id="plan",
                name="Plan",
                study_area=StudyArea(
                    area_id="area",
                    name="Area",
                    boundary=ArtifactLink(
                        artifact_id="area", uri="bundle://area", kind="study-area"
                    ),
                ),
                horizon=PlanHorizon(start_year=2026, end_year=2027),
            ),
            "plan_id",
        ),
        (
            lambda: StudyArea(
                area_id="area",
                name="Area",
                boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
            ),
            "name",
        ),
        (lambda: Objective(objective_id="objective", statement="Improve access"), "statement"),
        (
            lambda: PlanRelease(
                release_id="release",
                profile_id="profile",
                profile_fingerprint="a" * 64,
            ),
            "release_id",
        ),
        (
            lambda: PlanRelease(
                release_id="release",
                profile_id="profile",
                profile_fingerprint="a" * 64,
            ),
            "profile_id",
        ),
    ),
)
def test_required_public_lcwip_strings_reject_whitespace_only_values(
    factory: object, field: str
) -> None:
    model = factory()  # type: ignore[operator]
    with pytest.raises(ValueError):
        type(model).model_validate(model.model_dump() | {field: " \t "})


def test_plan_release_requires_a_lowercase_sha256_profile_fingerprint() -> None:
    payload = {
        "release_id": "release",
        "profile_id": "profile",
        "profile_fingerprint": "A" * 64,
    }
    with pytest.raises(ValueError, match="profile_fingerprint"):
        PlanRelease.model_validate(payload)
    release = PlanRelease.model_validate(payload | {"profile_fingerprint": "a" * 64})
    assert release.profile_id == "profile"


def test_direct_release_model_requires_an_external_decision_exactly_for_adoption_history() -> None:
    decision = ExternalDecisionRecord.model_validate(external_decision_payload())
    gate = TransitionGate(authority_name="Named officer", rationale="Recorded transition.")

    with pytest.raises(ValueError, match="external decision record"):
        PlanRelease(
            release_id="decision-without-adoption",
            profile_id="dft-lcwip-2017",
            profile_fingerprint="a" * 64,
            lifecycle_state=LifecycleState.SUPERSEDED,
            claims=("superseded",),
            transition_history=(
                LifecycleTransition(
                    from_state=LifecycleState.EXPLORATORY,
                    to_state=LifecycleState.SUPERSEDED,
                    gate=gate,
                ),
            ),
            external_decision=decision,
        )

    with pytest.raises(ValueError, match="external decision record"):
        PlanRelease(
            release_id="adoption-without-decision",
            profile_id="dft-lcwip-2017",
            profile_fingerprint="a" * 64,
            lifecycle_state=LifecycleState.SUPERSEDED,
            claims=("superseded",),
            transition_history=(
                LifecycleTransition(
                    from_state=LifecycleState.EXPLORATORY,
                    to_state=LifecycleState.ANALYSIS_DRAFT,
                    gate=gate,
                ),
                LifecycleTransition(
                    from_state=LifecycleState.ANALYSIS_DRAFT,
                    to_state=LifecycleState.ADOPTION_CANDIDATE,
                    gate=gate,
                ),
                LifecycleTransition(
                    from_state=LifecycleState.ADOPTION_CANDIDATE,
                    to_state=LifecycleState.ADOPTED,
                    gate=gate,
                ),
                LifecycleTransition(
                    from_state=LifecycleState.ADOPTED,
                    to_state=LifecycleState.SUPERSEDED,
                    gate=gate,
                ),
            ),
        )


def test_release_json_rejects_external_decision_mismatches_and_retains_adoption_decision() -> None:
    release = PlanRelease(
        release_id="release-01",
        profile_id="dft-lcwip-2017",
        profile_fingerprint="a" * 64,
    )
    gate = TransitionGate(authority_name="Named officer", rationale="Recorded transition.")
    non_adopted = transition_release(release, LifecycleState.EVIDENCE_INCOMPLETE, gate=gate)
    decision = ExternalDecisionRecord.model_validate(external_decision_payload())
    non_adopted_payload = non_adopted.model_dump(mode="json") | {
        "external_decision": decision.model_dump(mode="json")
    }

    with pytest.raises(ValueError, match="external decision record"):
        PlanRelease.model_validate_json(json.dumps(non_adopted_payload))

    candidate = transition_release(
        transition_release(non_adopted, LifecycleState.ANALYSIS_DRAFT, gate=gate),
        LifecycleState.ADOPTION_CANDIDATE,
        gate=gate,
    )
    adopted = transition_release(
        candidate,
        LifecycleState.ADOPTED,
        gate=gate,
        external_decision=decision,
    )
    superseded = transition_release(adopted, LifecycleState.SUPERSEDED, gate=gate)
    missing_decision_payload = superseded.model_dump(mode="json") | {"external_decision": None}

    with pytest.raises(ValueError, match="external decision record"):
        PlanRelease.model_validate_json(json.dumps(missing_decision_payload))

    restored = PlanRelease.model_validate_json(superseded.model_dump_json())
    assert restored.lifecycle_state is LifecycleState.SUPERSEDED
    assert restored.external_decision == decision


def test_waiver_needs_a_named_human_authority_and_satn_boundary_never_copies_geometry() -> None:
    with pytest.raises(ValueError, match="named human authority"):
        RequirementAssessment(
            requirement_id="dft-2017.scope-governance",
            status=RequirementStatus.WAIVED,
            rationale="Waived without accountable authority.",
        )

    waived = RequirementAssessment(
        requirement_id="dft-2017.scope-governance",
        status=RequirementStatus.WAIVED,
        rationale="A documented local exception applies.",
        waiver=Waiver(authority_name="Director of transport", rationale="Local exception."),
    )
    satn = PublishedArtifactReference(
        run_id="run-2026-07-24",
        artifact_key="geojson",
        uri="https://example.test/satn/network.geojson",
        sha256="a" * 64,
    )

    assert waived.waiver.authority_name == "Director of transport"
    assert SatnArtifactReference is PublishedArtifactReference
    assert "geometry" not in PublishedArtifactReference.model_json_schema()["properties"]
    assert satn.public_identifier == "run-2026-07-24:geojson"


def test_plan_accepts_geometry_free_satn_feature_audit_subject_and_rejects_collisions() -> None:
    feature = PublishedNetworkFeatureReference(
        run_id="run-2026-07-24",
        artifact_key="geojson",
        feature_id="edge-1",
        feature_type="spine-access-connection",
        network_role="spine-access-connection",
        source_artifact_uri="https://example.test/satn/network.geojson",
        source_artifact_sha256="a" * 64,
    )
    plan = Plan(
        plan_id="feature-plan",
        name="Feature plan",
        study_area=StudyArea(
            area_id="area",
            name="Area",
            boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
        ),
        horizon=PlanHorizon(start_year=2026, end_year=2027),
        satn_features=(feature,),
        audit_findings=(
            AuditFinding(
                finding_id="feature-audit",
                subject_id="edge-1",
                status=AuditFindingStatus.UNKNOWN,
            ),
        ),
    )
    assert plan.audit_findings[0].subject_id == feature.feature_id
    assert "geometry" not in PublishedNetworkFeatureReference.model_json_schema()["properties"]

    with pytest.raises(ValueError, match="SATN feature public identifiers"):
        Plan(
            plan_id="duplicate-feature-plan",
            name="Duplicate feature plan",
            study_area=plan.study_area,
            horizon=plan.horizon,
            satn_features=(feature, feature.model_copy(update={"feature_type": "different"})),
        )


def test_roleless_satn_feature_reference_round_trips_through_plan() -> None:
    feature = PublishedNetworkFeatureReference(
        run_id="run-2026-07-24",
        artifact_key="geojson",
        feature_id="a-road-fixture",
        feature_type="a-road-spine",
        source_artifact_uri="https://example.test/satn/network.geojson",
        source_artifact_sha256="a" * 64,
    )
    plan = Plan(
        plan_id="roleless-feature-plan",
        name="Roleless feature plan",
        study_area=StudyArea(
            area_id="area",
            name="Area",
            boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
        ),
        horizon=PlanHorizon(start_year=2026, end_year=2027),
        satn_features=(feature,),
        audit_findings=(
            AuditFinding(
                finding_id="a-road-audit",
                subject_id=feature.feature_id,
                status=AuditFindingStatus.UNKNOWN,
            ),
        ),
    )

    restored = Plan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert restored.satn_features[0].network_role is None


def test_packaged_dft_profile_round_trips_against_the_versioned_schema_and_cli() -> None:
    root = Path(__file__).parents[1]
    schema = json.loads((root / "src/lcwip/profiles/guidance-profile-1.0.schema.json").read_text())
    profile_path = root / "src/lcwip/profiles/dft-lcwip-2017.json"
    profile = GuidanceProfile.model_validate_json(profile_path.read_text())

    assert schema["$id"].endswith("guidance-profile-1.0.schema.json")
    assert profile.profile_id == "dft-lcwip-2017"
    assert {requirement.obligation for requirement in profile.requirements} >= {
        Obligation.MANDATORY
    }
    response = CliRunner().invoke(app, ["profile", "validate", str(profile_path)])
    assert response.exit_code == 0
    assert profile.fingerprint in response.stdout


def test_minimal_plan_round_trips_all_public_lcwip_records_without_geometry() -> None:
    boundary = ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area")
    baseline = ArtifactLink(artifact_id="baseline", uri="bundle://baseline", kind="baseline")
    local_plan = ArtifactLink(artifact_id="ltp", uri="bundle://ltp", kind="policy")
    plan = Plan(
        plan_id="banes-lcwip",
        name="B&NES LCWIP preparation",
        study_area=StudyArea(area_id="banes", name="B&NES", boundary=boundary),
        horizon=PlanHorizon(start_year=2027, end_year=2037),
        objectives=(Objective(objective_id="safe-travel", statement="Make active travel safer."),),
        targets=(
            Target(
                target_id="walking",
                objective_id="safe-travel",
                measure="walking trips",
                value=10,
                unit="percent",
            ),
        ),
        governance_directives=(
            GovernanceDirective(
                directive_id="board",
                authority_name="Plan board",
                directive="Review releases.",
            ),
        ),
        evidence_items=(EvidenceItem(evidence_id="baseline", item=baseline),),
        evidence_requests=(
            EvidenceRequest(request_id="traffic", purpose="Obtain traffic counts."),
        ),
        cycling_desire_lines=(
            CyclingDesireLine(desire_line_id="cycle-1", origin_id="a", destination_id="b"),
        ),
        walking_zones=(WalkingZone(zone_id="zone-1", name="Town centre"),),
        walking_routes=(WalkingRoute(route_id="walk-1", zone_id="zone-1", name="High street"),),
        audit_findings=(
            AuditFinding(
                finding_id="audit-1",
                subject_id="walk-1",
                status=AuditFindingStatus.UNKNOWN,
            ),
        ),
        deficiencies=(
            Deficiency(
                deficiency_id="deficiency-1",
                finding_id="audit-1",
                description="Crossing needs audit.",
            ),
        ),
        interventions=(
            Intervention(
                intervention_id="intervention-1",
                deficiency_ids=("deficiency-1",),
                description="Crossing improvement option.",
            ),
        ),
        programme_scenarios=(ProgrammeScenario(scenario_id="base", name="Base programme"),),
        programme_entries=(
            ProgrammeEntry(
                entry_id="entry-1",
                scenario_id="base",
                intervention_ids=("intervention-1",),
                phase="short",
            ),
        ),
        representations=(Representation(representation_id="representation-1", source="Resident"),),
        dispositions=(
            Disposition(
                disposition_id="disposition-1",
                representation_id="representation-1",
                decision="open",
                rationale="Awaiting review.",
            ),
        ),
        equality_findings=(
            EqualityFinding(
                equality_finding_id="equality-1",
                topic="accessibility",
                status=EqualityFindingStatus.UNKNOWN,
            ),
        ),
        policy_links=(
            PolicyLink(
                policy_link_id="policy-1",
                policy=local_plan,
                outcome="Supports active travel.",
            ),
        ),
        monitoring_indicators=(
            MonitoringIndicator(indicator_id="monitor-1", measure="walking trips", unit="percent"),
        ),
    )

    restored = Plan.model_validate_json(plan.model_dump_json())
    assert restored.programme_entries[0].intervention_ids == ("intervention-1",)
    assert "geometry" not in Plan.model_json_schema()["properties"]


def test_plan_rejects_cross_collection_ids_that_ambiguate_audit_subjects() -> None:
    with pytest.raises(ValueError, match="globally unique"):
        Plan(
            plan_id="test-plan",
            name="Test plan",
            study_area=StudyArea(
                area_id="area",
                name="Area",
                boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
            ),
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            objectives=(Objective(objective_id="shared", statement="Improve walking."),),
            targets=(
                Target(
                    target_id="shared",
                    objective_id="shared",
                    measure="walking trips",
                    value=10,
                    unit="percent",
                ),
            ),
            audit_findings=(
                AuditFinding(
                    finding_id="audit-1",
                    subject_id="shared",
                    status=AuditFindingStatus.UNKNOWN,
                ),
            ),
        )


def test_versioned_fixtures_cover_conformance_and_historical_profile_immutability() -> None:
    root = Path(__file__).parents[1]
    profile = GuidanceProfile.model_validate_json(
        (root / "src/lcwip/profiles/dft-lcwip-2017.json").read_text()
    )
    fixtures = root / "tests/fixtures/lcwip"
    complete = json.loads((fixtures / "complete.json").read_text())
    incomplete = json.loads((fixtures / "incomplete.json").read_text())
    not_applicable = json.loads((fixtures / "not-applicable.json").read_text())
    superseded = json.loads((fixtures / "superseded-guidance.json").read_text())

    complete_assessments = [
        RequirementAssessment.model_validate(item) for item in complete["assessments"]
    ]
    incomplete_assessments = [
        RequirementAssessment.model_validate(item) for item in incomplete["assessments"]
    ]
    inapplicable_assessments = [
        RequirementAssessment.model_validate(item) for item in not_applicable["assessments"]
    ]
    assert (
        evaluate_conformance(profile, complete_assessments).unresolved_mandatory_requirement_ids
        == ()
    )
    assert evaluate_conformance(
        profile, incomplete_assessments
    ).unresolved_mandatory_requirement_ids == (
        "dft-2017.cycling-network-planning",
        "dft-2017.information-and-barriers",
        "dft-2017.policy-integration",
        "dft-2017.prioritisation",
        "dft-2017.walking-network-planning",
    )
    assert evaluate_conformance(
        profile, inapplicable_assessments
    ).unresolved_mandatory_requirement_ids == (
        "dft-2017.cycling-network-planning",
        "dft-2017.information-and-barriers",
        "dft-2017.policy-integration",
        "dft-2017.prioritisation",
        "dft-2017.scope-governance",
        "dft-2017.walking-network-planning",
    )

    release = PlanRelease.model_validate(superseded["release"])
    future_profile = profile.model_copy(update={"profile_id": "ate-lcwip-2027"})
    historical = evaluate_release_conformance(
        release,
        profiles=(profile, future_profile),
        assessments=complete_assessments,
    )
    assert release.lifecycle_state is LifecycleState.SUPERSEDED
    assert historical.profile_id == "dft-lcwip-2017"

    attempted = json.loads((fixtures / "attempted-automatic-adoption.json").read_text())
    with pytest.raises(ValueError, match=r"verification|extra"):
        PlanRelease.model_validate(attempted["release"])


@pytest.mark.parametrize(
    "release",
    (
        PlanRelease.model_construct(
            release_id=" \t ",
            profile_id=" \t ",
            profile_fingerprint="",
        ),
        PlanRelease.model_construct(
            release_id="constructed-history",
            profile_id="test-profile",
            profile_fingerprint="a" * 64,
            lifecycle_state=LifecycleState.ANALYSIS_DRAFT,
            claims=("analysis_draft",),
            transition_history=(
                LifecycleTransition.model_construct(
                    from_state=LifecycleState.EXPLORATORY,
                    to_state=LifecycleState.ANALYSIS_DRAFT,
                    gate=TransitionGate.model_construct(
                        authority_name=" \t ", rationale="Recorded review."
                    ),
                ),
            ),
        ),
    ),
)
def test_release_conformance_revalidates_constructed_releases(
    release: PlanRelease,
) -> None:
    profile = GuidanceProfile(
        profile_id="test-profile",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.requirement",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("evidence",),
            ),
        ),
    )

    message = (
        "release_id|profile_id|profile_fingerprint"
        if release.profile_id == " \t "
        else "authority_name"
    )
    with pytest.raises(ValueError, match=message):
        evaluate_release_conformance(release, profiles=(profile,), assessments=())


def test_release_conformance_accepts_an_unchanged_valid_release() -> None:
    profile = GuidanceProfile(
        profile_id="test-profile",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.requirement",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("evidence",),
            ),
        ),
    )
    release = PlanRelease(
        release_id="valid-release",
        profile_id=profile.profile_id,
        profile_fingerprint=profile.fingerprint,
    )
    before = release.model_dump()

    result = evaluate_release_conformance(release, profiles=(profile,), assessments=())

    assert result.profile_id == profile.profile_id
    assert release.model_dump() == before


def test_conformance_rejects_ambiguous_assessments_and_is_order_independent() -> None:
    profile = GuidanceProfile(
        profile_id="test-profile",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.alpha",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("alpha",),
            ),
            Requirement(
                requirement_id="test.beta",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("beta",),
            ),
        ),
    )
    alpha = RequirementAssessment(
        requirement_id="test.alpha",
        status=RequirementStatus.SATISFIED,
        evidence=(ArtifactLink(artifact_id="alpha", uri="bundle://alpha", kind="alpha"),),
    )
    beta = RequirementAssessment(requirement_id="test.beta", status=RequirementStatus.FAILED)

    assert evaluate_conformance(profile, (alpha, beta)) == evaluate_conformance(
        profile, (beta, alpha)
    )
    with pytest.raises(ValueError, match="unknown requirement"):
        evaluate_conformance(
            profile,
            (
                RequirementAssessment(
                    requirement_id="test.not-in-profile", status=RequirementStatus.SATISFIED
                ),
            ),
        )
    with pytest.raises(ValueError, match="duplicate assessment"):
        evaluate_conformance(profile, (alpha, alpha))


def test_conformance_factory_derives_canonical_results_from_profile_and_assessments() -> None:
    profile = GuidanceProfile(
        profile_id="factory-test",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.alpha",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("alpha",),
            ),
            Requirement(
                requirement_id="test.beta",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("beta",),
            ),
        ),
    )
    alpha = RequirementAssessment(
        requirement_id="test.alpha",
        status=RequirementStatus.SATISFIED,
        evidence=(ArtifactLink(artifact_id="alpha", uri="bundle://alpha", kind="alpha"),),
    )
    beta = RequirementAssessment(requirement_id="test.beta", status=RequirementStatus.FAILED)

    missing = ConformanceResult.from_evaluation(profile, ())
    assert missing.unresolved_mandatory_requirement_ids == ("test.alpha", "test.beta")
    assert [assessment.status for assessment in missing.requirements] == [
        RequirementStatus.UNKNOWN,
        RequirementStatus.UNKNOWN,
    ]

    first = ConformanceResult.from_evaluation(profile, (alpha, beta))
    reversed_input = ConformanceResult.from_evaluation(profile, (beta, alpha))
    assert first.model_dump_json() == reversed_input.model_dump_json()
    assert first.conformance_fingerprint == reversed_input.conformance_fingerprint
    assert first == evaluate_conformance(profile, (alpha, beta))

    with pytest.raises(ValueError, match="expected artifact kinds"):
        ConformanceResult.from_evaluation(
            profile,
            (
                RequirementAssessment(
                    requirement_id="test.alpha", status=RequirementStatus.SATISFIED
                ),
            ),
        )
    with pytest.raises(ValueError, match="unknown requirement"):
        ConformanceResult.from_evaluation(
            profile,
            (
                RequirementAssessment(
                    requirement_id="test.unknown", status=RequirementStatus.FAILED
                ),
            ),
        )
    with pytest.raises(ValueError, match="duplicate assessment"):
        ConformanceResult.from_evaluation(profile, (alpha, alpha))


def test_conformance_canonicalizes_evidence_and_fingerprints_evaluated_assessments() -> None:
    profile = GuidanceProfile(
        profile_id="fingerprint-test",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.mandatory",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("alpha", "beta"),
            ),
        ),
    )
    alpha = ArtifactLink(artifact_id="alpha", uri="bundle://alpha", kind="alpha")
    beta = ArtifactLink(artifact_id="beta", uri="bundle://beta", kind="beta")
    revised_alpha = ArtifactLink(
        artifact_id="alpha-revised", uri="bundle://alpha-revised", kind="alpha"
    )
    first = evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.SATISFIED,
                evidence=(beta, alpha),
                rationale="Evidence checked.",
            ),
        ),
    )
    second = evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.SATISFIED,
                evidence=(alpha, beta),
                rationale="Evidence checked.",
            ),
        ),
    )

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.conformance_fingerprint == second.conformance_fingerprint
    assert first.requirements[0].evidence == (alpha, beta)
    assert first.conformance_fingerprint != evaluate_conformance(
        profile,
        (RequirementAssessment(requirement_id="test.mandatory", status=RequirementStatus.FAILED),),
    ).conformance_fingerprint
    assert first.conformance_fingerprint != evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.SATISFIED,
                evidence=(alpha, beta),
                rationale="Evidence rechecked.",
            ),
        ),
    ).conformance_fingerprint
    assert first.conformance_fingerprint != evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.SATISFIED,
                evidence=(revised_alpha, beta),
                rationale="Evidence checked.",
            ),
        ),
    ).conformance_fingerprint
    waived = evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.WAIVED,
                waiver=Waiver(authority_name="Named officer", rationale="Approved exception."),
            ),
        ),
    )
    assert first.conformance_fingerprint != waived.conformance_fingerprint
    assert waived.conformance_fingerprint != evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.WAIVED,
                waiver=Waiver(authority_name="Named officer", rationale="Exception renewed."),
            ),
        ),
    ).conformance_fingerprint

    payload = first.model_dump(mode="json")
    assert ConformanceResult.model_validate_json(first.model_dump_json()) == first
    del payload["conformance_fingerprint"]
    with pytest.raises(ValueError, match="conformance_fingerprint"):
        ConformanceResult.model_validate(payload)

    payload = first.model_dump(mode="json")
    del payload["conformance_fingerprint"]
    payload["requirements"][0]["status"] = RequirementStatus.FAILED
    payload["unresolved_mandatory_requirement_ids"] = ["test.mandatory"]
    with pytest.raises(ValueError, match="conformance_fingerprint"):
        ConformanceResult.model_validate(payload)

    payload = first.model_dump(mode="json")
    payload["conformance_fingerprint"] = "tampered"
    with pytest.raises(ValueError, match="conformance fingerprint"):
        ConformanceResult.model_validate(payload)


def test_conformance_rejects_self_checksummed_payloads_that_are_not_profile_bound() -> None:
    profile = GuidanceProfile(
        profile_id="semantic-binding",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.alpha",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("alpha",),
            ),
            Requirement(
                requirement_id="test.beta",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("beta",),
            ),
        ),
    )
    result = ConformanceResult.from_evaluation(profile, ())
    assert ConformanceResult.model_validate_json(result.model_dump_json()) == result

    def self_checksum(payload: dict[str, object]) -> dict[str, object]:
        unsigned = {
            key: value for key, value in payload.items() if key != "conformance_fingerprint"
        }
        payload["conformance_fingerprint"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return payload

    false_gap = result.model_dump(mode="json")
    false_gap["requirements"] = [
        {"requirement_id": "test.alpha", "status": "failed", "evidence": [], "rationale": ""},
        {"requirement_id": "test.beta", "status": "failed", "evidence": [], "rationale": ""},
    ]
    false_gap["unresolved_mandatory_requirement_ids"] = []
    with pytest.raises(ValueError, match="unresolved mandatory"):
        ConformanceResult.model_validate(self_checksum(false_gap))

    missing_evidence = result.model_dump(mode="json")
    missing_evidence["requirements"] = [
        {
            "requirement_id": "test.alpha",
            "status": "satisfied",
            "evidence": [],
            "rationale": "",
        },
        {"requirement_id": "test.beta", "status": "unknown", "evidence": [], "rationale": ""},
    ]
    missing_evidence["unresolved_mandatory_requirement_ids"] = ["test.beta"]
    with pytest.raises(ValueError, match="expected artifact kinds"):
        ConformanceResult.model_validate(self_checksum(missing_evidence))

    missing_assessments = result.model_dump(mode="json")
    missing_assessments["requirements"] = []
    missing_assessments["unresolved_mandatory_requirement_ids"] = []
    with pytest.raises(ValueError, match="profile requirement order"):
        ConformanceResult.model_validate(self_checksum(missing_assessments))

    out_of_order = result.model_dump(mode="json")
    out_of_order["requirements"] = list(reversed(out_of_order["requirements"]))
    with pytest.raises(ValueError, match="profile requirement order"):
        ConformanceResult.model_validate(self_checksum(out_of_order))

    false_profile_id = result.model_dump(mode="json")
    false_profile_id["profile_id"] = "other-profile"
    with pytest.raises(ValueError, match="profile_id"):
        ConformanceResult.model_validate(self_checksum(false_profile_id))

    revised_profile = result.model_dump(mode="json")
    revised_profile["profile"]["issuer"] = "Different issuer"
    with pytest.raises(ValueError, match="profile_fingerprint"):
        ConformanceResult.model_validate(self_checksum(revised_profile))


def test_conformance_checks_evidence_kinds_and_not_applicable_obligation() -> None:
    profile = GuidanceProfile(
        profile_id="evidence-test",
        issuer="Test issuer",
        document="Test document",
        version="1",
        effective_date=date(2026, 1, 1),
        applicability="Test scope",
        requirements=(
            Requirement(
                requirement_id="test.mandatory",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("baseline", "barriers"),
            ),
            Requirement(
                requirement_id="test.recommended",
                obligation=Obligation.RECOMMENDED,
                expected_artifacts=("engagement",),
            ),
        ),
    )

    with pytest.raises(ValueError, match="expected artifact kinds"):
        evaluate_conformance(
            profile,
            (
                RequirementAssessment(
                    requirement_id="test.mandatory",
                    status=RequirementStatus.SATISFIED,
                ),
            ),
        )
    with pytest.raises(ValueError, match="expected artifact kinds"):
        evaluate_conformance(
            profile,
            (
                RequirementAssessment(
                    requirement_id="test.mandatory",
                    status=RequirementStatus.SATISFIED,
                    evidence=(
                        ArtifactLink(artifact_id="base", uri="bundle://base", kind="baseline"),
                    ),
                ),
            ),
        )

    result = evaluate_conformance(
        profile,
        (
            RequirementAssessment(
                requirement_id="test.mandatory",
                status=RequirementStatus.NOT_APPLICABLE,
            ),
            RequirementAssessment(
                requirement_id="test.recommended",
                status=RequirementStatus.NOT_APPLICABLE,
            ),
        ),
    )
    assert result.unresolved_mandatory_requirement_ids == ("test.mandatory",)


def test_contract_models_are_closed_and_use_specific_finding_statuses() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        Requirement.model_validate(
            {
                "schema_version": "1.0",
                "requirement_id": "test.requirement",
                "obligation": "mandatory",
                "expected_artifacts": ["baseline"],
                "unexpected": True,
            }
        )
    with pytest.raises(ValueError, match=r"Input should be '1\.0'"):
        GuidanceProfile.model_validate(
            {
                "schema_version": "2.0",
                "profile_id": "test-profile",
                "issuer": "Test issuer",
                "document": "Test document",
                "version": "1",
                "effective_date": "2026-01-01",
                "applicability": "Test scope",
                "requirements": [],
            }
        )
    requirement = Requirement(
        requirement_id="test.requirement",
        obligation=Obligation.MANDATORY,
        expected_artifacts=("barriers", "baseline"),
    )
    assert requirement.expected_artifacts == ("barriers", "baseline")
    with pytest.raises(ValueError, match="unique"):
        Requirement(
            requirement_id="test.duplicate",
            obligation=Obligation.MANDATORY,
            expected_artifacts=("baseline", "baseline"),
        )
    with pytest.raises(ValueError):
        AuditFinding(finding_id="audit", subject_id="subject", status=RequirementStatus.UNKNOWN)
    with pytest.raises(ValueError):
        EqualityFinding(
            equality_finding_id="equality", topic="accessibility", status=RequirementStatus.FAILED
        )
    with pytest.raises(ValueError, match="geometry"):
        Plan.model_validate(
            {
                "plan_id": "geometry-plan",
                "name": "Geometry plan",
                "study_area": {
                    "area_id": "area",
                    "name": "Area",
                    "boundary": {
                        "artifact_id": "area",
                        "uri": "bundle://area",
                        "kind": "study-area",
                    },
                },
                "horizon": {"start_year": 2026, "end_year": 2027},
                "geometry": {"type": "Polygon"},
            }
        )


def test_non_exploratory_release_requires_a_contiguous_history() -> None:
    with pytest.raises(ValueError, match="transition history"):
        PlanRelease(
            release_id="direct-draft",
            profile_id="profile",
            profile_fingerprint="a" * 64,
            lifecycle_state=LifecycleState.ANALYSIS_DRAFT,
            claims=("analysis_draft",),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "objectives",
            (
                Objective(objective_id="same", statement="one"),
                Objective(objective_id="same", statement="two"),
            ),
            "objective IDs",
        ),
        (
            "walking_zones",
            (WalkingZone(zone_id="same", name="one"), WalkingZone(zone_id="same", name="two")),
            "walking zone IDs",
        ),
        (
            "satn_artifacts",
            (
                SatnArtifactReference(
                    run_id="run", artifact_key="network", uri="file:///one", sha256="a" * 64
                ),
                SatnArtifactReference(
                    run_id="run", artifact_key="network", uri="file:///two", sha256="b" * 64
                ),
            ),
            "SATN public identifiers",
        ),
    ],
)
def test_plan_rejects_duplicate_entity_and_satn_public_identifiers(
    field: str, value: tuple[object, ...], message: str
) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=message):
        Plan(
            plan_id="test-plan",
            name="Test plan",
            study_area=StudyArea(
                area_id="area",
                name="Area",
                boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
            ),
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            **kwargs,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "targets",
            (
                Target(
                    target_id="target",
                    objective_id="missing",
                    measure="trips",
                    value=1,
                    unit="percent",
                ),
            ),
            "objective_id",
        ),
        (
            "walking_routes",
            (WalkingRoute(route_id="route", zone_id="missing", name="Route"),),
            "zone_id",
        ),
        (
            "deficiencies",
            (Deficiency(deficiency_id="deficiency", finding_id="missing", description="Gap"),),
            "finding_id",
        ),
        (
            "interventions",
            (
                Intervention(
                    intervention_id="intervention", deficiency_ids=("missing",), description="Fix"
                ),
            ),
            "deficiency_ids",
        ),
        (
            "programme_entries",
            (
                ProgrammeEntry(
                    entry_id="entry",
                    scenario_id="missing",
                    intervention_ids=("missing",),
                    phase="short",
                ),
            ),
            "scenario_id",
        ),
        (
            "dispositions",
            (
                Disposition(
                    disposition_id="disposition",
                    representation_id="missing",
                    decision="open",
                    rationale="Review",
                ),
            ),
            "representation_id",
        ),
        (
            "audit_findings",
            (
                AuditFinding(
                    finding_id="audit", subject_id="missing", status=AuditFindingStatus.UNKNOWN
                ),
            ),
            "subject_id",
        ),
    ],
)
def test_plan_rejects_dangling_public_references(
    field: str, value: tuple[object, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Plan(
            plan_id="test-plan",
            name="Test plan",
            study_area=StudyArea(
                area_id="area",
                name="Area",
                boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
            ),
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            **{field: value},
        )


def test_audit_findings_cannot_self_reference_but_can_reference_plan_subjects() -> None:
    study_area = StudyArea(
        area_id="area",
        name="Area",
        boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
    )
    with pytest.raises(ValueError, match="subject_id"):
        Plan(
            plan_id="self-reference",
            name="Self reference",
            study_area=study_area,
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            audit_findings=(
                AuditFinding(
                    finding_id="finding",
                    subject_id="finding",
                    status=AuditFindingStatus.UNKNOWN,
                ),
            ),
        )

    plan = Plan(
        plan_id="area-audit",
        name="Area audit",
        study_area=study_area,
        horizon=PlanHorizon(start_year=2026, end_year=2027),
        objectives=(Objective(objective_id="objective", statement="Improve access"),),
        audit_findings=(
            AuditFinding(
                finding_id="area-finding",
                subject_id="area",
                status=AuditFindingStatus.UNKNOWN,
            ),
            AuditFinding(
                finding_id="objective-finding",
                subject_id="objective",
                status=AuditFindingStatus.UNKNOWN,
            ),
        ),
    )
    assert [finding.subject_id for finding in plan.audit_findings] == ["area", "objective"]


def test_audit_finding_ids_collide_with_satn_feature_ids_but_remain_non_subjects() -> None:
    feature = PublishedNetworkFeatureReference(
        run_id="run",
        artifact_key="geojson",
        feature_id="satn-feature",
        feature_type="connection",
        network_role="spine",
        source_artifact_uri="file:///network.geojson",
        source_artifact_sha256="a" * 64,
    )
    study_area = StudyArea(
        area_id="area",
        name="Area",
        boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
    )
    with pytest.raises(ValueError, match="globally unique"):
        Plan(
            plan_id="finding-feature-collision",
            name="Finding feature collision",
            study_area=study_area,
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            satn_features=(feature,),
            audit_findings=(
                AuditFinding(
                    finding_id="satn-feature",
                    subject_id="area",
                    status=AuditFindingStatus.UNKNOWN,
                ),
            ),
        )

    with pytest.raises(ValueError, match="subject_id"):
        Plan(
            plan_id="finding-subject",
            name="Finding subject",
            study_area=study_area,
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            audit_findings=(
                AuditFinding(
                    finding_id="finding",
                    subject_id="finding",
                    status=AuditFindingStatus.UNKNOWN,
                ),
            ),
        )


def test_plan_rejects_dangling_programme_interventions_after_resolving_the_scenario() -> None:
    with pytest.raises(ValueError, match="intervention_ids"):
        Plan(
            plan_id="test-plan",
            name="Test plan",
            study_area=StudyArea(
                area_id="area",
                name="Area",
                boundary=ArtifactLink(artifact_id="area", uri="bundle://area", kind="study-area"),
            ),
            horizon=PlanHorizon(start_year=2026, end_year=2027),
            programme_scenarios=(ProgrammeScenario(scenario_id="scenario", name="Scenario"),),
            programme_entries=(
                ProgrammeEntry(
                    entry_id="entry",
                    scenario_id="scenario",
                    intervention_ids=("missing",),
                    phase="short",
                ),
            ),
        )


def test_profile_cli_runs_schema_and_date_format_validation_before_pydantic(tmp_path: Path) -> None:
    profile = {
        "schema_version": "2.0",
        "profile_id": "test-profile",
        "issuer": "Test issuer",
        "document": "Test document",
        "version": "1",
        "effective_date": "not-a-date",
        "applicability": "Test scope",
        "requirements": [
            {
                "requirement_id": "test.requirement",
                "obligation": "mandatory",
                "expected_artifacts": ["baseline"],
                "unknown": True,
            }
        ],
        "unknown": True,
    }
    path = tmp_path / "invalid-profile.json"
    path.write_text(json.dumps(profile))
    response = CliRunner().invoke(app, ["profile", "validate", str(path)])
    assert response.exit_code != 0
    assert "schema validation failed" in response.output


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"schema_version": "2.0"}, "schema_version"),
        ({"unknown": True}, "Additional properties"),
        ({"effective_date": "not-a-date"}, "effective_date"),
        (
            {
                "requirements": [
                    {
                        "requirement_id": "test.requirement",
                        "obligation": "mandatory",
                        "expected_artifacts": ["baseline"],
                        "unknown": True,
                    }
                ]
            },
            "unknown",
        ),
    ],
)
def test_profile_cli_rejects_each_schema_level_violation(
    tmp_path: Path, change: dict[str, object], expected: str
) -> None:
    profile: dict[str, object] = {
        "schema_version": "1.0",
        "profile_id": "test-profile",
        "issuer": "Test issuer",
        "document": "Test document",
        "version": "1",
        "effective_date": "2026-01-01",
        "applicability": "Test scope",
        "requirements": [
            {
                "requirement_id": "test.requirement",
                "obligation": "mandatory",
                "expected_artifacts": ["baseline"],
            }
        ],
    }
    profile.update(change)
    path = tmp_path / "invalid-profile.json"
    path.write_text(json.dumps(profile))

    response = CliRunner().invoke(app, ["profile", "validate", str(path)])

    assert response.exit_code != 0
    assert "schema validation failed" in response.output
    assert expected in response.output
