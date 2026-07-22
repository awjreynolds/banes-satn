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
            "strategic_spines": sorted(compiled.strategic_spines["spine_id"]),
            "access_obligations": sorted(compiled.access_obligations["obligation_id"]),
            "spine_access_connections": sorted(
                (
                    row.access_connection_id,
                    row.community_id,
                    row.spine_id,
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
            "strategic_spines": len(compiled.strategic_spines),
            "access_obligations": len(compiled.access_obligations),
            "spine_access_connections": len(compiled.spine_access_connections),
            "spine_access_branches": len(compiled.spine_access_branches),
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
                    "service_status": row.service_status,
                    "access_connection_id": row.access_connection_id,
                    "root_spine_id": row.root_spine_id,
                    "branch_id": row.branch_id,
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
                    "spine_id": row.spine_id,
                    "root_spine_id": row.root_spine_id,
                    "branch_id": row.branch_id,
                    "parent_branch_id": row.parent_branch_id,
                    "parent_role": row.parent_role,
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
            "superseded_hypotheses": compiled.superseded_hypotheses,
            "cache": {"hits": compiled.cache_hits, "misses": compiled.cache_misses},
            "atm_mode": council.atm.mode if council.atm.enabled else "disabled",
            "atm_geometry_included": compiled.atm_reference is not None,
            "divergence_counts": dict(
                Counter(record.status for record in compiled.divergence_records)
            ),
        },
    )
