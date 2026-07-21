"""Persistent cache for immutable Validated Connections."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from shapely import from_wkb

from satn.constants import SCHEMA_VERSION
from satn.models import AgentRecord, CouncilConfig


class ConnectionCache:
    def __init__(self, config: CouncilConfig, *, atm_fingerprint: str | None = None):
        self.config = config
        self.directory = config.compilation.cache_dir / "connections"
        self.directory.mkdir(parents=True, exist_ok=True)
        compilation = config.compilation.model_dump(mode="json", exclude={"full", "cache_dir"})
        snapshot_manifest = (
            config.source.snapshot_dir / config.source.snapshot_id / "snapshot.json"
        )
        snapshot_fingerprint = (
            hashlib.sha256(snapshot_manifest.read_bytes()).hexdigest()
            if snapshot_manifest.exists()
            else "missing"
        )
        governed = {
            "schema_version": SCHEMA_VERSION,
            "council_id": config.council_id,
            "snapshot_id": config.source.snapshot_id,
            "snapshot_fingerprint": snapshot_fingerprint,
            "compilation": compilation,
            "atm_mode": config.atm.mode if config.atm.enabled else "none",
            "atm_fingerprint": atm_fingerprint if config.atm.mode == "seeded" else None,
        }
        self.governed_fingerprint = hashlib.sha256(
            json.dumps(governed, sort_keys=True).encode()
        ).hexdigest()

    def load(
        self,
        pair: tuple[str, str],
    ) -> tuple[dict[str, object], AgentRecord] | None:
        if self.config.compilation.full:
            return None
        path = self._path(pair)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("governed_fingerprint") != self.governed_fingerprint:
            return None
        row = payload["connection"]
        row["geometry"] = from_wkb(bytes.fromhex(row.pop("geometry_wkb")))
        row["cache_status"] = "reused"
        record = AgentRecord.model_validate(payload["agent_record"])
        if record.decision != "accept" or row.get("status") != "validated":
            return None
        return row, record

    def store(
        self,
        pair: tuple[str, str],
        row: dict[str, object],
        record: AgentRecord,
    ) -> None:
        if record.decision != "accept" or row.get("status") != "validated":
            return
        connection = {key: value for key, value in row.items() if key != "geometry"}
        connection["geometry_wkb"] = row["geometry"].wkb.hex()
        connection["cache_status"] = "compiled"
        payload = {
            "governed_fingerprint": self.governed_fingerprint,
            "connection": connection,
            "agent_record": record.model_dump(mode="json"),
        }
        destination = self._path(pair)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}-", dir=self.directory
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _path(self, pair: tuple[str, str]) -> Path:
        digest = hashlib.sha256("::".join(sorted(pair)).encode()).hexdigest()[:16]
        return self.directory / f"{digest}.json"
