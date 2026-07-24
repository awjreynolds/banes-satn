from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.evidence import (
    AccessLevel,
    AdapterKind,
    EvidenceAvailability,
    EvidenceFamily,
    EvidenceFamilyRequirement,
    EvidenceIssue,
    EvidenceQuality,
    EvidenceRegistryConfig,
    EvidenceRole,
    EvidenceSnapshotItem,
    EvidenceSnapshotManifest,
    EvidenceSourceSpec,
    PublicDisposition,
    SpatialCoverage,
    load_evidence_gate,
    snapshot_evidence_registry,
    validate_evidence_snapshot,
)

PROJECT = Path(__file__).parents[1]
FIXTURES = PROJECT / "tests" / "fixtures" / "lcwip" / "evidence"

ADAPTER_FIXTURES = {
    AdapterKind.CENSUS_POPULATION: (
        "census-population.json",
        EvidenceFamily.DEMOGRAPHICS,
        EvidenceRole.RAW,
    ),
    AdapterKind.DEPRIVATION_CHARACTERISTICS: (
        "deprivation-characteristics.json",
        EvidenceFamily.EQUITY_CONTEXT,
        EvidenceRole.RAW,
    ),
    AdapterKind.ORIGIN_DESTINATION: (
        "origin-destination.json",
        EvidenceFamily.DEMAND,
        EvidenceRole.OBSERVED,
    ),
    AdapterKind.PROPENSITY_TO_CYCLE: (
        "propensity-to-cycle.json",
        EvidenceFamily.DEMAND,
        EvidenceRole.MODELLED,
    ),
    AdapterKind.COLLISIONS_TRAFFIC: (
        "collisions-traffic.json",
        EvidenceFamily.SAFETY_TRAFFIC,
        EvidenceRole.OBSERVED,
    ),
    AdapterKind.PUBLIC_TRANSPORT_ATTRACTORS: (
        "public-transport-attractors.json",
        EvidenceFamily.PUBLIC_TRANSPORT_ATTRACTORS,
        EvidenceRole.RAW,
    ),
    AdapterKind.DEVELOPMENT_POLICY: (
        "development-policy.json",
        EvidenceFamily.DEVELOPMENT_POLICY,
        EvidenceRole.POLICY,
    ),
    AdapterKind.RIGHTS_OF_WAY_INFRASTRUCTURE: (
        "rights-of-way-infrastructure.json",
        EvidenceFamily.RIGHTS_OF_WAY_INFRASTRUCTURE,
        EvidenceRole.OBSERVED,
    ),
    AdapterKind.CONTROLLED_LOCAL_IMPORT: (
        "controlled-local-import.json",
        EvidenceFamily.LOCAL_EVIDENCE,
        EvidenceRole.STAKEHOLDER,
    ),
}


def evidence_source(
    adapter: AdapterKind,
    *,
    evidence_id: str | None = None,
    family: EvidenceFamily | None = None,
    role: EvidenceRole | None = None,
    path: Path | None = None,
    redacted_path: Path | None = None,
    access_level: AccessLevel = AccessLevel.PUBLIC,
    public_disposition: PublicDisposition = PublicDisposition.INCLUDE,
    quality: EvidenceQuality = EvidenceQuality.HIGH,
    covered_units: tuple[str, ...] = ("BANES",),
    permitted_uses: tuple[str, ...] = ("baseline-analysis",),
    observed_from: date = date(2025, 1, 1),
    observed_to: date = date(2026, 1, 31),
    lineage: tuple[str, ...] = (),
    transformation_version: str | None = None,
    non_reproducibility_reason: str | None = None,
) -> EvidenceSourceSpec:
    fixture_name, default_family, default_role = ADAPTER_FIXTURES[adapter]
    identifier = evidence_id or adapter.value
    return EvidenceSourceSpec(
        evidence_id=identifier,
        adapter=adapter,
        family=family or default_family,
        role=role or default_role,
        path=path if path is not None else FIXTURES / fixture_name,
        redacted_path=redacted_path,
        source_uri=f"fixture://banes/{identifier}",
        publisher="B&NES synthetic fixture publisher",
        licence="Open Government Licence v3.0",
        retrieved_on=date(2026, 2, 1),
        observed_from=observed_from,
        observed_to=observed_to,
        spatial_coverage=SpatialCoverage(
            expected_units=("BANES",),
            covered_units=covered_units,
            description="B&NES synthetic coverage",
        ),
        version="2026.1",
        methodology="Synthetic adapter contract fixture.",
        known_bias="Synthetic values are not suitable for real planning decisions.",
        quality=quality,
        permitted_uses=permitted_uses,
        access_level=access_level,
        public_disposition=public_disposition,
        lineage=lineage,
        transformation_version=transformation_version,
        non_reproducibility_reason=non_reproducibility_reason,
    )


