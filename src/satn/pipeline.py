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
        compiled.divergence_records = compare_atm(
            compiled, atm_reference, runtime, council
        )
        if (
            council.publication.audience == "local"
            or council.atm.redistribution_permitted
        ):
            compiled.atm_reference = atm_reference
        unresolved = any(not record.resolved for record in compiled.divergence_records)
        compiled.criteria["atm_comparison"] = {
            "comparison_available": TrafficLight.GREEN,
            "unresolved_divergences": (
                TrafficLight.AMBER if unresolved else TrafficLight.GREEN
            ),
        }
    run_fingerprint = json.dumps(
        {
            "council": council.council_id,
            "snapshot": council.source.snapshot_id,
            "connections": sorted(compiled.connections.get("connection_id", [])),
        },
        sort_keys=True,
    )
    run_id = f"run-{hashlib.sha256(run_fingerprint.encode()).hexdigest()[:12]}"
    artifacts = publish(council, compiled, run_id)
    return CompilationResult(
        run_id=run_id,
        status="complete" if compiled.gaps.empty else "reviewable",
        output_dir=council.publication.output_dir,
        connections=len(compiled.connections),
        gaps=len(compiled.gaps),
        artifacts=artifacts,
        criteria=compiled.criteria,
        agent_records=compiled.agent_records,
        metadata={
            "network_units": compiled.network_units,
            "cache": {"hits": compiled.cache_hits, "misses": compiled.cache_misses},
            "atm_mode": council.atm.mode if council.atm.enabled else "disabled",
            "atm_geometry_included": compiled.atm_reference is not None,
            "divergence_counts": dict(
                Counter(record.status for record in compiled.divergence_records)
            ),
        },
    )
