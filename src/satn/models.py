"""Typed contracts shared by the four compiler modules."""

from __future__ import annotations

from datetime import UTC, date, datetime
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


class NetworkScope(StrEnum):
    RURAL = "rural"
    URBAN = "urban"
    UNRESOLVED = "unresolved"


class OfficialRoadClassification(StrEnum):
    A_ROAD = "a-road"
    B_ROAD = "b-road"
    CLASSIFIED_UNNUMBERED = "classified-unnumbered"
    UNCLASSIFIED = "unclassified"
    UNKNOWN = "unknown"


class UrbanClassificationStatus(StrEnum):
    GOVERNED_OFFICIAL = "governed-official"
    EXPLICIT_UNKNOWN = "explicit-unknown"


class GovernedSpatialSourceConfig(BaseModel):
    path: Path
    source_id: str = Field(min_length=1)
    effective_date: date
    licence: str = Field(min_length=1)


class OfficialRoadClassificationConfig(GovernedSpatialSourceConfig):
    pass


class ObservedThroughTrafficConfig(GovernedSpatialSourceConfig):
    pass


class SourceConfig(BaseModel):
    kind: Literal["fixture", "osm"] = "fixture"
    fixture_dir: Path | None = None
    snapshot_dir: Path
    snapshot_id: str = "current"
    osm_place_query: str | None = None
    ncn_feature_service_url: str | None = None
    network_type: str = "bike"
    external_buffer_km: float = 15.0
    internal_portal_threshold_km: float = 1.0
    community_place_types: list[str] = Field(
        default_factory=lambda: ["town", "village", "suburb", "quarter", "neighbourhood"]
    )
    urban_place_types: list[str] = Field(
        default_factory=lambda: ["city", "town", "suburb", "quarter", "neighbourhood"]
    )
    urban_scope_buffer_km: float = Field(default=2.0, gt=0)
    strategic_destination_source_ids: list[str] = Field(default_factory=list)
    official_road_classification: OfficialRoadClassificationConfig | None = None
    observed_through_traffic: ObservedThroughTrafficConfig | None = None


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
    audience: Literal["public", "local"] = "public"


class CompilationConfig(BaseModel):
    max_connection_km: float = 15.0
    full: bool = False
    criteria_version: str = "1"
    cache_dir: Path = Path(".satn-cache")
    agent: AgentConfig = Field(default_factory=AgentConfig)


class ATMConfig(BaseModel):
    enabled: bool = False
    mode: Literal["blind", "seeded"] = "blind"
    path: Path | None = None
    redistribution_permitted: bool = False
    match_buffer_m: float = 100.0


class CouncilConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_path: Path
    council_id: str
    council_name: str
    source: SourceConfig
    compilation: CompilationConfig = Field(default_factory=CompilationConfig)
    atm: ATMConfig = Field(default_factory=ATMConfig)
    publication: PublicationConfig

    @model_validator(mode="after")
    def resolve_paths(self) -> CouncilConfig:
        root = self.config_path.parent
        if self.source.fixture_dir is not None and not self.source.fixture_dir.is_absolute():
            self.source.fixture_dir = (root / self.source.fixture_dir).resolve()
        if not self.source.snapshot_dir.is_absolute():
            self.source.snapshot_dir = (root / self.source.snapshot_dir).resolve()
        classification = self.source.official_road_classification
        if classification is not None and not classification.path.is_absolute():
            classification.path = (root / classification.path).resolve()
        observed_traffic = self.source.observed_through_traffic
        if observed_traffic is not None and not observed_traffic.path.is_absolute():
            observed_traffic.path = (root / observed_traffic.path).resolve()
        if not self.publication.output_dir.is_absolute():
            self.publication.output_dir = (root / self.publication.output_dir).resolve()
        if not self.compilation.cache_dir.is_absolute():
            self.compilation.cache_dir = (root / self.compilation.cache_dir).resolve()
        if self.atm.path is not None and not self.atm.path.is_absolute():
            self.atm.path = (root / self.atm.path).resolve()
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
    decision: Literal["accept", "gap", "superseded"]
    selected_role: str | None = None
    outcome_reason: str = ""
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DivergenceRecord(BaseModel):
    connection_id: str
    status: Literal["match", "omission", "deviation", "addition"]
    atm_feature_ids: list[str] = Field(default_factory=list)
    overlap_ratio: float = Field(ge=0, le=1)
    explanation: str
    resolution_attempts: list[dict[str, Any]] = Field(default_factory=list)
    resolved: bool = False


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
