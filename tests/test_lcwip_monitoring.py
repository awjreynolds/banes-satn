from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.conformance import evaluate_conformance
from lcwip.models import (
    ArtifactLink,
    GuidanceProfile,
    LifecycleState,
    Obligation,
    Requirement,
    RequirementAssessment,
    RequirementStatus,
)
from lcwip.monitoring import (
    CompletionState,
    CompletionStatusUpdate,
    ConstructionState,
    ConstructionStatusUpdate,
    DeliveryMilestone,
    DesignState,
    DesignStatusUpdate,
    EvidenceImpactMapping,
    EvidenceSnapshotReference,
    FundingState,
    FundingStatusUpdate,
    HistoricalReleaseReference,
    IndicatorDefinition,
    IndicatorKind,
    IndicatorObservation,
    MonitoringConfig,
    MonitoringManifest,
    MonitoringSource,
    ObservationKind,
    OutcomeState,
    OutcomeStatusUpdate,
    ProgrammeDeliveryRecord,
    RequirementImpactMapping,
    ReviewTrigger,
    ReviewTriggerKind,
    ScopeDeviation,
    SupersedingReleaseProposal,
    TargetDirection,
    UpdateConfidence,
    VerificationState,
    _fingerprint,
    build_monitoring_release,
    validate_monitoring_release,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SCOPE_PLANNED = "1" * 64
SCOPE_DELIVERED = "2" * 64


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles() -> tuple[GuidanceProfile, GuidanceProfile]:
    old = GuidanceProfile(
        profile_id="ate-lcwip-2025",
        issuer="Active Travel England",
        document="LCWIP guidance",
        version="2025",
        effective_date=date(2025, 1, 1),
        applicability="Adopted release",
        requirements=(
            Requirement(
                requirement_id="network-plan",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("network-plan",),
                description="Publish the adopted network.",
            ),
        ),
    )
    new = GuidanceProfile(
        profile_id="ate-lcwip-2027",
        issuer="Active Travel England",
        document="LCWIP guidance",
        version="2027",
        effective_date=date(2027, 1, 1),
        applicability="Scheduled review",
        requirements=(
            Requirement(
                requirement_id="monitoring-plan",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("monitoring-plan",),
                description="Publish governed monitoring and review arrangements.",
            ),
            Requirement(
                requirement_id="network-plan",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("network-plan",),
                description="Reconfirm the network against current evidence.",
            ),
        ),
    )
    return old, new


def source(
    source_id: str,
    *,
    fingerprint: str,
    summary: str,
) -> MonitoringSource:
    return MonitoringSource(
        source_id=source_id,
        uri=f"https://example.test/monitoring/{source_id}",
        sha256=fingerprint,
        public_summary=summary,
        contains_personal_data=False,
    )


def fixture_config(
    tmp_path: Path,
    *,
    cycle_id: str = "monitoring-2027",
) -> MonitoringConfig:
    old_profile, new_profile = profiles()
    old_assessment = RequirementAssessment(
        requirement_id="network-plan",
        status=RequirementStatus.SATISFIED,
        evidence=(
            ArtifactLink(
                artifact_id="network-adopted",
                uri="https://example.test/releases/adopted/network.geojson",
                kind="network-plan",
            ),
        ),
        rationale="The adopted release contains the governed network.",
    )
    old_conformance = evaluate_conformance(old_profile, (old_assessment,))
    historical_manifest = tmp_path / "historical-publication-manifest.json"
    historical_manifest.write_text(
        json.dumps(
            {
                "release_id": "banes-lcwip-adopted-1",
                "release_fingerprint": SHA_A,
                "evidence_fingerprint": SHA_B,
                "configuration_fingerprint": SHA_C,
                "lifecycle_state": "adopted",
                "conformance": {
                    "profile_fingerprint": old_profile.fingerprint,
                    "conformance_fingerprint": old_conformance.conformance_fingerprint,
                },
            },
            sort_keys=True,
        )
    )
    historical = HistoricalReleaseReference(
        release_id="banes-lcwip-adopted-1",
        lifecycle_state=LifecycleState.ADOPTED,
        release_fingerprint=SHA_A,
        evidence_fingerprint=SHA_B,
        configuration_fingerprint=SHA_C,
        publication_manifest_path=historical_manifest,
        publication_manifest_sha256=file_sha(historical_manifest),
        guidance_profile=old_profile,
        conformance=old_conformance,
        source_fingerprints={
            "evidence-demand": "3" * 64,
            "evidence-network": "4" * 64,
        },
    )

    evidence_manifest = tmp_path / "evidence-snapshot-2027.json"
    evidence_manifest.write_text(
        json.dumps(
            {
                "snapshot_id": "evidence-2027",
                "snapshot_fingerprint": "5" * 64,
                "reference_date": "2027-02-01",
                "items": {
                    "evidence-demand": "6" * 64,
                    "evidence-network": "4" * 64,
                    "evidence-policy": "7" * 64,
                },
            },
            sort_keys=True,
        )
    )
    snapshot = EvidenceSnapshotReference(
        snapshot_id="evidence-2027",
        snapshot_fingerprint="5" * 64,
        reference_date=date(2027, 2, 1),
        manifest_path=evidence_manifest,
        manifest_sha256=file_sha(evidence_manifest),
        item_fingerprints={
            "evidence-demand": "6" * 64,
            "evidence-network": "4" * 64,
            "evidence-policy": "7" * 64,
        },
    )
    sources = (
        source(
            "source-delivery",
            fingerprint="8" * 64,
            summary="Public project-board delivery status.",
        ),
        source(
            "source-indicator",
            fingerprint="9" * 64,
            summary="Published count monitoring dataset.",
        ),
        source(
            "source-review",
            fingerprint="d" * 64,
            summary="Scheduled review decision record.",
        ),
    )
    updates = (
        DesignStatusUpdate(
            update_id="update-design-concept",
            state=DesignState.CONCEPT,
            source_id="source-delivery",
            observer_authority="LCWIP programme manager",
            observed_on=date(2026, 9, 1),
            recorded_on=date(2026, 9, 2),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        ),
        FundingStatusUpdate(
            update_id="update-funding-bid",
            state=FundingState.BID_SUBMITTED,
            source_id="source-delivery",
            observer_authority="Council finance business partner",
            observed_on=date(2026, 10, 1),
            recorded_on=date(2026, 10, 2),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        ),
        ConstructionStatusUpdate(
            update_id="update-construction-reported",
            state=ConstructionState.UNDERWAY,
            source_id="source-delivery",
            observer_authority="Delivery partner",
            observed_on=date(2027, 1, 15),
            recorded_on=date(2027, 1, 16),
            confidence=UpdateConfidence.MEDIUM,
            verification=VerificationState.UNVERIFIED,
            scope_fingerprint=SCOPE_DELIVERED,
        ),
        CompletionStatusUpdate(
            update_id="update-completion-open",
            state=CompletionState.NOT_COMPLETE,
            source_id="source-delivery",
            observer_authority="LCWIP programme manager",
            observed_on=date(2027, 1, 20),
            recorded_on=date(2027, 1, 20),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        ),
        OutcomeStatusUpdate(
            update_id="update-outcome-due",
            state=OutcomeState.DATA_DUE,
            source_id="source-indicator",
            observer_authority="Transport monitoring officer",
            observed_on=date(2027, 2, 1),
            recorded_on=date(2027, 2, 1),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        ),
    )
    programme = ProgrammeDeliveryRecord(
        programme_entry_id="programme-crossing-1",
        intervention_id="intervention-crossing-1",
        responsible_owner="Sustainable Transport Programme Manager",
        planned_scope="Signal-controlled crossing and protected approaches.",
        planned_scope_fingerprint=SCOPE_PLANNED,
        milestones=(
            DeliveryMilestone(
                milestone_id="milestone-design",
                title="Detailed design complete",
                due_on=date(2026, 12, 1),
                completion_update_id=None,
                blocked_reason="Land agreement remains unresolved.",
                blocked_update_id="update-construction-reported",
            ),
        ),
        updates=updates,
        deviations=(
            ScopeDeviation(
                deviation_id="deviation-construction-scope",
                previous_scope_fingerprint=SCOPE_PLANNED,
                updated_scope_fingerprint=SCOPE_DELIVERED,
                rationale="Reported works cover only the eastern approach.",
                source_id="source-delivery",
                authority="LCWIP project board",
                recorded_on=date(2027, 1, 16),
                confidence=UpdateConfidence.MEDIUM,
                verification=VerificationState.UNVERIFIED,
            ),
        ),
    )
    observations = (
        IndicatorObservation(
            observation_id="observation-baseline",
            indicator_id="indicator-cycling-count",
            kind=ObservationKind.BASELINE,
            value=100.0,
            unit="daily-cycle-trips",
            period_start=date(2025, 9, 1),
            period_end=date(2025, 9, 30),
            due_on=date(2025, 10, 15),
            observed_on=date(2025, 10, 5),
            recorded_on=date(2025, 10, 6),
            source_id="source-indicator",
            observer_authority="Transport monitoring officer",
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            coverage="One complete neutral-month count period.",
            uncertainty="Weather-normalisation uncertainty remains.",
        ),
        IndicatorObservation(
            observation_id="observation-2027",
            indicator_id="indicator-cycling-count",
            kind=ObservationKind.MONITORING,
            value=108.0,
            unit="daily-cycle-trips",
            period_start=date(2027, 1, 1),
            period_end=date(2027, 1, 31),
            due_on=date(2027, 2, 10),
            observed_on=date(2027, 2, 5),
            recorded_on=date(2027, 2, 12),
            source_id="source-indicator",
            observer_authority="Transport monitoring officer",
            confidence=UpdateConfidence.MEDIUM,
            verification=VerificationState.UNVERIFIED,
            coverage="Twenty-eight valid days from the permanent counter.",
            uncertainty="Three days are missing and no causal inference is made.",
        ),
    )
    indicator = IndicatorDefinition(
        indicator_id="indicator-cycling-count",
        kind=IndicatorKind.OUTCOME,
        name="Observed cycling count",
        unit="daily-cycle-trips",
        methodology="Neutral-month daily mean at the governed counter.",
        baseline_observation_id="observation-baseline",
        target_value=130.0,
        target_direction=TargetDirection.AT_LEAST,
        target_date=date(2027, 12, 31),
        reporting_frequency_days=365,
        responsible_owner="Transport Monitoring Team",
    )
    trigger = ReviewTrigger(
        trigger_id="trigger-scheduled-2027",
        kind=ReviewTriggerKind.SCHEDULED_REVIEW,
        detected_on=date(2027, 2, 15),
        source_id="source-review",
        authority="LCWIP project board",
        rationale="The adopted review interval has elapsed.",
        affected_requirement_ids=("network-plan", "monitoring-plan"),
        affected_analysis_ids=("analysis-demand",),
        affected_programme_entry_ids=("programme-crossing-1",),
    )
    new_assessments = (
        RequirementAssessment(
            requirement_id="monitoring-plan",
            status=RequirementStatus.SATISFIED,
            evidence=(
                ArtifactLink(
                    artifact_id=cycle_id,
                    uri=f"https://example.test/monitoring/{cycle_id}",
                    kind="monitoring-plan",
                ),
            ),
            rationale="The governed monitoring release supplies the plan.",
        ),
        RequirementAssessment(
            requirement_id="network-plan",
            status=RequirementStatus.UNKNOWN,
            rationale="The changed evidence requires network reconfirmation.",
        ),
    )
    return MonitoringConfig(
        output_dir=tmp_path / "monitoring-releases",
        cycle_id=cycle_id,
        as_of=date(2027, 2, 15),
        historical_release=historical,
        evidence_snapshot=snapshot,
        sources=sources,
        programme=(programme,),
        indicators=(indicator,),
        observations=observations,
        review_triggers=(trigger,),
        current_guidance_profile=new_profile,
        current_requirement_assessments=new_assessments,
        requirement_impacts=(
            RequirementImpactMapping(
                requirement_id="monitoring-plan",
                analysis_ids=("analysis-monitoring",),
                programme_entry_ids=("programme-crossing-1",),
                action="Add the governed monitoring plan to the superseding release.",
            ),
            RequirementImpactMapping(
                requirement_id="network-plan",
                analysis_ids=("analysis-demand", "analysis-network"),
                programme_entry_ids=("programme-crossing-1",),
                action="Re-run network analysis against the refreshed demand evidence.",
            ),
        ),
        evidence_impacts=(
            EvidenceImpactMapping(
                evidence_id="evidence-demand",
                analysis_ids=("analysis-demand",),
                programme_entry_ids=("programme-crossing-1",),
                action="Re-run demand analysis before supersession.",
            ),
            EvidenceImpactMapping(
                evidence_id="evidence-policy",
                analysis_ids=("analysis-policy",),
                programme_entry_ids=("programme-crossing-1",),
                action="Assess the new policy evidence.",
            ),
        ),
        superseding_release=SupersedingReleaseProposal(
            release_id="banes-lcwip-review-2",
            predecessor_release_id="banes-lcwip-adopted-1",
            predecessor_release_fingerprint=SHA_A,
            evidence_snapshot_id="evidence-2027",
            evidence_snapshot_fingerprint="5" * 64,
            guidance_profile_fingerprint=new_profile.fingerprint,
            triggered_by=("trigger-scheduled-2027",),
            prepared_by="LCWIP programme manager",
            prepared_on=date(2027, 2, 15),
            lifecycle_state=LifecycleState.ANALYSIS_DRAFT,
        ),
    )


def test_complete_monitoring_cycle_builds_atomic_privacy_safe_release(
    tmp_path: Path,
) -> None:
    config = fixture_config(tmp_path)
    historical_before = file_sha(config.historical_release.publication_manifest_path)
    evidence_before = file_sha(config.evidence_snapshot.manifest_path)
    bundle = build_monitoring_release(config)
    manifest = validate_monitoring_release(bundle)

    assert manifest.cycle_id == "monitoring-2027"
    assert manifest.historical_release.release_fingerprint == SHA_A
    assert manifest.superseding_release.release_id == "banes-lcwip-review-2"
    assert manifest.superseding_release.lifecycle_state is LifecycleState.ANALYSIS_DRAFT
    assert file_sha(config.historical_release.publication_manifest_path) == historical_before
    assert file_sha(config.evidence_snapshot.manifest_path) == evidence_before
    assert {artifact.path for artifact in manifest.artifacts} == {
        "monitoring-status.json",
        "review-tasks.json",
        "migration-report.json",
        "release-comparison.json",
        "monitoring-dashboard.html",
    }

    status = json.loads((bundle / "monitoring-status.json").read_text())
    programme = status["programme"][0]
    assert programme["overdue_milestone_ids"] == ["milestone-design"]
    assert programme["blocked_milestone_ids"] == ["milestone-design"]
    assert programme["unverified_update_ids"] == [
        "update-construction-reported"
    ]
    assert programme["scope_deviation_ids"] == ["deviation-construction-scope"]
    assert programme["effective_status"]["funding"] == "bid-submitted"
    assert programme["effective_status"]["construction"] is None

    dashboard = (bundle / "monitoring-dashboard.html").read_text()
    assert '<html lang="en">' in dashboard
    assert 'href="#main-content"' in dashboard
    assert "<table" in dashboard
    assert dashboard.count('class="table-scroll"') == 5
    assert dashboard.count('tabindex="0"') == 5
    assert "Overdue" in dashboard
    assert "Unverified" in dashboard
    assert "No causal claim is made" in dashboard
    assert "contains_personal_data" not in dashboard

    result = CliRunner().invoke(app, ["monitoring", "validate", str(bundle)])
    assert result.exit_code == 0, result.output
    assert "valid monitoring-2027" in result.output


def test_status_dimensions_are_typed_and_do_not_imply_each_other() -> None:
    with pytest.raises(ValidationError):
        FundingStatusUpdate(
            update_id="bad-funding",
            state=DesignState.CONCEPT,
            source_id="source-delivery",
            observer_authority="Finance officer",
            observed_on=date(2027, 1, 1),
            recorded_on=date(2027, 1, 1),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        )

    update = FundingStatusUpdate(
        update_id="funding-secured",
        state=FundingState.SECURED,
        source_id="source-delivery",
        observer_authority="Finance officer",
        observed_on=date(2027, 1, 1),
        recorded_on=date(2027, 1, 1),
        confidence=UpdateConfidence.HIGH,
        verification=VerificationState.VERIFIED,
        scope_fingerprint=SCOPE_PLANNED,
    )
    assert update.state is FundingState.SECURED
    assert not hasattr(update, "construction_state")


def test_update_chronology_regression_and_verified_completion_fail_closed(
    tmp_path: Path,
) -> None:
    config = fixture_config(tmp_path)
    programme = config.programme[0]
    regression = DesignStatusUpdate(
        update_id="update-design-regression",
        state=DesignState.NOT_STARTED,
        source_id="source-delivery",
        observer_authority="LCWIP programme manager",
        observed_on=date(2027, 1, 1),
        recorded_on=date(2027, 1, 1),
        confidence=UpdateConfidence.HIGH,
        verification=VerificationState.VERIFIED,
        scope_fingerprint=SCOPE_PLANNED,
    )
    with pytest.raises(ValidationError, match="regress"):
        ProgrammeDeliveryRecord.model_validate(
            programme.model_dump() | {"updates": [*programme.updates, regression]}
        )

    verified_complete = CompletionStatusUpdate(
        update_id="update-completion-verified",
        state=CompletionState.VERIFIED_COMPLETE,
        source_id="source-delivery",
        observer_authority="Council contract manager",
        observed_on=date(2027, 2, 1),
        recorded_on=date(2027, 2, 2),
        confidence=UpdateConfidence.HIGH,
        verification=VerificationState.VERIFIED,
        scope_fingerprint=SCOPE_PLANNED,
    )
    with pytest.raises(ValidationError, match="construction complete"):
        ProgrammeDeliveryRecord.model_validate(
            programme.model_dump() | {
                "updates": [*programme.updates, verified_complete]
            }
        )

    with pytest.raises(ValidationError, match="cannot predate"):
        DesignStatusUpdate(
            update_id="bad-chronology",
            state=DesignState.CONCEPT,
            source_id="source-delivery",
            observer_authority="LCWIP programme manager",
            observed_on=date(2027, 2, 2),
            recorded_on=date(2027, 2, 1),
            confidence=UpdateConfidence.HIGH,
            verification=VerificationState.VERIFIED,
            scope_fingerprint=SCOPE_PLANNED,
        )


def test_scope_change_requires_a_matching_governed_deviation(tmp_path: Path) -> None:
    config = fixture_config(tmp_path)
    programme = config.programme[0]
    with pytest.raises(ValidationError, match="scope deviation"):
        ProgrammeDeliveryRecord.model_validate(
            programme.model_dump() | {"deviations": []}
        )
    premature_verified_update = programme.updates[2].model_copy(
        update={"verification": VerificationState.VERIFIED}
    )
    verified_deviation = programme.deviations[0].model_copy(
        update={"verification": VerificationState.VERIFIED}
    )
    with pytest.raises(ValidationError, match="prior verified scope deviation"):
        ProgrammeDeliveryRecord.model_validate(
            programme.model_dump()
            | {
                "updates": (
                    *programme.updates[:2],
                    premature_verified_update,
                    *programme.updates[3:],
                ),
                "deviations": (verified_deviation,),
            }
        )


def test_progress_cycle_needs_no_trigger_or_successor_and_unverified_reports_do_not_regress(
    tmp_path: Path,
) -> None:
    config = fixture_config(tmp_path, cycle_id="monitoring-progress-only")
    programme = config.programme[0]
    unverified_ahead = DesignStatusUpdate(
        update_id="update-design-reported-approved",
        state=DesignState.APPROVED,
        source_id="source-delivery",
        observer_authority="Delivery partner",
        observed_on=date(2026, 10, 1),
        recorded_on=date(2026, 10, 2),
        confidence=UpdateConfidence.LOW,
        verification=VerificationState.UNVERIFIED,
        scope_fingerprint=SCOPE_PLANNED,
    )
    verified_preliminary = DesignStatusUpdate(
        update_id="update-design-preliminary",
        state=DesignState.PRELIMINARY,
        source_id="source-delivery",
        observer_authority="LCWIP programme manager",
        observed_on=date(2026, 11, 1),
        recorded_on=date(2026, 11, 2),
        confidence=UpdateConfidence.HIGH,
        verification=VerificationState.VERIFIED,
        scope_fingerprint=SCOPE_PLANNED,
    )
    progress_programme = ProgrammeDeliveryRecord.model_validate(
        programme.model_dump()
        | {
            "updates": (
                *programme.updates,
                unverified_ahead,
                verified_preliminary,
            )
        }
    )
    progress = config.model_copy(
        update={
            "programme": (progress_programme,),
            "review_triggers": (),
            "superseding_release": None,
        }
    )

    bundle = build_monitoring_release(progress)
    manifest = validate_monitoring_release(bundle)

    assert manifest.review_tasks == ()
    assert manifest.superseding_release is None
    assert manifest.programme[0].effective_status.design is DesignState.PRELIMINARY
    assert "No superseding release proposal has been prepared." in (
        bundle / "monitoring-dashboard.html"
    ).read_text()


def test_monitoring_data_missing_late_and_contradictory_are_explicit(
    tmp_path: Path,
) -> None:
    config = fixture_config(tmp_path)
    bundle = build_monitoring_release(config)
    status = json.loads((bundle / "monitoring-status.json").read_text())
    indicator = status["indicators"][0]
    assert indicator["late_observation_ids"] == ["observation-2027"]
    assert indicator["unverified_observation_ids"] == ["observation-2027"]
    assert indicator["target_status"] == "unverified-data"

    missing = validate_monitoring_release(
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-missing",
                    "observations": (config.observations[0],),
                    "superseding_release": config.superseding_release.model_copy(
                        update={"release_id": "banes-lcwip-review-missing"}
                    ),
                }
            )
        )
    )
    assert missing.indicators[0].target_status.value == "missing-data"
    assert missing.indicators[0].next_observation_due_on == date(2026, 10, 15)

    observation = config.observations[-1]
    contradictory = observation.model_copy(
        update={
            "observation_id": "observation-2027-conflict",
            "value": 117.0,
            "verification": VerificationState.VERIFIED,
        }
    )
    with pytest.raises(ValueError, match="contradictory observation"):
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-contradiction",
                    "observations": (*config.observations, contradictory),
                }
            )
        )

    resolved = contradictory.model_copy(
        update={"contradicts_observation_id": "observation-2027"}
    )
    manifest = validate_monitoring_release(
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-contradiction-recorded",
                    "observations": (*config.observations, resolved),
                    "superseding_release": config.superseding_release.model_copy(
                        update={"release_id": "banes-lcwip-review-conflict"}
                    ),
                }
            )
        )
    )
    assert manifest.cycle_id == "monitoring-contradiction-recorded"

    invalid_link = contradictory.model_copy(
        update={"contradicts_observation_id": "observation-baseline"}
    )
    with pytest.raises(ValueError, match="same indicator, observation kind and period"):
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-invalid-contradiction-link",
                    "observations": (*config.observations, invalid_link),
                }
            )
        )


