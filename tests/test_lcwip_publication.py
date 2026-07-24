from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import geopandas as gpd
import pytest
from pydantic import ValidationError
from pypdf import PdfReader
from shapely.geometry import LineString
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.models import (
    ArtifactLink,
    GuidanceProfile,
    LifecycleState,
    Obligation,
    Requirement,
    RequirementAssessment,
    RequirementStatus,
)
from lcwip.publication import (
    ArtifactKind,
    CitationRecord,
    ClaimAuthority,
    ClaimAuthorityKind,
    ClaimPolarity,
    ConsultationChange,
    NarrativeClaim,
    NetworkFeatureRecord,
    PrivacySafeAuditEntry,
    ProgrammeScheduleRecord,
    PublicationAdoptionAnnotation,
    PublicationConfig,
    PublicationManifest,
    ReportSection,
    ReportSectionKind,
    SourceArtifact,
    SourceRecord,
    _fingerprint,
    _geometry_fingerprint,
    build_lcwip_publication,
    lcwip_release_fingerprint,
    validate_lcwip_publication,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile() -> GuidanceProfile:
    return GuidanceProfile(
        profile_id="ate-lcwip-publication",
        issuer="Active Travel England",
        document="LCWIP guidance",
        version="2026.1",
        effective_date=date(2026, 1, 1),
        applicability="B&NES adoption-candidate publication",
        requirements=(
            Requirement(
                requirement_id="network-plan",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("network-plan",),
                description="Publish an inspectable network plan.",
            ),
            Requirement(
                requirement_id="consultation-evidence",
                obligation=Obligation.MANDATORY,
                expected_artifacts=("consultation-record",),
                description="Resolve and publish consultation evidence.",
            ),
        ),
    )


def write_sources(root: Path, *, geometry_offset: float = 0) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    coordinates = [[0 + geometry_offset, 0], [1 + geometry_offset, 1]]
    feature = {
        "type": "Feature",
        "id": "network-feature-1",
        "properties": {
            "status": "proposal",
            "metrics": {"length_m": 157000.0, "corridor": "A4"},
            "name": "Bath to Keynsham strategic corridor",
        },
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }
    geojson = root / "network.geojson"
    geojson.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": [feature]},
            sort_keys=True,
        )
    )
    geopackage = root / "network.gpkg"
    gpd.GeoDataFrame(
        [
            {
                "feature_id": "network-feature-1",
                "status": "proposal",
                "length_m": 157000.0,
                "geometry": LineString(coordinates),
            }
        ],
        crs="EPSG:4326",
    ).to_file(geopackage, layer="network", driver="GPKG")
    evidence = root / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "snapshot_id": "evidence-snapshot-1",
                "coverage": "partial",
                "quality": "reviewed",
            },
            sort_keys=True,
        )
    )
    return {
        "geojson": geojson,
        "geopackage": geopackage,
        "evidence": evidence,
    }


def geometry_hash(source: Path) -> str:
    feature = json.loads(source.read_text())["features"][0]
    return _geometry_fingerprint(LineString(feature["geometry"]["coordinates"]))


