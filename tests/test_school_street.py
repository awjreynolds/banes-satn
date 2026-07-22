from __future__ import annotations

import json

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.school_street import assess_school_street_candidates


def frame(rows: list[dict[str, object]]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        rows,
        columns=None if rows else ["geometry"],
        geometry="geometry",
        crs=27700,
    )


def schools(*rows: dict[str, object]) -> gpd.GeoDataFrame:
    return frame(list(rows))


def school(school_id: str, status: str, point: Point) -> dict[str, object]:
    return {
        "place_id": school_id,
        "evidence_id": school_id,
        "source_id": school_id,
        "name": school_id.replace("-", " ").title(),
        "school_kind": "primary",
        "access_point_status": status,
        "access_point_source_id": f"{school_id}-entrance" if status == "mapped" else None,
        "access_point_rationale": f"{status} entrance evidence",
        "geometry": point,
    }


def test_mapped_unclassified_school_with_complete_favourable_evidence_is_promising() -> None:
    network = frame(
        [
            {
                "osmid": "school-street",
                "highway": "residential",
                "bus": "no",
                "motor_vehicle": "no",
                "alternative_through_route": "yes",
                "displacement_risk": "no",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ]
    )
    official = frame(
        [
            {
                "official_feature_id": "official-u",
                "official_classification": "unclassified",
                "source_id": "highways-list",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ]
    )

    assessment = assess_school_street_candidates(
        schools(school("mapped-school", "mapped", Point(10, 0))),
        network,
        official,
    ).iloc[0]

    assert assessment["assessment_status"] == "green"
    assert assessment["assessment_label"] == "Promising"
    assert assessment["adjoining_road_classification"] == "unclassified"
    evidence = json.loads(assessment["evidence"])
    assert evidence["bus_access"] == "absent"
    assert evidence["essential_access"] == "absent"
    assert evidence["alternative_through_route"] == "present"
    assert evidence["displacement_risk"] == "absent"
    assert "not scheme feasibility or calibrated probability" in assessment["qualification"]


def test_classified_road_is_unlikely_but_inferred_entrance_cannot_be_red() -> None:
    network = frame(
        [
            {
                "osmid": "a-road",
                "highway": "primary",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ]
    )
    official = frame(
        [
            {
                "official_feature_id": "official-a",
                "official_classification": "a-road",
                "source_id": "highways-list",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ]
    )

    assessed = assess_school_street_candidates(
        schools(
            school("mapped-school", "mapped", Point(10, 0)),
            school("inferred-school", "inferred", Point(20, 0)),
        ),
        network,
        official,
    ).set_index("school_id")

    assert assessed.loc["mapped-school", "assessment_status"] == "red"
    assert assessed.loc["mapped-school", "assessment_label"] == "Unlikely"
    assert assessed.loc["inferred-school", "assessment_status"] == "amber"
    assert assessed.loc["inferred-school", "assessment_label"] == "Needs Investigation"
    assert "inferred" in assessed.loc["inferred-school", "rationale"].lower()


def test_unresolved_entrance_and_missing_evidence_remain_not_evaluated() -> None:
    assessed = assess_school_street_candidates(
        schools(school("unresolved-school", "unresolved", Point(10, 10))),
        frame([]),
        frame([]),
    ).iloc[0]

    assert assessed["assessment_status"] == "grey"
    assert assessed["assessment_label"] == "Not Evaluated"
    assert assessed["missing_evidence"]
    assert "unresolved" in assessed["rationale"].lower()
