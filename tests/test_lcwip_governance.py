from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.evidence import AccessLevel, PublicDisposition
from lcwip.governance import (
    AgentRepresentationSummary,
    AmendmentRecord,
    AuthorityRole,
    AuthorityRoleKind,
    EngagementActivity,
    EngagementStrategy,
    EqualityImpactFinding,
    EqualityImpactStatus,
    ExternalAdoptionRecord,
    GateKind,
    GovernanceConfig,
    GovernanceDirectiveRecord,
    GovernanceStructure,
    GovernanceTransition,
    HumanGate,
    HumanRecord,
    PolicyAlignment,
    PolicyReference,
    RepresentationDisposition,
    RepresentationRecord,
    StakeholderRecord,
    TimetableMilestone,
    build_governance_record,
    governance_release_fingerprint,
    validate_governance_bundle,
)
from lcwip.models import (
    GuidanceProfile,
    LifecycleState,
    Objective,
    Obligation,
    Requirement,
    Target,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def profile() -> GuidanceProfile:
    return GuidanceProfile(
        profile_id="active-travel-england-lcwip",
        issuer="Active Travel England",
        document="LCWIP guidance",
        version="2026.1",
        effective_date=date(2026, 1, 1),
        applicability="B&NES plan preparation",
        requirements=(
            Requirement(
                requirement_id="governance",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("governance-record",),
                description="Human-governed LCWIP preparation.",
            ),
        ),
    )


def structure() -> GovernanceStructure:
    kinds = tuple(AuthorityRoleKind)
    roles = tuple(
        AuthorityRole(
            role_id=f"role-{kind.value}",
            person_name=f"Officer {index}",
            organisation="Bath and North East Somerset Council",
            kind=kind,
            responsibilities=(f"Exercise {kind.value} accountability.",),
            conflict_of_interest="No conflict declared.",
        )
        for index, kind in enumerate(kinds, start=1)
    )
    return GovernanceStructure(
        plan_sponsor_role_id="role-sponsor",
        sro_role_id="role-sro",
        project_board_role_ids=("role-project-board",),
        roles=roles,
    )


def role_id(kind: AuthorityRoleKind) -> str:
    return f"role-{kind.value}"


def human(
    record_id: str,
    kind: AuthorityRoleKind,
    recorded_on: date = date(2026, 4, 1),
) -> HumanRecord:
    return HumanRecord(
        record_id=record_id,
        authority_role_id=role_id(kind),
        recorded_on=recorded_on,
        rationale="An accountable officer reviewed the cited record.",
        evidence_uri=f"https://example.test/human-records/{record_id}",
    )


def gate(kind: GateKind, decided_on: date) -> HumanGate:
    role_kind = {
        GateKind.SCOPE: AuthorityRoleKind.SCOPE_AUTHORITY,
        GateKind.EVIDENCE_LIMITATIONS: AuthorityRoleKind.EVIDENCE_AUTHORITY,
        GateKind.PRIORITISATION_RULES: AuthorityRoleKind.PRIORITISATION_AUTHORITY,
        GateKind.CONSULTATION_RELEASE: AuthorityRoleKind.CONSULTATION_AUTHORITY,
        GateKind.REPRESENTATION_DISPOSITION: (
            AuthorityRoleKind.REPRESENTATION_AUTHORITY
        ),
        GateKind.EQUALITY_DISPOSITION: AuthorityRoleKind.EQUALITY_AUTHORITY,
        GateKind.ADOPTION_CANDIDATE: (
            AuthorityRoleKind.ADOPTION_CANDIDATE_AUTHORITY
        ),
        GateKind.EXTERNAL_ADOPTION: (
            AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY
        ),
        GateKind.SUPERSESSION: AuthorityRoleKind.SUPERSESSION_AUTHORITY,
    }[kind]
    return HumanGate(
        gate_id=f"gate-{kind.value}",
        kind=kind,
        authority_role_id=role_id(role_kind),
        decided_on=decided_on,
        rationale=f"Human authority approved the {kind.value} gate.",
        evidence_uri=f"https://example.test/gates/{kind.value}",
    )


def transitions(
    lifecycle_state: LifecycleState = LifecycleState.CONSULTATION_DRAFT,
) -> tuple[GovernanceTransition, ...]:
    result = [
        GovernanceTransition(
            from_state=LifecycleState.EXPLORATORY,
            to_state=LifecycleState.ANALYSIS_DRAFT,
            gates=(
                gate(GateKind.SCOPE, date(2026, 2, 1)),
                gate(GateKind.EVIDENCE_LIMITATIONS, date(2026, 2, 1)),
                gate(GateKind.PRIORITISATION_RULES, date(2026, 2, 1)),
            ),
        )
    ]
    if lifecycle_state in {
        LifecycleState.CONSULTATION_DRAFT,
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    }:
        result.append(
            GovernanceTransition(
                from_state=LifecycleState.ANALYSIS_DRAFT,
                to_state=LifecycleState.CONSULTATION_DRAFT,
                gates=(
                    gate(GateKind.CONSULTATION_RELEASE, date(2026, 5, 1)),
                    gate(GateKind.REPRESENTATION_DISPOSITION, date(2026, 5, 1)),
                    gate(GateKind.EQUALITY_DISPOSITION, date(2026, 5, 1)),
                ),
            )
        )
    if lifecycle_state in {
        LifecycleState.ADOPTION_CANDIDATE,
        LifecycleState.ADOPTED,
    }:
        result.append(
            GovernanceTransition(
                from_state=LifecycleState.CONSULTATION_DRAFT,
                to_state=LifecycleState.ADOPTION_CANDIDATE,
                gates=(gate(GateKind.ADOPTION_CANDIDATE, date(2026, 6, 1)),),
            )
        )
    if lifecycle_state is LifecycleState.ADOPTED:
        result.append(
            GovernanceTransition(
                from_state=LifecycleState.ADOPTION_CANDIDATE,
                to_state=LifecycleState.ADOPTED,
                gates=(gate(GateKind.EXTERNAL_ADOPTION, date(2026, 7, 1)),),
            )
        )
    return tuple(result)


def representations() -> tuple[RepresentationRecord, ...]:
    return (
        RepresentationRecord(
            representation_id="representation-public",
            source_reference_id="source-public",
            source_sha256=SHA_A,
            received_on=date(2026, 3, 1),
            access_level=AccessLevel.PUBLIC,
            public_disposition=PublicDisposition.INCLUDE,
            redacted_summary="Support for safer crossings.",
            personal_data="not-collected",
            themes=("crossings",),
            position="support",
        ),
        RepresentationRecord(
            representation_id="representation-controlled",
            source_reference_id="source-controlled",
            source_sha256=SHA_B,
            received_on=date(2026, 3, 2),
            access_level=AccessLevel.CONTROLLED,
            public_disposition=PublicDisposition.REDACTED,
            redacted_summary="Objection concerning the crossing location.",
            personal_data="removed",
            themes=("crossings",),
            position="object",
            contradicts_representation_ids=("representation-public",),
            lineage_note="A distinct respondent takes the opposite position.",
        ),
        RepresentationRecord(
            representation_id="representation-personal",
            source_reference_id="source-personal",
            source_sha256=SHA_C,
            received_on=date(2026, 3, 3),
            access_level=AccessLevel.PERSONAL,
            public_disposition=PublicDisposition.EXCLUDE,
            redacted_summary=None,
            personal_data="removed",
            themes=("accessibility",),
            position="mixed",
        ),
    )


def config(
    output_dir: Path,
    *,
    lifecycle_state: LifecycleState = LifecycleState.CONSULTATION_DRAFT,
    equality_status: EqualityImpactStatus = EqualityImpactStatus.MITIGATED,
) -> GovernanceConfig:
    guidance = profile()
    reps = representations()
    return GovernanceConfig(
        release_id="banes-lcwip-governance",
        release_version="1.0",
        guidance_profile=guidance,
        guidance_profile_id=guidance.profile_id,
        guidance_profile_fingerprint=guidance.fingerprint,
        output_dir=output_dir,
        structure=structure(),
        objectives=(
            Objective(
                objective_id="objective-access",
                statement="Improve everyday access by walking, wheeling and cycling.",
            ),
        ),
        targets=(
            Target(
                target_id="target-access",
                objective_id="objective-access",
                measure="Percentage of residents within reach of safe routes.",
                value=90,
                unit="percent",
            ),
        ),
        timetable=(
            TimetableMilestone(
                milestone_id="milestone-consultation",
                name="Public consultation",
                target_date=date(2026, 5, 1),
                accountable_role_id=role_id(AuthorityRoleKind.SRO),
            ),
        ),
        directives=(
            GovernanceDirectiveRecord(
                directive_id="directive-scope",
                authority_role_id=role_id(AuthorityRoleKind.SPONSOR),
                issued_on=date(2026, 1, 15),
                directive="Prepare a district-wide LCWIP with named human gates.",
                evidence_uri="https://example.test/directives/scope",
            ),
        ),
        stakeholders=(
            StakeholderRecord(
                stakeholder_id="stakeholder-disabled-people",
                group_name="Disabled residents",
                relationship="Affected users and accessibility experts.",
                contact_access="controlled",
                accessibility_adjustments=(
                    "Easy-read material",
                    "Step-free meeting venue",
                ),
            ),
        ),
        engagement_strategy=EngagementStrategy(
            strategy_id="strategy-public-engagement",
            purpose="Test and improve the draft LCWIP.",
            lawful_basis="Public task.",
            privacy_notice_uri="https://example.test/privacy/lcwip",
            stakeholder_ids=("stakeholder-disabled-people",),
            planned_methods=("Accessible workshops", "Online representations"),
            representativeness_limits=(
                "Participation was self-selecting and is not a population sample.",
            ),
            groups_not_reached=("Residents without digital or workshop access",),
        ),
        activities=(
            EngagementActivity(
                activity_id="activity-workshop",
                strategy_id="strategy-public-engagement",
                activity_type="Accessible workshop",
                occurred_on=date(2026, 3, 1),
                stakeholder_ids=("stakeholder-disabled-people",),
                attendance_count=18,
                limitations=("Attendance was voluntary.",),
            ),
        ),
        representations=reps,
        summaries=(
            AgentRepresentationSummary(
                summary_id="summary-crossings",
                included_representation_ids=(
                    "representation-public",
                    "representation-controlled",
                ),
                summary="Responses disagree about the proposed crossing location.",
                classifications=("crossings", "contradictory-positions"),
                confidence=0.82,
                covered_count=2,
                available_count=2,
                methodology_version="classification-1.0",
                human_verification=human(
                    "human-summary",
                    AuthorityRoleKind.REPRESENTATION_AUTHORITY,
                ),
            ),
        ),
        dispositions=tuple(
            RepresentationDisposition(
                disposition_id=f"disposition-{item.representation_id}",
                representation_id=item.representation_id,
                decision="partially-accepted",
                rationale="The officer considered this source independently.",
                human_record=human(
                    f"human-{item.representation_id}",
                    AuthorityRoleKind.REPRESENTATION_AUTHORITY,
                ),
            )
            for item in reps
        ),
        equality_findings=(
            EqualityImpactFinding(
                finding_id="equality-visual-impairment",
                affected_users=("Blind and partially sighted people",),
                evidence_references=("https://example.test/equality/evidence",),
                impact="Uncontrolled crossings may create an access barrier.",
                mitigations=("Retain controlled crossings at priority locations.",)
                if equality_status is EqualityImpactStatus.MITIGATED
                else (),
                owner_role_id=role_id(AuthorityRoleKind.EQUALITY_AUTHORITY),
                status=equality_status,
                eqia_process_uri="https://example.test/equality/eqia",
                officer_record=human(
                    "human-equality",
                    AuthorityRoleKind.EQUALITY_AUTHORITY,
                ),
            ),
        ),
        policy_references=(
            PolicyReference(
                policy_reference_id="policy-ltp-access",
                title="Local Transport Plan",
                source_uri="https://example.test/policy/ltp",
                source_sha256=SHA_A,
                clause_pointer="Policy 4.2",
                clause_excerpt="Improve inclusive access to everyday destinations.",
            ),
        ),
        policy_alignments=(
            PolicyAlignment(
                alignment_id="alignment-access",
                policy_reference_id="policy-ltp-access",
                subject_kind="objective",
                subject_id="objective-access",
                alignment_claim="The objective advances the cited accessibility clause.",
                basis="officer-judgement",
                subject_evidence_uri="https://example.test/lcwip/objective-access",
                subject_evidence_sha256=SHA_B,
                officer_record=human(
                    "human-policy",
                    AuthorityRoleKind.SRO,
                ),
            ),
            PolicyAlignment(
                alignment_id="alignment-network",
                policy_reference_id="policy-ltp-access",
                subject_kind="network",
                subject_id="network-strategic-active-travel",
                alignment_claim="The governed network supports the cited access policy.",
                basis="clause-evidence",
                subject_evidence_uri="https://example.test/lcwip/network",
                subject_evidence_sha256=SHA_C,
                officer_record=human(
                    "human-policy-network",
                    AuthorityRoleKind.SRO,
                ),
            ),
            PolicyAlignment(
                alignment_id="alignment-intervention",
                policy_reference_id="policy-ltp-access",
                subject_kind="intervention",
                subject_id="intervention-controlled-crossing",
                alignment_claim="The intervention supports inclusive network access.",
                basis="officer-judgement",
                subject_evidence_uri="https://example.test/lcwip/intervention",
                subject_evidence_sha256="e" * 64,
                officer_record=human(
                    "human-policy-intervention",
                    AuthorityRoleKind.SRO,
                ),
            ),
        ),
        transitions=transitions(lifecycle_state),
    )


def test_builds_traceable_privacy_safe_consultation_bundle(tmp_path: Path) -> None:
    bundle = build_governance_record(config(tmp_path))
    manifest = validate_governance_bundle(bundle)

    assert manifest.lifecycle_state is LifecycleState.CONSULTATION_DRAFT
    assert manifest.guidance_profile.fingerprint == manifest.guidance_profile_fingerprint
    assert "Silence is not support" in manifest.participation_statement
    assert "not a population sample" in manifest.participation_statement
    assert manifest.policy_references[0].clause_pointer == "Policy 4.2"
    assert manifest.policy_alignments[0].basis == "officer-judgement"

    public = json.loads((bundle / "engagement-record.json").read_text())
    public_ids = {
        item["representation_id"] for item in public["representations"]
    }
    assert public_ids == {
        "representation-public",
        "representation-controlled",
    }
    assert "representation-personal" not in json.dumps(public)
    assert public["representations"][1]["redacted_summary"].startswith("Objection")
    assert public["summaries"][0]["confidence"] == 0.82
    assert public["summaries"][0]["covered_count"] == 2


def test_named_human_gates_cannot_be_omitted_or_bypassed(tmp_path: Path) -> None:
    baseline = config(tmp_path)
    first = baseline.transitions[0].model_copy(
        update={"gates": baseline.transitions[0].gates[:-1]}
    )
    with pytest.raises(ValueError, match="named human gates"):
        build_governance_record(
            baseline.model_copy(update={"transitions": (first,)})
        )

    bypass = GovernanceTransition(
        from_state=LifecycleState.ANALYSIS_DRAFT,
        to_state=LifecycleState.ADOPTION_CANDIDATE,
        gates=(gate(GateKind.ADOPTION_CANDIDATE, date(2026, 6, 1)),),
    )
    with pytest.raises(ValueError, match="cannot bypass consultation"):
        build_governance_record(
            baseline.model_copy(
                update={"transitions": (baseline.transitions[0], bypass)}
            )
        )

    wrong_authority = baseline.transitions[1].gates[0].model_copy(
        update={"authority_role_id": role_id(AuthorityRoleKind.SRO)}
    )
    wrong_transition = baseline.transitions[1].model_copy(
        update={
            "gates": (
                wrong_authority,
                *baseline.transitions[1].gates[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="does not hold the required role"):
        build_governance_record(
            baseline.model_copy(
                update={
                    "transitions": (
                        baseline.transitions[0],
                        wrong_transition,
                    )
                }
            )
        )


def test_representation_duplicates_lineage_and_summary_coverage_are_governed(
    tmp_path: Path,
) -> None:
    baseline = config(tmp_path)
    assert baseline.representations[1].contradicts_representation_ids == (
        "representation-public",
    )

    duplicate = baseline.representations[1].model_copy(
        update={"source_sha256": SHA_A}
    )
    with pytest.raises(ValueError, match="duplicate representation"):
        build_governance_record(
            baseline.model_copy(
                update={
                    "representations": (
                        baseline.representations[0],
                        duplicate,
                        baseline.representations[2],
                    )
                }
            )
        )

    leaked = baseline.summaries[0].model_copy(
        update={
            "included_representation_ids": (
                "representation-public",
                "representation-controlled",
                "representation-personal",
            ),
            "covered_count": 3,
            "available_count": 3,
        }
    )
    with pytest.raises(ValueError, match="excluded personal representations"):
        build_governance_record(
            baseline.model_copy(update={"summaries": (leaked,)})
        )

    premature = baseline.dispositions[0].model_copy(
        update={
            "human_record": baseline.dispositions[0].human_record.model_copy(
                update={"recorded_on": date(2026, 2, 1)}
            )
        }
    )
    with pytest.raises(ValueError, match="cannot predate its source"):
        build_governance_record(
            baseline.model_copy(
                update={
                    "dispositions": (
                        premature,
                        *baseline.dispositions[1:],
                    )
                }
            )
        )


def test_privacy_contract_rejects_unredacted_controlled_source() -> None:
    with pytest.raises(ValidationError, match="privacy-safe redaction"):
        RepresentationRecord(
            representation_id="unsafe",
            source_reference_id="source-unsafe",
            source_sha256=SHA_A,
            received_on=date(2026, 3, 1),
            access_level=AccessLevel.CONTROLLED,
            public_disposition=PublicDisposition.REDACTED,
            redacted_summary=None,
            personal_data="removed",
            themes=("privacy",),
            position="neutral",
        )


def test_unresolved_equality_impact_blocks_consultation(tmp_path: Path) -> None:
    unresolved = config(
        tmp_path,
        equality_status=EqualityImpactStatus.ADVERSE_UNRESOLVED,
    )
    with pytest.raises(ValueError, match="blocked by unresolved equality"):
        build_governance_record(unresolved)


def test_consultation_policy_mapping_covers_all_governed_subjects(
    tmp_path: Path,
) -> None:
    baseline = config(tmp_path)
    with pytest.raises(ValueError, match="objectives, networks and interventions"):
        build_governance_record(
            baseline.model_copy(
                update={"policy_alignments": baseline.policy_alignments[:1]}
            )
        )


def test_adoption_requires_external_decision_exact_fingerprint_and_separation(
    tmp_path: Path,
) -> None:
    candidate = config(
        tmp_path / "candidate",
        lifecycle_state=LifecycleState.ADOPTION_CANDIDATE,
    )
    release_fingerprint = governance_release_fingerprint(candidate)
    adopted = candidate.model_copy(
        update={
            "output_dir": tmp_path / "adopted",
            "transitions": transitions(LifecycleState.ADOPTED),
            "external_adoption": ExternalAdoptionRecord(
                decision_identifier="cabinet-decision-2026-07",
                authority_name="B&NES Cabinet",
                decision_date=date(2026, 7, 1),
                decision_uri="https://example.test/decisions/cabinet-2026-07",
                release_fingerprint=release_fingerprint,
                decision_authority_role_id=role_id(
                    AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY
                ),
                verifier_role_id=role_id(AuthorityRoleKind.INDEPENDENT_VERIFIER),
                verification_date=date(2026, 7, 2),
                verification_evidence_uri=(
                    "https://example.test/verifications/cabinet-2026-07"
                ),
            ),
        }
    )
    manifest = validate_governance_bundle(build_governance_record(adopted))
    assert manifest.lifecycle_state is LifecycleState.ADOPTED
    assert manifest.external_adoption is not None
    assert manifest.external_adoption.decision_identifier == "cabinet-decision-2026-07"

    mismatched = adopted.model_copy(
        update={
            "output_dir": tmp_path / "bad-adoption",
            "external_adoption": adopted.external_adoption.model_copy(
                update={"release_fingerprint": "f" * 64}
            ),
        }
    )
    with pytest.raises(ValueError, match="release fingerprint mismatch"):
        build_governance_record(mismatched)

    verifier_role = adopted.structure.roles[
        tuple(AuthorityRoleKind).index(AuthorityRoleKind.INDEPENDENT_VERIFIER)
    ]
    decision_role = adopted.structure.roles[
        tuple(AuthorityRoleKind).index(
            AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY
        )
    ]
    conflicted_verifier = verifier_role.model_copy(
        update={"person_name": decision_role.person_name}
    )
    roles = tuple(
        conflicted_verifier
        if item.kind is AuthorityRoleKind.INDEPENDENT_VERIFIER
        else item
        for item in adopted.structure.roles
    )
    conflicted = adopted.model_copy(
        update={
            "output_dir": tmp_path / "conflicted",
            "structure": adopted.structure.model_copy(update={"roles": roles}),
        }
    )
    conflicted = conflicted.model_copy(
        update={
            "external_adoption": conflicted.external_adoption.model_copy(
                update={
                    "release_fingerprint": governance_release_fingerprint(conflicted)
                }
            )
        }
    )
    with pytest.raises(ValueError, match="different people"):
        build_governance_record(conflicted)

    with pytest.raises(ValidationError, match="separate evidence"):
        ExternalAdoptionRecord(
            decision_identifier="cabinet-decision-uri-alias",
            authority_name="B&NES Cabinet",
            decision_date=date(2026, 7, 1),
            decision_uri="https://example.test/records/decision",
            release_fingerprint=release_fingerprint,
            decision_authority_role_id=role_id(
                AuthorityRoleKind.EXTERNAL_ADOPTION_AUTHORITY
            ),
            verifier_role_id=role_id(AuthorityRoleKind.INDEPENDENT_VERIFIER),
            verification_date=date(2026, 7, 2),
            verification_evidence_uri=(
                "https://example.test/records/review/../decision"
            ),
        )


def test_amendments_are_chained_visible_and_immutable(tmp_path: Path) -> None:
    baseline = config(tmp_path)
    current = governance_release_fingerprint(baseline)
    amended = baseline.model_copy(
        update={
            "amendments": (
                AmendmentRecord(
                    amendment_id="amendment-after-consultation",
                    previous_release_fingerprint="d" * 64,
                    amended_release_fingerprint=current,
                    amended_on=date(2026, 5, 3),
                    author_role_id=role_id(AuthorityRoleKind.SRO),
                    rationale="Changed in response to a cited representation.",
                    trigger_record_ids=("representation-controlled",),
                ),
            ),
        }
    )
    bundle = build_governance_record(amended)
    decision_record = json.loads((bundle / "decision-provenance.json").read_text())
    assert decision_record["amendments"][0]["amendment_id"] == (
        "amendment-after-consultation"
    )

    changed_gate = amended.transitions[1].gates[0].model_copy(
        update={"rationale": "Changed human rationale after publication."}
    )
    changed_transition = amended.transitions[1].model_copy(
        update={"gates": (changed_gate, *amended.transitions[1].gates[1:])}
    )
    changed = amended.model_copy(
        update={
            "transitions": (
                amended.transitions[0],
                changed_transition,
            )
        }
    )
    with pytest.raises(ValueError, match="immutable and content changed"):
        build_governance_record(changed)


def test_bundle_tampering_and_cli_validation(tmp_path: Path) -> None:
    bundle = build_governance_record(config(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["governance", "validate", str(bundle)])
    assert result.exit_code == 0, result.output
    assert "valid banes-lcwip-governance" in result.output

    policy_path = bundle / "equality-and-policy.json"
    payload = json.loads(policy_path.read_text())
    payload["policy_alignments"][0]["alignment_claim"] = "Tampered"
    policy_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_governance_bundle(bundle)