def fixture_config(
    tmp_path: Path,
    *,
    release_id: str = "banes-lcwip-1.0",
    release_version: str = "1.0",
    previous_release_dir: Path | None = None,
    lifecycle_state: LifecycleState = LifecycleState.ADOPTION_CANDIDATE,
    geometry_offset: float = 0,
) -> PublicationConfig:
    sources = write_sources(
        tmp_path / f"sources-{release_id}",
        geometry_offset=geometry_offset,
    )
    guidance = profile()
    source_artifacts = (
        SourceArtifact(
            artifact_id="artifact-network-geojson",
            kind=ArtifactKind.NETWORK_GEOJSON,
            path=sources["geojson"],
            sha256=sha(sources["geojson"]),
            coverage_status="district-wide strategic network",
            quality_status="deterministically validated",
            limitations=("Indicative alignments are not detailed designs.",),
            public=True,
            contains_personal_data=False,
        ),
        SourceArtifact(
            artifact_id="artifact-network-geopackage",
            kind=ArtifactKind.NETWORK_GEOPACKAGE,
            path=sources["geopackage"],
            sha256=sha(sources["geopackage"]),
            coverage_status="district-wide strategic network",
            quality_status="deterministically validated",
            limitations=("Geometry remains indicative.",),
            public=True,
            contains_personal_data=False,
        ),
        SourceArtifact(
            artifact_id="artifact-evidence",
            kind=ArtifactKind.EVIDENCE,
            path=sources["evidence"],
            sha256=sha(sources["evidence"]),
            coverage_status="partial baseline coverage",
            quality_status="reviewed with explicit gaps",
            limitations=("Some trip-purpose evidence remains unavailable.",),
            public=True,
            contains_personal_data=False,
        ),
    )
    source_records = (
        SourceRecord(
            record_id="record-network-feature-1",
            artifact_id="artifact-network-geojson",
            record_fingerprint=geometry_hash(sources["geojson"]),
            public_summary="Governed network feature and geometry.",
        ),
        SourceRecord(
            record_id="record-programme-1",
            artifact_id="artifact-evidence",
            record_fingerprint="1" * 64,
            public_summary="Governed intervention programme record.",
        ),
        SourceRecord(
            record_id="record-consultation-change-1",
            artifact_id="artifact-evidence",
            record_fingerprint="2" * 64,
            public_summary="Privacy-safe consultation change record.",
        ),
        SourceRecord(
            record_id="record-equality-open-1",
            artifact_id="artifact-evidence",
            record_fingerprint="3" * 64,
            public_summary="Unresolved equality finding reference.",
        ),
        SourceRecord(
            record_id="record-representation-open-1",
            artifact_id="artifact-evidence",
            record_fingerprint="4" * 64,
            public_summary="Unresolved representation reference.",
        ),
        SourceRecord(
            record_id="record-method-1",
            artifact_id="artifact-evidence",
            record_fingerprint="5" * 64,
            public_summary="Governed analytical method record.",
        ),
    )
    citations = tuple(
        CitationRecord(
            citation_id=f"citation-{record.record_id}",
            source_artifact_id=record.artifact_id,
            source_record_id=record.record_id,
            label=record.public_summary,
            uri=f"https://example.test/records/{record.record_id}",
            sha256=record.record_fingerprint,
        )
        for record in source_records
    )
    citation = {item.source_record_id: item.citation_id for item in citations}
    claims = {
        ReportSectionKind.EXECUTIVE_SUMMARY: NarrativeClaim(
            claim_id="claim-summary",
            text="The adoption candidate identifies a strategic active travel network.",
            category="proposal",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-network-feature-1"],),
        ),
        ReportSectionKind.STATUS_CONFORMANCE: NarrativeClaim(
            claim_id="claim-status",
            text="This release is not adopted and contains a mandatory conformance gap.",
            category="uncertainty",
            polarity=ClaimPolarity.LIMITATION,
            material=True,
            citation_ids=(citation["record-method-1"],),
        ),
        ReportSectionKind.NETWORK_PLANS: NarrativeClaim(
            claim_id="claim-network",
            text="The A4 corridor is retained as an indicative network proposal.",
            category="proposal",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-network-feature-1"],),
        ),
        ReportSectionKind.INTERVENTION_PROGRAMME: NarrativeClaim(
            claim_id="claim-programme",
            text="The crossing intervention is scheduled for the short-term scenario.",
            category="analysis",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-programme-1"],),
        ),
        ReportSectionKind.METHODS: NarrativeClaim(
            claim_id="claim-method",
            text="The network and programme were generated from governed structured records.",
            category="method",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-method-1"],),
        ),
        ReportSectionKind.ENGAGEMENT: NarrativeClaim(
            claim_id="claim-engagement",
            text=(
                "Consultation changed the crossing location; one representation "
                "remains unresolved."
            ),
            category="consultation-change",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(
                citation["record-consultation-change-1"],
                citation["record-representation-open-1"],
            ),
        ),
        ReportSectionKind.EQUALITY: NarrativeClaim(
            claim_id="claim-equality",
            text="An equality impact concerning crossing accessibility remains unresolved.",
            category="uncertainty",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-equality-open-1"],),
        ),
        ReportSectionKind.POLICY: NarrativeClaim(
            claim_id="claim-policy",
            text="The network proposal is mapped to the governed Local Transport Plan record.",
            category="policy",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-method-1"],),
        ),
        ReportSectionKind.APPENDICES: NarrativeClaim(
            claim_id="claim-appendix",
            text="Appendices expose source coverage, quality, citations and audit provenance.",
            category="evidence",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=(citation["record-method-1"],),
        ),
    }
    sections = tuple(
        ReportSection(
            kind=kind,
            title=kind.value.replace("-", " ").title(),
            introduction=f"Structured {kind.value} publication section.",
            introduction_citation_ids=(claims[kind].citation_ids[0],),
            claims=(claims[kind],),
        )
        for kind in ReportSectionKind
    )
    assessments = (
        RequirementAssessment(
            requirement_id="network-plan",
            status=RequirementStatus.SATISFIED,
            evidence=(
                ArtifactLink(
                    artifact_id="artifact-network-geojson",
                    uri=sources["geojson"].as_uri(),
                    kind="network-plan",
                ),
            ),
            rationale="The network is published in inspectable GIS formats.",
        ),
        RequirementAssessment(
            requirement_id="consultation-evidence",
            status=RequirementStatus.UNKNOWN,
            rationale="One representation remains unresolved.",
        ),
    )
    return PublicationConfig(
        output_dir=tmp_path / "releases",
        release_id=release_id,
        release_version=release_version,
        plan_area="Bath and North East Somerset",
        publication_date=date(2026, 7, 24),
        lifecycle_state=lifecycle_state,
        evidence_fingerprint="a" * 64,
        configuration_fingerprint="b" * 64,
        guidance_profile=guidance,
        requirement_assessments=assessments,
        sources=source_artifacts,
        source_records=source_records,
        citations=citations,
        sections=sections,
        network_features=(
            NetworkFeatureRecord(
                feature_id="network-feature-1",
                source_artifact_id="artifact-network-geojson",
                source_record_id="record-network-feature-1",
                status="proposal",
                metrics={"length_m": 157000.0, "corridor": "A4"},
                geometry_sha256=geometry_hash(sources["geojson"]),
                bbox=(
                    0 + geometry_offset,
                    0,
                    1 + geometry_offset,
                    1,
                ),
            ),
        ),
        programme=(
            ProgrammeScheduleRecord(
                intervention_id="intervention-crossing-1",
                source_record_id="record-programme-1",
                phase="short",
                status="strategic-option",
                lower_cost=100_000,
                upper_cost=250_000,
                dependencies=(),
                risks=("Detailed design and funding are unresolved.",),
            ),
        ),
        consultation_changes=(
            ConsultationChange(
                change_id="consultation-change-1",
                source_record_id="record-consultation-change-1",
                representation_ids=("representation-redacted-1",),
                before="Crossing west of the junction.",
                after="Crossing east of the junction.",
                human_decision_record_id="human-disposition-1",
                citation_ids=(citation["record-consultation-change-1"],),
            ),
        ),
        unresolved_representation_record_ids=("record-representation-open-1",),
        unresolved_equality_finding_record_ids=("record-equality-open-1",),
        audit_entries=(
            PrivacySafeAuditEntry(
                entry_id="audit-agent-1",
                kind="agent-decision",
                occurred_on=date(2026, 7, 1),
                actor="cycling-analyst",
                summary="Selected one compiler-authored action with governed citations.",
                source_record_id="record-method-1",
                citation_ids=(citation["record-method-1"],),
                contains_personal_data=False,
            ),
            PrivacySafeAuditEntry(
                entry_id="audit-human-1",
                kind="human-decision",
                occurred_on=date(2026, 7, 2),
                actor="LCWIP project board",
                summary="Approved publication as an adoption candidate, not an adopted plan.",
                source_record_id="record-method-1",
                citation_ids=(citation["record-method-1"],),
                contains_personal_data=False,
            ),
        ),
        previous_release_dir=previous_release_dir,
    )


