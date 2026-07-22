# Domain Docs

## Before exploring

- Read `CONTEXT.md` at the repository root.
- Read relevant ADRs under `docs/adr/`.
- If an expected document does not exist, proceed silently. Domain-modeling skills create these documents when decisions are resolved.

## Layout

This is a single-context repository:

/
├── CONTEXT.md
├── docs/adr/
└── src/

## Vocabulary

Use domain concepts exactly as defined in `CONTEXT.md`. Avoid synonyms that the glossary explicitly rejects.

If a required concept is absent, reconsider whether new language is necessary or note the gap for `domain-modeling`.

## ADR conflicts

Explicitly identify any proposal that contradicts an existing ADR rather than silently overriding it.
