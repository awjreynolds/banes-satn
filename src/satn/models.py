"""Typed contracts shared by the four compiler modules."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrafficLight(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    GREY = "grey"


class SourceConfig(BaseModel):
    kind: Literal["fixture", "osm"] = "fixture"
    fixture_dir: Path | None = None
    snapshot_dir: Path
    snapshot_id: str = "current"
    osm_place_query: str | None = None
    network_type: str = "bike"
    external_buffer_km: float = 15.0
    internal_portal_threshold_km: float = 1.0
    community_place_types: list[str] = Field(
        default_factory=lambda: ["town", "village", "suburb", "quarter", "neighbourhood"]
    )
    urban_place_types: list[str] = Field(
        default_factory=lambda: ["suburb", "quarter", "neighbourhood"]
    )


class AgentConfig(BaseModel):
    provider: str = "fake"
    model: str | None = None
    enabled: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_requests: int = Field(default=12, ge=1)
    max_tokens: int = Field(default=4000, ge=100)


class PublicationConfig(BaseModel):
    output_dir: Path
    title: str
    pdf_page_size: str = "A3"


class CompilationConfig(BaseModel):
    max_connection_km: float = 15.0
    full: bool = False
    agent: AgentConfig = Field(default_factory=AgentConfig)


class CouncilConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    council_id: str
    council_name: str
    source: SourceConfig
    compilation: CompilationConfig = Field(default_factory=CompilationConfig)
    publication: PublicationConfig

    @model_validator(mode="after")
    def resolve_paths(self) -> CouncilConfig:
        root = self.config_path.parent
        if self.source.fixture_dir is not None and not self.source.fixture_dir.is_absolute():
            self.source.fixture_dir = (root / self.source.fixture_dir).resolve()
        if not self.source.snapshot_dir.is_absolute():
            self.source.snapshot_dir = (root / self.source.snapshot_dir).resolve()
        if not self.publication.output_dir.is_absolute():
            self.publication.output_dir = (root / self.publication.output_dir).resolve()
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> CouncilConfig:
        config_path = Path(path).resolve()
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return cls(config_path=config_path, **raw)


class AgentRecord(BaseModel):
    connection_id: str
    runtime: str
    model: str
    proposal: str
    critique: str
    revision: str
    decision: Literal["accept", "gap"]
    selected_role: str | None = None
    outcome_reason: str = ""
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompilationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    status: Literal["reviewable", "complete"]
    output_dir: Path
    connections: int
    gaps: int
    artifacts: dict[str, Path]
    criteria: dict[str, dict[str, TrafficLight]]
    agent_records: list[AgentRecord]
    metadata: dict[str, Any] = Field(default_factory=dict)
