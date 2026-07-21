"""Governed ATM seeding, comparison and typed divergence review."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd

from satn.agents import (
    AgentRole,
    AgentRuntime,
    DivergenceAssessment,
    DivergenceInput,
)
from satn.models import CouncilConfig, DivergenceRecord
from satn.routing import RouteOption

if TYPE_CHECKING:
    from satn.compiler import CompiledNetwork


def load_atm(config: CouncilConfig) -> gpd.GeoDataFrame:
    if not config.atm.enabled:
        raise ValueError("ATM comparison is not enabled")
    if config.atm.path is None or not config.atm.path.exists():
        raise ValueError("ATM comparison requires an existing local atm.path")
    frame = gpd.read_file(config.atm.path)
    if frame.crs is None:
        raise ValueError("ATM reference geometry has no CRS")
    if frame.empty:
        raise ValueError("ATM reference geometry is empty")
    return frame


def source_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_seeded_alignment(
    options: list[RouteOption],
    atm: gpd.GeoDataFrame,
    left: object,
    right: object,
) -> RouteOption | None:
    if not options:
        return None
    projected_atm = atm.to_crs(27700)
    endpoints = gpd.GeoSeries([left, right], crs=atm.crs).to_crs(27700)
    candidates = projected_atm[
        (projected_atm.distance(endpoints.iloc[0]) <= 2000)
        & (projected_atm.distance(endpoints.iloc[1]) <= 2000)
    ]
    if candidates.empty:
        return None
    reference = candidates.geometry.union_all()
    ranked: list[tuple[float, RouteOption]] = []
    for option in options:
        geometry = gpd.GeoSeries([option.geometry], crs=atm.crs).to_crs(27700).iloc[0]
        ranked.append((geometry.hausdorff_distance(reference), option))
    return min(ranked, key=lambda item: item[0])[1]


def compare_atm(
    compiled: CompiledNetwork,
    atm: gpd.GeoDataFrame,
    runtime: AgentRuntime,
    config: CouncilConfig,
) -> list[DivergenceRecord]:
    connections = compiled.connections.to_crs(27700)
    reference = atm.to_crs(27700).copy().reset_index(drop=False)
    reference["_atm_id"] = [
        _feature_id(row, index) for index, row in reference.iterrows()
    ]
    reference_buffer = reference.geometry.buffer(config.atm.match_buffer_m).union_all()
    records: list[DivergenceRecord] = []
    matched_atm_ids: set[str] = set()

    for _, connection in connections.iterrows():
        geometry = connection.geometry
        overlap = (
            geometry.intersection(reference_buffer).length / geometry.length
            if geometry.length
            else 0
        )
        matched = reference[
            reference.geometry.buffer(config.atm.match_buffer_m).intersects(geometry)
        ]
        atm_ids = sorted(matched["_atm_id"].tolist())
        matched_atm_ids.update(atm_ids)
        status = "match" if overlap >= 0.7 else "deviation" if overlap > 0 else "addition"
        records.append(
            _assess(
                runtime,
                connection.connection_id,
                status,
                atm_ids,
                min(float(overlap), 1.0),
            )
        )

    for _, feature in reference.iterrows():
        atm_id = feature["_atm_id"]
        if atm_id in matched_atm_ids:
            continue
        records.append(_assess(runtime, f"atm:{atm_id}", "omission", [atm_id], 0.0))
    return records


def _assess(
    runtime: AgentRuntime,
    connection_id: str,
    status: str,
    atm_ids: list[str],
    overlap: float,
) -> DivergenceRecord:
    payload = DivergenceInput(
        connection_id=connection_id,
        status=status,
        atm_feature_ids=atm_ids,
        overlap_ratio=overlap,
    )
    try:
        reply = runtime.run(AgentRole.DIVERGENCE, payload, DivergenceAssessment)
        assessment = DivergenceAssessment.model_validate(reply.output)
        attempts = [assessment.model_dump() | {"attempt": 1, "tokens": reply.tokens}]
        return DivergenceRecord(
            connection_id=connection_id,
            status=status,
            atm_feature_ids=atm_ids,
            overlap_ratio=overlap,
            explanation=assessment.explanation,
            resolution_attempts=attempts,
            resolved=assessment.resolved,
        )
    except Exception as error:  # the governed record must survive provider failure
        return DivergenceRecord(
            connection_id=connection_id,
            status=status,
            atm_feature_ids=atm_ids,
            overlap_ratio=overlap,
            explanation=f"Divergence review failed: {error}",
            resolution_attempts=[{"attempt": 1, "error": str(error)}],
            resolved=False,
        )


def _feature_id(row: object, index: object) -> str:
    for key in ("portal_feature_id", "id", "fid", "osmid"):
        value = row.get(key)
        if value is not None and str(value).lower() not in {"nan", "none", ""}:
            return str(value)
    return str(index)
