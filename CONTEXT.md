# Strategic Active Travel Network

This context defines the language for a council-portable process that develops one continuous, evidence-led cycling network from connections between places.

## Language

**Community**:
A named, inhabited settlement or recognisable urban neighbourhood admitted as a Network Place. It is not defined by an administrative ward, a universal population threshold or an individual destination.
_Avoid_: ward, destination, settlement point

**Community Reference Point**:
The single canonical network attachment shared by every connection to a compact Community in one compilation. It uses the Community Centre where practical, otherwise a usable on-route point that serves the built-up Community without an artificial detour.
_Avoid_: geometric centroid, arbitrary settlement point

**Community Portal**:
One of multiple canonical points where an external Community Connection meets the internal network of a physically extensive Community.
_Avoid_: boundary crossing, arbitrary entrance

**Urban Community**:
A named neighbourhood within a larger settlement that has its own cluster of everyday services and is admitted as a Community, preventing the larger settlement from collapsing into one network endpoint.
_Avoid_: ward, suburb label, city-centre spoke

**Community Centre**:
A named local high street or dense cluster of everyday services that anchors an Urban Community and must be reached by its internal network.
_Avoid_: city centre, individual shop, arbitrary centroid

**Community Amenity Profile**:
Qualitative present, absent or unknown facts about everyday services in a Community, used to explain local usefulness without creating Network Places, Community Connections or an unexplained score.
_Avoid_: destination list, demand score, required access

**Low-Traffic Area**:
An urban network area with defined portals and sufficiently permeable low-traffic internal streets or paths that an Alignment Option need not assert one exact centreline through it.
_Avoid_: single route, Community boundary, guaranteed LTN

**Candidate Low-Traffic Area**:
A proposed Low-Traffic Area inferred from a connected urban minor-road fabric bounded by the main-road network. It may cross Community or administrative boundaries and does not claim that low-traffic conditions already exist.
_Avoid_: existing LTN, neighbourhood boundary, quiet-road assumption

**Required Access Target**:
A school, hospital, major employment site or comparable centre of activity that must receive safe access from the network through its nearest Community or Low-Traffic Area without becoming a Community or generating inter-community adjacency.
_Avoid_: Community, optional amenity, strategic-network hub

**Network Place**:
A named endpoint admitted to the network as a Community, standalone Strategic Destination or interchange, or Cross-Boundary Gateway.
_Avoid_: arbitrary endpoint, map point

**Community Connection**:
The single selected connection between an unordered pair of Network Places. Competing ways to make the connection are Alignment Options, not parallel Community Connections.
_Avoid_: route alternative, duplicate link

**Local Adjacency**:
An evidence-backed relationship between nearby Network Places measured over the plausible cycling network. It emerges through recursive compilation and network validation rather than a fixed neighbour count; unusually long candidates are challenged rather than automatically excluded.
_Avoid_: fixed-radius link, all-to-hub connection, k-nearest rule

**Cross-Boundary Gateway**:
A Network Place at the governed study-area boundary with a named onward place or network connection.
_Avoid_: clipped endpoint, map-edge stub

**Gateway Destination**:
The nearest relevant town or city outside the governed study area reached along a Cross-Boundary Gateway's onward corridor. Intervening villages may inform routing but do not name the gateway.
_Avoid_: nearest settlement, boundary label, arbitrary external point

**Network Terminus**:
A degree-one endpoint of the authority-wide network, normally a Cross-Boundary Gateway. A Community is a Network Terminus only when no credible onward connection exists and the reason is recorded.
_Avoid_: dead end, dangling route

**Alignment Option**:
One evidence-backed, end-to-end way of realising a Community Connection. Only one Alignment Option may be selected into a published network.
_Avoid_: parallel connection, final design

**Network Gap**:
An unresolved absence of a continuous, bidirectionally traversable connection with plausible intervention coverage. A Network Gap prevents a network being Complete.
_Avoid_: visual gap, omitted link

**Route Refinement Finding**:
A recorded defect in an Alignment Option, such as a discontinuity, invalid join, excessive detour, or uncovered intervention need, that must be repaired or become a Network Gap.
_Avoid_: automatic snap, hidden error

**Crossing Warning**:
A non-blocking indication that selected route geometries cross without a shared Junction Node. It invites agentic inspection for a useful missing junction but does not imply that the crossing must connect.
_Avoid_: topology failure, automatic junction, prohibited crossing

**Quiet Lane**:
A rural lane whose low motor-traffic conditions and treatment make it a plausible active-travel alignment; the term does not imply that through motor traffic is prohibited.
_Avoid_: traffic-free lane, access-only lane

**Access-Only Quiet Lane**:
A rural lane where through motor traffic is physically or legally filtered while authorised access, including landowner, property and emergency access, remains.
_Avoid_: Quiet Lane, traffic-free path

**Strategic Spine**:
A rural A-road corridor whose cycling provision defaults to a wide shared-use path alongside the road. A parallel alignment is used only where adjacent provision is physically impracticable and the reason is recorded.
_Avoid_: cycling on the carriageway, optional corridor, unexplained diversion

**Urban Main-Road Spine**:
An urban main-road corridor that bounds Candidate Low-Traffic Areas and requires protected cycling infrastructure along the corridor.
_Avoid_: shared-use default, unprotected carriageway route, LTN interior