def test_future_dated_updates_cannot_enter_an_as_of_release(tmp_path: Path) -> None:
    config = fixture_config(tmp_path)
    future = config.programme[0].updates[0].model_copy(
        update={
            "update_id": "update-future",
            "observed_on": date(2027, 3, 1),
            "recorded_on": date(2027, 3, 1),
        }
    )
    programme = config.programme[0].model_copy(
        update={"updates": (*config.programme[0].updates, future)}
    )
    with pytest.raises(ValueError, match="postdate monitoring"):
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-future",
                    "programme": (programme,),
                    "superseding_release": config.superseding_release.model_copy(
                        update={"release_id": "banes-lcwip-review-future"}
                    ),
                }
            )
        )


def test_review_triggers_create_tasks_without_mutating_historical_state(
    tmp_path: Path,
) -> None:
    config = fixture_config(tmp_path)
    bundle = build_monitoring_release(config)
    tasks = json.loads((bundle / "review-tasks.json").read_text())["tasks"]
    assert tasks == [
        {
            "affected_analysis_ids": ["analysis-demand"],
            "affected_programme_entry_ids": ["programme-crossing-1"],
            "affected_requirement_ids": ["network-plan", "monitoring-plan"],
            "authority": "LCWIP project board",
            "created_on": "2027-02-15",
            "rationale": "The adopted review interval has elapsed.",
            "schema_version": "1.0",
            "source_id": "source-review",
            "state": "superseding-release-prepared",
            "task_id": "review-trigger-scheduled-2027",
            "trigger_id": "trigger-scheduled-2027",
            "trigger_kind": "scheduled-review",
        }
    ]
    assert (
        config.historical_release.lifecycle_state is LifecycleState.ADOPTED
    )


