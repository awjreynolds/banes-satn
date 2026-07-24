# ADR 0004: Monitoring creates review work and never rewrites history

- Status: Accepted
- Date: 2026-07-24
- Issue: #98

## Context

LCWIP delivery and outcomes continue after publication. A mutable dashboard record
would make later reports appear to have been known at adoption time, conflate funding
with delivery, and silently apply new evidence or guidance to a historical release.
Monitoring must expose uncertainty, delay and disagreement without becoming a project
management or causal-evaluation system.

## Decision

Every monitoring cycle seals the exact historical publication manifest, substantive
release fingerprint, evidence and configuration fingerprints, Guidance Profile and
conformance result. It separately seals a new evidence snapshot. Neither referenced
file is modified, and one monitoring cycle ID is content-immutable.

Programme status is a discriminated union. Design, funding, construction, completion
and outcome updates have distinct state types and transition rules. Every update is
bound to a source, observer or authority, observation and recording dates, confidence,
verification state and scope fingerprint. Only verified updates contribute to
effective status. Changed scope requires a governed deviation with rationale and
fingerprint lineage.

Indicator definitions bind one governed baseline, target direction and date, method,
unit, reporting frequency and owner. Observations add their period, due and recording
dates, source, coverage, uncertainty, confidence and verification. Missing, late,
unverified and explicitly contradictory observations remain visible. Activity and
outcome indicators are separate, and monitoring artifacts make no causal claim.

Each scheduled or event-based Review Trigger produces a governed Review Task. New
Guidance Profiles are re-evaluated and compared with the historical profile; new
evidence snapshots are compared with historical source fingerprints. Exact impact
mappings identify the analyses and programme entries requiring migration.

A progress-only monitoring cycle may contain no trigger and no successor proposal.
It publishes an empty governed-task set instead of inventing review work. Unverified
or contradicted delivery reports remain visible but cannot advance, regress or
otherwise constrain the verified programme state.

A Superseding Release Proposal may be prepared only for the sealed predecessor,
current evidence snapshot and Guidance Profile, and must cite its Review Triggers. It
remains analysis-draft or adoption-candidate state; monitoring cannot adopt or
silently supersede a plan.

## Consequences

- Historical publication, evidence and conformance provenance remain unchanged.
- Funding, design, construction, completion and outcomes cannot imply each other.
- Overdue, blocked, changed-scope and unverified work is machine- and human-readable.
- Future-dated records cannot enter an as-of monitoring release.
- Guidance and evidence changes create explicit migration work.
- Release generation is atomic; failure preserves prior monitoring releases.
