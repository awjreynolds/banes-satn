# Robin Lovelace transport-modelling toolkit: implications for a council-portable SATN

**Scope and method.** This is a bounded review of first-party PCT, package, and project sources directly relevant to PCT data generation, OD analysis, routing, accessibility, and network construction. It is not a survey of the author's repositories. “Fact” statements are source-backed; “Recommendation” statements are inference for the B&NES SATN requirements.

## Decision in brief

Adopt the **method seams**, not the historical PCT application stack:

1. adopt PCT's OD → desire-line → route → segment-flow chain, its separation of trip purposes, and its explicit scenario functions as transparent analytical patterns;
2. adapt the contracts into versioned, local GeoParquet/GeoJSON-plus-manifest artefacts and a deterministic CLI, rather than make an R/Shiny app or remote data calls part of the SATN run path;
3. interoperate optionally with `pct`, `stplanr`, `dodgr`, and local OpenTripPlanner (OTP) behind adapters when they add value;
4. avoid treating PCT's modelled route network as a final intervention alignment, a census-only network as community adjacency, or a routing service response as reproducible evidence.

This supports a B&NES-configured, bottom-up, cumulative network only if SATN adds explicit continuity, topology, provenance, and auditable agent/human-over-the-loop review stages that the reviewed packages do not supply.

## What the PCT lineage establishes

### 1. A staged OD-to-network analytical model — **adopt**