def test_builds_golden_cited_atomic_publication_bundle(tmp_path: Path) -> None:
    bundle = build_lcwip_publication(fixture_config(tmp_path))
    manifest = validate_lcwip_publication(bundle)

    assert manifest.release_id == "banes-lcwip-1.0"
    assert manifest.lifecycle_state is LifecycleState.ADOPTION_CANDIDATE
    assert set(manifest.unresolved_mandatory_requirement_ids) == {
        "consultation-evidence"
    }
    assert {artifact.path for artifact in manifest.artifacts} == {
        "conformance-manifest.json",
        "decision-agent-audit.json",
        "executive-summary.html",
        "lcwip-report.pdf",
        "network-plan.geojson",
        "network-plan.gpkg",
        "programme-schedule.json",
        "release-diff.json",
        "release-history.json",
        "report-data.json",
        "source-coverage-quality.json",
        "lcwip-release.zip",
    }
    assert manifest.publication_fingerprint

    report_text = "\n".join(
        page.extract_text() or "" for page in PdfReader(bundle / "lcwip-report.pdf").pages
    )
    for section in ReportSectionKind:
        assert section.value.replace("-", " ").title() in report_text
    assert "MANDATORY CONFORMANCE GAPS" in report_text
    assert "consultation-evidence" in report_text
    assert "ADOPTION CANDIDATE - NOT ADOPTED" in report_text