def test_guidance_and_evidence_migration_identifies_affected_work(
    tmp_path: Path,
) -> None:
    bundle = build_monitoring_release(fixture_config(tmp_path))
    migration = json.loads((bundle / "migration-report.json").read_text())
    by_requirement = {
        item["requirement_id"]: item for item in migration["guidance_changes"]
    }
    assert by_requirement["monitoring-plan"]["change"] == "added"
    assert by_requirement["network-plan"]["change"] == "changed"
    assert by_requirement["network-plan"]["analysis_ids"] == [
        "analysis-demand",
        "analysis-network",
    ]
    by_evidence = {
        item["evidence_id"]: item for item in migration["evidence_changes"]
    }
    assert by_evidence["evidence-demand"]["change"] == "changed"
    assert by_evidence["evidence-policy"]["change"] == "added"
    assert "evidence-network" not in by_evidence


def test_historical_seals_and_atomic_release_ids_are_immutable(tmp_path: Path) -> None:
    config = fixture_config(tmp_path)
    bundle = build_monitoring_release(config)
    before = {
        path.relative_to(bundle).as_posix(): file_sha(path)
        for path in bundle.rglob("*")
        if path.is_file()
    }
    changed = config.model_copy(
        update={
            "as_of": date(2027, 2, 16),
        }
    )
    with pytest.raises(ValueError, match="immutable"):
        build_monitoring_release(changed)
    after = {
        path.relative_to(bundle).as_posix(): file_sha(path)
        for path in bundle.rglob("*")
        if path.is_file()
    }
    assert after == before

    config.historical_release.publication_manifest_path.write_text("{}")
    with pytest.raises(ValueError, match="historical publication manifest hash"):
        build_monitoring_release(
            config.model_copy(
                update={
                    "cycle_id": "monitoring-tampered-history",
                    "superseding_release": config.superseding_release.model_copy(
                        update={"release_id": "banes-lcwip-review-tampered"}
                    ),
                }
            )
        )