def requirement(
    family: EvidenceFamily,
    *,
    required_units: tuple[str, ...] = ("BANES",),
    maximum_age_days: int = 730,
    minimum_quality: EvidenceQuality = EvidenceQuality.MEDIUM,
    required_use: str = "baseline-analysis",
) -> EvidenceFamilyRequirement:
    return EvidenceFamilyRequirement(
        family=family,
        required_units=required_units,
        maximum_age_days=maximum_age_days,
        minimum_quality=minimum_quality,
        required_use=required_use,
    )


def registry_config(
    tmp_path: Path,
    *,
    sources: tuple[EvidenceSourceSpec, ...],
    requirements: tuple[EvidenceFamilyRequirement, ...] | None = None,
    snapshot_id: str = "banes-baseline-2026",
) -> EvidenceRegistryConfig:
    configured_requirements = requirements
    if configured_requirements is None:
        configured_requirements = tuple(
            requirement(family) for family in sorted({source.family for source in sources})
        )
    return EvidenceRegistryConfig(
        snapshot_id=snapshot_id,
        council_id="bath-and-north-east-somerset",
        profile_id="dft-lcwip-2017",
        reference_date=date(2026, 2, 1),
        output_dir=tmp_path / "evidence-snapshots",
        requirements=configured_requirements,
        sources=sources,
    )


def report_payload(snapshot_path: Path) -> dict[str, object]:
    return json.loads((snapshot_path / "coverage-report.json").read_text())


def test_each_banes_adapter_contract_snapshots_complete_governed_metadata(
    tmp_path: Path,
) -> None:
    raw_private = tmp_path / "controlled-private.json"
    raw_private.write_text('{"name":"Private respondent","comment":"Use redacted fixture"}')
    sources = tuple(
        evidence_source(
            adapter,
            access_level=(
                AccessLevel.CONTROLLED
                if adapter is AdapterKind.CONTROLLED_LOCAL_IMPORT
                else AccessLevel.PUBLIC
            ),
            public_disposition=(
                PublicDisposition.REDACTED
                if adapter is AdapterKind.CONTROLLED_LOCAL_IMPORT
                else PublicDisposition.INCLUDE
            ),
            path=raw_private if adapter is AdapterKind.CONTROLLED_LOCAL_IMPORT else None,
            redacted_path=(
                FIXTURES / "controlled-local-import.json"
                if adapter is AdapterKind.CONTROLLED_LOCAL_IMPORT
                else None
            ),
        )
        for adapter in AdapterKind
    )
    config = registry_config(tmp_path, sources=sources)

    snapshot_path = snapshot_evidence_registry(config)
    manifest = validate_evidence_snapshot(snapshot_path)

    assert {item.adapter for item in manifest.items} == set(AdapterKind)
    assert manifest.snapshot_id == config.snapshot_id
    assert len(manifest.snapshot_fingerprint) == 64
    assert len(manifest.input_fingerprint) == 64
    assert (snapshot_path / "coverage-report.json").is_file()
    assert (snapshot_path / "coverage-report.md").is_file()
    assert manifest.evidence_requests == ()
    coverage_entries = report_payload(snapshot_path)["entries"]
    assert all(entry["freshest_observation"] == "2026-01-31" for entry in coverage_entries)
    assert all(entry["best_quality"] == EvidenceQuality.HIGH for entry in coverage_entries)
    assert all(
        entry["licences"] == ["Open Government Licence v3.0"]
        for entry in coverage_entries
    )
    assert all(entry["required_use"] == "baseline-analysis" for entry in coverage_entries)
    human_report = (snapshot_path / "coverage-report.md").read_text()
    assert "2026-01-31" in human_report
    assert "Open Government Licence v3.0" in human_report
    assert "high" in human_report
    for item in manifest.items:
        assert item.availability is EvidenceAvailability.AVAILABLE
        assert item.publisher
        assert item.licence
        assert item.retrieved_on
        assert item.observed_from <= item.observed_to
        assert item.spatial_coverage.expected_units
        assert item.version
        assert item.methodology
        assert item.known_bias
        assert item.permitted_uses
        assert item.artifact_path
        artifact = snapshot_path / item.artifact_path
        assert artifact.is_file()
        assert item.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert "Private respondent" not in (snapshot_path / "evidence-registry.json").read_text()
    assert "Private respondent" not in (snapshot_path / "coverage-report.md").read_text()
    assert not any("controlled-private" in path.name for path in snapshot_path.rglob("*"))


