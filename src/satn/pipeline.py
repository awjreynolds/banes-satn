"""Stable orchestration API."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from satn.agents import runtime_for
from satn.atm import compare_atm, load_atm, source_fingerprint
from satn.cache import ConnectionCache
from satn.compiler import compile_network
from satn.models import CompilationResult, CouncilConfig, TrafficLight
from satn.publisher import publish
from satn.sources import load_snapshot


def compile(config: CouncilConfig | str | Path) -> CompilationResult:
    """Compile a council configuration into a complete current publication."""
    council = config if isinstance(config, CouncilConfig) else CouncilConfig.from_yaml(config)
    source = load_snapshot(council)
    runtime = runtime_for(council.compilation.agent)
    atm_reference = None
    atm_seed = None
    atm_hash = None
    if council.atm.enabled and council.atm.mode == "seeded":
        atm_reference = load_atm(council).to_crs(source["network"].crs)
        atm_seed = atm_reference
        atm_hash = source_fingerprint(council.atm.path)
    cache = ConnectionCache(council, atm_fingerprint=atm_hash)
    compiled = compile_network(
        council,
        source,
        runtime,
        cache=cache,
        atm_seed=atm_seed,
    )
    if council.atm.enabled:
        if council.atm.mode == "blind":
            atm_reference = load_atm(council).to_crs(source["network"].crs)
        compiled.divergence_records = compare_atm(compiled, atm_reference, runtime, council)
        if council.publication.audience == "local" or council.atm.redistribution_permitted:
            compiled.atm_reference = atm_reference
        unresolved = any(not record.resolved for record in compiled.divergence_records)
        compiled.criteria["atm_comparison"] = {
            "comparison_available": TrafficLight.GREEN,
            "unresolved_divergences": (TrafficLight.AMBER if unresolved else TrafficLight.GREEN),
        }
    run_fingerprint = json.dumps(
        {
            "council": council.council_id,
            "snapshot": council.source.snapshot_id,
            "snapshot_manifest": hashlib.sha256(
                (
                    council.source.snapshot_dir / council.source.snapshot_id / "snapshot.json"
                ).read_bytes()
            ).hexdigest(),
            "connections": sorted(
                (
                    row.connection_id,
                    row.classification,
                    row.geometry.wkb_hex,
                )
                for row in compiled.connections.itertuples()
            ),
            "context": sorted(
                evidence_id
                for frame in (
                    compiled.a_road_spines,
                    compiled.ncn_routes,
                    compiled.schools,
                    compiled.retail_centres,
                    compiled.healthcare,
                )
                for evidence_id in frame.get("evidence_id", [])
            ),
            "school_street_assessments": sorted(
                (
                    row.assessment_id,
                    row.assessment_status,
                    row.rationale,
                    row.evidence,
                    row.geometry.wkb_hex,
                )
                for row in compiled.school_street_assessments.itertuples()
            ),
            "strategic_spines": sorted(compiled.strategic_spines["spine_id"]),
            "urban_classification_status": compiled.urban_classification_status,
            "urban_spines": sorted(
                (
                    row.structure_id,
                    row.official_classification,
                    row.source_id,
                    row.content_fingerprint,
                    row.geometry.wkb_hex,
                )
                for row in compiled.urban_spines.itertuples()
            ),
            "urban_classification_unknowns": sorted(
                (
                    row.structure_id,
                    row.official_feature_id,
                    row.source_id,
                    row.content_fingerprint,
                    row.geometry.wkb_hex,
                )
                for row in compiled.urban_classification_unknowns.itertuples()
            ),
            "candidate_low_traffic_areas": sorted(
                (
                    row.structure_id,
                    row.boundary_ids,
                    row.intervention_need,
                    row.observed_through_traffic_evidence_ids,
                    row.observed_through_traffic_source_ids,
                    row.geometry.wkb_hex,
                )
                for row in compiled.low_traffic_areas.itertuples()
            ),
            "low_traffic_area_portals": sorted(
                (
                    row.portal_id,
                    row.area_id,
                    row.boundary_id,
                    row.geometry.wkb_hex,
                )
                for row in compiled.low_traffic_area_portals.itertuples()
            ),
            "access_obligations": sorted(
                (
                    row.obligation_id,
                    row.service_status,
                    row.access_point_status,
                    row.access_point_source_id,
                    row.access_point_rationale,
                    row.low_traffic_area_id,
                    row.portal_id,
                    row.fabric_source_ids,
                    row.finding,
                    row.geometry.wkb_hex,
                )
                for row in compiled.access_obligations.itertuples()
            ),
            "spine_access_connections": sorted(
                (
                    row.access_connection_id,
                    row.community_id,
                    row.school_id,
                    row.access_point_status,
                    row.spine_id,
                    row.parent_target_id,
                    row.parent_target_name,
                    row.community_attachment_node,
                    row.community_attachment_distance_m,
                    row.spine_attachment_node,
                    row.spine_attachment_distance_m,
                    row.geometry.wkb_hex,
                )
                for row in compiled.spine_access_connections.itertuples()
            ),
            "spine_access_branches": sorted(
                (
                    row.branch_id,
                    row.root_spine_id,
                    row.connection_ids,
                    row.geometry.wkb_hex,
                )
                for row in compiled.spine_access_branches.itertuples()
            ),
            "branch_meeting_connections": sorted(
                (
                    row.meeting_connection_id,
                    row.from_place_id,
                    row.to_place_id,
                    row.from_root_spine_id,
                    row.to_root_spine_id,
                    row.geometry.wkb_hex,
                )
                for row in compiled.branch_meeting_connections.itertuples()
            ),
            "cross_spine_connectors": sorted(
                (
                    row.cross_spine_connector_id,
                    row.meeting_connection_id,
                    row.connection_ids,
                    row.geometry.wkb_hex,
                )
                for row in compiled.cross_spine_connectors.itertuples()
            ),
            "atm_mode": council.atm.mode if council.atm.enabled else "disabled",
        },
        sort_keys=True,
    )
    run_id = f"run-{hashlib.sha256(run_fingerprint.encode()).hexdigest()[:12]}"
    artifacts = publish(council, compiled, run_id)
    return CompilationResult(
        run_id=run_id,
        status=compiled.status,
        output_dir=council.publication.output_dir,
        connections=len(compiled.connections),
        gaps=len(compiled.gaps),
        artifacts=artifacts,
        criteria=compiled.criteria,
        agent_records=compiled.agent_records,
        metadata={
            "network_units": compiled.network_units,
            "urban_classification_status": compiled.urban_classification_status,
            "urban_spines": len(compiled.urban_spines),
            "urban_classification_unknowns": len(
                compiled.urban_classification_unknowns
            ),
            "urban_spine_records": [
                {
                    "structure_id": row.structure_id,
                    "official_classification": row.official_classification,
                    "official_feature_id": row.official_feature_id,
                    "source_id": row.source_id,
                    "effective_date": row.effective_date,
                    "licence": row.licence,
                    "content_fingerprint": row.content_fingerprint,
                    "classification_status": row.classification_status,
                    "intervention_assumption": row.intervention_assumption,
                }
                for row in compiled.urban_spines.itertuples()
            ],
            "urban_classification_unknown_records": [
                {
                    "structure_id": row.structure_id,
                    "official_feature_id": row.official_feature_id,
                    "source_id": row.source_id,
                    "effective_date": row.effective_date,
                    "licence": row.licence,
                    "content_fingerprint": row.content_fingerprint,
                    "classification_status": row.classification_status,
                }
                for row in compiled.urban_classification_unknowns.itertuples()
            ],
            "candidate_low_traffic_areas": len(compiled.low_traffic_areas),
            "low_traffic_area_portals": len(compiled.low_traffic_area_portals),
            "candidate_low_traffic_area_records": [
                {
                    "structure_id": row.structure_id,
                    "name": row.name,
                    "status": row.status,
                    "intervention_need": row.intervention_need,
                    "boundary_ids": row.boundary_ids,
                    "observed_through_traffic_evidence_ids": (
                        row.observed_through_traffic_evidence_ids
                    ),
                    "observed_through_traffic_source_ids": (
                        row.observed_through_traffic_source_ids
                    ),
                    "portal_count": row.portal_count,
                }
                for row in compiled.low_traffic_areas.itertuples()
            ],
            "low_traffic_area_portal_records": [
                {
                    "portal_id": row.portal_id,
                    "area_id": row.area_id,
                    "name": row.name,
                    "boundary_id": row.boundary_id,
                    "boundary_name": row.boundary_name,
                    "boundary_kind": row.boundary_kind,
                }
                for row in compiled.low_traffic_area_portals.itertuples()
            ],
            "strategic_spines": len(compiled.strategic_spines),
            "access_obligations": len(compiled.access_obligations),
            "school_access_obligations": int(
                (compiled.access_obligations["obligation_kind"] == "school").sum()
            ),
            "school_street_assessments": len(
                compiled.school_street_assessments
            ),
            "school_street_assessment_records": [
                {
                    "assessment_id": row.assessment_id,
                    "school_id": row.school_id,
                    "school_name": row.school_name,
                    "assessment_status": row.assessment_status,
                    "assessment_label": row.assessment_label,
                    "rationale": row.rationale,
                    "qualification": row.qualification,
                    "access_point_status": row.access_point_status,
                    "adjoining_road_classification": (
                        row.adjoining_road_classification
                    ),
                    "bus_access": row.bus_access,
                    "essential_access": row.essential_access,
                    "alternative_through_route": row.alternative_through_route,
                    "displacement_risk": row.displacement_risk,
                    "missing_evidence": row.missing_evidence,
                    "evidence": row.evidence,
                    "source_ids": row.source_ids,
                }
                for row in compiled.school_street_assessments.itertuples()
            ],
            "spine_access_connections": len(compiled.spine_access_connections),
            "spine_access_branches": len(compiled.spine_access_branches),
            "branch_meeting_connections": len(compiled.branch_meeting_connections),
            "cross_spine_connectors": len(compiled.cross_spine_connectors),
            "strategic_spine_records": [
                {
                    "spine_id": row.spine_id,
                    "evidence_id": row.evidence_id,
                    "source_id": row.source_id,
                    "provenance": row.provenance,
                }
                for row in compiled.strategic_spines.itertuples()
            ],
            "access_obligation_records": [
                {
                    "obligation_id": row.obligation_id,
                    "community_id": row.community_id,
                    "school_id": row.school_id,
                    "school_kind": row.school_kind,
                    "service_status": row.service_status,
                    "service_rationale": row.service_rationale,
                    "access_point_status": row.access_point_status,
                    "access_point_source_id": row.access_point_source_id,
                    "access_point_rationale": row.access_point_rationale,
                    "access_connection_id": row.access_connection_id,
                    "root_spine_id": row.root_spine_id,
                    "branch_id": row.branch_id,
                    "network_scope": row.network_scope,
                    "criterion_continuity": row.criterion_continuity,
                    "low_traffic_area_id": row.low_traffic_area_id,
                    "low_traffic_area_name": row.low_traffic_area_name,
                    "portal_id": row.portal_id,
                    "portal_name": row.portal_name,
                    "urban_spine_id": row.urban_spine_id,
                    "fabric_source_ids": row.fabric_source_ids,
                    "supporting_evidence": row.supporting_evidence,
                    "finding": row.finding,
                    "geometry_semantics": row.geometry_semantics,
                    "provenance": row.provenance,
                }
                for row in compiled.access_obligations.itertuples()
            ],
            "spine_access_connection_records": [
                {
                    "access_connection_id": row.access_connection_id,
                    "place_id": row.place_id,
                    "place_kind": row.place_kind,
                    "community_id": row.community_id,
                    "school_id": row.school_id,
                    "school_kind": row.school_kind,
                    "access_point_status": row.access_point_status,
                    "access_point_source_id": row.access_point_source_id,
                    "access_point_rationale": row.access_point_rationale,
                    "spine_id": row.spine_id,
                    "root_spine_id": row.root_spine_id,
                    "branch_id": row.branch_id,
                    "parent_branch_id": row.parent_branch_id,
                    "parent_role": row.parent_role,
                    "parent_target_id": row.parent_target_id,
                    "parent_target_name": row.parent_target_name,
                    "parent_place_id": row.parent_place_id,
                    "parent_access_connection_id": row.parent_access_connection_id,
                    "attachment_depth": row.attachment_depth,
                    "community_attachment_node": row.community_attachment_node,
                    "community_attachment_distance_m": row.community_attachment_distance_m,
                    "community_attachment_point": row.community_attachment_point,
                    "spine_attachment_node": row.spine_attachment_node,
                    "spine_attachment_distance_m": row.spine_attachment_distance_m,
                    "spine_attachment_point": row.spine_attachment_point,
                    "source_ids": row.source_ids,
                    "provenance": row.provenance,
                }
                for row in compiled.spine_access_connections.itertuples()
            ],
            "spine_access_branch_records": [
                {
                    "branch_id": row.branch_id,
                    "root_spine_id": row.root_spine_id,
                    "connection_ids": row.connection_ids,
                    "place_ids": row.place_ids,
                    "provenance": row.provenance,
                }
                for row in compiled.spine_access_branches.itertuples()
            ],
            "branch_meeting_connection_records": [
                {
                    "meeting_connection_id": row.meeting_connection_id,
                    "from_place_id": row.from_place_id,
                    "to_place_id": row.to_place_id,
                    "from_root_spine_id": row.from_root_spine_id,
                    "to_root_spine_id": row.to_root_spine_id,
                    "source_ids": row.source_ids,
                    "provenance": row.provenance,
                }
                for row in compiled.branch_meeting_connections.itertuples()
            ],
            "cross_spine_connector_records": [
                {
                    "cross_spine_connector_id": row.cross_spine_connector_id,
                    "meeting_connection_id": row.meeting_connection_id,
                    "branch_ids": row.branch_ids,
                    "connection_ids": row.connection_ids,
                    "source_ids": row.source_ids,
                    "provenance": row.provenance,
                }
                for row in compiled.cross_spine_connectors.itertuples()
            ],
            "superseded_hypotheses": compiled.superseded_hypotheses,
            "cache": {"hits": compiled.cache_hits, "misses": compiled.cache_misses},
            "atm_mode": council.atm.mode if council.atm.enabled else "disabled",
            "atm_geometry_included": compiled.atm_reference is not None,
            "divergence_counts": dict(
                Counter(record.status for record in compiled.divergence_records)
            ),
        },
    )
