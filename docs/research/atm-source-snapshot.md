# B&NES ATM source snapshot: lawful public reuse assessment

**Research date:** 19 July 2026  
**Decision requested:** whether a public MIT repository may carry a reusable copy of the 784-feature B&NES ATM GeoJSON.  
**Bottom line:** **do not publish or present the copied 784-feature GeoJSON as MIT-licensed until B&NES confirms that this WFS layer is available under OGL v3 (or supplies another express redistribution licence and attribution).** Publish the independently authored extractor, schema and a source manifest now; keep the raw and converted geometry out of the public repository. This is the lawful, reproducible route on the present evidence.

This is a licensing and provenance assessment, not legal advice. “Publicly reachable” is evidence of access, not by itself an express grant to copy, adapt and redistribute a whole geospatial dataset.

## What the local material is

The local repository is [`awjreynolds/atm-prioritisation`](https://github.com/awjreynolds/atm-prioritisation), whose root `LICENSE` is MIT, copyright Adam Reynolds 2026. That licence can govern copyright in the repository author’s software and documentation; it cannot grant rights in upstream material that the author does not own.

The relevant committed inputs are:

| Item | Local identity / evidence | Meaning |
|---|---|---|
| Converted snapshot | `data/banes-atm-full.geojson`; SHA-256 `8671eac4d17d0d081e4fd8e7e143fde6af70be7ef95663e443fdc3f62fb9eb8c` | 784-feature, EPSG:4326 derivative currently in the repo. Its own metadata says it was extracted 21 May 2026 from the public B&NES WFS. |
| Extractor | `scripts/extract-banes-atm-geojson.mjs`; SHA-256 `428c9f3453d7c8d2d150aff4e9f45139b62b5aab4929de9956e87dda77c960ae` | Independently authored Node script: fetches WFS, retains only ID, `fid`, name and `type_2`, converts EPSG:27700 to EPSG:4326 using embedded mathematical conversion, and writes GeoJSON. |
| Schema | `data/atm-route-extraction-schema.json`; SHA-256 `40d78b741e5c343e48cf7efa8b450fa6b308ae7af3c1ea9cd0f23cf67f121bef` | A review/extraction contract. It expressly says the extraction is **not official reusable council GeoJSON** and should not imply legal/engineering alignment. |
| Creation commit | [`29785299c15c35d06d094408f0dc108c0bd1e663`](https://github.com/awjreynolds/atm-prioritisation/commit/29785299c15c35d06d094408f0dc108c0bd1e663), 21 May 2026 | Introduced both the full GeoJSON and extraction script (“Add full BANES ATM map layer”). Earlier scaffold: [`eb52980ef56edd2fc06ab0509a266a4f162c430c`](https://github.com/awjreynolds/atm-prioritisation/commit/eb52980ef56edd2fc06ab0509a266a4f162c430c). |

The present live service remains available at the exact WFS endpoint recorded in the extractor:

```text
https://bathnes.maps.xmap.cloud/bathnes_public/ows?typeName=final_february25&service=WFS&version=1.1.0&request=GetFeature&outputFormat=application/json&SrsName=urn:ogc:def:crs:EPSG::27700
```

On 19 July 2026 it returned 784 features (`final_february25.1` first), properties `fid,name,type_2`, and raw-response SHA-256 `c2ac29a99800092e2c0d1ed7af3979b715dee3d3fa4edcc79025c8b2ef5f837e`. Its official WFS capabilities identify the layer as `bathnes_public:final_february25`, title `ATM_final_february25`, default SRS EPSG:27700 and list `application/json` as an output format. The capabilities’ service `Fees`, `AccessConstraints`, layer abstract and provider fields are blank. [WFS GetCapabilities](https://bathnes.maps.xmap.cloud/bathnes_public/ows?service=WFS&version=1.1.0&request=GetCapabilities)

## Primary-source rights assessment

B&NES describes the online map as its planned Active Travel network, says users can view it and give feedback, and says it will periodically update the map and plans. It also describes the ATM as a living document under continual review. Those statements establish provenance and volatility, **not an open-data licence**. [B&NES planned-routes page](https://www.bathnes.gov.uk/view-and-comment-planned-active-travel-routes) [B&NES ATM page](https://www.bathnes.gov.uk/active-travel-masterplan)

B&NES’s specific reuse page is narrower than a blanket website/WFS licence: it says information supplied under FOIA/EIR is OGL “except where otherwise stated”; it provides a required attribution for **text content covered by OGL**; and it says third-party material needs the third party’s permission. It also says its voluntary application of OGL does not alter the Council’s IP rights. The page does not identify this WFS layer as OGL information. [B&NES reuse guidance](https://www.bathnes.gov.uk/reusing-public-sector-information)

If B&NES confirms OGL v3 coverage, OGL would permit copying, publication, adaptation and commercial/non-commercial use, subject to attribution. It explicitly excludes third-party rights the provider is not authorised to license, logos, and use implying official status/endorsement. [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)

**Inference:** because (1) the authoritative WFS has no licence/attribution metadata, (2) B&NES’s published reuse statement only expressly applies OGL to FOIA/EIR-supplied information and calls out third-party rights, and (3) the official ATM route map carries an Ordnance Survey Crown-copyright notice, there is not enough evidence to attach an open redistribution licence to the WFS geometry. The OS notice is an additional warning to avoid copying any basemap, labels, tiles, screenshots or map composition; it does not prove that the vector ATM layer itself contains OS-derived geometry. [Official Appendix B route map](https://democracy.bathnes.gov.uk/documents/s85703/E3594%20-%20Appendix%20B%20-%20Active%20Travel%20Masterplan%20Route%20Map.pdf)

## Recommended lawful, reusable public shape

### Publish now under MIT

- `scripts/extract-banes-atm-geojson.mjs`, only after adding a clear header that it is software and **does not licence output data**.
- The extraction schema, validators and documentation authored for the project.
- A small source manifest and a fixture containing no source geometry (or a synthetic fixture), plus checks that validate the manifest structure.
- A citation/provenance README that links to B&NES’s map, the exact WFS request, the B&NES reuse guidance and the written permission/response once obtained.

### Do not publish until rights are confirmed

- `data/banes-atm-full.geojson`, its transformed EPSG:4326 coordinates, or any whole/substantial geometry-derived derivative that can substitute for the WFS layer.
- Raw WFS responses, SHAPE-ZIP/KML exports, feature-level coordinate fragments, map screenshots/tiles, Council or OS logos, and a regenerated “convenience” GeoJSON.
- A statement that the data are MIT-licensed, official, endorsed, surveyed design, legal alignment, deliverable scheme, or current after the recorded snapshot date.

This withholding is deliberately conservative. A feature count, hash and non-geometric field schema are useful reproducibility metadata; they should not be represented as a right to redistribute the underlying data.

### Permission gate

Ask B&NES Information Governance / the ATM data owner for a short written answer that identifies:

1. the exact layer, `bathnes_public:final_february25` / `ATM_final_february25`;
2. whether its vector features, attributes and transformed derivatives are licensed under OGL v3 (or name a different licence);
3. the required attribution wording and link;
4. whether third-party rights, OS data, portal-provider terms or attribution requirements apply to the layer; and
5. whether GitHub redistribution and derivative EPSG:4326 GeoJSON are permitted.

If the answer is OGL v3 and names no conflicting third-party restriction, record the answer immutablely (URL/email date and a redacted copy if required) and use this attribution adjacent to the dataset and in repository NOTICE:

> Contains B&NES Active Travel Masterplan route data, `ATM_final_february25`, obtained [snapshot date] from Bath & North East Somerset Council’s WFS; © Bath & North East Somerset Council, licensed under the Open Government Licence v3.0. Contains OS data © Crown copyright and database right [only if B&NES confirms this applies]. This derivative is not an official Council product or endorsement.

Use B&NES’s own wording instead if supplied. Do not use a Council logo.

## Minimum source-snapshot manifest

Create a new immutable snapshot ID per fetch; never overwrite a previous source response. Keep the raw response privately while rights are unresolved. The public manifest should include:

```json
{
  "snapshot_id": "banes-atm-final-february25-YYYY-MM-DD",
  "source_owner": "Bath & North East Somerset Council (to be confirmed for layer)",
  "source_url": "<exact encoded WFS URL>",
  "capabilities_url": "<GetCapabilities URL>",
  "layer": "bathnes_public:final_february25",
  "layer_title_observed": "ATM_final_february25",
  "retrieved_at_utc": "<ISO-8601 instant>",
  "source_crs": "EPSG:27700",
  "derived_crs": "EPSG:4326",
  "feature_count": 784,
  "raw_sha256": "<raw-response SHA-256>",
  "derived_sha256": "<derived GeoJSON SHA-256, private until permitted>",
  "extractor_path": "scripts/extract-banes-atm-geojson.mjs",
  "extractor_sha256": "<script SHA-256>",
  "extractor_commit": "<Git commit>",
  "conversion": "OSGB36 / British National Grid to WGS84; coordinates rounded to 7 decimals",
  "licence_status": "unconfirmed-redistribution-blocked",
  "licence_evidence_url": "https://www.bathnes.gov.uk/reusing-public-sector-information",
  "attribution_status": "awaiting-layer-specific-confirmation",
  "publication_allowed": false,
  "claim_limit": "Snapshot of a living proposed network; not an official, surveyed, approved or current design."
}
```

For a permitted release, add the confirmed licence URI, exact attribution, permission evidence identifier, and all contributors/third-party notices. Hash the raw response *as received* before parsing; hash the canonical derived bytes after deterministic serialization; record response headers such as `Date`, `ETag`/`Last-Modified` if offered; pin Node version and script commit; and preserve a feature-ID list/count/classification histogram for change detection. A rerun must produce a new manifest and report adds/removes/geometry/attribute changes; it must not silently replace the earlier snapshot. B&NES explicitly says the network and map are periodically updated, so refreshability is essential. [B&NES planned-routes page](https://www.bathnes.gov.uk/view-and-comment-planned-active-travel-routes)

## Claim limits for any future public release

Describe it only as: “a timestamped derivative of the B&NES ATM WFS layer, transformed for analysis/display.” State snapshot date, source CRS/output CRS and licence status. Do not call it “the B&NES network”, “official reusable Council GeoJSON”, “final design”, or “current” without a time qualifier. The Council says the map presents routes/infrastructure it plans to focus on and welcomes suggestions to change route/layout; the data should therefore be treated as proposed planning context, not a commitment or design specification. [B&NES planned-routes page](https://www.bathnes.gov.uk/view-and-comment-planned-active-travel-routes)

## Implementation decision

**Proceed now:** copy the MIT-owned extractor/schema pattern and publish only a blocked manifest plus documentation.  
**Release geometry only after:** a layer-specific written licence confirmation passes the permission gate above.  
**If confirmation is not obtained:** retain only private snapshot artefacts and make a public tool that directs users to B&NES’s live map/WFS, without serving copied geometry.