**Intervention Archetype**:
A plausible category of treatment that could make part of an indicative alignment accessible and traversable without asserting detailed feasibility or design.
_Avoid_: final design, unfunded promise

**Detour Factor**:
The measured relationship between an Alignment Option's travel distance and the direct distance between its Network Places, used to trigger challenge rather than impose one universal cutoff.
_Avoid_: directness pass/fail

**Bridge Connection**:
A Community Connection whose removal would split the network into disconnected parts.
_Avoid_: weak link

**Articulation Place**:
A Network Place whose removal would split the network into disconnected parts.
_Avoid_: critical town

**Reviewable Network**:
A published network state that may contain visible Network Gaps and open Route Refinement Findings for inspection.
_Avoid_: complete network, failed output

**Complete Network**:
A connected, bidirectionally traversable network with unique Community Connections, justified termini, continuous selected alignments, complete intervention-archetype coverage, and no blocking Route Refinement Findings.
_Avoid_: final design, adopted network

**Evidence Packet**:
An immutable, versioned collection of governed evidence and rules supplied to an agent role for one compilation scope.
_Avoid_: prompt context, live web research

**Agent Decision Record**:
A schema-valid, evidence-citing proposal, critique, synthesis or refinement emitted by an agent role without directly changing compiled state.
_Avoid_: free-form answer, silent edit

**Challenge Finding**:
A critic's evidence-backed challenge to a proposal, classified as blocking, revision-required or advisory and displayed through a traffic-light status.
_Avoid_: comment, untracked objection

**Governance Directive**:
A versioned, scoped human instruction that becomes governed input to a later compilation without overriding mandatory network invariants.
_Avoid_: manual output edit, validation waiver, prompt pragma

**Human Intervention Request**:
A structured handoff describing a blocked decision, attempted revisions, unresolved findings, missing evidence, available choices and the smallest human input needed.
_Avoid_: review requested, agent failure message

**Agent Role Contract**:
A provider-neutral definition of one agent role's instructions, Evidence Packet, permitted tools, output schema, citation duties and stopping behaviour.
_Avoid_: Codex prompt, model-specific workflow

**Compiled Connection**:
The typed result of compiling one Community Connection, including its selected Alignment Option, rejected alternatives, evidence, findings, intervention coverage and provenance.
_Avoid_: drawn route, agent response

**Network Compilation Unit**:
A recursively compiled subgraph assembled from Compiled Connections or smaller Network Compilation Units and assessed through the same proposal, critique, synthesis and validation protocol.
_Avoid_: map tile, administrative area

**Validated Connection**:
An immutable Compiled Connection that satisfies its applicable deterministic and agent-review contract and can be reused until a relevant governed input changes.
_Avoid_: cached guess, permanently approved route

**Criteria Set**:
A versioned collection of connection-level and network-level assessment criteria used by agent roles and deterministic validation for a compilation run.
_Avoid_: mutable scorecard, hidden rubric

**Criterion Status**:
The visible result of applying one criterion: Green when satisfied, Amber when agentic refinement or challenge is required, Red when a mandatory network invariant fails, and Grey when unevaluated or evidence is unavailable.
_Avoid_: aggregate score, implicit confidence, hidden failure

**Criteria Section**:
A coherent group of Criterion Statuses evaluated and displayed on its own merit. Sections are never collapsed into one overall traffic light or weighted score.
_Avoid_: dashboard total, worst-status rollup, composite score

**Full Recompile Directive**:
A Governance Directive requiring every connection and Network Compilation Unit to be compiled again under a declared Criteria Set while preserving prior results for comparison.
_Avoid_: cache clear, overwrite run

**Evidence Request**:
A structured request for evidence absent from an Evidence Packet, to be acquired and governed outside the compilation run.
_Avoid_: live browsing, unsupported assumption

**Wayfinding Pass**:
The compilation phase that connects Network Places into a valid end-to-end network using topology, constraints and alignment evidence. Demand and accessibility evidence do not determine connections in this pass.
_Avoid_: prioritisation, demand-led routing

**Prioritisation Pass**:
A later phase that uses demand, accessibility and other delivery evidence to order already-valid Community Connections without changing the network's required connectivity.
_Avoid_: wayfinding, network generation

**ATM Reference Corpus**:
The human-reviewed B&NES Active Travel Masterplan network, including existing and potentially planned alignments, used to improve and test the portable SATN compiler rather than define its rules.
_Avoid_: ground truth, portable dependency

**ATM-Seeded Compilation**:
A B&NES compilation that starts from ATM alignments where present and records reasons for any deviation.
_Avoid_: ATM validation, copied network

**ATM-Blind Compilation**:
A B&NES compilation that does not use ATM geometry during route proposal and compares its result with the ATM Reference Corpus afterwards.
_Avoid_: evidence-free compilation, automatic benchmark

**Divergence Record**:
The evidence-citing, red-teamed explanation of a difference between an ATM-seeded or ATM-blind result and the ATM Reference Corpus, including the attempted resolution and remaining uncertainty.
_Avoid_: geometry diff, unexplained mismatch

**Explicit Unknown**:
A material fact that the available evidence does not establish. It remains visible and must not be silently interpreted as absent, safe or zero.
_Avoid_: missing value, assumed absence
