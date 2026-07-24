# ADR 0003: LCWIP publication is atomic, cited and release-bound

- Status: Accepted
- Date: 2026-07-24
- Issue: #97

## Context

An adoption-candidate LCWIP must be usable as a report, accessible web publication
and GIS dataset without allowing those representations to drift. Generated narrative
can otherwise conceal evidence gaps or overstate adoption, feasibility and funding.
Partial export failure can also leave a plausible but incomplete public release.

## Decision

One frozen `PublicationConfig` is the only publication input. It binds the Guidance
Profile and conformance result, privacy-safe source descriptors and source records,
citations, structured report sections and claims, network features, programme,
consultation changes, equality and representation gaps, audit records and any later
adoption annotation.

Every material narrative claim resolves to governed citations. Adoption, feasibility
and funding assertions require matching typed authority evidence carried by one of
those citations and bound to the exact substantive release fingerprint. Section
introductions cannot bypass this authority contract. Missing evidence is an explicit
placeholder.

The publisher writes PDF, accessible HTML, GeoJSON, GeoPackage, programme,
conformance, coverage/quality, audit, release-diff, release-history and ZIP artifacts
to a temporary sibling directory. Cross-artifact identifiers, geometry, metrics,
watermarks, fingerprints and required accessible alternatives validate before one
atomic rename. An existing release ID is immutable.

The substantive release fingerprint excludes only its self-referential authority
binding and a later adoption annotation. An adoption annotation is valid only for an
adopted lifecycle, names the external decision and distinct human verification
evidence, and identifies that exact release fingerprint. It does not rewrite the
substantive report.

## Consequences

- Report, web and GIS consumers see the same governed feature and programme state.
- Mandatory conformance, representation and equality gaps remain visible blockers.
- Recomputed hashes cannot conceal an internally inconsistent manifest.
- Multiple governed evidence artifacts are supported while the canonical GeoJSON and
  GeoPackage sources remain singular.
- Every release retains semantic and spatial history across evidence, method,
  geometry, programme, narrative and decision categories.
- Failed generation leaves prior immutable releases unchanged.
