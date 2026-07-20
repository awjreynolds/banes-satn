"""Stable orchestration API."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from satn.agents import runtime_for
from satn.compiler import compile_network
from satn.models import CompilationResult, CouncilConfig
from satn.publisher import publish
from satn.sources import load_snapshot


def compile(config: CouncilConfig | str | Path) -> CompilationResult:
    """Compile a council configuration into a complete current publication."""
    council = config if isinstance(config, CouncilConfig) else CouncilConfig.from_yaml(config)
    source = load_snapshot(council)
    runtime = runtime_for(council.compilation.agent.provider)
    compiled = compile_network(council, source, runtime)
    fingerprint = json.dumps(
        {
            "council": council.council_id,
            "snapshot": council.source.snapshot_id,
            "connections": sorted(compiled.connections.get("connection_id", [])),
        },
        sort_keys=True,
    )
    run_id = f"run-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12]}"
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
    )

