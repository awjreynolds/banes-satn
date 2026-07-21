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

This retrieves the full governed boundary, cycling graph, named place features and
public-transport stations. The immutable snapshot records its query, retrieval time
and OpenStreetMap attribution. Towns, villages and named urban neighbourhoods are
admitted as Community candidates; hamlets are not mandatory Network Places. Large
Community polygons can expose connected network portals, and genuine outward road
crossings are named for their nearest external town or city.

The network request is intentionally live and can take time. Its explicit smoke test
is:

```shell
uv run pytest --live-osm -m live_osm tests/test_osm_sources.py
```

## How routes are compiled

Each Community nominates its nearest reachable Community using cycling-network
distance. Reciprocal nominations become one unordered Community Connection. The
compiler compares only continuous OSM alignments:

- a direct A-road corridor is the preferred Strategic Spine, representing a wide
  alongside shared path rather than cycling in the carriageway;
- a parallel route is used when alongside provision is explicitly found physically
  impracticable, with that reason retained;
- other rural connections compare direct and low-traffic OSM paths;
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

ATM is an optional B&NES quality reference, not a portable network rule and not
ground truth. Put the locally governed file at
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

## Check

```shell
uv run ruff check .
uv run pytest
```

## Status

The complete compiler, full-boundary OSM snapshot path, network assembly and governed
ATM comparison are implemented. Publication and full B&NES validation remain in the
linked PRD issues.

Released under the MIT licence. OpenStreetMap-derived outputs must retain
OpenStreetMap attribution and comply with the ODbL.
