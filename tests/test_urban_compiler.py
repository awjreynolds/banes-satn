from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import FakeAgentRuntime
from satn.compiler import compile_network
from satn.models import CouncilConfig
from satn.routing import RoadGraph, choose_alignment
from satn.urban import derive_urban_structure


def test_urban_spines_and_low_traffic_fabrics_share_one_representation() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "neighbourhood",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "portal-west",
                "name": "West portal",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "urban-centre",
                "geometry": Point(-0.01, 0),
            },
            {
                "place_id": "portal-east",
                "name": "East portal",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "urban-centre",
                "geometry": Point(0.01, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "main",
                "highway": "primary",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            },
            {
                "osmid": "minor-west",
                "highway": "residential",
                "geometry": LineString([(-0.015, 0), (-0.005, 0)]),
            },
            {
                "osmid": "minor-west-2",
                "highway": "residential",
                "geometry": LineString([(-0.005, 0), (-0.005, 0.005)]),
            },
            {
                "osmid": "minor-east",
                "highway": "unclassified",
                "geometry": LineString([(0.005, 0), (0.015, 0)]),
            },
            {
                "osmid": "minor-east-2",
                "highway": "residential",
                "geometry": LineString([(0.005, 0), (0.005, 0.005)]),
            },
        ],
        crs=4326,
    )
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": f"official-a-{index}",
                "official_classification": "a-road",
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "Open Government Licence v3.0",
                "content_fingerprint": "abc123",
                "geometry": geometry,
            }
            for index, geometry in enumerate(
                (
                    LineString([(0, -0.02), (0, -0.01), (0, 0), (0, 0.01), (0, 0.02)]),
                    LineString([(-0.01, -0.01), (-0.01, 0.01)]),
                    LineString([(0.01, -0.01), (0.01, 0.01)]),
                    LineString([(-0.01, -0.01), (0, -0.01), (0.01, -0.01)]),
                    LineString([(-0.01, 0.01), (0, 0.01), (0.01, 0.01)]),
                ),
                start=1,
            )
        ],
        crs=4326,
    )

    urban = derive_urban_structure(places, network, official)
    spines = urban.spines
    unknowns = urban.classification_unknowns
    areas = urban.low_traffic_areas
    portals = urban.low_traffic_area_portals

    assert len(spines) == 5
    assert set(spines["role"]) == {"urban-main-road-spine"}
    assert set(spines["intervention"]) == {"protected-cycle-infrastructure"}
    assert set(spines["official_classification"]) == {"a-road"}
    assert set(spines["classification_status"]) == {"governed-official"}
    assert unknowns.empty
    assert "Major engineering" in spines.iloc[0]["intervention_assumption"]
    assert len(areas) == 2
    assert set(areas["role"]) == {"candidate-low-traffic-area"}
    assert areas.iloc[0].geometry.geom_type in {"Polygon", "MultiPolygon"}
    projected_spine = spines.to_crs(27700).iloc[0].geometry
    assert all(not geometry.crosses(projected_spine) for geometry in areas.to_crs(27700).geometry)
    assert len(portals) == 2
    assert portals["portal_id"].is_unique
    assert set(portals["area_id"]) == set(areas["structure_id"])
    assert all("A road" in name for name in portals["name"])


def test_geojson_array_tags_preserve_urban_fabric_and_a_road_routing(tmp_path: Path) -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "neighbourhood",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "main",
                "highway": ["primary"],
                "ref": ["A4"],
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            },
            {
                "osmid": "minor-west",
                "highway": ["residential"],
                "geometry": LineString([(-0.01, 0), (-0.005, 0)]),
            },
            {
                "osmid": "minor-west-2",
                "highway": ["residential"],
                "geometry": LineString([(-0.005, 0), (-0.005, 0.005)]),
            },
            {
                "osmid": "minor-east",
                "highway": ["unclassified"],
                "geometry": LineString([(0.005, 0), (0.01, 0)]),
            },
            {
                "osmid": "minor-east-2",
                "highway": ["residential"],
                "geometry": LineString([(0.005, 0), (0.005, 0.005)]),
            },
        ],
        crs=4326,
    )
    network_path = tmp_path / "network.geojson"
    network.to_file(network_path, driver="GeoJSON")
    reloaded = gpd.read_file(network_path)
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": f"official-a-{index}",
                "official_classification": "a-road",
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "Open Government Licence v3.0",
                "content_fingerprint": "abc123",
                "geometry": geometry,
            }
            for index, geometry in enumerate(
                (
                    LineString([(0, -0.02), (0, 0.02)]),
                    LineString([(-0.01, -0.01), (-0.01, 0.01)]),
                    LineString([(0.01, -0.01), (0.01, 0.01)]),
                    LineString([(-0.01, -0.01), (0.01, -0.01)]),
                    LineString([(-0.01, 0.01), (0.01, 0.01)]),
                ),
                start=1,
            )
        ],
        crs=4326,
    )

    urban = derive_urban_structure(places, reloaded, official)
    graph = RoadGraph(reloaded)
    selected, _, _ = choose_alignment(
        graph,
        graph.nearest_node(Point(0, -0.02))[0],
        graph.nearest_node(Point(0, 0.02))[0],
    )

    assert type(reloaded.iloc[0]["highway"]).__name__ == "ndarray"
    assert len(urban.low_traffic_areas) == 2
    assert selected is not None
    assert selected.role == "strategic-spine"
    assert selected.a_road_share == 1


