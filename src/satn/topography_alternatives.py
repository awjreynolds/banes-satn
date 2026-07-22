"""Bounded, evidence-led comparison of difficult Alignment Options."""

from __future__ import annotations

import json
from dataclasses import dataclass

import geopandas as gpd

from satn.models import TopographyComparisonStatus, TopographyConfig
from satn.routing import RouteOption
from satn.topography import GradientThresholds, build_topography_profiles


@dataclass(frozen=True)
class TopographyComparison:
    """Inspectable deterministic recommendation made before the Compilation Gate."""

    original: RouteOption
    selected: RouteOption
    triggered: bool
    status: TopographyComparisonStatus
    rationale: str
    assessments: dict[str, dict[str, object]]

    def serialise_options(
        self,
        options: list[RouteOption],
        selected_role: str | None,
    ) -> str:
        rows: list[dict[str, object]] = []
        for option in options:
            rows.append(
                option.summary()
                | {
                    "selected": option.role == selected_role,
                    "topography": self.assessments[option.role],
                }
            )
        return json.dumps(rows, sort_keys=True)


def compare_alignment_topography(
    selected: RouteOption | None,
    options: list[RouteOption],
    elevation_evidence: gpd.GeoDataFrame,
    config: TopographyConfig,
    crs: object,
) -> TopographyComparison | None:
    """Compare distinct plausible options when the selected alignment is challenging."""

    if selected is None:
        return None
    frames = gpd.GeoDataFrame(
        [
            {"option_id": option.role, "geometry": option.geometry}
            for option in options
        ],
        geometry="geometry",
        crs=crs,
    )
    profiles, sections = build_topography_profiles(
        [("alignment-option", "option_id", frames)],
        elevation_evidence,
        thresholds=GradientThresholds(
            gentle=config.gentle_max_pct,
            noticeable=config.noticeable_max_pct,
            steep=config.steep_max_pct,
            very_steep=config.very_steep_max_pct,
        ),
        maximum_sample_spacing_m=config.maximum_sample_spacing_m,
        minimum_sustained_spacing_m=config.minimum_sustained_spacing_m,
    )
    assessments = {
        option.role: _assessment(
            profiles[profiles["edge_id"] == option.role].iloc[0],
            sections[sections["edge_id"] == option.role],
            config,
        )
        for option in options
    }
    original = assessments[selected.role]
    triggered = bool(original["trigger_reasons"])
    if original["evidence_status"] != "available":
        return TopographyComparison(
            original=selected,
            selected=selected,
            triggered=False,
            status=TopographyComparisonStatus.EVIDENCE_UNAVAILABLE,
            rationale=(
                "Elevation Evidence is unavailable, so the original Alignment Option "
                "remains selected and the comparison is explicitly unresolved."
            ),
            assessments=assessments,
        )
    if not triggered:
        return TopographyComparison(
            original=selected,
            selected=selected,
            triggered=False,
            status=TopographyComparisonStatus.NOT_TRIGGERED,
            rationale="No governed Topography Alternative Trigger was met.",
            assessments=assessments,
        )
    trigger_text = "; ".join(str(item) for item in original["trigger_reasons"])
    if selected.role == "strategic-spine":
        return TopographyComparison(
            original=selected,
            selected=selected,
            triggered=True,
            status=TopographyComparisonStatus.STRATEGIC_SPINE_RETAINED,
            rationale=(
                f"{trigger_text}. The Strategic Spine remains selected because gradient "
                "does not remove a strategic corridor."
            ),
            assessments=assessments,
        )
    candidates = [
        option
        for option in options
        if option.role != selected.role
        and not option.geometry.equals(selected.geometry)
        and not option.geometry.is_empty
        and option.bidirectional
        and not option.impracticable_alongside
        and option.length_km
        <= selected.length_km * config.maximum_alternative_detour_ratio
        and _materially_easier(original, assessments[option.role], config)
    ]
    if not candidates:
        return TopographyComparison(
            original=selected,
            selected=selected,
            triggered=True,
            status=TopographyComparisonStatus.ORIGINAL_RETAINED,
            rationale=(
                f"{trigger_text}. No materially easier plausible Alignment Option was "
                "found within the bounded "
                f"{config.maximum_alternative_detour_ratio:g} detour ratio, so the "
                "original remains "
                "selected and visibly flagged."
            ),
            assessments=assessments,
        )
    easier = min(candidates, key=lambda option: _candidate_rank(option, assessments[option.role]))
    easier_assessment = assessments[easier.role]
    return TopographyComparison(
        original=selected,
        selected=easier,
        triggered=True,
        status=TopographyComparisonStatus.EASIER_ALTERNATIVE_SELECTED,
        rationale=(
            f"{trigger_text}. The {easier.role} Alignment Option is materially easier: "
            f"worst-direction cumulative ascent falls from "
            f"{float(original['worst_direction_ascent_m']):.1f} m to "
            f"{float(easier_assessment['worst_direction_ascent_m']):.1f} m within the "
            "bounded detour allowance."
        ),
        assessments=assessments,
    )


