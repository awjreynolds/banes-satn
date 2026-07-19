# Strategic Active Travel Network

This context defines the language for a council-portable process that develops one continuous, evidence-led cycling network from connections between places.

## Language

**Network Place**:
A named endpoint admitted to the network as a Community, standalone Strategic Destination or interchange, or Cross-Boundary Gateway.
_Avoid_: arbitrary endpoint, map point

**Community Connection**:
The single selected connection between an unordered pair of Network Places. Competing ways to make the connection are Alignment Options, not parallel Community Connections.
_Avoid_: route alternative, duplicate link

**Cross-Boundary Gateway**:
A Network Place at the governed study-area boundary with a named onward place or network connection.
_Avoid_: clipped endpoint, map-edge stub

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

**Quiet Lane**:
A rural lane whose low motor-traffic conditions and treatment make it a plausible active-travel alignment; the term does not imply that through motor traffic is prohibited.
_Avoid_: traffic-free lane, access-only lane

**Access-Only Quiet Lane**:
A rural lane where through motor traffic is physically or legally filtered while authorised access, including landowner, property and emergency access, remains.
_Avoid_: Quiet Lane, traffic-free path

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

**Full Recompile Directive**:
A Governance Directive requiring every connection and Network Compilation Unit to be compiled again under a declared Criteria Set while preserving prior results for comparison.
_Avoid_: cache clear, overwrite run

**Evidence Request**:
A structured request for evidence absent from an Evidence Packet, to be acquired and governed outside the compilation run.
_Avoid_: live browsing, unsupported assumption