def test_recomputed_hashes_cannot_hide_inconsistent_effective_status(
    tmp_path: Path,
) -> None:
    manifest = validate_monitoring_release(
        build_monitoring_release(fixture_config(tmp_path))
    )
    payload = manifest.model_dump(mode="json")
    payload["programme"][0]["effective_status"]["funding"] = "secured"
    monitoring_keys = (
        "cycle_id",
        "as_of",
        "watermark",
        "historical_release",
        "evidence_snapshot",
        "sources",
        "conformance",
        "programme",
        "indicators",
        "review_tasks",
        "guidance_changes",
        "evidence_changes",
        "superseding_release",
    )
    payload["monitoring_fingerprint"] = _fingerprint(
        {key: payload[key] for key in monitoring_keys}
    )
    payload["manifest_fingerprint"] = _fingerprint(
        {
            key: value
            for key, value in payload.items()
            if key != "manifest_fingerprint"
        }
    )
    with pytest.raises(ValidationError, match="programme status view"):
        MonitoringManifest.model_validate(payload)


def test_failed_monitoring_build_preserves_prior_release(tmp_path: Path) -> None:
    baseline = fixture_config(tmp_path)
    prior = build_monitoring_release(baseline)
    before = {
        path.relative_to(prior).as_posix(): file_sha(path)
        for path in prior.rglob("*")
        if path.is_file()
    }
    broken = fixture_config(tmp_path, cycle_id="monitoring-broken")
    broken_source = broken.sources[0].model_copy(
        update={"contains_personal_data": True}
    )
    with pytest.raises(ValidationError, match="personal data"):
        build_monitoring_release(
            broken.model_copy(
                update={"sources": (broken_source, *broken.sources[1:])}
            )
        )
    after = {
        path.relative_to(prior).as_posix(): file_sha(path)
        for path in prior.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (broken.output_dir / broken.cycle_id).exists()
