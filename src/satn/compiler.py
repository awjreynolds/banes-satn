"""Deterministic Community Connection compilation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import geopandas as gpd
from shapely.geometry import LineString, Point

from satn.agents import AgentRuntime
from satn.models import AgentRecord, CouncilConfig, TrafficLight


@dataclass
class CompiledNetwork:
    places: gpd.GeoDataFrame
    connections: gpd.GeoDataFrame
    gaps: gpd.GeoDataFrame
    agent_records: list[AgentRecord]
    criteria: dict[str, TrafficLight]


def _connection_id(left: str, right: str) -> str:
    pair = "::".join(sorted((left, right)))
    return f"connection-{hashlib.sha256(pair.encode()).hexdigest()[:12]}"


def compile_network(
    config: CouncilConfig,
    source: dict[str, gpd.GeoDataFrame],
    runtime: AgentRuntime,
) -> CompiledNetwork:
    places = source["places"].copy().sort_values("place_id").reset_index(drop=True)
    routes = source["network"].copy()
    if len(places) < 2:
        raise ValueError("a network requires at least two Network Places")

    left = places.iloc[0]
    right = places.iloc[1]
    connection_id = _connection_id(str(left.place_id), str(right.place_id))
    geometry = _best_route(routes, left.geometry, right.geometry)
    projected_geometry = gpd.GeoSeries([geometry], crs=routes.crs).to_crs(27700)
    distance_km = float(projected_geometry.length.iloc[0] / 1000)
    checks_passed = not geometry.is_empty and distance_km <= config.compilation.max_connection_km
    record = runtime.review(
        connection_id,
        {
            "checks_passed": checks_passed,
            "distance_km": round(distance_km, 3),
            "from_place": left.place_id,
            "to_place": right.place_id,
        },
    )
    base = {
        "connection_id": connection_id,
        "from_place": left.place_id,
        "to_place": right.place_id,
        "distance_km": round(distance_km, 3),
        "classification": "community-connection",
        "status": "validated" if record.decision == "accept" else "gap",
    }
    accepted = [base | {"geometry": geometry}] if record.decision == "accept" else []
    rejected = [base | {"geometry": geometry}] if record.decision == "gap" else []
    crs = routes.crs
    columns = [*base, "geometry"]
    connections = gpd.GeoDataFrame(accepted, columns=columns, geometry="geometry", crs=crs)
    gaps = gpd.GeoDataFrame(rejected, columns=columns, geometry="geometry", crs=crs)
    criteria = {
        "connections": TrafficLight.GREEN if accepted else TrafficLight.RED,
        "network": TrafficLight.GREEN if accepted else TrafficLight.RED,
        "atm_comparison": TrafficLight.GREY,
    }
    return CompiledNetwork(places, connections, gaps, [record], criteria)


def _best_route(routes: gpd.GeoDataFrame, start: Point, end: Point) -> LineString:
    if routes.empty:
        return LineString()
    projected = routes.to_crs(27700)
    endpoints = gpd.GeoSeries([start, end], crs=routes.crs).to_crs(27700)
    direct = LineString(endpoints.tolist())
    ranked = projected.assign(_distance=projected.geometry.distance(direct))
    source_index = ranked.sort_values("_distance").index[0]
    geometry = routes.loc[source_index].geometry
    if not isinstance(geometry, LineString):
        raise ValueError("fixture network routes must be LineStrings")
    return geometry
