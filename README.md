# banes-satn

Council-portable tooling for compiling an evidence-led Strategic Active Travel
Network (SATN), with Bath and North East Somerset as the reference implementation.

> Experimental SATN POC — not an adopted B&NES plan.

**[Open the interactive network map](https://awjreynolds.github.io/banes-satn/)** — inspect Strategic Spines, access connections, National Cycle Network evidence, Candidate Low-Traffic Areas, Schools and visible Network Gaps. The map links back here for source, methodology and issue tracking.

The compiler grows a rural Backbone-and-Access Network outward from governed A-road
and established NCN Strategic Spines. Communities and Schools attach to that shared
backbone or remain visible Network Gaps; it does not generate a nearest-neighbour
spider's web. Route choice remains separate from later demand or delivery
prioritisation.

## Install

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```shell
uv sync --all-groups
```

## Run the checked-in fixture

Both public commands are driven by the same council YAML configuration used by the
Python API:

```shell
uv run satn snapshot examples/fixture/council.yaml
uv run satn compile examples/fixture/council.yaml
```

The first command creates an attributable immutable snapshot. The second atomically
replaces `examples/fixture/work/output/` with the current authoritative GeoPackage,
GeoJSON, run and agent records, accessible MapLibre review map, shareable ZIP, and A3
PDF.

The stable library interface is:

```python
from satn import compile

result = compile("examples/fixture/council.yaml")
```

The default `fake` agent provider is deterministic and requires no credentials. It
exercises the same typed compilation gate used by configured model providers.

## Snapshot B&NES from OpenStreetMap

The reference configuration contains only council data and thresholds; acquisition
and place derivation remain portable compiler behaviour:

```shell
uv run satn snapshot config/banes.yaml
```

OSM acquisition uses the governed `source.overpass_url` and
`source.osm_timeout_seconds` settings. The B&NES configuration decomposes its broad
evidence tags and uses a ten-minute per-request timeout because its buffered source
queries can exceed the default three-minute budget.

This retrieves the full governed boundary, cycling graph, named place features,
public-transport stations and everyday amenities from OpenStreetMap, plus the current
National Cycle Network from the Walk Wheel Cycle Trust public feature service. The
immutable snapshot records retrieval time, content hashes, OSM/ODbL attribution and
NCN/Open Government Licence v3.0 attribution. Towns, villages and named urban neighbourhoods are
admitted as Community candidates; hamlets are not mandatory Network Places. Large
Community polygons can expose connected network portals, and genuine outward road
crossings are named for the relevant external town or city along the onward corridor.
The Council Configuration also governs which OSM place types define urban extents and
their evidence buffer. Snapshot creation splits A-road and established NCN linework at
that extent, recording each continuous part as `rural` or `urban`; invalid scope values
are rejected rather than silently omitted. This lets the normal live snapshot path
produce rural Strategic Spines without hard-coding a B&NES-only geography.

The network request is intentionally live and can take time. Its explicit smoke test
is:

```shell
uv run pytest --live-osm -m live_osm tests/test_osm_sources.py
```

## How routes are compiled

Schema 2.0 uses Backbone-Outward Assembly as the only authoritative rural network
model. All governed Strategic Spines seed one concurrent frontier. Each iteration
serves the nearest reachable rural Community, extending an existing branch where that
is cheaper than creating another direct spine attachment. The compiler compares only
continuous, bidirectional OSM alignments.

Where one strongly connected cycling component contains at least 90% of graph nodes,
Community attachment prefers that dominant routable component instead of snapping to
a nearby isolated digitising fragment.

The Backbone-and-Access tracer promotes only governed rural A-road and established NCN
evidence. Its first Spine Access Connection publishes only routed OSM geometry between
canonical graph attachment points. Bounded Community and spine snap distances, node IDs
and point coordinates remain visible and auditable metadata; they are not drawn or
validated as paths without traversable network evidence.

- a direct A-road corridor is the preferred Strategic Spine, representing a wide
  alongside shared path rather than cycling in the carriageway. Its authoritative
  geometry is an indicative corridor centreline; the review map offsets it
  cartographically to show “alongside” without inventing survey-level geometry;
- a parallel route is used when alongside provision is explicitly found physically
  impracticable, with that reason retained;
- other rural connections compare direct and low-traffic OSM paths;
- where no qualifying A-road spine wins, NCN overlap can inform the selected
  continuous alignment;
- no continuous two-way path becomes a visible Red Network Gap rather than a drawn
  straight line; and
- a connection over 15 km is challenged Amber, not silently removed.

In urban areas, governed official A roads, B roads and Classified Unnumbered Roads
form protected-route spines. Unclassified streets do not become through-traffic
spines, and OSM functional tags do not silently replace missing official evidence.
When no governed classification source is configured, the publication records an
`explicit-unknown` classification status. Urban NCN Evidence remains a separate
permeability layer rather than automatically becoming a Circulation Boundary. Connected
fabrics of minor roads become Candidate Low-Traffic Area polygons, without claiming
that an LTN already exists or asserting an artificial centreline. Official Urban
Main-Road Spines, mapped built-up edges adjoining open land, substantial rivers,
canals and railways can close those fabrics; administrative wards, property lines and
individual field parcels cannot. Each candidate records its intervention need and
stable named portals to the qualifying boundary network. Observed internal through
traffic strengthens the intervention need but never promotes an unclassified street
into a through-traffic spine.

For reproducibility, a river, canal or surface railway segment must provide at least
250 metres of continuous physical boundary evidence before it can close a candidate.

Urban School Access Obligations are assessed against this same topology. A mapped or
inferred usable entrance is served only when it shares continuous low-traffic street
or path fabric with a named portal on an Urban Main-Road Spine. The published point
record cites the candidate area, portal and supporting source identifiers; it never
draws a preferred route through residential streets. Unresolved entrances, missing
main-road portals and discontinuous fabric remain visible findings.

Every in-scope School also receives a separate preliminary School Street Candidate
Assessment. Green/Promising, Amber/Needs Investigation, Red/Unlikely and Grey/Not
Evaluated markers summarise entrance evidence, adjoining official road class, bus and
essential access, alternative through-route evidence and displacement risk. Unknown
inputs remain explicit; an inferred entrance cannot produce Green or Red. These are
qualitative investigation prompts, never scheme feasibility or calibrated probability.

Every generated Community Connection, Strategic Spine section, Spine Access
Connection, Branch Meeting Connection, Cross-Spine Connector and Urban Main-Road
Spine also receives a directional Topography Profile. Governed Elevation Evidence
sampled throughout the edge records distance, cumulative ascent and descent in both
directions, steepest sustained gradient and stable Gradient Sections. The adjustable
display bands are Gentle (up to 3%), Noticeable (above 3% to 5%), Steep (above 5% to
8%), Very Steep (above 8% to 12.5%) and Severe (above 12.5%). These sections are
always visible. A bounded Topography Alternative comparison is triggered by 100 m of
Steep, 50 m of Very Steep, 30 m of Severe, or repeated shorter climbs with material
cumulative ascent. It may select a longer materially easier plausible Alignment Option,
but it keeps and visibly flags the original when none is easier. Gradient never removes
a Strategic Spine. Missing or unusable Elevation Evidence is published as an explicit
Grey evidence-unavailable Topography Profile and unresolved comparison; it never implies
flat terrain.

The display bands and evidence-spacing rules are governed trial configuration. The
maximum spacing prevents sparse endpoint-only evidence from being mistaken for a
profile, while the minimum sustained spacing suppresses isolated sub-window noise.
Governed short steeper sections still contribute to cumulative ascent/descent and
remain visible with an explicit non-sustained rationale; only the separately named
steepest-sustained-gradient statistic applies the sustained window.

```yaml
compilation:
  topography:
    gentle_max_pct: 3
    noticeable_max_pct: 5
    steep_max_pct: 8
    very_steep_max_pct: 12.5
    maximum_sample_spacing_m: 250
    minimum_sustained_spacing_m: 10
    steep_trigger_length_m: 100
    very_steep_trigger_length_m: 50
    severe_trigger_length_m: 30
    repeated_climb_count: 2
    cumulative_ascent_trigger_m: 40
    maximum_alternative_detour_ratio: 1.5
    material_ascent_reduction_m: 20
    material_ascent_reduction_ratio: 0.25
```

Each compiled Community Connection records whether comparison triggered, the original
and selected roles, the reason for selection or retention, and an Elevation Evidence
summary for every candidate Alignment Option. These are deterministic bounded
refinements before the existing agent Compilation Gate; routine choices do not require
per-edge human approval.

Offline fixtures can supply `source/elevation-evidence.geojson` containing Point
samples with `evidence_id`, `source_id`, `effective_date`, `licence` and
`elevation_m`. Snapshot creation validates and fingerprints that governed file, and
normal compilation loads it without a live lookup. National terrain acquisition for
real council snapshots uses the same contract. A configured local GeoJSON or remote
GeoJSON point service is clipped to the governed boundary plus compilation buffer,
canonicalised, attributed and fingerprinted in the immutable snapshot:

```yaml
source:
  national_elevation:
    provider: local-geojson # or remote-geojson with url
    path: data/local/national-terrain-samples.geojson
    source_id: national-dtm-2026
    effective_date: 2026-01-15
    licence: Open Government Licence v3.0
    attribution: National terrain model
    elevation_field: elevation_m
    identifier_field: evidence_id
```

Remote sources receive the governed bounding box and must return a GeoJSON
FeatureCollection of Point samples. Compilation performs no live lookup: it reads the
snapshotted `elevation-evidence.geojson`. Changing that evidence changes the snapshot
and run fingerprints. Sparse OSM `ele` and `incline` tags are published only as
`corroborating-only` evidence and never substitute for missing national coverage. Run
the optional live-source smoke test explicitly with `--live-terrain` and
`SATN_TEST_TERRAIN_GEOJSON_URL`.

Configure a council-governed classification dataset as follows. The source must be
line geometry with an `official_classification`, `road_classification` or
`classification` field; common A, B, C/Classified Unnumbered and Unclassified values
are normalised in the immutable snapshot.

```yaml
source:
  official_road_classification:
    path: data/local/official-road-classification.geojson
    source_id: council-highways-list
    effective_date: 2026-04-01
    licence: Open Government Licence v3.0
```

Observed internal through-traffic can also be supplied as governed line evidence.
The compiler snapshots its source, effective date, licence and content fingerprint,
then marks intersecting Candidate Low-Traffic Areas as needing intervention without
promoting their internal streets into the through-traffic network.

```yaml
source:
  observed_through_traffic:
    path: data/local/observed-through-traffic.geojson
    source_id: council-traffic-study
    effective_date: 2026-03-01
    licence: Open Government Licence v3.0
```

## Agent compilation gate

Council Configuration selects exactly which Criterion Statuses require agent review.
The default is Amber and Red; Green is deterministic and Grey can be selected
independently. A selected status returns a
typed, fingerprinted Agent Decision Request containing the exact criterion, governed
evidence, deterministic findings and finite compiler-authored choices.
An unselected Green, Amber or Grey decision is applied deterministically, while an
unselected Red still becomes an explicit Network Gap. No Criteria Section aggregate
is used to choose review.

```yaml
compilation:
  agent:
    provider: fake
    response_mode: caller
    review_statuses: [amber, red]
```

The public library returns `decision-required` with the currently actionable menu and
no partial artifacts. The CLI prints the equivalent JSON and exits immediately; it
does not read stdin, poll, sleep, maintain a heartbeat or retain a live continuation.
Each choice is a simple identifier such as `1`, `2` or `terminate`, and already states
the action, consequence and constraints the compiler will enforce. An empty
`review_statuses` list guarantees that no Agent Runtime is constructed or called.
Agents cannot invent actions, mutate compiled state or override a Red mandatory
criterion.

To apply a choice, start a fresh compilation with a data-only decision ledger. Each
response contains only the regenerated request identifier, its dependency fingerprint
and one offered choice identifier; executable actions and free-form instructions are
rejected. The compiler locates the same decision point, revalidates the fingerprint,
membership and mandatory invariants, then applies its own typed action. Stale, unknown
or cross-request responses return the current `decision-required` menu without changing
compiled state. `terminate` returns a non-publishing `terminated` result and preserves
the previous valid publication.

```json
{
  "decision_contract": "agent-decision-menu/v1",
  "responses": [
    {
      "request_id": "agent-decision-…",
      "dependency_fingerprint": "…",
      "choice_id": "1"
    }
  ]
}
```

```shell
uv run satn compile config/banes.yaml --decision-ledger decisions.json
```

Accepted choices participate in publication fingerprints and are repeated in the run
manifest and Agent Decision Records. Choices affecting published spatial features are
also linked through spatial properties and accessible review-map details; ATM comparison
choices remain in typed divergence records because they never mutate authoritative
geometry. Identical governed inputs and the same ledger reproduce the same identifiers
and authoritative artifacts.

Set `response_mode: direct-runtime` to let the configured Agent Runtime answer the
same menu in-process. The runtime receives the complete fingerprinted request and may
return only `request_id` and one offered `choice_id`; the compiler supplies and validates
the fingerprint and applies its own predefined action. Each call is limited to one
request and attempt, `max_tokens`, and the hard `deadline_seconds` wall-clock limit.
Timeout, provider failure, malformed output, request mismatch or an unknown choice
returns the same non-publishing `decision-required` result immediately. The accepted
record identifies `direct-runtime` as the responder and includes provider, model, usage
and choice-validation provenance. A caller decision ledger still takes precedence and
does not construct the runtime.

```yaml
compilation:
  agent:
    provider: pydantic-ai
    model: your-model-name
    response_mode: direct-runtime
    review_statuses: [amber, red]
    deadline_seconds: 30
    max_requests: 1
    max_attempts: 1
    max_tokens: 4000
```

Routine unresolved refinements remain typed findings and visible gaps. Historical
free-form Agent Runtime records remain readable, but compilation no longer creates
proposal, critique, red-team, synthesis or divergence action-selection calls. A
`human-intervention-requests.json` record records any retained historical exhausted
review, unresolved findings, missing evidence, available choices and the smallest human input
needed. Ordinary no-path or missing-spine gaps do not create intervention requests.

`fake` is the deterministic default. Any Pydantic AI model identifier can be supplied
in Council Configuration as `compilation.agent.model`, with provider credentials read
from its normal environment variables. Codex is not required. A live adapter check is
explicit and opt-in:

```shell
SATN_TEST_AGENT_MODEL=openai:gpt-5-mini \
  uv run pytest --live-agent -m live_agent tests/test_agent_gate.py
```

## Network assembly

The compiler produces one authoritative rural Backbone-Outward Assembly. Every governed Strategic Spine is available
as a seed before growth begins. The compiler repeatedly selects the globally nearest
reachable unserved Community by bidirectional cycling-network cost, then adds that
Community's canonical graph attachment to the served frontier. A hinterland Community
can therefore inherit its root spine and branch through an already served Community
instead of originating another direct spine route.

Every Spine Access Connection records its root spine, owning branch, immediate parent,
attachment depth, source edge IDs and deterministic rationale. Degree-one served
Communities are valid leaves. Unreachable Communities become point-only Network Gaps,
and meaningful Cross-Boundary Gateways attach to the same served frontier without
becoming Community Access Obligations. Stable sorting and identifiers make topology
independent of source feature order.

When independently rooted fronts reach locally adjacent Communities, their first
validated cycling-network meeting becomes a Branch Meeting Connection. Meetings are
selected in global cost order and join spine components as a tree, so parallel or cyclic
links cannot turn the result into a mesh. Each published Cross-Spine Connector traces
that meeting through both parent lineages to the relevant Strategic Spines, preserving
the full connection, branch, evidence and agent-gate provenance.

Rural primary, secondary, all-through and special Schools are separate School Access
Obligations rather than Network Places. A mapped usable entrance is preferred; a point
inferred from a mapped school-boundary/path intersection remains Amber and provisional,
while an unresolved entrance is never silently snapped to a road. Each resolvable School
selects one governed attachment to fixed spine, connector or established branch geometry
after Community growth, so it can reuse a branch without becoming a frontier for another
School or generating school-to-school or school-to-Community journey pairs. Colleges and
universities remain contextual evidence unless their OSM source IDs are explicitly listed in
`source.strategic_destination_source_ids`.

The previous pairwise network is absent from compilation, GeoPackage, GeoJSON, PDF and
review-map layers. If an earlier publication exists, `backbone-comparison.json`
summarises topology, gaps, linework/noise and explainability differences under the
explicit role `superseded-reference-not-ground-truth`; agreement with it is not a
correctness criterion. `publication.comparison_reference` may identify a governed
tracked predecessor. The B&NES configuration uses an immutable schema-1 summary under
`references/`, so a clean full compile remains reproducible after the schema-2 site is
promoted.

## Deterministic recompilation

Schema 2.0 does not read or write the legacy pairwise Connection cache. A default run
may reuse only a complete, validated schema-2 publication whose source snapshot,
governed configuration, criteria, schema and compiler implementation fingerprints all
match. Otherwise it reassembles the authoritative backbone from the immutable snapshot.
Stable identifiers and ordering make unchanged runs topologically and fingerprint stable.
Changing any governed input invalidates whole-publication reuse.

```shell
# compile the authoritative backbone
uv run satn compile config/banes.yaml

# force a complete deterministic rebuild
uv run satn compile config/banes.yaml --full
```

CLI commands emit timestamped standard-library logs to stderr. `INFO` is the default
and reports acquisition groups, snapshot counts, periodic backbone and School progress,
publication validation and elapsed time. Use `--log-level DEBUG` for selected frontier
decisions and artifact diagnostics, or `WARNING`, `ERROR` or `CRITICAL` for quieter
automation:

```shell
uv run satn compile config/banes.yaml --log-level DEBUG
```

`run.json` retains deterministic compilation diagnostics: graph/search dimensions,
candidate evaluations, frontier growth and typed optimisation findings. Wall-clock
timings and throughput remain in the logs because they are operational observations,
not reproducible governed output. Changing `compilation.criteria_version` invalidates
whole-publication reuse.

## ATM quality comparison

ATM is an optional B&NES quality reference, not a portable network rule or an
authoritative answer. Put the locally governed file at
`data/local/banes-atm-full.geojson`, set `atm.enabled: true`, and choose one mode:

- `blind` compiles routes before the ATM file is loaded, then compares them;
- `seeded` records that the reference was available before comparison, but schema 2.0
  does not permit it to replace or steer the authoritative Backbone-Outward result.

The typed divergence output distinguishes matches, deviations, additions and
omissions. Each uses its own governing Criterion Status and the same configured agent
review policy; there is no aggregate agreement score and a match does not prove
correctness.

For `publication.audience: public`, ATM geometry is omitted unless
`atm.redistribution_permitted: true`. A `local` review may include the overlay. The
default public B&NES configuration keeps comparison disabled and redistribution
false because public retrieval is not, by itself, a licence grant.

The public review map still provides a governed local-file control. Select an ATM
GeoJSON in the browser to load it only into that browser session, then toggle “ATM
reference (before/after)” without uploading or republishing its geometry.

## Review and share the result

Every successful compile replaces the configured output directory only after all
artifacts validate against each other:

- `network.gpkg` is the authoritative multi-layer spatial output;
- `network.geojson`, `run.json`, `agent-records.json`,
  `human-intervention-requests.json`, `divergence-records.json` and
  `backbone-comparison.json` expose the same governed run;
- `review-map/` is a backend-free static site with a vendored, pinned MapLibre build;
- `review-map.zip` contains that complete directory unchanged; and
- `network-map.pdf` is A3 landscape by default, with configurable A2/A3/A4 size,
  title, date, legend, scale and disclaimer.

Open `review-map/index.html` directly or serve the directory from any static host.
The map presents Strategic Spines, Spine Access Connections and Cross-Spine
Connectors as the core rural network, with NCN evidence as a distinct overlay.
Schools, derived high-street/retail
centres and healthcare facilities default off to avoid noise; each has its own
control. Road-classification evidence gaps and LTA portal evidence also default off,
keeping the circulation-plan view legible while remaining independently auditable.
Places, urban structure, gaps/warnings and ATM comparison are independently toggleable.
The map itself carries a compact, collapsible legend for every symbol shown by the
default layers, so the key remains available when the controls are off-screen on mobile.
Gradient Sections use a separately selectable sequential blue terrain
palette with a text-labelled legend distinct from Criterion Status colours; Grey
dashed profiles expose unavailable Elevation Evidence. Connections, Network,
Topography and ATM criteria remain separate. Hover or keyboard
focus updates the semantic details panel; click pins and unpins it. The panel exposes
Community names, stable IDs, length, role, indicative intervention, criterion states,
rationale, findings and source IDs, so browser agents do not need to infer state from
the map canvas.

Publisher tests include cross-artifact identifiers, ZIP equivalence, PDF extraction
and preservation of the previous output after a simulated print failure. Install the
pinned Chromium once and run the interaction test explicitly:

```shell
uv run playwright install chromium
uv run pytest --browser -m browser tests/test_review_map_browser.py
```

The current full B&NES result is published at
[awjreynolds.github.io/banes-satn](https://awjreynolds.github.io/banes-satn/).
The [A3 PDF network map](https://awjreynolds.github.io/banes-satn/network-map.pdf)
is published beside it for download and printing. Until the next governed B&NES
snapshot run is promoted, that tracked site remains the superseded schema-1 reference;
it is comparison evidence, not ground truth for schema 2.0. The public map excludes
the governed ATM geometry. After a validated public compile, refresh the tracked GitHub
Pages bundle with:

```shell
uv run python scripts/publish_site.py
```

## Check

```shell
uv run ruff check .
uv run pytest
```

## Status

The POC compiler now treats the schema-2 Backbone-and-Access Network as authoritative.
A full B&NES publication must be generated from its governed immutable snapshot; no
legacy pairwise output or cache is accepted as a replacement when that evidence is
unavailable. This is an experimental generated network, not an adopted plan, and its
alignments still require scheme-level feasibility and design work.

Released under the MIT licence. OpenStreetMap-derived outputs must retain
OpenStreetMap attribution and comply with the ODbL. NCN-derived outputs must retain
Walk Wheel Cycle Trust attribution and comply with the Open Government Licence v3.0.