def test_tuple_and_set_tags_preserve_a_road_routing_semantics() -> None:
    for highway in (("primary",), {"primary"}):
        graph = RoadGraph(
            gpd.GeoDataFrame(
                [
                    {
                        "osmid": "main",
                        "highway": highway,
                        "ref": ("A4",) if isinstance(highway, tuple) else {"A4"},
                        "geometry": LineString([(0, 0), (0.01, 0)]),
                    }
                ],
                crs=4326,
            )
        )

        selected, _, _ = choose_alignment(
            graph,
            graph.nearest_node(Point(0, 0))[0],
            graph.nearest_node(Point(0.01, 0))[0],
        )

        assert selected is not None
        assert selected.role == "strategic-spine"
        assert selected.a_road_share == 1


def test_osm_tags_do_not_override_missing_or_unclassified_official_evidence() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "osm-primary",
                "highway": "primary",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            }
        ],
        crs=4326,
    )
    unclassified = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": "official-u",
                "official_classification": "unclassified",
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "abc123",
                "geometry": LineString([(0, -0.02), (0, 0.02)]),
            }
        ],
        crs=4326,
    )

    missing = derive_urban_structure(places, network)
    unclassified_result = derive_urban_structure(places, network, unclassified)

    assert missing.spines.empty
    assert missing.classification_unknowns.empty
    assert unclassified_result.spines.empty
    assert unclassified_result.classification_unknowns.empty

    unknown = unclassified.copy()
    unknown["official_classification"] = "unknown"
    unknowns = derive_urban_structure(places, network, unknown).classification_unknowns
    assert len(unknowns) == 1
    assert unknowns.iloc[0]["classification_status"] == "explicit-unknown"
    assert unknowns.iloc[0]["role"] == "urban-road-classification-unknown"


def test_official_a_b_and_classified_unnumbered_are_stable_urban_spines() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "minor",
                "highway": "residential",
                "geometry": LineString([(-0.02, 0), (0.02, 0)]),
            }
        ],
        crs=4326,
    )
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": f"official-{classification}",
                "official_classification": classification,
                "source_id": "council-highways",
                "effective_date": "2026-01-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "abc123",
                "geometry": LineString([(offset, -0.01), (offset, 0.01)]),
            }
            for classification, offset in (
                ("a-road", -0.005),
                ("b-road", 0.0),
                ("classified-unnumbered", 0.005),
            )
        ],
        crs=4326,
    )

    first = derive_urban_structure(places, network, official)
    second = derive_urban_structure(places, network, official)

    assert set(first.spines["official_classification"]) == {
        "a-road",
        "b-road",
        "classified-unnumbered",
    }
    assert list(first.spines["structure_id"]) == list(second.spines["structure_id"])
    assert set(first.spines["source_id"]) == {"council-highways"}
    assert first.classification_unknowns.empty
    assert second.classification_unknowns.empty
    assert list(first.low_traffic_area_portals["portal_id"]) == list(
        second.low_traffic_area_portals["portal_id"]
    )