def test_snapshot_is_immutable_reproducible_and_detects_artifact_tampering(
    tmp_path: Path,
) -> None:
    source = evidence_source(AdapterKind.CENSUS_POPULATION)
    first_config = registry_config(tmp_path / "first", sources=(source,))
    second_config = registry_config(tmp_path / "second", sources=(source,))

    first_path = snapshot_evidence_registry(first_config)
    second_path = snapshot_evidence_registry(second_config)
    first = validate_evidence_snapshot(first_path)
    second = validate_evidence_snapshot(second_path)

    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert first.input_fingerprint == second.input_fingerprint
    assert (first_path / "coverage-report.json").read_bytes() == (
        second_path / "coverage-report.json"
    ).read_bytes()
    assert snapshot_evidence_registry(first_config) == first_path

    changed = tmp_path / "changed-census.json"
    changed.write_text('{"area":"BANES","population":193401,"year":2021}')
    conflicting_config = registry_config(
        tmp_path / "first",
        sources=(evidence_source(AdapterKind.CENSUS_POPULATION, path=changed),),
    )
    with pytest.raises(ValueError, match="immutable"):
        snapshot_evidence_registry(conflicting_config)

    artifact = first_path / first.items[0].artifact_path
    artifact.write_text('{"tampered":true}')
    with pytest.raises(ValueError, match="content hash"):
        validate_evidence_snapshot(first_path)


@pytest.mark.parametrize("adapter", tuple(AdapterKind))
def test_each_adapter_rejects_payloads_that_do_not_meet_its_contract(
    tmp_path: Path, adapter: AdapterKind
) -> None:
    invalid = tmp_path / f"{adapter}.json"
    invalid.write_text('{"unexpected":"payload"}')
    source = evidence_source(adapter, path=invalid)
    if adapter is AdapterKind.CONTROLLED_LOCAL_IMPORT:
        source = source.model_copy(
            update={
                "access_level": AccessLevel.CONTROLLED,
                "public_disposition": PublicDisposition.REDACTED,
                "redacted_path": invalid,
            }
        )

    with pytest.raises(ValueError, match="adapter contract"):
        snapshot_evidence_registry(registry_config(tmp_path, sources=(source,)))


def test_adapter_family_cannot_be_misclassified() -> None:
    with pytest.raises(ValidationError, match="adapter belongs to"):
        evidence_source(
            AdapterKind.CENSUS_POPULATION,
            family=EvidenceFamily.SAFETY_TRAFFIC,
        )


