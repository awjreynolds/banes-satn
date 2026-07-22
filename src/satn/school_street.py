"""Preliminary evidence-backed School Street Candidate Assessments."""

from __future__ import annotations

import json
from enum import StrEnum

import geopandas as gpd
import pandas as pd

from satn.identifiers import stable_id
from satn.models import AccessPointStatus, OfficialRoadClassification, TrafficLight

ADJOINING_EVIDENCE_M = 20.0
ASSESSMENT_QUALIFICATION = (
    "Qualitative plausibility for investigation; not scheme feasibility or calibrated probability."
)

SCHOOL_STREET_COLUMNS = [
    "assessment_id",
    "school_id",
    "school_name",
    "school_kind",
    "assessment_status",
    "assessment_label",
    "rationale",
    "qualification",
    "access_point_status",
    "access_point_source_id",
    "adjoining_road_classification",
    "adjoining_road_source_id",
    "bus_access",
    "essential_access",
    "alternative_through_route",
    "displacement_risk",
    "missing_evidence",
    "evidence",
    "source_ids",
    "geometry",
]


class EvidenceState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


ASSESSMENT_LABELS = {
    TrafficLight.GREEN: "Promising",
    TrafficLight.AMBER: "Needs Investigation",
    TrafficLight.RED: "Unlikely",
    TrafficLight.GREY: "Not Evaluated",
}


def assess_school_street_candidates(
    schools: gpd.GeoDataFrame,
    network: gpd.GeoDataFrame,
    official_classification: gpd.GeoDataFrame | None,
) -> gpd.GeoDataFrame:
    """Assess every supplied School conservatively from inspectable evidence."""
    crs = schools.crs or network.crs
    if schools.empty:
        return gpd.GeoDataFrame(
            columns=SCHOOL_STREET_COLUMNS,
            geometry="geometry",
            crs=crs,
        )
    projected_schools = schools.to_crs(27700)
    projected_network = network.to_crs(27700)
    projected_official = (
        official_classification.to_crs(27700)
        if official_classification is not None and not official_classification.empty
        else gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=27700)
    )
    rows: list[dict[str, object]] = []
    for _, school in projected_schools.sort_values("place_id").iterrows():
        school_id = str(school["place_id"])
        access_status = _access_point_status(school.get("access_point_status"))
        adjoining_network = _adjoining(projected_network, school.geometry)
        adjoining_official = _adjoining(projected_official, school.geometry)
        road_classification, road_source_id = _road_classification(adjoining_official)
        bus_access = _tag_evidence(
            adjoining_network,
            keys=("bus", "psv"),
            present={"yes", "designated", "permissive"},
            absent={"no"},
        )
        essential_access = _essential_access_evidence(adjoining_network)
        alternative_route = _tag_evidence(
            adjoining_network,
            keys=("alternative_through_route",),
            present={"yes", "available", "present"},
            absent={"no", "unavailable", "absent"},
        )
        displacement_risk = _tag_evidence(
            adjoining_network,
            keys=("displacement_risk",),
            present={"yes", "high", "present"},
            absent={"no", "low", "absent"},
        )
        evidence = {
            "usable_entrance": access_status.value,
            "adjoining_road_classification": road_classification,
            "bus_access": bus_access.value,
            "essential_access": essential_access.value,
            "alternative_through_route": alternative_route.value,
            "displacement_risk": displacement_risk.value,
        }
        missing = sorted(
            key
            for key, value in evidence.items()
            if value in {EvidenceState.UNKNOWN.value, AccessPointStatus.UNRESOLVED.value}
            or (key == "adjoining_road_classification" and value == "unknown")
        )
        status, rationale = _assessment(
            access_status,
            road_classification,
            bus_access,
            essential_access,
            alternative_route,
            displacement_risk,
            missing,
        )
        network_source_ids = sorted(
            {_source_id(row, index) for index, row in adjoining_network.iterrows()}
        )
        source_ids = sorted(
            {
                str(school.get("source_id") or school_id),
                *network_source_ids,
                *([road_source_id] if road_source_id else []),
                *(
                    [str(school.get("access_point_source_id"))]
                    if school.get("access_point_source_id")
                    else []
                ),
            }
        )
        rows.append(
            {
                "assessment_id": stable_id("school-street-assessment", school_id),
                "school_id": school_id,
                "school_name": school.get("name"),
                "school_kind": school.get("school_kind"),
                "assessment_status": status.value,
                "assessment_label": ASSESSMENT_LABELS[status],
                "rationale": rationale,
                "qualification": ASSESSMENT_QUALIFICATION,
                "access_point_status": access_status.value,
                "access_point_source_id": school.get("access_point_source_id"),
                "adjoining_road_classification": road_classification,
                "adjoining_road_source_id": road_source_id,
                "bus_access": bus_access.value,
                "essential_access": essential_access.value,
                "alternative_through_route": alternative_route.value,
                "displacement_risk": displacement_risk.value,
                "missing_evidence": json.dumps(missing),
                "evidence": json.dumps(evidence, sort_keys=True),
                "source_ids": json.dumps(source_ids),
                "geometry": school.geometry,
            }
        )
    return gpd.GeoDataFrame(
        rows,
        columns=SCHOOL_STREET_COLUMNS,
        geometry="geometry",
        crs=27700,
    ).to_crs(crs)