def test_material_claims_require_resolving_governed_citations(tmp_path: Path) -> None:
    baseline = fixture_config(tmp_path)
    section = baseline.sections[0]
    uncited = section.claims[0].model_copy(update={"citation_ids": ()})
    with pytest.raises(ValidationError, match="material claim requires"):
        section.model_copy(update={"claims": (uncited,)}, deep=True)
        ReportSection.model_validate(
            section.model_dump() | {"claims": [uncited.model_dump()]}
        )

    broken = section.claims[0].model_copy(
        update={"citation_ids": ("citation-does-not-exist",)}
    )
    with pytest.raises(ValueError, match="claim citation must resolve"):
        build_lcwip_publication(
            baseline.model_copy(
                update={
                    "sections": (
                        section.model_copy(update={"claims": (broken,)}),
                        *baseline.sections[1:],
                    )
                }
            )
        )

    placeholder = NarrativeClaim(
        claim_id="claim-placeholder",
        text="[Evidence required: collision severity by corridor]",
        category="uncertainty",
        polarity=ClaimPolarity.PLACEHOLDER,
        material=True,
        citation_ids=(),
    )
    assert placeholder.citation_ids == ()

    with pytest.raises(ValidationError, match="must use https"):
        CitationRecord(
            citation_id="citation-unsafe",
            source_artifact_id="artifact-evidence",
            source_record_id="record-method-1",
            label="Unsafe public link",
            uri="javascript:alert(1)",
            sha256="5" * 64,
        )


def test_section_introductions_cannot_bypass_typed_authority_claims() -> None:
    with pytest.raises(ValidationError, match="untyped authority claim"):
        ReportSection(
            kind=ReportSectionKind.EXECUTIVE_SUMMARY,
            title="Executive summary",
            introduction="The programme is funded.",
            introduction_citation_ids=("citation-authority",),
            claims=(
                NarrativeClaim(
                    claim_id="claim-bounded",
                    text="The programme remains an indicative proposal.",
                    category="proposal",
                    polarity=ClaimPolarity.ASSERTION,
                    material=True,
                    citation_ids=("citation-authority",),
                ),
            ),
        )


def test_multiple_evidence_sources_are_supported_but_gis_sources_are_singular(
    tmp_path: Path,
) -> None:
    baseline = fixture_config(tmp_path)
    supplementary = tmp_path / "supplementary-evidence.json"
    supplementary.write_text('{"coverage":"supplementary"}')
    extra = SourceArtifact(
        artifact_id="artifact-evidence-supplementary",
        kind=ArtifactKind.EVIDENCE,
        path=supplementary,
        sha256=sha(supplementary),
        coverage_status="supplementary corridor evidence",
        quality_status="reviewed",
        limitations=("Not all corridors are represented.",),
        public=True,
        contains_personal_data=False,
    )
    manifest = validate_lcwip_publication(
        build_lcwip_publication(
            baseline.model_copy(update={"sources": (*baseline.sources, extra)})
        )
    )
    assert sum(item.kind is ArtifactKind.EVIDENCE for item in manifest.sources) == 2

    duplicate_gis = baseline.sources[0].model_copy(
        update={"artifact_id": "artifact-network-geojson-copy"}
    )
    with pytest.raises(ValueError, match="exactly one source artifact kind"):
        build_lcwip_publication(
            baseline.model_copy(update={"sources": (*baseline.sources, duplicate_gis)})
        )


