# Oxfordshire SATN, LCWIP equivalence, and an agentic LCWIP foundation

- Retrieved: 2026-07-24
- Scope: official/current Oxfordshire and national requirements; no assessment of the B&NES implementation
- Sources: first-party Oxfordshire County Council, Department for Transport and Active Travel England material only
- Status labels used below:
  - **Fact** — stated or directly demonstrated by an official source
  - **Inference** — analytical conclusion drawn from the cited facts
  - **Evidence gap** — information or artefact needed to verify a claim was not found in the official published record

## Executive conclusion

**Fact.** Oxfordshire's Strategic Active Travel Network (SATN) is an approved, countywide strategic network-planning programme for inter-urban and rural walking and cycling links. Its approved first stage produced a prioritised straight-line desire network, possible on-the-ground alignments, a primary/complementary classification and an illustrative design toolkit. The second stage is intended to turn those strategic links into area packages, feasibility work, preferred alignments, detailed design, costing and construction. It was explicitly created to connect and fill gaps between more detailed, settlement-focused LCWIPs. ([Oxfordshire SATN final report, pp. 6–7, 50–70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [Cabinet Member report, paragraphs 1–8](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [current OCC active-travel page, “Strategic Active Travel Network”](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel))

**Inference.** SATN is a strong strategic-network discovery and corridor-prioritisation process. It is not, on the published evidence, a complete replacement for a conventional LCWIP. The clearest blockers are:

1. it does not publish a separate LCWIP-standard walking method with Core Walking Zones, key walking routes and WRAT audits;
2. it does not publish RST-equivalent route-condition audits or a route-by-route programme of required improvements;
3. it does not produce a prioritised, costed, short/medium/long-term infrastructure pipeline;
4. the April 2024 decision approved Stage 1 and the Stage 2 approach, while describing SATN as an LTCP supporting document; the final report itself recommends that OCC *consider* adopting it as an LCWIP;
5. its final primary/complementary classification includes officer judgement and the pre-existing delivery pipeline, but the published evidence does not contain the underlying GIS, scoring workbook, full score table, cut-off rules or decision log needed for deterministic reproduction.

The distinction is also visible in Oxfordshire's own current practice. The council's active-travel page separately describes and lists approved LCWIPs and SATN. A recent approved Oxfordshire LCWIP includes separate cycling and walking network maps, site audits, RST/WRAT evidence, specific interventions, route-level prioritisation, indicative costs, delivery timescales, integration and a monitoring/review cycle. ([current OCC active-travel page, “Local Walking and Cycling Infrastructure Plans” and “Strategic Active Travel Network”](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel); [Eynsham LCWIP, 2026, pp. 7–47 and appendices](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/EynshamLCWIP.pdf))

**Inference.** SATN can be part of the foundation for agentic LCWIP production, but only as one module: strategic demand modelling, desire-line creation, inter-settlement network construction and one layer of prioritisation. A safe LCWIP agent must add the missing walking, route-audit, intervention, phasing, costing, equality, consultation, governance, monitoring and provenance layers. It must prepare evidence and draft recommendations for human review; it cannot safely replace site investigation, stakeholder deliberation, accountable prioritisation or formal council adoption.

## 1. What Oxfordshire SATN is

### 1.1 Purpose and boundary

**Fact.** SATN is a long-term countywide plan for walking and cycling routes. Its objectives are to:

- link relevant origins and destinations across the county;
- provide a framework for prioritising routes by their potential to sustain commuting, leisure and other active trips;
- outline indicative infrastructure improvements;
- support funding bids where detailed plans such as LCWIPs do not exist;
- use opportunities in developments, local plans, regeneration and infrastructure projects; and
- bridge strategic/infrastructure plans and promote consistent active-travel design.
([SATN final report, pp. 6–7](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** Oxfordshire describes LCWIPs as town/local networks and SATN as the network connecting them for longer-distance travel. SATN works at a less detailed, inter-settlement and rural scale. ([current OCC active-travel page, lines under “Local Walking and Cycling Infrastructure Plans” and “Strategic Active Travel Network”](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel); [initial SATN consultation, “Background”](https://letstalk.oxfordshire.gov.uk/satn-initial))

**Fact.** Oxfordshire Greenways is presented as a further layer between local LCWIPs and SATN: SATN identifies strategic inter-settlement connections, LCWIPs local settlement networks, and Greenways fills the connection between them. ([Oxford Greenways consultation, “How does this fit with other walking and cycling plans?”](https://letstalk.oxfordshire.gov.uk/oxford-greenways))

**Inference.** Oxfordshire operates a layered planning model, not an either/or substitution:

`local LCWIP networks → Greenway/route development → countywide SATN corridors`.

SATN's geographic breadth is a feature, but its lesser detail is the reason it cannot automatically displace the local LCWIP layer.

### 1.2 Two meanings of “stage”

The source material uses two different stage models. A replacement must preserve the distinction.

**Fact — technical methodology.** The report describes four analytical components:

1. baseline analysis;
2. network development;
3. network prioritisation using a SATN Index;
4. route optioneering/design development.
([SATN final report, pp. 6–7](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact — delivery programme.** The approved programme has two stages:

1. **Stage 1, concluded:** data analysis, stakeholder engagement, prioritised straight-line network and initial alignment/design work.
2. **Stage 2, in progress:** divide the network into local area packages; undertake feasibility, land and infrastructure checks; confirm/amend alignments; then perform detailed design, costing and construction.
([Cabinet Member report, paragraphs 1–7](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [current OCC active-travel page, “Stage 1” and “Stage 2”](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel))

**Inference.** A tool that recreates the four-part Stage 1 analysis has not thereby delivered the approved Stage 2 programme, still less an LCWIP. “Generated alignments” must not be represented as feasible, costed or committed routes.

## 2. SATN inputs and data requirements

### 2.1 Baseline layers

**Fact.** Stage 1 used open-source mapping, data supplied by Oxfordshire, its districts and Oxford City Council, and Steering Group feedback. Its baseline grouped evidence into:

- **existing network:** cycle routes and Public Rights of Way;
- **policy and parallel projects:** Local Plan allocated sites, LCWIP extents and Greenways;
- **demand:** National Travel Survey, Census mode share, Strava, PCT and an “Everyday Trips” model;
- **geographic/social context:** terrain, severance, isochrones, population density, deprivation, public transport, collision data and car-free households.
([SATN final report, pp. 14–38](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [SATN Equalities Impact Assessment, pp. 5–7](https://mycouncil.oxfordshire.gov.uk/documents/s70849/CMDIDS25042024%2B-%2BAnnex%2B4%2B-%2BEqualities%2BImpact%2BAssessment.pdf))

The detailed published data inventory is:

| Theme | Published SATN input |
|---|---|
| Population and development | ONS built-up areas; 2019 mid-year population estimates; Census 2021 usual residents; LSOA/MSOA population; housing and employment allocations/committed sites |
| Existing and potential travel | Census 2011/2021 mode share; National Travel Survey; PCT commuting/school model; Strava walking/cycling; custom Everyday Trips model |
| Public transport | rail stations and DfT station categories; strategic bus network; bus stops |
| Destinations | town/village/local centres; schools; health services; supermarkets; leisure; libraries; tourist attractions; employment sites |
| Network | existing cycle facilities; PRoW; LCWIPs; Greenways; National Cycle Network and related proposals |
| Context/constraints | elevation; severance by roads, rail and rivers; pedestrian/cycle collisions; deprivation; car-free households |

([SATN final report, pp. 14–38 and 51](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

### 2.2 PCT demand

**Fact.** SATN used the top 300 residence-to-workplace PCT pairings and the e-bike scenario, which the SATN report describes as an ambitious long-term outlook with 22% of commuting trips by bicycle and improved access to e-bikes. The report also acknowledges that PCT still relies on 2011 Census data. ([SATN final report, p. 33](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** DfT describes PCT as a recommended strategic cycling-network tool for mapping areas, origins/destinations, desire lines, route assignments and scenarios. DfT also states that PCT's route/desire-line estimates exclude some trips, including within-zone commuting, and that non-work destinations and post-2011 developments need separate treatment. ([DfT LCWIP tools annex, Annex A](https://assets.publishing.service.gov.uk/media/5f32c8f8d3bf7f1b10d58fd7/cycling-walking-infrastructure-tools-document.pdf); [DfT LCWIP technical guidance, paragraphs 4.8–4.12 and 5.13–5.16](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

### 2.3 Everyday Trips model

**Fact.** The custom model:

1. divided the county into 0.5 km² hexagons;
2. selected origin hexagons containing LSOA population-weighted centroids or housing allocations/committed developments over 100 dwellings;
3. defined Class 1 destinations as centres, railway stations and future/key employment sites;
4. defined Class 2 destinations as schools, hospitals, supermarkets, leisure centres, libraries, bus stops and similar amenities;
5. linked each origin to its nearest Class 2 destination and to all Class 1 destinations;
6. generated about 17,000 origin-destination pairs;
7. removed intra-settlement pairs and retained strategic trips between 5 km and 20 km, leaving fewer than 1,000;
8. used ArcGIS density-based clustering and a linear directional mean to identify/rank desire-line clusters; and
9. combined this layer with PCT and Strava demand.
([SATN final report, pp. 34–38](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Inference.** The 5–20 km and no-intra-settlement filters are appropriate to SATN's strategic inter-urban purpose but are incompatible with a full local LCWIP if applied globally. DfT expects local cycle networks and walking analysis around trips typically up to about 2 km; Oxfordshire's latest local LCWIP practice uses an explicit local Core Walking Zone and surrounding key walking routes. ([DfT LCWIP technical guidance, paragraphs 3.3–3.6 and 6.14–6.17](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf); [Eynsham LCWIP, geographic scope and walking-network chapters](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/EynshamLCWIP.pdf))

### 2.4 Data-quality evidence gaps

**Evidence gap.** The published record does not include:

- a source manifest with exact dataset versions, access dates, licences and coordinate systems;
- the ArcGIS model, code, notebook or geoprocessing history;
- the underlying origin/destination, cluster and demand-combination GIS layers;
- a rule for reconciling overlaps and double counting between PCT, Strava and Everyday Trips;
- missing-data or proxy-data rules;
- a quantified uncertainty or sensitivity analysis;
- a refresh/rescoring protocol.

**Inference.** A map that visually resembles SATN is not computationally equivalent unless those provenance and transformation details are reconstructed and independently validated.

## 3. SATN network-building workflow

### 3.1 From long list to segments

**Fact.** The published sequence is:

1. create Long List V1 from demand clusters, public-transport proximity, strategic-network contribution and alignment with existing cycle routes;
2. use the December 2022 engagement to create a Longer List;
3. refine this into Long List V2;
4. convert the lines into 46 route segments, usually book-ended by settlements;
5. subdivide at settlements/junctions into 176 subsegments;
6. have the Steering Group check whether the segmentation is locally logical;
7. score segments and subsegments;
8. compare results with Oxfordshire's existing delivery pipeline;
9. use an OCC/PJA workshop to select primary links and propose ground alignments; and
10. revise the proposals after the July–August 2023 consultation.
([SATN final report, pp. 42–56](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** Initial straight lines were normally book-ended by settlements so routes would connect to a focal point or local network rather than terminate without a destination. Some lines extend beyond Oxfordshire to important neighbouring settlements. ([SATN final report, pp. 43–47](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

### 3.2 From desire line to possible alignment

**Fact.** A joint workshop translated selected straight lines into possible ground alignments using officer/stakeholder local knowledge. Multiple options were retained where useful, covering on-carriageway, low-traffic, traffic-free and PRoW routes. The resulting alignments are explicitly provisional and require feasibility, design, landowner and stakeholder work. ([SATN final report, p. 56](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [final-draft consultation, “The proposals”](https://letstalk.oxfordshire.gov.uk/satn))

**Fact.** The public consultation page says the maps are early optioneering and do not commit the council to deliver any route. Feasibility and further engagement, including with landowners, are required. ([final-draft consultation](https://letstalk.oxfordshire.gov.uk/satn))

**Inference.** An agent may propose route candidates, but it must preserve a state distinction between:

- modelled desire line;
- possible alignment;
- audited option;
- preferred feasible alignment;
- concept design;
- funded/approved scheme; and
- constructed route.

Collapsing these states would materially misrepresent the evidence.

## 4. SATN prioritisation and scoring

### 4.1 Settlement/location index

**Fact.** The SATN Index assigned comparable strategic scores to settlements and standalone sites within Oxfordshire and up to 20 km beyond the county boundary. ([SATN final report, pp. 50–51](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

| Metric | Published source and scoring approach |
|---|---|
| Existing + future residential population | 2019 ONS estimates plus Census 2021 usual residents; future development assumes 2.4 people per dwelling; eight population bands from ≤500 to >75,000 |
| Workplace population | Census 2011 workplace population; same population-band scoring |
| Housing allocations/committed developments | Count within 1 km of settlement boundary |
| Employment sites/allocations | Count within 1 km of settlement boundary |
| Key attractors/trip generators | Count within settlement boundary, using OS open data, NHS data and OpenStreetMap |
| Train stations | Each station scored 1–6 according to DfT station category F–A, then summed |
| Strategic bus routes | Count crossing the built-up-area boundary |

([SATN final report, p. 51](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

### 4.2 Route scores

**Fact.** For every segment/subsegment, SATN:

1. created a 2 km catchment;
2. summed Index scores for sites/settlements in that catchment;
3. divided the total by segment length to obtain a per-km result; and
4. converted results to percentage scores for comparison.
([SATN final report, pp. 50–54](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** The final network has:

- **strategic/primary links:** a combination of links SATN would develop further and links already in OCC's designs/pipeline; and
- **complementary/secondary links:** other strategically valuable links recommended for development outside the immediate SATN programme.
([SATN final report, p. 55](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Inference.** The final classification is a hybrid policy judgement, not the mechanical output of the Index alone. Existing-pipeline status and an officer workshop materially influenced which routes became primary.

### 4.3 Reproducibility gaps

**Evidence gap.** The official public record does not expose:

- the complete settlement/site Index table;
- the complete segment and subsegment score tables;
- an exact aggregation/normalisation formula for every Index component;
- relative weights, if any;
- the numeric cut-off or tie-breaking rule for primary/complementary status;
- the record of pipeline comparisons and workshop changes;
- sensitivity to 1 km/2 km/20 km catchments, population bands or route segmentation; or
- the handling of a settlement/site intersecting more than one catchment.

**Inference.** Published SATN can define the shape of a replacement algorithm, but it cannot establish bit-for-bit or route-for-route equivalence. A replacement should publish its full score ledger and all manual decision overrides rather than imply that it has recovered the unpublished original.

## 5. SATN outputs

### 5.1 Approved/public artefacts

**Fact.** The official Stage 1 package comprises:

- [prioritised straight-line desire map](https://mycouncil.oxfordshire.gov.uk/documents/s70846/CMDIDS25042024%20-%20Annex%201%20-%20Prioritised%20Straight-Line%20Desire%20Map.pdf);
- [March 2024 SATN final report](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf);
- possible ground-alignments map;
- strategic/primary and complementary/secondary classifications;
- an illustrative design toolkit;
- [Climate Impact Assessment](https://mycouncil.oxfordshire.gov.uk/documents/s70848/CMDIDS25042024%20-%20Annex%203%20-%20Climate%20Impact%20Assessment.pdf); and
- [Equalities Impact Assessment](https://mycouncil.oxfordshire.gov.uk/documents/s70849/CMDIDS25042024%2B-%2BAnnex%2B4%2B-%2BEqualities%2BImpact%2BAssessment.pdf).
([April 2024 Cabinet Member report, annex list](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf))

### 5.2 Design toolkit

**Fact.** The SATN toolkit is expressly illustrative and non-prescriptive. It covers:

- linear interventions: protected tracks, cycle streets, speed reduction, Greenways, shared paths, towpaths, disused railways, farm tracks, PRoW and behind-hedge routes;
- area interventions: Quiet Lanes, traffic calming and local-centre improvements; and
- spot/operational interventions: crossings, junctions, drainage, fencing, access control, structures, cycle parking, signage and wayfinding.
([SATN final report, pp. 60–67](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** Oxfordshire separately maintains local Cycling and Walking Design Standards and says they are being updated in light of LTN 1/20 and Inclusive Mobility. ([OCC active-travel page, “Walking and cycling design standards”](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel); [OCC Transport Development Management guidance](https://www.oxfordshire.gov.uk/transport-and-travel/transport-policies-and-plans/transport-new-developments/transport-development))

**Inference.** SATN's toolkit is not a route-audit scoring model, concept-design standard or compliance checker. An equivalent LCWIP tool must keep “example intervention” separate from “audited deficiency”, “selected treatment” and “design-standard compliance”.

### 5.3 The report's own missing-output recommendations

**Fact.** The final report recommends that OCC:

1. create a single GIS-compatible online plan of SATN, LCWIP, NCN and existing routes;
2. undertake detailed level-of-service audits of priority routes using LTN 1/20 tools while considering LCWIP RST/WRAT where networks converge;
3. consider a freely available online SATN route-audit toolkit;
4. perform further design, surveys, landowner/stakeholder engagement and cross-boundary coordination;
5. consider adopting SATN as an LCWIP; and
6. create a SATN Oversight Group.
([SATN final report, p. 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Inference.** These recommendations are a direct official definition of non-equivalence at the end of Stage 1: unified machine-readable mapping, LCWIP-compatible audits, formal LCWIP adoption and continuing oversight were recommendations, not demonstrated completed outputs.

## 6. Governance, consultation and adoption

### 6.1 Governance

**Fact.**

- OCC's Active Travel Programme Board made SATN a priority workstream in March 2021.
- PJA supported OCC from August 2022 to February 2024.
- a Steering Group included county, city and district officers/councillors and stakeholder groups;
- neighbouring authorities were engaged on cross-boundary work;
- the Cabinet Member approved the prioritised straight-line network and the packaged Stage 2 approach on 25 April 2024;
- Stage 2 is to be delivered by local/place teams with the Active Travel Team; and
- the decision report says future route delivery requires separate resources/business cases and that SATN will be an LTCP supporting document.
([SATN final report, pp. 6, 14 and 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [Cabinet Member report, paragraphs 11–19](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [decision record](https://mycouncil.oxfordshire.gov.uk/mgIssueHistoryHome.aspx?IId=35483))

**Fact.** The decision report says SATN should be reviewed regularly, including continued discussion of route prioritisation, but it does not set a cadence. The final report recommends an Oversight Group. ([Cabinet Member report, paragraphs 23–25](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [SATN final report, p. 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Evidence gap.** No published SATN Oversight Group terms of reference, Stage 2 package register, change-control procedure, review cadence or version history after approval was found.

### 6.2 Engagement and consultation

**Fact.**

- Early engagement ran 5–28 December 2022 and tested whether key inter-settlement connections were missing.
- The final-draft consultation ran 4 July–6 August 2023.
- Feedback added destinations and routes, reclassified three links, increased recognition of horse riders/bridleways, corrected map keys and added stronger caveats about sensitive areas, landowners, feasibility and delivery barriers.
- Further scheme-level consultation and landowner engagement remain necessary.
([initial SATN consultation and lifecycle](https://letstalk.oxfordshire.gov.uk/satn-initial); [final-draft consultation and lifecycle](https://letstalk.oxfordshire.gov.uk/satn); [final “You said, we did” page](https://letstalk.oxfordshire.gov.uk/strategic-active-travel-network-satn-yswd))

**Fact.** The final report records 46 early responses: 63% strongly supported, 34% supported and 3% neutral. ([SATN final report, p. 44](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

### 6.3 Official-record inconsistencies

The following discrepancies must be preserved rather than silently resolved:

- the final report says 148 final-consultation responses; the Cabinet report/current “You said, we did” page say 147;
- the Cabinet report says the final consultation was in July 2022, but both consultation lifecycle pages identify July–August 2023;
- the Equalities Impact Assessment says 307 comments, while the public page says 310 suggestions;
- the current OCC active-travel page gives a consultation range beginning in 2021 that conflicts with the consultation lifecycle; and
- some Cabinet text expands SATN as “Sustainable”, while the project/policy name is “Strategic”.
([SATN final report, p. 56](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [Cabinet Member report, paragraph 26](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [Equalities Impact Assessment, pp. 6–7](https://mycouncil.oxfordshire.gov.uk/documents/s70849/CMDIDS25042024%2B-%2BAnnex%2B4%2B-%2BEqualities%2BImpact%2BAssessment.pdf); [“You said, we did” page](https://letstalk.oxfordshire.gov.uk/strategic-active-travel-network-satn-yswd); [current OCC active-travel page](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel))

**Inference.** An agentic system needs source-level provenance, conflict flags and an authorised resolution record. It must not turn inconsistent official counts/dates into a false single “fact”.

### 6.4 Formal status

**Fact.** The April 2024 recommendation/decision approved the prioritised straight-line map and the Stage 2 approach. The legal section describes SATN as a supporting document to the LTCP. The final SATN report recommends that OCC consider adopting SATN as an LCWIP. ([Cabinet Member report, recommendation and paragraphs 16–17](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf); [SATN final report, p. 70](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf))

**Fact.** Later Oxfordshire material sometimes calls SATN a countywide or “super” LCWIP, but the council's current active-travel page still lists approved local LCWIPs and SATN as separate sections and functions. ([current OCC active-travel page](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel); [OCC Health Improvement Board active-travel update, section 2.3](https://mycouncil.oxfordshire.gov.uk/documents/s79106/251028_HIB%2Breport%2Bon%2BActive%2BTravel_Final%2Bversion.pdf))

**Inference.** Descriptive use of “countywide/super LCWIP” does not prove that SATN has the same adopted outputs or planning status as a DfT-process LCWIP. No separate published decision explicitly adopting the SATN package *as an LCWIP* was found.

## 7. The official/current LCWIP framework

### 7.1 Which guidance is current

**Fact.** DfT's current LCWIP publication page still provides the 2017 technical guidance, PCT annex, Route Selection Tool and Walking Route Audit Tool. The page has no later replacement listed. ([DfT, “Planning local cycling and walking networks”](https://www.gov.uk/government/publications/local-cycling-and-walking-infrastructure-plans-technical-guidance-and-tools))

**Fact.** The 2017 guidance calls LCWIP preparation non-mandatory, recommends a roughly ten-year plan and approximately four-to-five-year review, and defines feasibility, detailed design/costing, delivery and scheme monitoring/evaluation as outside that guidance's direct scope. ([DfT LCWIP technical guidance, paragraphs 2.1–2.13, 3.19–3.21 and 8.7](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

**Fact.** The 2026 statutory Local Transport Plan guidance now says:

- LTAs must set active-travel policies in the statutory LTP;
- LCWIPs are to be kept up to date and aligned with LTP active-travel policies;
- the LTP should describe the LCWIP information-gathering, walking/wheeling/cycling network planning, ten-year priority pipeline and broad stakeholder engagement approach; and
- active-travel capability includes evidence, appraisal, monitoring/evaluation, consultation and technical skills.
([DfT 2026 statutory LTP guidance, “Active travel”](https://www.gov.uk/government/publications/local-transport-plans/local-transport-plans))

**Fact.** CWIS3, published 12 June 2026, commits ATE to new LCWIP guidance by 2027 with enhanced walking-network planning and support for LTP integration. It also plans to combine existing, planned and proposed local/national active-travel schemes in a single digital platform by 2030. ([CWIS3, “Mapping a national network”](https://www.gov.uk/government/publications/the-third-cycling-and-walking-investment-strategy/active-travel-active-england-the-third-cycling-and-walking-investment-strategy-cwis3))

**Inference.** As of 2026-07-24, the operative technical baseline is the 2017 LCWIP guidance as augmented by the newer 2026 statutory LTP expectations and scheme-monitoring guidance. Any implementation must version its rules and be designed for a 2027 LCWIP-guidance migration.

### 7.2 Required/recommended outputs

**Fact.** The 2017 LCWIP guidance defines three key outputs:

1. a walking and cycling network plan identifying preferred routes and core zones;
2. a prioritised programme of infrastructure improvements for future investment; and
3. a report explaining the analysis and supporting the proposed network/improvements.
([DfT LCWIP technical guidance, paragraphs 2.1–2.3](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

**Fact.** The 2026 LTP guidance adds an expected ten-year pipeline in priority order and explicit breadth of engagement, including residents, businesses, road users, emergency services, disabled people, elected representatives, older people, education, ethnic-minority groups and religious groups. ([DfT 2026 statutory LTP guidance, “Active travel”](https://www.gov.uk/government/publications/local-transport-plans/local-transport-plans))

### 7.3 Six-stage LCWIP process

| Stage | Official purpose/output |
|---|---|
| 1. Determining Scope | Set geographic extent; choose single/lead/joint authority delivery; appoint project team, project manager, Senior Responsible Owner and preferably Project Board; identify stakeholders and engagement; set delivery periods/timescales; produce a Scoping Report for approval/sharing. |
| 2. Gathering Information | Evidence-led collection of current/potential trips, network, barriers, trip generators, policy/programmes and perceptions; identify data gaps/proxies; use local/national data proportionately; strongly consider PCT; optionally publish a Background Report. |
| 3. Network Planning for Cycling | GIS-map origins/destinations; create and classify desire lines; consider network density; turn desire lines into preferred routes; validate locally; audit route options/current and potential condition; define an indicative improvement scope and produce a Cycling Network Map plus programme of cycle improvements. |
| 4. Network Planning for Walking | GIS-map trip generators; define Core Walking Zones; map key walking routes (normally up to about 2 km); identify severance/funnel routes; audit with local knowledge and vulnerable/disabled users in mind; define improvements and produce a Walking Network Map plus programme of walking improvements. |
| 5. Prioritising Improvements | Jointly prioritise walking/cycling improvement packages by effectiveness, policy and deliverability; consider appraisal/value; assign short (<3 years), medium (<5 years) and long (>5 years) periods; share the programme with governance/stakeholders. |
| 6. Integration and Application | Link to the LTP and local planning; use in funding bids, delivery plans, planning applications, developer contributions and major-scheme proofing; review/update periodically and after material local change. |

([DfT LCWIP technical guidance, chapters 3–8](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

### 7.4 Cycling route planning and RST

**Fact.** DfT recommends:

- GIS origins/destinations and separate additions for non-work trips/new development not represented by PCT;
- stakeholder verification of desire lines;
- primary/secondary/local demand classifications;
- routes that are coherent, direct, safe, comfortable and attractive;
- iterative comparison of route options;
- a preliminary audit of required improvements; and
- local-condition checking of PCT route assignments.
([DfT LCWIP technical guidance, paragraphs 5.9–5.30](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

**Fact.** DfT's RST compares current and potential route condition on a 0–5 scale for directness, gradient, safety, connectivity and comfort, records critical junctions, can split routes into homogeneous sections up to 1 km, and can record interventions, cost and deliverability. DfT says routes should have the potential to reach at least 3 and ideally have no critical junctions. ([DfT LCWIP tools annex, Annex B](https://assets.publishing.service.gov.uk/media/5f32c8f8d3bf7f1b10d58fd7/cycling-walking-infrastructure-tools-document.pdf))

### 7.5 Walking planning and WRAT

**Fact.** DfT's walking method requires:

- mapped walking trip generators;
- Core Walking Zones, with 400 m/five-minute distance as a guide to minimum extent;
- key routes serving those zones from up to about 2 km;
- severance/funnel-route identification;
- current-infrastructure audits;
- explicit consideration of older people, visual/hearing/mobility impairments, learning disabilities, buggy users and children; and
- a programme of route/zone improvements detailed enough for indicative scope/cost.
([DfT LCWIP technical guidance, paragraphs 6.8–6.34](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

**Fact.** WRAT scores attractiveness, comfort, directness, safety and coherence from 0–2; 70% is the stated normal minimum overall level, with zero-scored items identifying improvement needs. It stores comments and proposed actions because some scoring is qualitative. ([DfT LCWIP tools annex, Annex C](https://assets.publishing.service.gov.uk/media/5f32c8f8d3bf7f1b10d58fd7/cycling-walking-infrastructure-tools-document.pdf))

### 7.6 Prioritisation

**Fact.** DfT says prioritisation should focus on complete/coherent packages and may include:

- **effectiveness:** forecast active trips, beneficiaries, existing deficiency, network contribution, safety, air quality, other-user impacts and scheme integration;
- **policy:** health/inclusion, target groups, journey purpose, local-plan/LTP performance and engagement priority;
- **deliverability:** feasibility, acceptability, dependencies and environmental constraints; and
- indicative value-for-money appraisal using likely users, intervention type and delivery/maintenance costs.
([DfT LCWIP technical guidance, paragraphs 7.1–7.17](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

### 7.7 Monitoring and review

**Fact.** The 2017 LCWIP guide expects periodic plan review but treats scheme monitoring/evaluation as a related activity outside its direct scope. ([DfT LCWIP technical guidance, paragraphs 2.11–2.13 and 8.7](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf))

**Fact.** ATE's 2025 monitoring guidance requires all Active Travel Fund schemes/programmes to submit monitoring data and requires a formal evaluation/M&E plan for permanent schemes costing £2 million or more. It recommends a proportionate logic model covering inputs, outputs, outcomes and impacts; modal-shift measurement; baseline/before and repeated after data; comparable collection; and recording confounders. ([ATE, Active Travel Fund monitoring and evaluation](https://www.gov.uk/government/publications/active-travel-fund-monitoring-and-evaluation-of-schemes/active-travel-fund-monitoring-and-evaluation))

**Fact.** Oxfordshire's Eynsham LCWIP commits to a local baseline, two-year review, progress/target reporting, local walking/wheeling/cycling counts, public/stakeholder consultation for updates and reissue where necessary. ([Eynsham LCWIP, section 6.2](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/EynshamLCWIP.pdf))

## 8. Oxfordshire's own LCWIP template in current practice

Oxfordshire's local LCWIPs are the strongest first-party comparator for “replacement equivalence”.

### 8.1 Eynsham LCWIP (approved January 2026)

**Fact.** Eynsham's plan includes:

- a defined vision and targets;
- geographic scope based on trip generators, 10 km cycling and 2 km walking considerations;
- separate cycling and walking/wheeling network plans;
- public engagement and a multi-party Steering Group;
- site audits with a dedicated audit appendix;
- RST/WRAT-informed assessment;
- a table of specific walking/wheeling/cycling interventions;
- grouping into 25 routes;
- multi-criterion route scoring and short/medium/long delivery timescales;
- Q2 2025 indicative costs with disclosed assumptions and risk allowance;
- planning/funding/behaviour-change integration; and
- baseline monitoring and two-year review.
([Eynsham LCWIP, pp. 7–47 and appendices](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/EynshamLCWIP.pdf); [OCC current approved-LCWIP list](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel))

### 8.2 Thame LCWIP (approved October 2025)

**Fact.** Thame reports 188 possible interventions and uses OCC's standardised 14-factor prioritisation framework:

- forecast walking/cycling increase;
- population benefit;
- road safety;
- RST score;
- WRAT score;
- network continuity/severance;
- access to public transport;
- access to schools;
- benefits across active-travel users;
- environmental effect;
- indicative cost;
- funding likelihood;
- land ownership; and
- stakeholder acceptability.
([Thame LCWIP, executive summary and prioritisation chapter](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport/thamelcwipfinalreportlowres.pdf); [OCC current approved-LCWIP list](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel))

**Inference.** For an Oxfordshire-compatible replacement, the SATN Index is not enough. It scores the strategic importance of places/corridors; Oxfordshire's LCWIP framework scores the quality, effect, policy fit and deliverability of specific interventions. Both layers are useful and must remain distinguishable.

## 9. SATN-to-LCWIP equivalence assessment

| LCWIP requirement | SATN published evidence | Assessment |
|---|---|---|
| Scope and cross-boundary governance | Countywide scope, Steering Group, neighbouring-authority engagement | **Partial.** Strong strategic scope; no published LCWIP Scoping Report, named SRO/project-board approvals or formal engagement plan. |
| Evidence-led baseline | Broad strategic network, demand, development, social and constraint layers | **Strong for strategic cycling/inter-settlement discovery; partial overall.** Data provenance, refresh and uncertainty artefacts are missing. |
| Cycling origins, desire lines and network | PCT + Everyday Trips + Strava; long-list refinement; 46 segments/176 subsegments; possible alignments | **Substantial.** No published RST audit or route-improvement programme; final classification is not deterministically reproducible. |
| Walking network/Core Walking Zones | Walking Strava and destinations appear in baseline; report describes walking/cycling network | **Blocker.** No published CWZ method, key local walking-route map or WRAT programme equivalent to DfT/OCC local LCWIPs. |
| Current-condition route audits | Report recommends future LTN 1/20/RST/WRAT-compatible audits | **Blocker.** Recommendation confirms this was not a completed Stage 1 output. |
| Specific infrastructure improvement programme | Illustrative, non-prescriptive design toolkit and possible alignments | **Blocker.** No route-by-route deficiency → intervention programme of sufficient detail for indicative scope. |
| Prioritised 10-year pipeline | Strategic/primary vs complementary/secondary corridors | **Blocker.** No improvement-level short/medium/long pipeline, delivery programme, costs or maintenance costs. |
| Equality and inclusion | EqIA and consultation; equestrian changes after feedback | **Partial/major gap.** EqIA records no disability impact and no review; it does not provide route-level accessibility audits or demonstrate representative disabled-user validation. ([SATN EqIA, pp. 8–14](https://mycouncil.oxfordshire.gov.uk/documents/s70849/CMDIDS25042024%2B-%2BAnnex%2B4%2B-%2BEqualities%2BImpact%2BAssessment.pdf)) |
| Consultation and stakeholder influence | Two engagement phases, Steering Group, documented network changes | **Substantial but incomplete.** No published route-by-route issue/disposition log; counts/dates conflict across official sources. |
| Policy/planning integration and adoption | LTCP supporting document; Stage 1/Stage 2 decision; “consider LCWIP adoption” recommendation | **Major governance/adoption limit.** Approval is real, but full LCWIP-equivalent adoption/integration is not evidenced. |
| Monitoring, review and change control | Regular review stated; Oversight Group recommended | **Major gap.** No cadence, baseline/KPIs, change-control log or published rescore/update protocol. |
| Machine-readable/public evidence | Maps and PDFs; recommendation for unified GIS online resource | **Blocker for safe agentic reproduction.** No published source GIS, schemas, score ledgers or computation artefacts. |

## 10. Independent red-team assessment

### 10.1 Can SATN replace an LCWIP?

**Red-team conclusion: no, not by itself.**

The strongest contrary argument is that SATN mirrors several LCWIP functions: evidence-led origin/destination analysis, desire lines, route candidates, strategic prioritisation, engagement, maps and a supporting report. Oxfordshire later sometimes calls it a countywide or “super” LCWIP. Those facts justify treating SATN as an LCWIP-like strategic network layer. ([SATN final report](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf); [OCC Health Improvement Board update](https://mycouncil.oxfordshire.gov.uk/documents/s79106/251028_HIB%2Breport%2Bon%2BActive%2BTravel_Final%2Bversion.pdf))

That argument fails for full replacement because:

- SATN deliberately excludes intra-settlement Everyday Trips and focuses on 5–20 km links, while LCWIP walking and local-cycling networks need different spatial models;
- “walking and cycling routes” in a title/map is not equivalent to a separate walking-demand, CWZ, severance and WRAT process;
- corridor importance is not route quality or scheme deliverability;
- an illustrative design menu is not an audited programme of necessary interventions;
- primary/complementary status is not a ten-year, costed, improvement-level delivery pipeline;
- Stage 2 defers the feasibility, ownership, auditing, detailed engagement, design and costing needed to select real routes; and
- formal approval of a strategic supporting document is not evidence that all LCWIP outputs were adopted.

### 10.2 Is the published SATN record complete enough to regenerate SATN agentically?

**Red-team conclusion: not safely or exactly.**

An agent could implement a defensible *SATN-inspired* model using the published distances, bins, catchments and data themes. It could not claim exact replacement equivalence because:

- core source layers, versions and transformations are not published;
- custom Everyday Trips/clustering implementation is described but not supplied;
- demand-layer combination/deduplication is unspecified;
- scoring inputs and all route results are absent;
- the final classification contains undocumented judgement and pipeline comparison;
- consultation decision records are incomplete and official totals conflict; and
- no governed refresh/versioning process is public.

### 10.3 Is it safe to generate an LCWIP agentically from SATN?

**Red-team conclusion: only with mandatory human and fieldwork gates.**

The unsafe failure modes are:

- presenting a desire line as an accessible/feasible route;
- routing across private land, environmental constraints or an unusable PRoW without disclosing rights/feasibility;
- reinforcing historic travel and app-user bias;
- favouring population/attractor density over deprived, disabled or low-car communities;
- inventing missing route-condition evidence;
- optimising cycling while neglecting walking/wheeling;
- treating a model score as political/public acceptability;
- silently using stale PCT/Census/Strava inputs;
- treating consultation comments as representative votes; and
- allowing an agent to make an adoption/funding decision for which named public officials are accountable.

### 10.4 Severity classification

**Blockers before claiming LCWIP replacement**

1. Dedicated walking/wheeling network planning, CWZs and WRAT-compatible audits.
2. RST/LTN 1/20-compatible cycling route and junction audits.
3. Specific deficiency-to-intervention records with indicative scope/cost.
4. Improvement-level prioritisation and short/medium/long ten-year pipeline.
5. Machine-readable provenance and deterministic score/decision ledgers.
6. Accountable human scope, consultation, equality, prioritisation and adoption gates.

**Major gaps before production use**

1. Current, licensed, versioned datasets and refresh protocol.
2. Constraint/land/ecology/PRoW evidence and explicit unknown states.
3. Equality/accessibility evidence with representative user involvement.
4. Monitoring baseline, targets, cadence and plan/scheme evaluation.
5. Consultation issue/disposition workflow and version history.
6. Sensitivity testing and explanation of how parameter changes affect routes/ranks.

**Desirable extensions**

1. Unified SATN/LCWIP/Greenways/NCN GIS publication.
2. Portfolio dependency and funding-opportunity management.
3. Scenario comparison and benefit appraisal.
4. Automated document/map generation and accessible public views.
5. Migration support for the announced 2027 LCWIP guidance and 2030 national digital network.

## 11. Minimum safe foundation for an agentic LCWIP

### 11.1 Governed domain model

Use distinct, versioned objects for:

- Evidence Source
- Dataset Version
- Origin/Destination
- Desire Line
- Demand Scenario
- Candidate Alignment
- Audited Route Section
- Critical Junction/Barrier
- Core Walking Zone
- Infrastructure Deficiency
- Intervention Option
- Improvement Package
- Priority Assessment
- Consultation Representation
- Decision/Override
- Funding/Delivery Stage
- Monitoring Measure
- Published Plan Version

Every derived object should carry its source references, transformation version, responsible reviewer, uncertainty/quality status and current lifecycle state.

### 11.2 Deterministic evidence pipeline

At minimum:

1. ingest governed GIS/tabular sources with licence, date, CRS, coverage and known limitations;
2. preserve raw inputs and hashes;
3. run versioned origin/destination, PCT, clustering and network logic;
4. publish all parameters, score components and sensitivity tests;
5. keep SATN strategic-place scoring separate from LCWIP intervention prioritisation;
6. never impute a route condition, ownership right or accessibility result without an explicit evidence status; and
7. export full GIS and tabular ledgers, not only PDFs and map tiles.

### 11.3 Separate cycling and walking workflows

**Cycling**

- local and strategic origins/destinations;
- PCT plus non-work/new-development evidence;
- desire-line classification and route options;
- RST-compatible current/potential section scores;
- critical junctions and design capacity;
- route-level intervention packages.

**Walking/wheeling**

- trip generators;
- CWZs and key routes;
- severance/funnel routes;
- WRAT-compatible route/zone evidence;
- explicit disabled/older/child/buggy-user evidence;
- intervention packages.

Shared interventions can be recombined only after each mode's needs have been evaluated.

### 11.4 Human-review gates

The agent may draft; named accountable humans must approve:

1. scope, delivery model, SRO/board and engagement plan;
2. data selection, exclusions and known gaps;
3. origins/destinations and candidate networks;
4. site-audit evidence;
5. route feasibility and land/environment constraints;
6. equality/accessibility assessment;
7. consultation issue disposition;
8. prioritisation criteria, weights, exceptions and phasing;
9. publication/adoption; and
10. monitoring results and plan revisions.

### 11.5 Outputs needed for equivalence

An agentic LCWIP publication pack should include:

- approved Scoping Report;
- Background/Evidence Report;
- cycling network map;
- walking network/CWZ map;
- RST/WRAT/site-audit evidence;
- route/zone deficiencies and interventions;
- cost assumptions and estimates;
- joint prioritised ten-year pipeline with short/medium/long timing;
- equality/climate/other required assessments;
- consultation log and change/disposition report;
- policy/planning integration statement;
- monitoring/review plan;
- decision and sign-off record; and
- machine-readable GIS, data dictionary, score ledger and provenance manifest.

## 12. Replacement-equivalence test

A candidate tool/process should not be described as equivalent until it can answer “yes” with evidence to all of the following:

1. Can it reproduce SATN's strategic OD, clustering, segment/subsegment and Index process with published parameters and source provenance?
2. Can it show every manual override and explain why the final class differs from the raw score?
3. Can it model local/intra-settlement trips separately from SATN's 5–20 km inter-settlement filter?
4. Can it produce distinct cycling and walking/wheeling network plans?
5. Can it store RST/WRAT-compatible, route-section and junction evidence?
6. Can it trace every proposed intervention to an audited deficiency?
7. Can it score effectiveness, policy and deliverability rather than strategic importance alone?
8. Can it output a costed, short/medium/long ten-year pipeline?
9. Can it represent unknown, disputed, private-land and environmentally constrained options without false certainty?
10. Can it ingest consultation evidence, retain contradictions and publish issue-by-issue dispositions?
11. Can it enforce human sign-off for equality, feasibility, prioritisation and adoption?
12. Can it monitor, rescore, version and republish the plan without losing the audit trail?
13. Can it migrate when ATE publishes new LCWIP guidance in 2027?

## 13. Source ledger

### Oxfordshire

1. [SATN Final Project Report, March 2024](https://mycouncil.oxfordshire.gov.uk/documents/s70847/CMDIDS25042024%20-%20Annex%202%20-%20SATN%20Final%20Report.pdf) — core methodology, inputs, network, scoring, alignments, toolkit and recommendations.
2. [Cabinet Member report, 25 April 2024](https://mycouncil.oxfordshire.gov.uk/documents/s70845/CMDIDS25042024%20-%20Strategic%20Active%20Travel%20Network%20Stage%201.pdf) — approved programme, finance/legal/staff/governance status and consultation.
3. [Decision record: SATN Stage 1](https://mycouncil.oxfordshire.gov.uk/mgIssueHistoryHome.aspx?IId=35483) — decision status and approved recommendation.
4. [Prioritised Straight-Line Desire Map](https://mycouncil.oxfordshire.gov.uk/documents/s70846/CMDIDS25042024%20-%20Annex%201%20-%20Prioritised%20Straight-Line%20Desire%20Map.pdf).
5. [SATN Equalities Impact Assessment](https://mycouncil.oxfordshire.gov.uk/documents/s70849/CMDIDS25042024%2B-%2BAnnex%2B4%2B-%2BEqualities%2BImpact%2BAssessment.pdf).
6. [SATN Climate Impact Assessment](https://mycouncil.oxfordshire.gov.uk/documents/s70848/CMDIDS25042024%20-%20Annex%203%20-%20Climate%20Impact%20Assessment.pdf).
7. [Current OCC active-travel page](https://www.oxfordshire.gov.uk/transport-and-travel/local-transport-and-connectivity-plan/active-travel) — current list/role of LCWIPs, SATN stages, local standards and source links.
8. [Initial SATN consultation](https://letstalk.oxfordshire.gov.uk/satn-initial) — initial scope, data, Steering Group and early engagement.
9. [SATN final-draft consultation](https://letstalk.oxfordshire.gov.uk/satn) — consulted outputs and non-commitment/feasibility caveat.
10. [SATN “You said, we did”](https://letstalk.oxfordshire.gov.uk/strategic-active-travel-network-satn-yswd) — consultation changes, approval and current delivery roles.
11. [OCC Active Travel Strategy](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/ActiveTravelStrategy.pdf) — policy-level SATN and LCWIP actions.
12. [OCC Transport Development Management guidance](https://www.oxfordshire.gov.uk/transport-and-travel/transport-policies-and-plans/transport-new-developments/transport-development) — local walking/cycling/street standards and planning boundary.
13. [Oxford Greenways consultation](https://letstalk.oxfordshire.gov.uk/oxford-greenways) — current distinction among LCWIP, SATN and Greenways functions.
14. [Eynsham LCWIP, approved January 2026](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport-policies-and-plans/EynshamLCWIP.pdf) — recent Oxfordshire local LCWIP output/template.
15. [Thame LCWIP, approved October 2025](https://www.oxfordshire.gov.uk/sites/default/files/file/roads-and-transport/thamelcwipfinalreportlowres.pdf) — OCC standard 14-factor prioritisation and intervention programme.
16. [OCC Health Improvement Board active-travel update, November 2025](https://mycouncil.oxfordshire.gov.uk/documents/s79106/251028_HIB%2Breport%2Bon%2BActive%2BTravel_Final%2Bversion.pdf) — later “super LCWIP” terminology.

### National

17. [DfT, Planning local cycling and walking networks](https://www.gov.uk/government/publications/local-cycling-and-walking-infrastructure-plans-technical-guidance-and-tools) — current publication landing page and tools.
18. [DfT LCWIP Technical Guidance](https://assets.publishing.service.gov.uk/media/5f32aa668fa8f57ac88dc9dc/cycling-walking-infrastructure-technical-guidance-document.pdf) — six stages, outputs, evidence, engagement, network planning, prioritisation and integration.
19. [DfT LCWIP Planning Tools Annexes](https://assets.publishing.service.gov.uk/media/5f32c8f8d3bf7f1b10d58fd7/cycling-walking-infrastructure-tools-document.pdf) — PCT, RST and WRAT semantics.
20. [DfT 2026 Statutory Local Transport Plan Guidance](https://www.gov.uk/government/publications/local-transport-plans/local-transport-plans) — current active-travel/LTP expectations and LCWIP alignment/updating.
21. [CWIS3, June 2026](https://www.gov.uk/government/publications/the-third-cycling-and-walking-investment-strategy/active-travel-active-england-the-third-cycling-and-walking-investment-strategy-cwis3) — planned 2027 LCWIP guidance and 2030 national network platform.
22. [ATE Active Travel Fund Monitoring and Evaluation, July 2025](https://www.gov.uk/government/publications/active-travel-fund-monitoring-and-evaluation-of-schemes/active-travel-fund-monitoring-and-evaluation) — current scheme M&E requirements and recommended evidence model.