**Fact.** `stplanr` states that it was originally developed for PCT and identifies its main functions as: create/manipulate geographic desire lines from OD data; calculate routes locally or via routing services; and calculate route-segment attributes. It also implements travel-flow aggregation (overlapping routed flows become segment values) and OD jittering. [Package description](https://raw.githubusercontent.com/ropensci/stplanr/master/DESCRIPTION)

**Fact.** The `pct` package exposes a concrete six-layer PCT data contract: zones (`z`), centroids (`c`), desire lines (`l`), fast routes (`rf`), quiet routes (`rq`), and route network (`rnet`); regional layers are GeoJSON and national layers RDS. [`get_pct()` source](https://raw.githubusercontent.com/ITSLeeds/pct/master/R/get_pct.R)

**Recommendation / adaptation.** Make that chain the SATN run contract, with stable IDs at every transition:

| SATN artefact | PCT analogue | Minimum additions for SATN |
|---|---|---|
| `origins`, `destinations`, `od_flows` | zones, centroids, desire lines | source version, purpose, time period, confidence, boundary rule |
| `desire_lines` | `l` | origin/destination IDs, demand metric, straight-line and network distance |
| `candidate_routes` | `rf` / `rq` | router/version/profile/snapshot hash, edge IDs, continuity status |
| `edge_flows` | `rnet` | directed and undirected values, contributing route IDs, scenario/purpose |
| `review_corridors` | no direct PCT equivalent | alignment geometry, joins, gaps, evidence, decision and review state |

Use a single B&NES YAML/JSON configuration to define boundary, source snapshots, purposes, router profile, thresholds, scenario parameters and output CRS. Persist the resolved configuration and input hashes in every run manifest. This is an inference from the packages' otherwise parameterised functions and remote-data defaults.

### 2. Demand by purpose, then overlay — **adopt, but do not conflate**

**Fact.** PCT's public description says its initial basis was OD data, used to identify high volumes of short trips and estimate cycling switch potential. [`stplanr` README](https://github.com/ropensci/stplanr#readme)

**Fact.** PCT documented that commute-only data emphasised arterial routes to employment hubs; adding school OD data produced denser, more diffuse, more orbital residential networks. It recommended combining the layers for a whole-network estimate. [PCT project post](https://blog.pct.bike/2020/02/02/overlaying-commute-and-school-route-network-layers-to-estimate-whole-network-cycling-potential/)

**Recommendation / adaptation.** Keep commute, school, local-service, retail/health, interchange, leisure and community-supplied adjacency evidence as separate demand families with declared weights. Overlay them only into a named cumulative score. This preserves the PCT insight while preventing a commuter model from silently defining B&NES's local network.

### 3. Explicit, inspectable scenario functions — **adopt as optional sensitivity analysis**

**Fact.** `pct` implements Government Target and Go Dutch cycling uptake as logistic functions of route distance, gradient and interactions; its source exposes coefficients and input-unit handling. [`uptake.R`](https://raw.githubusercontent.com/ITSLeeds/pct/master/R/uptake.R)

**Fact.** PCT later changed some scenarios to individual-level microsimulation to include correlations among demographic/geographic characteristics, rather than only aggregate distance and hilliness. [PCT project post](https://blog.pct.bike/2019/05/02/new-pct-commute-layer-government-target-near-market/)

**Recommendation / adaptation.** Put PCT-like uptake models in a versioned `scenario` stage, never in base network construction. SATN's core evidence should remain observed/authoritative demand plus explicitly recorded assumptions. Report sensitivity bands across baseline, e-bike and local-policy scenarios rather than presenting a single predicted future flow as fact.

**Gap.** These functions estimate potential uptake; they do not decide whether a corridor is continuous, deliverable, safe, or community-endorsed. Do not use them as the SATN priority decision rule.

## Relevant packages and usable seams

### `pct` (ITS Leeds): retrieval, examples, and scenario reproduction — **interoperate; do not make runtime-critical**

**Facts.** `pct` is an R package intended to make PCT data easier to access and reproduce; it explicitly says the main PCT codebase is public but not easy to run/reproduce. [README](https://github.com/ITSLeeds/pct#readme) Its DESCRIPTION names Robin Lovelace as author/creator, version 0.10.0, R >= 3.5, GPL-3, and imports `stplanr`, `sf`, `readr`, and `crul`. [DESCRIPTION](https://raw.githubusercontent.com/ITSLeeds/pct/master/DESCRIPTION) GitHub metadata shows its latest push was 2025-03-04. [Repository API record](https://api.github.com/repos/ITSLeeds/pct)

**Usable seam.** Treat it as a reference implementation and an optional importer for historical PCT layers. Its functions retrieve layers by `purpose`, `geography`, `region`, and `layer`, returning `sf` objects. [`get_pct.R`](https://raw.githubusercontent.com/ITSLeeds/pct/master/R/get_pct.R)

**Constraints / avoid.** It defaults to GitHub-hosted output repositories and reads remote data at invocation time; a council-grade deterministic run must instead snapshot/download inputs once, checksum them, and run offline from a manifest. Its GPL-3 licence is compatible with separate-process interoperability but is a strong-copyleft constraint if SATN copies or links code into a distributed combined program; obtain legal advice before reuse. Do not build the SATN core around its R object/RDS output format.

### `stplanr`: OD geometry, route allocation and segment aggregation — **adopt concepts; optionally interoperate**

**Facts.** `stplanr` is an MIT-licensed R package for spatial transport data and non-motorised modes, requiring R >= 3.5 and `sf`/R spatial dependencies. [DESCRIPTION](https://raw.githubusercontent.com/ropensci/stplanr/master/DESCRIPTION) It defines `od2line()`'s contract as flow data plus georeferenced zones/points to produce spatial flows. [README](https://github.com/ropensci/stplanr#readme) Its `overline()` operation splits routed lines into unique segments and aggregates attributes over overlaps. [README](https://github.com/ropensci/stplanr#readme) GitHub lists a release in April 2025. [Releases](https://github.com/ropensci/stplanr/releases)

**Recommendation / adaptation.** Reimplement or call the narrow `od2line` and route-overlay semantics behind language-neutral files, not R-memory objects. The important invariant is provenance: every aggregated edge must retain the IDs and weights of input OD routes, so a reviewer can explain why it appeared.

**Constraints / avoid.** `stplanr` can call OSRM, CycleStreets and other services. Its README illustrates external routing and even name lookup through Google Maps. [README](https://github.com/ropensci/stplanr#readme) Do not permit those network calls in the deterministic default path. Pin a local routing graph/profile instead; external providers may be an explicitly non-reproducible exploratory adapter.

### CycleStreets and OSRM interfaces: useful API boundary, not an evidential engine — **optional adapter only**

**Fact.** `stplanr` documents route functions that can allocate flows through CycleStreets and OSRM interfaces. [README](https://github.com/ropensci/stplanr#readme)

**Recommendation.** Preserve the router-adapter shape (`route(desire_line, profile, graph_snapshot) -> geometry + edge sequence + metrics`) because it makes swapping providers possible. For SATN, accept a result only when it records router/provider, profile, request coordinates, graph/data date, response hash and a topology validation result. A web API cannot by itself prove a durable route or explain a dead end.

### `dodgr`: local directed network construction, weighting and accessibility — **interoperate for analysis; do not couple the product to it**

**Facts.** `dodgr` calculates distances on dual-weighted directed graphs using priority-queue shortest paths. Its canonical case is a street network in which route choice uses mode/way weights but reported length remains direct distance. [DESCRIPTION](https://raw.githubusercontent.com/UrbanAnalyst/dodgr/main/DESCRIPTION) It is GPL-3, R >= 3.5, compiles C++/parallel components, and depends on OSM data tooling. [DESCRIPTION](https://raw.githubusercontent.com/UrbanAnalyst/dodgr/main/DESCRIPTION)

**Facts.** It makes weighting profiles externally editable as JSON. [`weighting_profiles.R`](https://raw.githubusercontent.com/UrbanAnalyst/dodgr/main/R/weighting_profiles.R) It supports a flow-dispersal model using exponential distance decay, graph contraction, and a cache; the documentation warns that changed input graphs may continue using cached contracted graphs unless cache handling is explicit. [`flows-disperse.R`](https://raw.githubusercontent.com/UrbanAnalyst/dodgr/main/R/flows-disperse.R)

**Recommendation / adaptation.** `dodgr` is a strong optional local engine for B&NES accessibility matrices, directed bike/e-bike/foot route tests, and sensitivity tests with declared weighting profiles. Make every profile a versioned config artefact, and disable/clear cache or key it by complete graph+profile hash. Export ordinary edge tables and geometries, not a `dodgr`-specific internal graph, as SATN's durable boundary.

**Gap / avoid.** A shortest-path engine optimises a supplied weighted graph; it does not establish whether OSM connectivity, crossing legality, severance, scheme feasibility or community adjacency is correct. Its GPL-3 and compiled R toolchain also make it unsuitable as a mandatory embedded dependency for a portable multi-runtime CLI.

### `opentripplanner` R interface: multimodal and time-dependent accessibility — **optional, separately deployed service**

**Facts.** The package manages or connects to local/remote OTP and returns `sf` objects; OTP itself is a Java multimodal journey-planning platform. [README](https://github.com/ropensci/opentripplanner#readme) Its functions include local graph build/setup/config validation plus routing, isochrones and travel-time matrices. [README](https://github.com/ropensci/opentripplanner#readme) It is GPL-3, requires R >= 4.0, and its README labels the project “Active”, with the newest stated release 0.5.0 (Jan 2023) supporting OTP 2.2. [DESCRIPTION](https://raw.githubusercontent.com/ropensci/opentripplanner/master/DESCRIPTION) [README](https://github.com/ropensci/opentripplanner#readme)

**Recommendation / adaptation.** Use OTP only where SATN needs GTFS-aware multimodal accessibility or time-of-day travel times—not to make the first active-network inventory. Run it locally or as a pinned container/service, snapshot OSM/GTFS/build config/JAR version, and save request/result manifests. Keep the adapter process boundary so the base SATN CLI works without Java/R/OTP.

## PCT's historical application delivery: do not adopt as SATN architecture

**Fact.** The `pct` README says the principal source code is in the `npct` organisation and that it is not easy to run or reproduce. [README](https://github.com/ITSLeeds/pct#readme) The `npct/pct-team` repository is AGPL-3 according to GitHub's first-party repository metadata. [Repository API record](https://api.github.com/repos/npct/pct-team)

**Recommendation.** Do not fork/copy the Shiny/web delivery architecture into SATN. It would add an R/Shiny runtime, older project layout, difficult reproducibility, and AGPL obligations without solving the required CLI, B&NES configuration, community adjacency, cumulative incremental network, or alignment-continuity needs. Use it as a methodological and UI reference only.

## Specific SATN gaps that must be designed rather than imported

### Bottom-up community adjacency

**Inference.** The reviewed PCT contracts start with administrative OD zones and centroids; they contain no first-class contract for resident-reported missing links, perceived barriers, informal routes, or a resolution workflow. Add a `community_observation` input with geometry or place references, claim type, contributor/source, date, consent/privacy class, evidence links, confidence, and disposition. Convert observations into named candidate links only through an auditable evidence disposition recorded by the agent workflow or a human intervention.

### Cumulative local-to-e-bike network

**Inference.** PCT's separate fast/quiet route and scenario outputs are valuable comparators, but the B&NES requirement is one cumulative graph, not separate local and e-bike networks. Each edge should record immediate local utility and the longer end-to-end journeys it enables when chained with neighbouring links. E-bike assumptions change impedance and reachable opportunity on that same graph; they do not silently create a second topology. Demand scenarios may change edge scores, but every topology change must remain explicit.

### Continuous alignments and no unexplained dead ends

**Inference.** Route aggregation creates segment demand but does not prove a recommended corridor has connected ends. Add a topology gate after every network-building stage:

* snap only within a declared tolerance and record each snap;
* identify degree-1 endpoints, components, gaps and mode-restricted discontinuities;
* require each endpoint to be a justified network boundary, destination, phase boundary, or linked continuation; otherwise classify it as an unresolved gap;
* preserve original router geometry/edge sequence and validate it against the pinned graph—never simplify away an unexplained break.

This is the key extra layer between PCT-style strategic flow maps and buildable/reviewable SATN alignments.

### Deterministic CLI/library and optional orchestration

**Recommendation.** Make stages pure, rerunnable commands (`snapshot`, `ingest`, `build-od`, `route`, `aggregate`, `score`, `topology-check`, `export`) over versioned artefacts. Each command should accept config + manifest, emit hashes and an auditable machine-readable report, and be usable as a library function. Agent orchestration may propose, challenge, choose, and revise structured network decisions, but every change must cite evidence and appear in the run record. Neither an agent nor a human may silently alter configuration or waive a deterministic topology failure; a human can observe, intervene, or reject the run.

## Practical interoperability profile

| Component | SATN stance | Why |
|---|---|---|
| `pct` data/package | importer/reference only | valuable PCT contract and examples; remote default + GPL-3 + R coupling |
| PCT uptake functions | port/reimplement as declared scenario models | transparent formulae; never topology or priority truth |
| `stplanr` | semantic reference / optional R adapter | mature OD and overlay patterns, MIT; external-router defaults must be controlled |
| CycleStreets/OSRM | exploratory adapter | useful comparison routes, but remote results are mutable |
| `dodgr` | optional local analysis sidecar | directed weighted graph and accessibility; GPL-3/compiled R/cache discipline |
| OTP + `opentripplanner` | optional pinned service | multimodal/time-aware access, but Java/R/GTFS/OSM operational burden |
| `npct` Shiny application | avoid as implementation base | public methodology reference, but difficult reproducibility and AGPL delivery stack |

## Maturity and reproducibility assessment

* **Mature reusable concepts:** PCT's OD/scenario/route-network framing and `stplanr`'s OD/overlay API are documented, package-distributed and actively released (the PCT data package has a 2025 push; `stplanr` a 2025 release). [PCT API metadata](https://api.github.com/repos/ITSLeeds/pct) [stplanr releases](https://github.com/ropensci/stplanr/releases)
* **Mature but operationally heavy engines:** `dodgr` and OTP support local computation, but respectively bring compiled R/network-data dependencies and Java/GTFS/OSM graph-build dependencies. [dodgr DESCRIPTION](https://raw.githubusercontent.com/UrbanAnalyst/dodgr/main/DESCRIPTION) [OTP interface README](https://github.com/ropensci/opentripplanner#readme)
* **Reproducibility rule:** source licences and public code do not make a result reproducible. SATN must pin raw data, derived graph, routing profile, software/container versions, config and random seeds (if any), and retain all intermediate artefact hashes. This is an inference from `pct`'s live remote retrieval and `dodgr`'s documented cache behaviour.

## Sources consulted

Primary project/package sources only: [PCT site](https://www.pct.bike/), [PCT data package](https://github.com/ITSLeeds/pct), [PCT project repositories](https://github.com/npct), [stplanr](https://github.com/ropensci/stplanr), [dodgr](https://github.com/UrbanAnalyst/dodgr), and [opentripplanner R](https://github.com/ropensci/opentripplanner). Accessed 2026-07-19.
