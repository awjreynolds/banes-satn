# ADR 0002: Stage agents select finite proposals; only the compiler mutates state

- Status: Accepted
- Date: 2026-07-24
- Issue: #96

## Context

LCWIP preparation benefits from specialised critique, synthesis and red-teaming, but
an unconstrained agent that can write evidence, policy choices or plan state would
erase provenance and cross the council's authority boundary. Provider failure,
prompt injection, stale responses and agent disagreement must also terminate safely
rather than produce a partially trusted continuation.

## Decision

Every staged review uses a closed Agent Role Contract and a canonical LCWIP Stage
Decision Envelope. The envelope binds:

- one role and stage;
- an immutable, role-scoped Evidence Packet whose text is explicitly untrusted data;
- the current authoritative plan-state fingerprint;
- compiler-authored targets and finite actions;
- prompt-template and role-contract fingerprints;
- hard deadline, retry and bounded-revision controls.

The runtime response contains only the request ID, dependency fingerprint, offered
action ID and governed citations. Runtime outputs are non-authoritative. Failures,
malformed or stale responses, fabricated citations, exhausted revisions and
no-consensus create replayable Human Intervention Requests. Missing evidence creates
an Evidence Request to be handled outside the agent run.

Selected stages require an Independent Critique Gate. The deterministic compiler
accepts that gate only when the critic is a different configured role, its accepted
record explicitly names the primary request and all material findings have an
evidenced resolution, permitted named-human waiver or unresolved-blocker outcome.
Mandatory findings cannot be waived.

The only authoritative mutation is performed by the deterministic compiler after all
of those contracts validate against the current state fingerprint. Its state model
has no fields through which an agent action can alter source content, policy weights,
lifecycle state, representations, conformance waivers or adoption. No-Agent Mode uses
the same envelope and declared fallback action without constructing a runtime.

## Consequences

- Agent providers are replaceable adapters and are not part of the domain contract.
- Adding an agent capability requires adding a finite action to one exact role
  vocabulary and deterministic compiler handling; prose cannot become executable.
- Prompt, packet, provider/model/runtime, response hashes, usage, selected action and
  validation remain serialisable audit evidence.
- A valid primary response is insufficient at stages configured for independent
  critique.
- Deterministic builds remain complete when agents are unavailable or disabled.