def _assessment(
    access_status: AccessPointStatus,
    road_classification: str,
    bus_access: EvidenceState,
    essential_access: EvidenceState,
    alternative_route: EvidenceState,
    displacement_risk: EvidenceState,
    missing: list[str],
) -> tuple[TrafficLight, str]:
    if access_status is AccessPointStatus.UNRESOLVED:
        return (
            TrafficLight.GREY,
            "Not evaluated because the usable School entrance is unresolved; missing "
            f"evidence: {', '.join(missing)}. {ASSESSMENT_QUALIFICATION}",
        )
    if access_status is AccessPointStatus.INFERRED:
        return (
            TrafficLight.AMBER if len(missing) < 5 else TrafficLight.GREY,
            "The entrance is inferred, so the assessment cannot be definitively Green "
            f"or Red. Missing evidence: {', '.join(missing) or 'none'}. "
            f"{ASSESSMENT_QUALIFICATION}",
        )
    if road_classification in {
        OfficialRoadClassification.A_ROAD.value,
        OfficialRoadClassification.B_ROAD.value,
        OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value,
    }:
        return (
            TrafficLight.RED,
            "The mapped entrance adjoins an official through-traffic road, making a "
            "timed School Street restriction unlikely at that entrance. "
            f"Missing evidence: {', '.join(missing) or 'none'}. "
            f"{ASSESSMENT_QUALIFICATION}",
        )
    favourable = (
        road_classification == OfficialRoadClassification.UNCLASSIFIED.value
        and bus_access is EvidenceState.ABSENT
        and essential_access is EvidenceState.ABSENT
        and alternative_route is EvidenceState.PRESENT
        and displacement_risk is EvidenceState.ABSENT
    )
    if favourable and not missing:
        return (
            TrafficLight.GREEN,
            "The mapped entrance adjoins an unclassified street, bus and essential "
            "access are recorded absent, an alternative through route is recorded and "
            f"displacement risk is recorded low. {ASSESSMENT_QUALIFICATION}",
        )
    return (
        TrafficLight.AMBER,
        "The mapped entrance has some usable evidence but bus/essential access, "
        "alternative routing or displacement needs investigation. Missing evidence: "
        f"{', '.join(missing) or 'none'}. {ASSESSMENT_QUALIFICATION}",
    )


def _adjoining(frame: gpd.GeoDataFrame, geometry: object) -> gpd.GeoDataFrame:
    if frame.empty:
        return frame
    return frame[frame.geometry.distance(geometry) <= ADJOINING_EVIDENCE_M].copy()


def _road_classification(frame: gpd.GeoDataFrame) -> tuple[str, str | None]:
    if frame.empty or "official_classification" not in frame:
        return OfficialRoadClassification.UNKNOWN.value, None
    priority = {
        OfficialRoadClassification.A_ROAD.value: 0,
        OfficialRoadClassification.B_ROAD.value: 1,
        OfficialRoadClassification.CLASSIFIED_UNNUMBERED.value: 2,
        OfficialRoadClassification.UNCLASSIFIED.value: 3,
        OfficialRoadClassification.UNKNOWN.value: 4,
    }
    selected = min(
        frame.iterrows(),
        key=lambda item: (
            priority.get(str(item[1].get("official_classification")), 5),
            str(item[1].get("official_feature_id") or item[0]),
        ),
    )[1]
    classification = str(
        selected.get("official_classification") or OfficialRoadClassification.UNKNOWN.value
    )
    return classification, str(selected.get("source_id") or "") or None


def _essential_access_evidence(frame: gpd.GeoDataFrame) -> EvidenceState:
    explicit = _tag_evidence(
        frame,
        keys=("essential_access",),
        present={"yes", "required", "present"},
        absent={"no", "absent"},
    )
    if explicit is not EvidenceState.UNKNOWN:
        return explicit
    return _tag_evidence(
        frame,
        keys=("access", "motor_vehicle", "vehicle", "emergency"),
        present={"destination", "delivery", "customers", "private", "permit", "yes"},
        absent={"no"},
    )


def _tag_evidence(
    frame: gpd.GeoDataFrame,
    *,
    keys: tuple[str, ...],
    present: set[str],
    absent: set[str],
) -> EvidenceState:
    values = {
        str(row.get(key) or "").strip().lower()
        for _, row in frame.iterrows()
        for key in keys
        if str(row.get(key) or "").strip()
    }
    if values & present:
        return EvidenceState.PRESENT
    if values & absent:
        return EvidenceState.ABSENT
    return EvidenceState.UNKNOWN


def _access_point_status(value: object) -> AccessPointStatus:
    try:
        return AccessPointStatus(str(value))
    except ValueError:
        return AccessPointStatus.UNRESOLVED


def _source_id(row: pd.Series, fallback: object) -> str:
    for key in ("source_id", "osmid", "osm_id", "id"):
        value = row.get(key)
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(fallback)
