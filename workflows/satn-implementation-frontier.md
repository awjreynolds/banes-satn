# SATN Implementation Frontier

**Status:** Ready to run

## Intent

Run the implementation frontier for specification issue #31 while the user is away, starting from ticket #32 and respecting the native ticket dependency graph.

## Known loop

For each eligible ticket, the run will:

1. obtain the complete ticket and specification context;
2. implement through the confirmed public compilation seam using TDD;
3. run focused verification and the full suite at the ticket integration boundary;
4. run the two-axis code review and resolve blocking findings; and
5. preserve a durable ticket boundary before considering another frontier ticket.

## Trigger

This is an event-triggered, one-shot workflow. It begins only when the user explicitly starts an overnight implementation run for specification issue #31. It is not scheduled and does not recur automatically.

## Preflight

1. Read the repository agent instructions, domain glossary, relevant ADRs, parent specification #31 and the complete current-frontier ticket.
2. Preserve the existing approved documentation and workflow changes in a dedicated setup branch and pull request; validate and merge that setup before ticket #32 so subsequent ticket branches start from governed context.
3. Confirm the working tree is clean, update local `main` from the remote and verify GitHub authentication and the required issue labels.
4. Confirm ticket #32 is the native GitHub frontier and no unexpected assignee or conflicting active pull request owns it.

## Ticket selection

- Query the native GitHub dependency graph after every successful merge.
- Select the lowest-numbered open, unassigned `ready-for-agent` child of #31 whose blockers are all closed.
- Process tickets sequentially; do not implement multiple tickets concurrently.
- Expected initial order is #32. Later order is recalculated from live dependency state rather than hard-coded.

## Ticket iteration

For the selected ticket:

1. Assign the ticket to the running GitHub user and read its full body, comments, parent specification, glossary and relevant current code.
2. Create `codex/issue-<number>-<slug>` from the latest remote `main`.
3. Use the `implement` skill and TDD at the confirmed public `satn.compile(...)` seam. Work as vertical red-green slices; focused deterministic unit tests are supplementary diagnostics only.
4. Run focused tests throughout. Before review, run the ticket's full relevant suite, formatting, linting and type checks.
5. Run the two-axis `code-review` skill against the current `main`. Resolve every blocking Standards or Spec finding, rerun affected checks and repeat review until clean or the retry policy stops the ticket.
6. Commit the completed ticket intentionally, push its branch and open a pull request whose body closes that ticket when merged.
7. Wait for required pull-request checks. Diagnose and fix failures within the retry policy; never merge with a failing required check.
8. Merge using a merge commit, preserving the ticket's commit history. Confirm the child issue closed and its native dependants updated.
9. Refresh local `main`, verify the merge and record the ticket, pull request, merge commit and validation result in the run ledger.

## Delivery boundary

- Process one eligible ticket at a time on its own `codex/issue-<number>-<slug>` branch created from the latest `main`.
- Complete TDD, focused verification, the full ticket-level suite and code review before publishing that ticket's branch.
- Create one pull request per ticket, wait for its required checks, and merge it into `main` only when the ticket's acceptance criteria and review are clean.
- Preserve the ticket's engineering history with a merge commit rather than squashing it away.
- Close the child ticket only after its pull request has merged successfully; the resulting native GitHub dependency state determines the next frontier.
- Refresh local `main` after each merge, then begin the next eligible ticket from that updated state.
- Attempt every ticket from #32 through #43 in dependency order. After #43 merges, run a final main-branch validation and produce the morning Brief.
- Leave parent specification #31 open for the user's morning review.
- Do not lower validation standards merely because the project is a proof of concept; the resulting implementation may be exploratory, but its recorded tests and findings must be truthful.
- Preserve all pre-existing user changes and keep them distinct from ticket commits.

## Retry and stopping policy

- The run is outcome-bound, not attempt-bound. Continue until every ticket #32–#43 has merged and final validation passes.
- Never repeat an identical failed action without learning from it. Diagnose the cause, inspect evidence and logs, change the implementation strategy, repair prerequisite code or tooling, or research a governed alternative before retrying.
- Treat test, review and pull-request-check failures as work to resolve rather than ordinary stopping conditions.
- For transient GitHub, network or evidence-service failures, use bounded waits and retry until service returns or a governed offline alternative is available; never weaken validation or evidence semantics.
- If a ticket is temporarily blocked, keep its branch and pull request in a truthful draft state, record the current diagnosis, complete any independent eligible frontier work, then return to the blocked ticket.
- If no ticket is currently eligible, work the blocking chain itself: repair failed prerequisites, resolve conflicts, fix infrastructure and re-run validation until the frontier advances.
- Do not skip an acceptance criterion, manufacture evidence, mark a failing test as passing, merge with required checks failing, or close an unmerged ticket.
- There is no arbitrary retry, ticket or wall-clock limit.
- Successful completion is the normal terminal condition: all tickets merged, final `main` validation green and the morning Brief produced.
- Stop incomplete only when progress requires authority the user has not granted, risks credential exposure or destructive out-of-scope action, conflicts with unrecognised user changes, or requires materially changing specification #31. Before stopping, exhaust safe alternatives and complete every independent ticket that remains possible.

## Final validation

After #43 merges:

1. update and verify local `main` against the remote;
2. run formatting, linting, type checks and the complete automated test suite;
3. run the full governed B&NES compilation and verify GeoPackage, GeoJSON, run records, agent records, PDF, ZIP and Inspectable Review Map consistency;
4. run browser accessibility and layer interaction checks, including legends, School state and Gradient Sections;
5. inspect the generated comparison of pairwise and Backbone-and-Access topology without treating the former as ground truth; and
6. if final validation uncovers a regression, create and merge a narrowly scoped corrective pull request under the same rigor before declaring completion.

## Morning checkpoint

Push the human checkpoint to the end. Present one decision-ready Brief containing:

- overall complete or blocked status;
- links to every ticket and merged pull request;
- the final `main` commit;
- concise test, validation and B&NES compilation results;
- links to the resulting Inspectable Review Map and other review artifacts;
- material topology, Network Gap, School access, Candidate Low-Traffic Area and Gradient Section findings; and
- any blocked ticket, attempts made, evidence missing and the smallest human decision needed.

Leave parent specification #31 open so the user can review the end-to-end outcome in the morning.

## Unresolved decisions

- None.