def test_missing_stale_low_quality_spatial_and_licence_gaps_are_reported_and_requested(
    tmp_path: Path,
) -> None:
    sources = (
        evidence_source(
            AdapterKind.CENSUS_POPULATION,
            quality=EvidenceQuality.LOW,
            covered_units=("Bath",),
            observed_from=date(2019, 1, 1),
            observed_to=date(2020, 1, 1),
            permitted_uses=("research-only",),
        ),
    )
    requirements = (
        requirement(
            EvidenceFamily.DEMOGRAPHICS,
            required_units=("Bath", "Keynsham"),
            maximum_age_days=365,
            minimum_quality=EvidenceQuality.HIGH,
        ),
        requirement(EvidenceFamily.SAFETY_TRAFFIC),
    )

    snapshot_path = snapshot_evidence_registry(
        registry_config(tmp_path, sources=sources, requirements=requirements)
    )
    manifest = validate_evidence_snapshot(snapshot_path)
    report = report_payload(snapshot_path)
    entries = {entry["family"]: entry for entry in report["entries"]}

    assert set(entries[EvidenceFamily.DEMOGRAPHICS.value]["issues"]) == {
        EvidenceIssue.STALE.value,
        EvidenceIssue.LOW_QUALITY.value,
        EvidenceIssue.SPATIALLY_INCOMPLETE.value,
        EvidenceIssue.LICENCE_RESTRICTED.value,
    }
    assert entries[EvidenceFamily.SAFETY_TRAFFIC.value]["issues"] == [
        EvidenceIssue.MISSING.value
    ]
    assert {request.family for request in manifest.evidence_requests} == {
        EvidenceFamily.DEMOGRAPHICS,
        EvidenceFamily.SAFETY_TRAFFIC,
    }
    demographic_request = next(
        request
        for request in manifest.evidence_requests
        if request.family is EvidenceFamily.DEMOGRAPHICS
    )
    assert demographic_request.missing_units == ("Keynsham",)
    assert "Keynsham" in (snapshot_path / "coverage-report.md").read_text()


def test_requirements_are_profile_and_council_configured_not_globally_hard_coded(
    tmp_path: Path,
) -> None:
    source = evidence_source(AdapterKind.CENSUS_POPULATION)
    demographics_only = registry_config(
        tmp_path / "demographics",
        sources=(source,),
        requirements=(requirement(EvidenceFamily.DEMOGRAPHICS),),
    )
    with_safety = EvidenceRegistryConfig(
        **(
            demographics_only.model_dump()
            | {
                "snapshot_id": "with-safety",
                "output_dir": tmp_path / "with-safety",
                "requirements": (
                    requirement(EvidenceFamily.DEMOGRAPHICS),
                    requirement(EvidenceFamily.SAFETY_TRAFFIC),
                ),
            }
        )
    )

    complete = validate_evidence_snapshot(snapshot_evidence_registry(demographics_only))
    incomplete = validate_evidence_snapshot(snapshot_evidence_registry(with_safety))

    assert complete.evidence_requests == ()
    assert tuple(request.family for request in incomplete.evidence_requests) == (
        EvidenceFamily.SAFETY_TRAFFIC,
    )


def test_derived_evidence_requires_complete_resolved_lineage_and_transformation_version(
    tmp_path: Path,
) -> None:
    raw = evidence_source(AdapterKind.ORIGIN_DESTINATION, evidence_id="od-raw")
    derived = evidence_source(
        AdapterKind.PROPENSITY_TO_CYCLE,
        evidence_id="pct-derived",
        role=EvidenceRole.DERIVED,
        lineage=("od-raw",),
        transformation_version="pct-adapter-1.0",
    )
    config = registry_config(tmp_path, sources=(raw, derived))
    manifest = validate_evidence_snapshot(snapshot_evidence_registry(config))
    derived_item = next(item for item in manifest.items if item.evidence_id == "pct-derived")

    assert derived_item.lineage == ("od-raw",)
    assert derived_item.transformation_version == "pct-adapter-1.0"

    for invalid in (
        derived.model_copy(update={"lineage": ()}),
        derived.model_copy(update={"transformation_version": None}),
        derived.model_copy(update={"lineage": ("missing-input",)}),
        derived.model_copy(update={"lineage": ("pct-derived",)}),
    ):
        with pytest.raises(
            (ValidationError, ValueError),
            match=r"lineage|transformation|input",
        ):
            invalid_config = registry_config(tmp_path / invalid.evidence_id, sources=(raw, invalid))
            snapshot_evidence_registry(invalid_config)