def test_authority_support_resolves_to_citation_and_exact_release(tmp_path: Path) -> None:
    baseline = fixture_config(tmp_path, release_id="authority-release")
    section_index = tuple(item.kind for item in baseline.sections).index(
        ReportSectionKind.INTERVENTION_PROGRAMME
    )
    section = baseline.sections[section_index]
    citation = next(
        item
        for item in baseline.citations
        if item.source_record_id == "record-programme-1"
    )
    authority = ClaimAuthority(
        kind=ClaimAuthorityKind.FEASIBILITY,
        authority_identifier="technical-review-2026",
        authority_name="Independent technical reviewer",
        decided_on=date(2026, 7, 20),
        evidence_uri=citation.uri,
        evidence_sha256=citation.sha256,
        release_fingerprint="0" * 64,
    )
    claim = section.claims[0].model_copy(
        update={
            "text": "The crossing intervention is feasible.",
            "authority": authority,
        }
    )
    sections = list(baseline.sections)
    sections[section_index] = section.model_copy(update={"claims": (claim,)})
    with_authority = baseline.model_copy(update={"sections": tuple(sections)})
    release_fingerprint = lcwip_release_fingerprint(with_authority)
    bound_claim = claim.model_copy(
        update={
            "authority": authority.model_copy(
                update={"release_fingerprint": release_fingerprint}
            )
        }
    )
    sections[section_index] = section.model_copy(update={"claims": (bound_claim,)})
    bound = with_authority.model_copy(update={"sections": tuple(sections)})
    assert (
        validate_lcwip_publication(build_lcwip_publication(bound)).release_fingerprint
        == release_fingerprint
    )

    bad_authority = authority.model_copy(update={"evidence_sha256": "f" * 64})
    bad_claim = claim.model_copy(update={"authority": bad_authority})
    sections[section_index] = section.model_copy(update={"claims": (bad_claim,)})
    with pytest.raises(ValueError, match="authority evidence must resolve"):
        build_lcwip_publication(
            baseline.model_copy(
                update={
                    "release_id": "authority-release-bad",
                    "sections": tuple(sections),
                }
            )
        )


def test_cross_artifact_geometry_status_and_metrics_must_match(tmp_path: Path) -> None:
    baseline = fixture_config(tmp_path)
    mismatched = baseline.network_features[0].model_copy(
        update={"status": "complete"}
    )
    with pytest.raises(ValueError, match="status differs"):
        build_lcwip_publication(
            baseline.model_copy(update={"network_features": (mismatched,)})
        )

    mismatched = baseline.network_features[0].model_copy(
        update={"geometry_sha256": "f" * 64}
    )
    with pytest.raises(ValueError, match="geometry differs"):
        build_lcwip_publication(
            baseline.model_copy(update={"network_features": (mismatched,)})
        )

    altered = fixture_config(tmp_path, release_id="geopackage-mismatch")
    geopackage_source = next(
        item
        for item in altered.sources
        if item.kind is ArtifactKind.NETWORK_GEOPACKAGE
    )
    frame = gpd.read_file(geopackage_source.path)
    frame["geometry"] = [LineString([(0, 0), (2, 1)])]
    geopackage_source.path.unlink()
    frame.to_file(geopackage_source.path, layer="network", driver="GPKG")
    updated_source = geopackage_source.model_copy(
        update={"sha256": sha(geopackage_source.path)}
    )
    with pytest.raises(ValueError, match="GeoPackage geometry differs"):
        build_lcwip_publication(
            altered.model_copy(
                update={
                    "sources": tuple(
                        updated_source
                        if item.artifact_id == updated_source.artifact_id
                        else item
                        for item in altered.sources
                    )
                }
            )
        )


@pytest.mark.parametrize(
    ("claim_text", "authority_kind"),
    (
        ("The plan is adopted.", ClaimAuthorityKind.ADOPTION),
        ("The intervention is feasible.", ClaimAuthorityKind.FEASIBILITY),
        ("The programme is funded.", ClaimAuthorityKind.FUNDING),
    ),
)
def test_authority_claims_are_impossible_without_exact_typed_support(
    claim_text: str,
    authority_kind: ClaimAuthorityKind,
) -> None:
    with pytest.raises(ValidationError, match="typed supporting authority"):
        NarrativeClaim(
            claim_id=f"unsupported-{authority_kind.value}",
            text=claim_text,
            category="decision",
            polarity=ClaimPolarity.ASSERTION,
            material=True,
            citation_ids=("citation-authority",),
        )

    supported = NarrativeClaim(
        claim_id=f"supported-{authority_kind.value}",
        text=claim_text,
        category="decision",
        polarity=ClaimPolarity.ASSERTION,
        material=True,
        citation_ids=("citation-authority",),
        authority=ClaimAuthority(
            kind=authority_kind,
            authority_identifier=f"authority-{authority_kind.value}",
            authority_name="Accountable external authority",
            decided_on=date(2026, 7, 20),
            evidence_uri="https://example.test/authority/decision",
            evidence_sha256="6" * 64,
            release_fingerprint="7" * 64,
        ),
    )
    assert supported.authority.kind is authority_kind


