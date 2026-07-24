# ADR 0001: LCWIP governance records evidence authority but never exercises it

- Status: Accepted
- Date: 2026-07-24
- Issue: #95

## Context

LCWIP analysis can be generated and validated by software, but plan scope,
consultation release, representation and equality dispositions, programme rules and
adoption are accountable human or democratic decisions. A technically valid
lifecycle transition must not become a route around one of those decisions.
Representations may also contain personal or sensitive information that must remain
traceable without becoming public content.

## Decision

The governance lifecycle is derived from one contiguous transition history. Each
transition supplies the exact named gates for its target state, while a cumulative
check prevents adoption-candidate or adopted states from bypassing consultation.
Every gate resolves to a named authority role and retains its date, rationale and
evidence.

Representations retain immutable opaque source references and content fingerprints.
Public output contains only public or redacted records; excluded personal records
remain absent. Agent summaries cite publishable source records, disclose confidence,
methodology and complete coverage, and require human verification. A separate human
disposition remains mandatory for every source.

The substantive governance content has a canonical Governance Release Fingerprint.
An adopted record requires an external decision identifier and date, the exact
fingerprint, a decision authority and an independent verifier who is a different
person and cites separate evidence. Software can validate that record but cannot
create democratic authority.

Unknown or unresolved adverse equality findings block consultation and adoption.
Policy alignments require exact clause provenance, governed subject evidence and a
named officer judgement. Post-consultation amendments retain a trigger and a
fingerprint-contiguous audit chain.

## Consequences

- A state transition that is otherwise permitted by the generic lifecycle may still
  be rejected by the governance record.
- Adoption is a two-stage operation: fingerprint the candidate, obtain and verify the
  external decision, then build the adopted immutable record.
- Public engagement artifacts are deliberately less complete than the controlled
  manifest; source traceability does not imply publication of source content.
- A changed gate, disposition, equality finding or policy judgement creates a
  different immutable input even when the substantive release fingerprint is
  unchanged.