def _assessment(
    profile: object,
    sections: gpd.GeoDataFrame,
    config: TopographyConfig,
) -> dict[str, object]:
    evidence_status = str(profile["evidence_status"])
    forward_ascent = profile["forward_ascent_m"]
    reverse_ascent = profile["reverse_ascent_m"]
    worst_ascent = (
        max(float(forward_ascent), float(reverse_ascent))
        if evidence_status == "available"
        else None
    )
    trigger_reasons: list[str] = []
    thresholds = {
        "steep": config.steep_trigger_length_m,
        "very-steep": config.very_steep_trigger_length_m,
        "severe": config.severe_trigger_length_m,
    }
    labels = {"steep": "Steep", "very-steep": "Very Steep", "severe": "Severe"}
    for band, minimum_length in thresholds.items():
        matching = sections[sections["gradient_band"] == band]
        qualifying_length = float(matching["length_m"].max()) if not matching.empty else 0.0
        if qualifying_length >= minimum_length:
            trigger_reasons.append(
                f"{labels[band]} section sustained for {qualifying_length:.1f} m "
                f"(trigger {minimum_length:.0f} m)"
            )
    challenging = sections[
        sections["gradient_band"].isin(["steep", "very-steep", "severe"])
    ]
    repeated_climbs = max(
        int((challenging["uphill_direction"] == "forward").sum()),
        int((challenging["uphill_direction"] == "reverse").sum()),
    )
    if (
        not trigger_reasons
        and repeated_climbs >= config.repeated_climb_count
        and worst_ascent is not None
        and worst_ascent >= config.cumulative_ascent_trigger_m
    ):
        trigger_reasons.append(
            "Repeated shorter climbs produce "
            f"{worst_ascent:.1f} m worst-direction cumulative ascent "
            f"(trigger {config.cumulative_ascent_trigger_m:g} m)"
        )
    return {
        "evidence_status": evidence_status,
        "worst_direction_ascent_m": worst_ascent,
        "steepest_sustained_gradient_pct": (
            float(profile["steepest_sustained_gradient_pct"])
            if evidence_status == "available"
            else None
        ),
        "trigger_reasons": trigger_reasons,
    }


def _materially_easier(
    original: dict[str, object],
    candidate: dict[str, object],
    config: TopographyConfig,
) -> bool:
    if candidate["evidence_status"] != "available":
        return False
    original_reasons = list(original["trigger_reasons"])
    candidate_reasons = list(candidate["trigger_reasons"])
    original_ascent = float(original["worst_direction_ascent_m"])
    candidate_ascent = float(candidate["worst_direction_ascent_m"])
    if original_reasons and not candidate_reasons and candidate_ascent <= original_ascent:
        return True
    return original_ascent - candidate_ascent >= max(
        config.material_ascent_reduction_m,
        original_ascent * config.material_ascent_reduction_ratio,
    )


def _candidate_rank(
    option: RouteOption,
    assessment: dict[str, object],
) -> tuple[object, ...]:
    steepest = assessment["steepest_sustained_gradient_pct"]
    return (
        len(assessment["trigger_reasons"]),
        float(assessment["worst_direction_ascent_m"]),
        float(steepest) if steepest is not None else float("inf"),
        option.length_km,
        option.role,
    )