def test_controlled_and_personal_inputs_never_enter_public_artifacts(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private-consultation.json"
    private.write_text('{"name":"Jane Citizen","email":"jane@example.test","comment":"Crossing"}')
    redacted = FIXTURES / "controlled-local-import.json"
    controlled = evidence_source(
        AdapterKind.CONTROLLED_LOCAL_IMPORT,
        evidence_id="controlled-redacted",
        path=private,
        redacted_path=redacted,
        access_level=AccessLevel.CONTROLLED,
        public_disposition=PublicDisposition.REDACTED,
    )
    personal = evidence_source(
        AdapterKind.CONTROLLED_LOCAL_IMPORT,
        evidence_id="personal-excluded",
        path=private,
        access_level=AccessLevel.PERSONAL,
        public_disposition=PublicDisposition.EXCLUDE,
        non_reproducibility_reason=(
            "Personal consultation data remains in the access-controlled store."
        ),
    )
    manifest = validate_evidence_snapshot(
        snapshot_evidence_registry(registry_config(tmp_path, sources=(controlled, personal)))
    )
    public_text = "\n".join(
        path.read_text(errors="ignore") for path in manifest_path_files(tmp_path, manifest)
    )

    assert "Jane Citizen" not in public_text
    assert "jane@example.test" not in public_text
    excluded = next(item for item in manifest.items if item.evidence_id == "personal-excluded")
    assert excluded.artifact_path is None
    assert excluded.sha256 is None
    assert excluded.non_reproducibility_reason


def manifest_path_files(tmp_path: Path, manifest: EvidenceSnapshotManifest) -> list[Path]:
    snapshot_path = tmp_path / "evidence-snapshots" / manifest.snapshot_id
    return [path for path in snapshot_path.rglob("*") if path.is_file()]


def test_configured_missing_source_is_explicitly_non_reproducible_not_present(
    tmp_path: Path,
) -> None:
    missing = evidence_source(
        AdapterKind.COLLISIONS_TRAFFIC,
        path=tmp_path / "missing-collisions.json",
        non_reproducibility_reason="Licensed collision extract was not supplied.",
    )
    manifest = validate_evidence_snapshot(
        snapshot_evidence_registry(registry_config(tmp_path, sources=(missing,)))
    )
    item = manifest.items[0]

    assert item.availability is EvidenceAvailability.UNAVAILABLE
    assert item.artifact_path is None
    assert item.non_reproducibility_reason == "Licensed collision extract was not supplied."
    assert manifest.evidence_requests[0].family is EvidenceFamily.SAFETY_TRAFFIC
    assert EvidenceIssue.NON_REPRODUCIBLE in manifest.evidence_requests[0].reasons


def test_agents_cannot_mutate_registry_items_or_mark_missing_evidence_present(
    tmp_path: Path,
) -> None:
    missing = evidence_source(
        AdapterKind.COLLISIONS_TRAFFIC,
        path=tmp_path / "missing.json",
        non_reproducibility_reason="Not provided.",
    )
    manifest = validate_evidence_snapshot(
        snapshot_evidence_registry(registry_config(tmp_path, sources=(missing,)))
    )
    item = manifest.items[0]

    with pytest.raises(ValidationError):
        item.availability = EvidenceAvailability.AVAILABLE
    with pytest.raises(ValidationError):
        item.sha256 = "a" * 64
    assert item.availability is EvidenceAvailability.UNAVAILABLE

    forged = item.model_copy(update={"availability": EvidenceAvailability.AVAILABLE})
    with pytest.raises(ValidationError, match="requires a copied artifact"):
        EvidenceSnapshotManifest.create(
            config=registry_config(tmp_path / "forged", sources=(missing,)),
            input_fingerprint=manifest.input_fingerprint,
            items=(forged,),
            requests=manifest.evidence_requests,
        )


def test_snapshot_items_reject_semantically_impossible_states(tmp_path: Path) -> None:
    manifest = validate_evidence_snapshot(
        snapshot_evidence_registry(
            registry_config(
                tmp_path,
                sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
            )
        )
    )
    payload = manifest.items[0].model_dump()
    invalid_updates = (
        {
            "availability": EvidenceAvailability.UNAVAILABLE,
            "non_reproducibility_reason": "Not supplied.",
        },
        {"artifact_path": None, "sha256": None},
        {
            "role": EvidenceRole.DERIVED,
            "lineage": (),
            "transformation_version": None,
        },
        {
            "access_level": AccessLevel.PUBLIC,
            "public_disposition": PublicDisposition.REDACTED,
        },
        {
            "access_level": AccessLevel.CONTROLLED,
            "public_disposition": PublicDisposition.EXCLUDE,
            "artifact_path": None,
            "sha256": None,
            "non_reproducibility_reason": None,
        },
    )

    for update in invalid_updates:
        with pytest.raises(ValidationError):
            EvidenceSnapshotItem.model_validate(payload | update)


def test_manifest_rejects_duplicate_items_and_unresolved_derived_lineage(
    tmp_path: Path,
) -> None:
    config = registry_config(
        tmp_path,
        sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
    )
    manifest = validate_evidence_snapshot(snapshot_evidence_registry(config))
    item = manifest.items[0]

    with pytest.raises(ValidationError, match="item IDs must be unique"):
        EvidenceSnapshotManifest.create(
            config=config,
            input_fingerprint=manifest.input_fingerprint,
            items=(item, item),
            requests=(),
        )

    derived = EvidenceSnapshotItem.model_validate(
        item.model_dump()
        | {
            "evidence_id": "derived-population",
            "role": EvidenceRole.DERIVED,
            "lineage": ("not-in-this-manifest",),
            "transformation_version": "population-transform-v1",
        }
    )
    with pytest.raises(ValidationError, match=r"input.*not present"):
        EvidenceSnapshotManifest.create(
            config=config,
            input_fingerprint=manifest.input_fingerprint,
            items=(item, derived),
            requests=(),
        )


def test_evidence_gate_requires_valid_machine_and_human_reports(tmp_path: Path) -> None:
    config = registry_config(
        tmp_path,
        sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
    )
    snapshot_path = snapshot_evidence_registry(config)

    report = load_evidence_gate(snapshot_path)
    assert report.snapshot_id == config.snapshot_id

    (snapshot_path / "coverage-report.md").unlink()
    with pytest.raises(ValueError, match=r"coverage-report\.md"):
        load_evidence_gate(snapshot_path)


def test_snapshot_validation_rederives_machine_and_human_coverage_reports(
    tmp_path: Path,
) -> None:
    config = registry_config(
        tmp_path,
        sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
    )
    snapshot_path = snapshot_evidence_registry(config)
    machine_path = snapshot_path / "coverage-report.json"
    machine = json.loads(machine_path.read_text())
    machine["complete"] = False
    machine["entries"][0]["issues"] = [EvidenceIssue.MISSING.value]
    machine_path.write_text(json.dumps(machine))

    with pytest.raises(ValueError, match="coverage report"):
        validate_evidence_snapshot(snapshot_path)

    snapshot_path = snapshot_evidence_registry(
        registry_config(
            tmp_path / "human",
            sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
        )
    )
    (snapshot_path / "coverage-report.md").write_text("# Everything is complete\n")
    with pytest.raises(ValueError, match="human coverage report"):
        validate_evidence_snapshot(snapshot_path)


def test_evidence_cli_snapshots_and_validates_registry(tmp_path: Path) -> None:
    config = registry_config(
        tmp_path,
        sources=(evidence_source(AdapterKind.CENSUS_POPULATION),),
    )
    config_path = tmp_path / "registry-config.json"
    config_path.write_text(config.model_dump_json(indent=2))
    runner = CliRunner()

    created = runner.invoke(app, ["evidence", "snapshot", str(config_path)])
    assert created.exit_code == 0, created.output
    snapshot_path = config.output_dir / config.snapshot_id
    validated = runner.invoke(app, ["evidence", "validate", str(snapshot_path)])
    assert validated.exit_code == 0, validated.output
    assert "valid banes-baseline-2026" in validated.output