def test_governed_urban_a_road_evidence_extends_the_urban_spine_extent() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=27700,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "urban-street",
                "highway": "residential",
                "geometry": LineString([(-100, 0), (100, 0)]),
            }
        ],
        crs=27700,
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "urban-a-evidence",
                "feature_type": "a-road-spine",
                "network_scope": "urban",
                "geometry": LineString([(2500, -100), (2500, 100)]),
            },
            {
                "evidence_id": "rural-a-evidence",
                "feature_type": "a-road-spine",
                "network_scope": "rural",
                "geometry": LineString([(3500, -100), (3500, 100)]),
            },
        ],
        crs=27700,
    )
    official = gpd.GeoDataFrame(
        [
            {
                "official_feature_id": feature_id,
                "official_classification": "a-road",
                "source_id": "official-roads",
                "effective_date": "2026-01-01",
                "licence": "OGL v3.0",
                "content_fingerprint": "abc123",
                "geometry": geometry,
            }
            for feature_id, geometry in (
                ("urban-a", LineString([(2530, -100), (2530, 100)])),
                ("rural-a", LineString([(3530, -100), (3530, 100)])),
            )
        ],
        crs=27700,
    )

    urban = derive_urban_structure(places, network, official, context)

    assert list(urban.spines["official_feature_id"]) == ["urban-a"]
    assert urban.spines.iloc[0]["role"] == "urban-main-road-spine"


def test_compiler_requires_every_urban_a_road_evidence_segment_to_have_an_official_spine() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": place_id,
                "name": name,
                "kind": "community",
                "place_class": "town",
                "geometry": Point(x, 0),
            }
            for place_id, name, x in (
                ("west", "West", 0),
                ("east", "East", 100),
            )
        ],
        crs=27700,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "urban-street",
                "highway": "residential",
                "geometry": LineString([(0, 0), (100, 0)]),
            }
        ],
        crs=27700,
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": f"urban-a-{index}",
                "feature_type": "a-road-spine",
                "name": f"A{index}",
                "category": "A-road strategic spine",
                "source_id": f"osm-a-{index}",
                "network_scope": "urban",
                "geometry": geometry,
            }
            for index, geometry in enumerate(
                (
                    LineString([(0, 0), (1000, 0)]),
                    LineString([(0, 500), (1000, 500)]),
                ),
                start=1,
            )
        ],
        crs=27700,
    )

    def official_roads(*, include_second_a_road: bool) -> gpd.GeoDataFrame:
        roads = [
            ("official-a-1", "a-road", LineString([(0, 40), (1000, 40)])),
            ("official-b-extra", "b-road", LineString([(0, 900), (1000, 900)])),
        ]
        if include_second_a_road:
            roads.append(("official-a-2", "a-road", LineString([(0, 540), (1000, 540)])))
        return gpd.GeoDataFrame(
            [
                {
                    "official_feature_id": feature_id,
                    "official_classification": classification,
                    "source_id": "official-roads",
                    "effective_date": "2026-01-01",
                    "licence": "OGL v3.0",
                    "content_fingerprint": "abc123",
                    "geometry": geometry,
                }
                for feature_id, classification, geometry in roads
            ],
            crs=27700,
        )

    config = CouncilConfig.from_yaml(
        Path(__file__).parents[1] / "examples" / "fixture" / "council.yaml"
    )
    source = {
        "places": places,
        "network": network,
        "boundary": gpd.GeoDataFrame(geometry=[], crs=27700),
        "context": context,
    }
    missing = compile_network(
        config,
        source | {"official_road_classification": official_roads(include_second_a_road=False)},
        FakeAgentRuntime(),
    )
    represented = compile_network(
        config,
        source | {"official_road_classification": official_roads(include_second_a_road=True)},
        FakeAgentRuntime(),
    )

    assert missing.criteria["urban_network"]["official_main_road_spines"] == "green"
    assert missing.criteria["urban_network"]["urban_a_road_evidence_coverage"] == "red"
    assert missing.compilation_diagnostics["urban_a_road_spine_coverage"] == {
        "source_alignment_tolerance_m": 100.0,
        "evidence_segment_count": 2,
        "total_km": 2.0,
        "unmatched_km": 1.0,
    }
    assert represented.criteria["urban_network"]["official_main_road_spines"] == "green"
    assert represented.criteria["urban_network"]["urban_a_road_evidence_coverage"] == "green"
    assert represented.compilation_diagnostics["urban_a_road_spine_coverage"] == {
        "source_alignment_tolerance_m": 100.0,
        "evidence_segment_count": 2,
        "total_km": 2.0,
        "unmatched_km": 0.0,
    }
    assert "b-road" in set(represented.urban_spines["official_classification"])


