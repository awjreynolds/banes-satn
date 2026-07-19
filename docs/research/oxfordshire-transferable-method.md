# Oxfordshire SATN: transferable method for a B&NES reference POC

## Scope, status and evidence discipline

This note maps Oxfordshire County Council’s (OCC) **Stage 1** Strategic Active Travel Network (SATN) process into a council-portable analytical method. It is not a claim that Oxfordshire’s network, priorities or decision has been adopted by B&NES. The reference implementation should be an independent, cycling-led proof of concept (POC) that produces reviewable evidence and indicative alignments.

The evidence base below is confined to OCC-owned primary material: the March 2024 final technical report, OCC’s Cabinet Member decision report and OCC’s consultation pages. Each recommendation labelled **Inference / adaptation** is a reasoned application to the stated B&NES constraints, rather than a fact claimed by OCC.

Principal sources: [OCC SATN Final Report, March 2024](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [Cabinet Member report and decision, 25 April 2024](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [OCC final SATN consultation and outcome](https://letstalk.oxfordshire.gov.uk/strategic-active-travel-network-satn-yswd); [OCC initial consultation](https://letstalk.oxfordshire.gov.uk/satn-initial).

## What Oxfordshire actually did

OCC framed SATN as a long-term, countywide walking-and-cycling network intended to join town LCWIPs and cover strategic/rural connections. It deliberately separated a prioritised *straight desire-line* network (Stage 1) from later feasibility, detailed design and construction (Stage 2). The Cabinet Member approved the Stage 1 map and a packaged Stage 2 approach on 25 April 2024. [Decision report, pp. 1–3](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [Final Report, pp. 6–7](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

Its four technical stages were:

1. **Baseline analysis.** Desk analysis brought together existing cycle routes and PRoW; Local Plan allocations, LCWIPs and Greenways; NTS, Census mode share, Strava, PCT and an "Everyday Trips" model; and terrain, severance, isochrones, population density, deprivation, public transport and collision data. A steering group supplied a continuing challenge function. [Final Report, p. 32](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
2. **Network development.** The evidence generated a long list of straight desire lines; early online engagement revised and extended it; the list was converted into 46 longer segments and 176 sub-segments. [Final Report, pp. 42–47](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
3. **Network prioritisation.** OCC created a settlement/location SATN Index, aggregated index scores within a 2 km corridor catchment and normalised results per kilometre; it considered both long segments and shorter sub-segments to avoid a purely central, short-link outcome. Results were reviewed with OCC and compared to its delivery pipeline before primary versus complementary categorisation. [Final Report, pp. 50–55](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
4. **Route optioneering.** Officers and stakeholders translated priority desire lines into multiple indicative physical alignments, classified them by typology and supplied a non-prescriptive design toolkit. OCC explicitly says these alignments were not definitive and still needed feasibility, design and engagement. [Final Report, pp. 56, 60–67](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

## Transfer decision register

| Oxfordshire element | B&NES POC treatment | Reason / guardrail |
| --- | --- | --- |
| Staged separation: strategic demand lines → feasibility/design | **Adopt** | It prevents indicative lines being mistaken for schemes. OCC’s decision report makes feasibility, land ownership, design and costing later-stage work. [Decision report, p. 2](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf) |
| Data baseline and combined-demand view | **Adopt** | Reuse the evidence-family structure, retain source/version metadata and publish limitations. OCC combined demand sources because each had limitations. [Final Report, pp. 32, 38](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Cycling PCT e-bike scenario | **Adapt** | Cycling-led is aligned, but make the e-bike scenario explicit, parameterised and sensitivity-tested rather than presenting it as observed demand. OCC used an e-bike scenario assuming 22% cycle mode share for commuting and better e-bike access. [Final Report, p. 33](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Straight lines between strategic focal points | **Adopt, with a hard topology rule** | OCC said desire lines should be book-ended by a settlement centre or existing local cycle network, “rather than ending nowhere.” B&NES should additionally require every line to join the cumulative network or be recorded as a cross-boundary gateway; no unexplained dead ends. [Final Report, p. 43](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Origins/destinations and “Everyday Trips” OD clustering | **Adopt, then localise** | This is a reproducible bottom-up mechanism for nearby-community links. Recreate the origin/destination classes and record B&NES substitutions where data differs. [Final Report, pp. 34–38](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| 5–20 km OD filter | **Replace** | It is an OCC strategic-network assumption, not a universal active-travel rule. B&NES should publish a distance-band policy (including e-bike bands) and test it; retain shorter inter-settlement links when they close a network gap or connect nearby communities. **Inference / adaptation.** |
| Settlement SATN Index and 2 km catchment/per-km normalisation | **Adapt** | Keep transparent, auditable scoring and length normalisation, but expose weights, thresholds and sensitivity tests. OCC’s report lists criteria and thresholds but does not publish a complete reproducible weighting formula or treatment for overlaps/double-counting. [Final Report, pp. 51–53](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Dual scoring of segments and sub-segments | **Adopt** | It counterbalances a short-link-only result with continuity of longer strategic routes. The POC should report both score types plus a network-continuity measure. [Final Report, pp. 53–55](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Primary / complementary classification | **Adapt** | Use it as a transparent analytical queue, not a funding commitment or adopted policy. OCC itself says complementary links still have strategic value and are not precluded from future work. [Final Report, p. 55](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| Multiple end-to-end ground alignments and typologies | **Adopt** | For each selected link, generate complete endpoint-to-endpoint indicative alternatives, identify the network joins at both ends, and label constraints. OCC used multiple alternatives so a failed preferred alignment did not terminate delivery. [Final Report, pp. 56, 60](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) |
| A broad walking/wheeling/equestrian framing | **Omit from the POC’s scoring objective; retain compatibility checks** | The stated B&NES scope is cycling-led. Do not claim a multi-user priority model that the POC does not implement; flag PRoW, access, equality and conflict considerations for later scheme work. OCC included a wider user set and received horse-riding feedback. [Final Report, pp. 6, 56](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [OCC consultation outcome](https://letstalk.oxfordshire.gov.uk/strategic-active-travel-network-satn-yswd) |
| OCC formal approval / integration with statutory LTCP | **Replace** | B&NES POC needs auditable review stages and a provenance statement, not mandatory per-link human approval, a Cabinet approval path, or an assertion of planning status. OCC’s approval and policy integration were specific governance choices. [Decision report, pp. 3–5](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf) |

## Portable analytical pipeline

### 0. Define the contract before mapping

Publish the study boundary, the B&NES settlement/community registry, a *gateway registry* for every cross-boundary connection, cycling-led purpose, candidate distance bands, the design-standard reference, and a statement that outputs are indicative. Every feature needs stable IDs, source, date/version, confidence/limitation, and a relationship to its parent link/segment.

**Inference / adaptation:** A B&NES-wide cumulative network needs this data contract earlier than Oxfordshire’s report makes explicit; it is what makes “no unexplained dead ends” mechanically testable.

### 1. Build the source snapshot

Use the OCC families as a portable checklist:

* existing cycle provision, PRoW and barriers/severance;
* committed and allocated housing/employment, local plan and transport schemes;
* population, destinations/trip generators, public-transport interchange and collision context;
* cycling-demand models, observed use where licensing/coverage permits, and a locally defined everyday-trip model;
* terrain and an e-bike scenario.

Store raw input references, import date, geographic coverage, licence and known bias. OCC itself notes that the PCT analysis used 2011 Census data rather than the newer 2021 outputs, and describes Strava as data from a digital activity-tracking service; neither should be treated as ground truth. [Final Report, pp. 33, 31–32](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

### 2. Generate a bottom-up candidate network

Replicate the transparent parts of OCC’s model:

* create origins from population-weighted small-area centroids and material committed/allocated development;
* classify destinations as higher-order centres/stations/key employment and local daily destinations (schools, healthcare, food, leisure and bus access);
* generate OD candidates, cluster them spatially, and combine them with cycling-demand evidence;
* turn clusters into straight indicative links between named communities, local networks or registered gateways.

OCC used 0.5 km² hexagons, included LSOAs/developments above 100 dwellings, distinguished two destination classes and created about 17,000 initial OD pairs before filtering and clustering. Those are documented implementation choices, not portable defaults. [Final Report, pp. 34–37](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

Run topology validation after each generation step:

* each candidate must have two declared endpoints;
* each endpoint must be a community, local-network join, destination hub, or cross-boundary gateway;
* isolated components must carry an explicit rationale and a proposed gateway, else be rejected;
* parallel/duplicate candidates and broken geometries must be reported, not silently discarded.

### 3. Segment without losing continuity

Maintain two network grains: **links** for community-to-community continuity and **sub-segments** for local intervention prioritisation. Segment boundaries should be named settlements, junctions, gateways or material constraint points—never arbitrary geometry alone. OCC also extended segments to rail stations and, where necessary, used iterative subdivision in dense areas. [Final Report, pp. 46–47](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

### 4. Score transparently; do not make the index a black box

Implement a published scorecard for every community, destination and route sub-segment. OCC’s criteria were existing/future residential population, workplace population, housing and employment allocations, key attractors, rail stations and strategic bus routes; its future-population calculation assumed 2.4 residents per new dwelling. [Final Report, p. 51](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

For B&NES, use a declared formula such as:

`priority = demand + access/need + network-connectivity + deliverability-readiness + strategic-policy fit`

where each component has published inputs, transform, weight, missing-data rule and sensitivity range. Score both (a) sub-segments within a stated catchment and normalised per km, and (b) full links for cumulative network value. OCC’s 2 km catchment and per-km conversion are documented choices; select and test B&NES values rather than inheriting them. [Final Report, pp. 52–54](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

**Inference / adaptation:** Add explicit network-connectivity credit (component connection, access to the growing e-bike network, and gateway continuity). This directly implements the B&NES constraint and corrects a limitation of a settlement-proximity score, which can favour central short links.

### 5. Convert priority lines into indicative, end-to-end alignments

For each primary link, develop at least one continuous map trace from endpoint to endpoint; where a plausible alternative exists, retain it. Break the trace at constraint locations and record route type, road/PRoW status where known, terrain, severance/crossing need, visible connection to the cumulative network, and unresolved feasibility question. Use a typology catalogue—e.g. protected on-carriageway, low-traffic street/quiet lane, greenway/shared path, towpath, former railway, farm track/PRoW, plus area and junction measures—without asserting a design solution.

This reflects OCC’s multi-alignment, typology-led toolkit and its warning that land ownership, cost and design constraints are only resolved through later work. [Final Report, pp. 56, 60–67](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

### 6. Auditable review stages, not adoption theatre

Use four explicit review stages. Each emits inspectable artifacts, deterministic validation results, and agent critique/red-team records. A human can observe, intervene, or reject a run without having to approve every link:

1. **Evidence review:** challenge the source snapshot, data gaps/biases and candidate-generation parameters.
2. **Network review:** challenge communities, gateways, topology validation and cumulative-network coverage, drawing on recorded local knowledge where available.
3. **Prioritisation review:** challenge the scorecard, sensitivity results, pipeline interactions and primary/complementary queue.
4. **Alignment review:** challenge indicative traces and the constraint register; only then recommend separate surveys, landowner/stakeholder engagement, feasibility, design and costing.

This follows OCC’s use of a steering group, early and final consultation, officer workshops, and a Stage 2 feasibility/design sequence, while respecting that this POC is not an adopted B&NES plan. [Initial consultation](https://letstalk.oxfordshire.gov.uk/satn-initial); [Final Report, pp. 43–56, 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

### 7. Manage cross-boundary links as first-class network objects

OCC’s initial index considered locations up to 20 km beyond the county boundary, its engagement identified cross-boundary routes, and its recommendations called for structured, consistent coordination with neighbouring authorities. [Final Report, pp. 6–7, 45–46, 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).

For B&NES, do not clip a desire line at the authority boundary. Create a gateway record containing: boundary point, external settlement/network it serves, evidence of demand, neighbouring authority/route-plan reference if known, owner for contact, and the B&NES-side indicative alignment. **Inference / adaptation:** this is the portable operationalisation of OCC’s cross-boundary coordination recommendation and avoids map-edge dead ends.

## Undocumented or non-transferable assumptions to surface

The following are either explicitly acknowledged as assumptions by OCC, or important details not supplied in the report; they must not be copied silently.

* **Mode and trip assumptions:** the e-bike PCT scenario assumes 22% commuting trips by cycle and improved e-bike access; PCT was based on 2011 travel-to-work/school data. OCC uses it for ambitious long-term potential, not measured B&NES demand. [Final Report, p. 33](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
* **Strategic-distance rule:** excluding intracommunity pairs and keeping only 5–20 km pairs was a purposeful Oxfordshire definition of strategic. It may suppress short but essential B&NES connections. [Final Report, p. 37](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
* **Geographic thresholds:** 0.5 km² hexagons, >100-dwelling origin inclusion, 2 km scoring catchments, 20 km external index extent, 1 km development buffers, population bands and 2.4 persons/dwelling are all model choices. The report documents them but supplies no transferability justification or sensitivity analysis. [Final Report, pp. 34, 51–53](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
* **Index reproducibility:** OCC names the score criteria and some scoring bands, but the public report does not fully specify component weights, aggregation mechanics, handling of overlapping catchments, data cleaning, or tie-break rules. A B&NES toolchain must publish those.
* **Quiet-lane deliverability:** OCC’s toolkit says its quiet-lane approach assumes low motor-traffic volumes and may need modal filters. It cannot be inferred from a road label alone. [Final Report, p. 64](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
* **Alignment feasibility:** OCC explicitly treats physical alignments as non-definitive pending feasibility, landowner engagement and detailed survey. The POC must not imply rights, costs, permissions, safety audit outcomes or deliverability. [Final Report, pp. 56, 60](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf).
* **Governance and legal weight:** OCC’s SATN was tied to its LTCP and Cabinet Member decision; that status, staff structure, funding routes and relationship with district authorities are not portable to an independent B&NES POC. [Decision report, pp. 3–5](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf).

## Minimum POC outputs

1. Versioned source-and-assumption manifest.
2. Community, destination and cross-boundary gateway registers.
3. Candidate desire-line network with topology-validation report.
4. Published scoring specification, input table and sensitivity results for both links and sub-segments.
5. One cumulative local-to-e-bike network map, with each route’s endpoints and joins visible.
6. End-to-end indicative alignment cards for selected links: alternatives, typology, constraints and explicit “not feasibility/design” status.
7. Review log distinguishing source fact, stakeholder/local-knowledge input, model result, and agent or human inference.

These outputs preserve Oxfordshire’s strongest transferable discipline—separating evidence, strategic prioritisation and scheme development—while making the B&NES-specific cycling, nearby-community, cumulative-network and gateway requirements auditable.
