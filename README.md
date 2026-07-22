# banes-satn

Council-portable tooling for compiling an evidence-led Strategic Active Travel
Network (SATN), with Bath and North East Somerset as the reference implementation.

> Experimental SATN POC — not an adopted B&NES plan.

The compiler connects communities to nearby communities, then assembles and repairs
those connections into an end-to-end network. It keeps route choice separate from
later demand or delivery prioritisation.

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

Each Community nominates its nearest reachable Community using cycling-network
distance. Reciprocal nominations become one unordered Community Connection. The
compiler compares only continuous OSM alignments:

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

In urban areas, main roads form protected-route spines. Connected fabrics of minor
roads become Candidate Low-Traffic Area polygons, without claiming that an LTN
already exists or asserting an artificial centreline. Community Centres, portals,
spines and those areas stay in one routable and publishable representation.

## Agent compilation gate

Every candidate passes a bounded typed sequence: Proposer, deterministic checks,
Evidence Critic, Network Red Team and Synthesiser. Findings feed a subsequent
revision attempt, but agents cannot mutate compiled state or override a Red mandatory
criterion. Repeated output, request/token limits or exhausted revisions terminate as
an explicit Network Gap. The full Pydantic records are published as JSON; the review
map shows their concise rationale.

`fake` is the deterministic default. Any Pydantic AI model identifier can be supplied
in Council Configuration as `compilation.agent.model`, with provider credentials read
from its normal environment variables. Codex is not required. A live adapter check is
explicit and opt-in:

```shell
SATN_TEST_AGENT_MODEL=openai:gpt-5-mini \
  uv run pytest --live-agent -m live_agent tests/test_agent_gate.py
```

## Network assembly

Compiled Connections are recursively joined into network units. The compiler first
bridges disconnected components using the nearest viable untried pair, then repairs
unexplained degree-one Communities. Cross-boundary Gateways remain legitimate
termini. A pair is attempted at most once, every successful iteration changes the
graph, and the finite pair set guarantees termination. Unjoinable components produce
visible Network Gaps; unjoined route crossings produce non-blocking Amber warnings.

## Incremental and full compilation

Validated Connections are cached outside the replaceable publication directory. A
cache key covers the council, immutable snapshot, Criteria Set version, compilation
and agent configuration, ATM mode and — for seeded runs — the ATM file fingerprint.
The same governed inputs reuse the validated result without invoking its agent gate.
Gaps are never cached.

```shell
# reuse unchanged Validated Connections
uv run satn compile config/banes.yaml

# ignore every reusable connection and rebuild the network units
uv run satn compile config/banes.yaml --full
```

Changing `compilation.criteria_version` invalidates all version-one reuse.

## ATM quality comparison

ATM is an optional B&NES quality reference, not a portable network rule or an
authoritative answer. Put the locally governed file at
`data/local/banes-atm-full.geojson`, set `atm.enabled: true`, and choose one mode:

- `blind` compiles routes before the ATM file is loaded, then compares them;
- `seeded` uses ATM proximity to choose the starting hypothesis among available OSM
  alignments and records any later deviation.

The typed divergence output distinguishes matches, deviations, additions and
omissions. Each receives a bounded agent review, but there is no aggregate agreement
score and a match does not prove correctness.

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
- `network.geojson`, `run.json`, `agent-records.json` and
  `divergence-records.json` expose the same stable identifiers;
- `review-map/` is a backend-free static site with a vendored, pinned MapLibre build;
- `review-map.zip` contains that complete directory unchanged; and
- `network-map.pdf` is A3 landscape by default, with configurable A2/A3/A4 size,
  title, date, legend, scale and disclaimer.

Open `review-map/index.html` directly or serve the directory from any static host.
The map presents A-road corridors as its core spine, Community Connections above
them, and NCN evidence as a distinct overlay. Schools, derived high-street/retail
centres and healthcare facilities default off to avoid noise; each has its own
control. Places, urban structure, gaps/warnings and ATM comparison are independently
toggleable. Connections, Network and ATM criteria remain separate. Hover or keyboard
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
is published beside it for download and printing.
It contains 163 unique Community Connections in one end-to-end network, with no Red
Network Gaps and five non-blocking route-crossing warnings. The public map excludes
the governed ATM geometry. After a validated public compile, refresh the tracked
GitHub Pages bundle with:

```shell
uv run python scripts/publish_site.py
```

## Check

```shell
uv run ruff check .
uv run pytest
```

## Status

The POC compiler and its full B&NES reference publication are complete. The current
snapshot contains 127 Network Places and 41,158 OSM road edges. The same governed
snapshot also contains 2,373 A-road segments, 195 NCN segments, 104 education sites,
55 derived retail centres and 78 healthcare sites. The resulting 163 Connections
form one network unit; an unchanged incremental run reuses all 163
validated Connections. This is an experimental generated network, not an adopted
plan, and its alignments still require scheme-level feasibility and design work.

Released under the MIT licence. OpenStreetMap-derived outputs must retain
OpenStreetMap attribution and comply with the ODbL. NCN-derived outputs must retain
Walk Wheel Cycle Trust attribution and comply with the Open Government Licence v3.0.
