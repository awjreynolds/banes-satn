# Workspace Notes

- Work is tracked in GitHub Issues for `awjreynolds/banes-satn`.
- Issue #31 is the spine-led Backbone-and-Access Network specification.
- Issues #32–#43 are implementation tickets with native blocking relationships.
- Issue #32 is the current implementation frontier. Completing it unlocks #33, #36 and #40.
- The agreed primary acceptance seam is the public `satn.compile(...)` interface using governed fixture snapshots and inspecting its Compilation Result and published artifacts.
- Implementation uses the `implement` skill, TDD at the agreed seam, a full test run at the integration boundary, and `code-review` before completion.
- The user wants an unattended overnight implementation loop rather than a scheduled recurring process.
- The user authorises one rigorously tested and reviewed pull request per ticket, merged into `main` before the next ticket begins.
- When several tickets are eligible, the user wants the lowest issue number selected.
- The user values completion over preserving a preconceived proof-of-concept outcome, but does not want validation standards lowered.
- The overnight run is outcome-bound rather than attempt-bound: blockers should be diagnosed, repaired and revisited until every ticket is merged.
- Existing uncommitted workspace changes belong to the user and must be preserved.