def test_consultation_changes_open_records_and_privacy_safe_audit_are_visible(
    tmp_path: Path,
) -> None:
    bundle = build_lcwip_publication(fixture_config(tmp_path))
    report = json.loads((bundle / "report-data.json").read_text())
    audit = json.loads((bundle / "decision-agent-audit.json").read_text())

    assert report["consultation_changes"][0]["before"].startswith("Crossing west")
    assert report["unresolved_representation_record_ids"] == [
        "record-representation-open-1"
    ]
    assert report["unresolved_equality_finding_record_ids"] == [
        "record-equality-open-1"
    ]
    assert all(entry["contains_personal_data"] is False for entry in audit["entries"])


def test_failed_build_preserves_prior_immutable_release(tmp_path: Path) -> None:
    first = build_lcwip_publication(fixture_config(tmp_path))
    before = {
        path.relative_to(first).as_posix(): sha(path)
        for path in first.rglob("*")
        if path.is_file()
    }
    invalid = fixture_config(
        tmp_path,
        release_id="banes-lcwip-broken",
        release_version="broken",
    )
    missing_source = invalid.sources[0].model_copy(
        update={"sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="source artifact hash"):
        build_lcwip_publication(
            invalid.model_copy(
                update={"sources": (missing_source, *invalid.sources[1:])}
            )
        )
    after = {
        path.relative_to(first).as_posix(): sha(path)
        for path in first.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (invalid.output_dir / invalid.release_id).exists()


def test_release_history_and_diff_cover_all_change_categories(tmp_path: Path) -> None:
    first = build_lcwip_publication(fixture_config(tmp_path))
    second_config = fixture_config(
        tmp_path,
        release_id="banes-lcwip-1.1",
        release_version="1.1",
        previous_release_dir=first,
        geometry_offset=0.25,
    )
    changed_claim = second_config.sections[0].claims[0].model_copy(
        update={"text": "The revised adoption candidate identifies the network."}
    )
    second_config = second_config.model_copy(
        update={
            "configuration_fingerprint": "c" * 64,
            "sections": (
                second_config.sections[0].model_copy(
                    update={"claims": (changed_claim,)}
                ),
                *second_config.sections[1:],
            ),
            "programme": (
                second_config.programme[0].model_copy(update={"phase": "medium"}),
            ),
            "audit_entries": (
                *second_config.audit_entries,
                PrivacySafeAuditEntry(
                    entry_id="audit-change-1",
                    kind="amendment",
                    occurred_on=date(2026, 7, 23),
                    actor="LCWIP project board",
                    summary="Recorded the revised geometry and programme.",
                    source_record_id="record-method-1",
                    citation_ids=("citation-record-method-1",),
                    contains_personal_data=False,
                ),
            ),
        }
    )
    second = build_lcwip_publication(second_config)
    diff = json.loads((second / "release-diff.json").read_text())
    history = json.loads((second / "release-history.json").read_text())

    assert diff["previous_release_id"] == "banes-lcwip-1.0"
    assert set(diff["changed_categories"]) >= {
        "evidence",
        "method",
        "geometry",
        "programme",
        "narrative",
        "decision",
    }
    assert diff["spatial_changes"][0]["feature_id"] == "network-feature-1"
    assert [item["release_id"] for item in history["releases"]] == [
        "banes-lcwip-1.0",
        "banes-lcwip-1.1",
    ]


def test_adoption_is_only_a_typed_later_annotation_bound_to_release(
    tmp_path: Path,
) -> None:
    candidate = fixture_config(tmp_path)
    status_index = tuple(
        item.kind for item in candidate.sections
    ).index(ReportSectionKind.STATUS_CONFORMANCE)
    status_section = candidate.sections[status_index]
    annotated_status = status_section.claims[0].model_copy(
        update={
            "text": (
                "External adoption is recorded only by the typed decision annotation; "
                "the cited report narrative remains the adoption-candidate record."
            )
        }
    )
    adopted_sections = list(candidate.sections)
    adopted_sections[status_index] = status_section.model_copy(
        update={"claims": (annotated_status,)}
    )
    adopted_base = candidate.model_copy(
        update={
            "release_id": "banes-lcwip-adopted",
            "lifecycle_state": LifecycleState.ADOPTED,
            "sections": tuple(adopted_sections),
        }
    )
    fingerprint = lcwip_release_fingerprint(adopted_base)
    adopted = adopted_base.model_copy(
        update={
            "adoption_annotation": PublicationAdoptionAnnotation(
                decision_identifier="cabinet-2026-07-24",
                authority_name="B&NES Cabinet",
                decision_date=date(2026, 7, 24),
                decision_uri="https://example.test/cabinet/2026-07-24",
                verifier_name="Democratic Services Officer",
                verification_evidence_uri=(
                    "https://example.test/democratic-services/verification"
                ),
                verification_date=date(2026, 7, 25),
                release_fingerprint=fingerprint,
            ),
        }
    )
    manifest = validate_lcwip_publication(build_lcwip_publication(adopted))
    assert manifest.adoption_annotation.decision_identifier == "cabinet-2026-07-24"

    mismatched = adopted.model_copy(
        update={
            "release_id": "banes-lcwip-adopted-bad",
            "adoption_annotation": adopted.adoption_annotation.model_copy(
                update={"release_fingerprint": "f" * 64}
            ),
        }
    )
    with pytest.raises(ValueError, match="adoption annotation release fingerprint"):
        build_lcwip_publication(mismatched)


def test_public_accessibility_integrity_watermarks_and_gis_schema(tmp_path: Path) -> None:
    bundle = build_lcwip_publication(fixture_config(tmp_path))
    html = (bundle / "executive-summary.html").read_text()
    assert '<html lang="en">' in html
    assert 'href="#main-content"' in html
    assert "<nav" in html
    assert "<table" in html
    assert '<svg viewBox="0 0 800 440" role="img"' in html
    assert 'aria-labelledby="network-svg-title network-svg-description"' in html
    assert "Non-map network schedule" in html
    assert "ADOPTION CANDIDATE - NOT ADOPTED" in html

    geojson = json.loads((bundle / "network-plan.geojson").read_text())
    assert geojson["lcwip_watermark"]["release_id"] == "banes-lcwip-1.0"
    assert geojson["features"][0]["id"] == "network-feature-1"

    with sqlite3.connect(bundle / "network-plan.gpkg") as database:
        metadata = dict(
            database.execute(
                "select metadata_key, metadata_value from lcwip_publication_metadata"
            ).fetchall()
        )
        columns = {
            row[1] for row in database.execute("pragma table_info('network')")
        }
    assert metadata["release_id"] == "banes-lcwip-1.0"
    assert {"feature_id", "status", "length_m", "geom"}.issubset(columns)

    with zipfile.ZipFile(bundle / "lcwip-release.zip") as archive:
        assert archive.testzip() is None
        comment = json.loads(archive.comment)
        assert comment["release_id"] == "banes-lcwip-1.0"
        assert "lcwip-report.pdf" in archive.namelist()

    result = CliRunner().invoke(
        app,
        ["publication", "validate", str(bundle)],
    )
    assert result.exit_code == 0, result.output
    assert "valid banes-lcwip-1.0" in result.output


def test_recomputed_manifest_hash_cannot_hide_cross_content_mismatch(
    tmp_path: Path,
) -> None:
    manifest = validate_lcwip_publication(
        build_lcwip_publication(fixture_config(tmp_path))
    )
    payload = manifest.model_dump(mode="json")
    payload["unresolved_mandatory_requirement_ids"] = []
    payload["manifest_fingerprint"] = _fingerprint(
        {
            key: value
            for key, value in payload.items()
            if key != "manifest_fingerprint"
        }
    )
    with pytest.raises(ValidationError, match="mandatory gaps differ"):
        PublicationManifest.model_validate(payload)