def test_candidate_areas_use_only_qualifying_boundaries_and_flag_through_traffic() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "urban-centre",
                "name": "Urban Centre",
                "kind": "community",
                "place_class": "town",
                "geometry": Point(0, 0),
            }
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "residential-1",
                "highway": "residential",
                "observed_through_traffic": True,
                "geometry": LineString([(-0.012, 0), (0, 0)]),
            },
            {
                "osmid": "residential-2",
                "highway": "unclassified",
                "observed_through_traffic": False,
                "geometry": LineString([(0, 0), (0.012, 0.005)]),
            },
            {
                "osmid": "residential-3",
                "highway": "residential",
                "observed_through_traffic": False,
                "geometry": LineString([(0, 0), (0, 0.005)]),
            },
            {
                "osmid": "disconnected-1",
                "highway": "residential",
                "observed_through_traffic": False,
                "geometry": LineString([(-0.012, 0.008), (-0.005, 0.008)]),
            },
            {
                "osmid": "disconnected-2",
                "highway": "residential",
                "observed_through_traffic": False,
                "geometry": LineString([(-0.005, 0.008), (-0.005, 0.009)]),
            },
        ],
        crs=4326,
    )
    context = gpd.GeoDataFrame(
        [
            {
                "evidence_id": "built-edge",
                "feature_type": "circulation-boundary",
                "name": "Open-land edge",
                "category": "built-up-edge",
                "source_id": "built-edge-source",
                "geometry": LineString(
                    [
                        (-0.01, -0.01),
                        (0.01, -0.01),
                        (0.01, 0.01),
                        (-0.01, 0.01),
                        (-0.01, -0.01),
                    ]
                ),
            },
            {
                "evidence_id": "ward-line",
                "feature_type": "circulation-boundary",
                "name": "Ward boundary",
                "category": "administrative-boundary",
                "source_id": "ward-source",
                "geometry": LineString([(-0.01, -0.01), (-0.01, 0.01)]),
            },
        ],
        crs=4326,
    )

    urban = derive_urban_structure(places, network, context=context)
    areas = urban.low_traffic_areas
    portals = urban.low_traffic_area_portals

    assert len(areas) == 1
    area = areas.iloc[0]
    assert area["status"] == "candidate"
    assert area["intervention_need"] == "observed-through-traffic"
    assert area["permeability_representation"] == "area-no-internal-centreline"
    assert "built-edge" in area["boundary_ids"]
    assert "ward-line" not in area["boundary_ids"]
    assert list(portals["boundary_id"]) == ["built-edge", "built-edge", "built-edge"]
    assert portals["portal_id"].is_unique


def test_urban_portals_do_not_create_internal_peer_to_peer_routes() -> None:
    places = gpd.GeoDataFrame(
        [
            {
                "place_id": "west",
                "name": "West",
                "kind": "community",
                "place_class": "neighbourhood",
                "parent_place_id": None,
                "geometry": Point(-0.05, 0),
            },
            {
                "place_id": "west-outer",
                "name": "West outer",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "west",
                "geometry": Point(-0.04, 0),
            },
            {
                "place_id": "west-inner",
                "name": "West inner",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "west",
                "geometry": Point(0, 0),
            },
            {
                "place_id": "east",
                "name": "East",
                "kind": "community",
                "place_class": "neighbourhood",
                "parent_place_id": None,
                "geometry": Point(0.15, 0),
            },
            {
                "place_id": "east-inner",
                "name": "East inner",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "east",
                "geometry": Point(0.1, 0),
            },
            {
                "place_id": "east-outer",
                "name": "East outer",
                "kind": "community_portal",
                "place_class": "neighbourhood",
                "parent_place_id": "east",
                "geometry": Point(0.14, 0),
            },
        ],
        crs=4326,
    )
    network = gpd.GeoDataFrame(
        [
            {
                "osmid": "urban-link",
                "highway": "residential",
                "geometry": LineString([(0, 0), (0.1, 0)]),
            }
        ],
        crs=4326,
    )
    config = CouncilConfig.from_yaml(
        Path(__file__).parents[1] / "examples" / "fixture" / "council.yaml"
    )

    compiled = compile_network(
        config,
        {"places": places, "network": network, "boundary": gpd.GeoDataFrame()},
        FakeAgentRuntime(),
    )

    assert compiled.spine_access_connections.empty
    assert compiled.urban_spines.empty
    assert compiled.urban_classification_unknowns.empty
    assert compiled.urban_classification_status == "explicit-unknown"
    assert compiled.criteria["urban_network"]["official_road_classification"] == "grey"
    assert compiled.criteria["network"]["legacy_pairwise_absent"] == "green"
