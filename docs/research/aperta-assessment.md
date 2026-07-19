# Aperta assessment — how it should influence the SATN toolchain

**Decision: adapt selected patterns; optionally interoperate at a bounded analytical seam. Do not adopt Aperta as the SATN platform or depend on it for the core deterministic CLI.**

**Scope and method.** This assessment is based on Aperta's first-party repository at commit [`8253788` (4 June 2026)](https://github.com/mmiotti/aperta/tree/8253788), its documentation, manifests, tests, examples, releases and linked project resources, reviewed on 19 July 2026. Statements labelled **Inference** are this assessment's conclusions, not maintainer claims. The target is a council-portable, deterministic SATN CLI/library with replaceable agent orchestration and a B&NES reference configuration.

## What Aperta actually provides

Aperta is a Python library for cross-modal transport-network accessibility analysis: NetworkX graph input; SciPy sparse-graph routing; travel cost/distance; utility-based costs; and cumulative-opportunity, gravity, nearest-*k*, and logsum metrics. This is its stated scope, not a general SATN authoring or decision system. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L265-L303) · [package metadata](https://github.com/mmiotti/aperta/blob/8253788/pyproject.toml#L6-L51)

Its substantive reusable concepts and code are:

| Area | Evidence | Value to SATN |
|---|---|---|
| **Tiered OD contract** | Immutable `TieredODPairs`, with node-keyed and geography-keyed forms; near cell→cell, middle cell→zone, and far zone→zone tiers. [source](https://github.com/mmiotti/aperta/blob/8253788/src/aperta/od_pairs.py#L42-L133) | Strong pattern for bounded-scale reproducible accessibility calculations. Adopt the *idea*, but define SATN-owned schemas and IDs rather than Python object contracts. |
| **Path-first routing** | A route/cost primitive supports aggregation of edge features, while routing uses a live NetworkX graph converted to SciPy CSR per call. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L326-L344) · [routing source](https://github.com/mmiotti/aperta/blob/8253788/src/aperta/routing.py#L1-L45) | Useful for route-quality/equity criteria and scenario sensitivity; live mutable graphs are a poor default evidence boundary. Persist immutable graph snapshots and input/output manifests around any use. |
| **Mode preparation and snap safety** | `PreparedGraph` records mode, directedness, edge exclusions and snap-eligible nodes; defaults distinguish walk/bike/car and avoid trapped nodes. [source](https://github.com/mmiotti/aperta/blob/8253788/src/aperta/routing_prep.py#L1-L121) | A highly relevant implementation pattern: explicit mode policies, topology safety and serialisable flags. B&NES needs local, reviewable rules—not Aperta's OSM defaults as policy. |
| **Geospatial operations** | OSM network helpers, graph cleaning/splitting/snapping, point/polygon/line mapping, H3 grid, raster samples and DEM download. [API index](https://github.com/mmiotti/aperta/tree/8253788/docs/api) · [optional-dependency definitions](https://github.com/mmiotti/aperta/blob/8253788/pyproject.toml#L54-L88) | Potential adapter utilities only. They are Python/GeoPandas/OSMnx-shaped, not a portable source-snapshot or licensing framework. |
| **Accessibility and calibration** | Accessibility metrics, linear utilities/overheads, sampled traffic-flow estimation and OLS edge-weight calibration against surveys/counters. [changelog](https://github.com/mmiotti/aperta/blob/8253788/CHANGELOG.md#L105-L132) | Useful later for analytical experiments, contingent on transparent local calibration data, uncertainty handling and methodological approval. Not a replacement for SATN prioritisation governance. |
| **Interoperation seam** | It expressly supports an external transit OD matrix (e.g. R5/r5py) aligned to cells, then cross-mode aggregation; it can also hand calibrated edge attributes to Pandana/pandarm. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L337-L344) | The right integration boundary: exchange declared OD-cost / route-feature tables and graph manifests, never conceal SATN decision logic inside the library. |

### What it does *not* provide

It intentionally has no filesystem assumptions, DAG engine, global state, caching, dependency tracking or orchestration; functions accept graphs/dataframes/arrays explicitly. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L326-L336) It has no native GTFS reader or time-dependent public-transit routing. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L337-L342) There is also no CLI declared in the package metadata, no API/service layer, no agent abstraction, no source provenance model, no council/configuration model, no decision/audit workflow, and no SATN domain entities (corridor, intervention, option, score, gate, recommendation). **Inference:** these omissions make it unsuitable as the SATN toolchain foundation even though its functions may be useful downstream.

## Data contracts and interfaces

The stable practical input boundary is Python-native: `networkx` Graph/MultiGraph variants with caller-defined edge attributes; `pandas`/`geopandas` frames; `numpy` arrays; typed tiered-OD Python dataclasses/dicts; results mostly as pandas dataframes. The workflow test demonstrates a plain graph plus GeoDataFrames becoming tiered pairs, routed costs and a binned output dataframe. [workflow test](https://github.com/mmiotti/aperta/blob/8253788/tests/test_workflow.py#L35-L239) Routing weights are supplied as caller functions and write mutable edge attributes. [routing source](https://github.com/mmiotti/aperta/blob/8253788/src/aperta/routing.py#L32-L86)

**Inference:** these are effective library-level contracts, but insufficient evidence contracts. The SATN interface should instead version and validate portable artifacts: GeoPackage/GeoParquet (or explicitly governed GeoJSON) for geometry, Parquet/CSV for OD and scoring tables, JSON/YAML for run/configuration manifests, SHA-256 source inventory, CRS/units, method-version, deterministic seed, and a field-level provenance/uncertainty status. An Aperta adapter should be one optional stage that consumes a frozen graph/units snapshot and emits a normalised cost/feature table accompanied by an execution manifest.

## Maturity, quality, dependencies and licence

* It is explicitly **pre-1.0 alpha**, warns that APIs may change without notice, and requires Python >=3.11. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L273-L284) The declared version is `0.2.0a0` and classifiers state “Development Status :: 3 - Alpha.” [manifest](https://github.com/mmiotti/aperta/blob/8253788/pyproject.toml#L6-L51)
* History is short: initial public `0.1.0a0` on 30 May 2026 and `0.2.0a0` on 3 June, tagged as `v0.1.0-alpha` and `v0.2.0-alpha`; the latter makes breaking API changes (including removal/renaming of snapping functions) while pre-1.0. [releases](https://github.com/mmiotti/aperta/releases) · [changelog](https://github.com/mmiotti/aperta/blob/8253788/CHANGELOG.md#L1-L104) · [commit history](https://github.com/mmiotti/aperta/commits/8253788)
* It has broad unit coverage in 13 test modules plus a documented toy end-to-end workflow; CI runs Ruff, mypy and the unit suite on Python 3.11–3.13 with all extras. [CI workflow](https://github.com/mmiotti/aperta/blob/8253788/.github/workflows/tests.yml) · [tests](https://github.com/mmiotti/aperta/tree/8253788/tests) · [workflow test](https://github.com/mmiotti/aperta/blob/8253788/tests/test_workflow.py) The local execution here could not validate them: only Python 3.14.5 was installed and core dependencies (e.g. NumPy, GeoPandas, NetworkX) were absent. This is an environment limitation, not a test failure attributable to Aperta.
* Core dependencies are NumPy, pandas, GeoPandas, NetworkX, SciPy, statsmodels, Numba and Matplotlib; optional functionality adds OSMnx, Rasterio, Requests and H3. [manifest](https://github.com/mmiotti/aperta/blob/8253788/pyproject.toml#L35-L88) **Inference:** that is a substantial geospatial/scientific Python supply chain for a council-portable CLI; isolate it in an optional adapter environment/container and pin/lock it, rather than making it a mandatory runtime dependency.
* The licence is MIT (copyright 2026 Marco Miotti), allowing reuse/modification/distribution subject to notice inclusion and disclaimer. [LICENSE](https://github.com/mmiotti/aperta/blob/8253788/LICENSE) **Inference:** licence compatibility is favourable, but it does not resolve licences, attribution, update policy or redistribution rights for B&NES/OS/OSM/transit/counter inputs.

## Fit-gap against the SATN requirement

| Required capability | Aperta fit | Decision implication |
|---|---|---|
| Council-portable deterministic CLI/library | Partial algorithm library; no CLI, files, run manifests, caching or orchestration. | SATN owns a language-agnostic CLI, config spec, deterministic run envelope and artifact validation. |
| Replaceable agent orchestration | No agents, tools, prompts, task model or DAG. | Keep agents outside the analytical core; they may draft configs/reports but must invoke validated deterministic stages. |
| B&NES reference config | Has generic OSM mode defaults and Bern/Paris/Cambridge examples, not B&NES rules/data. [examples](https://github.com/mmiotti/aperta/tree/8253788/examples) | Encode B&NES CRS, boundary/buffer, source versions, local mode/access rules and policy weights in SATN config—not library defaults. |
| Public-transport multimodality | External-OD interoperability only; no GTFS/time-dependent router. | Use an explicit transit adapter/backend; normalise results at the SATN OD-cost contract. |
| Auditability and review | Explicit function inputs are positive; mutable graphs/caller callbacks and alpha API are risks. | Snapshot every input and graph, record code/version/hash/parameters, prohibit implicit downloads in production runs. |
| Network/route analytical enrichment | Strong: routing, edge/path attributes, snapping, terrain/OSM helpers. | Pilot behind an adapter for reproducible walking/cycling scenario calculations after acceptance tests. |
| Prioritisation and governance | Not its domain. | Retain SATN-owned scoring, evidence grades, exclusions, auditable agent/human-over-the-loop review and publication checks. |

## Recommendation and implementation boundary

**Recommendation: adapt selected patterns now; interoperate later only after a controlled spike.** Do not vendor or make Aperta a required dependency in the core SATN CLI. This conclusion is an **Inference** from its stated alpha status, Python/geospatial coupling, lack of SATN/governance/orchestration interfaces, and useful but bounded analytical scope.

1. Adopt these *patterns* into SATN design: explicit mode configuration; the cell/zone multi-scale OD idea; path-feature-aware routing outputs; separated deterministic stages; and external-backend OD normalisation.
2. Preserve a clean optional `aperta` adapter seam: frozen input graph + units + declared edge-weight function/config → normalised `od_costs` and optional `path_features` output + provenance manifest. The core should work identically with R5/r5py, another router, or a precomputed matrix.
3. Before any operational use, conduct a B&NES acceptance spike on fixed snapshots: route/snap correctness, EPSG:27700 and units, duplicate/missing-ID behaviour, deterministic repeatability, runtime/memory, sensitivity to weights/cutoffs, comparison with an independently computed fixture, licence/attribution record, and an upgrade pin/rollback plan.
4. Treat traffic-flow and OLS calibration as research-only until their local data representativeness, bias, uncertainty and governance are explicitly approved. The project itself describes these as optional workflow phases. [README](https://github.com/mmiotti/aperta/blob/8253788/README.md#L293-L303)

This preserves Aperta's real strengths without allowing an early-stage external library to determine the SATN domain model, evidence standards, portability or accountability.
