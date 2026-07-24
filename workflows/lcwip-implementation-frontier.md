# LCWIP Implementation Frontier

**Status:** Ready to run

## Intent

Implement, validate and merge issues #89 through #98 as one unattended,
outcome-bound run. Issue #99 is a separate human-assurance workflow and is not
part of this run.

## Known loop

For each dependency-ready issue in #89–#98:

1. the control agent determines the next eligible ticket;
2. an implementation sub-agent receives a bounded ticket brief and implements
   the ticket;
3. the result is tested, reviewed and repaired until it meets the ticket and
   repository contracts;
4. one pull request is merged into `main`; and
5. the control agent refreshes the dependency frontier and starts the next
   eligible ticket.

The run ends only after every ticket in #89–#98 is merged and the integrated
result has been validated.

## Agent topology

- Keep one SOL-high agent as the durable control loop.
- Delegate implementation work to fresh Terra-high sub-agents because Luna is
  not exposed by the current workspace runtime. Luna may replace Terra-high if
  it becomes available before the run without changing any worker contract or
  acceptance rule.
- Delegate diagnosis, Standards review, Spec review, adversarial audit and
  validation tasks only to fresh SOL-high sub-agents. Terra-high agents do not
  validate or accept work.
- Use sub-agents to minimise token consumption without transferring sequencing,
  acceptance or completion authority away from the control loop.
- The SOL-high controller alone selects the next ticket, defines the bounded
  worker brief, assesses implementation quality, determines whether validation
  is sufficient, accepts or rejects worker output and authorises publication
  and merge.
- Implementation workers may inspect, edit, test and repair their assigned
  ticket, but they do not declare acceptance, weaken validation or merge their
  own work.
- Create a fresh Terra-high implementation worker for each ticket after the prior
  accepted ticket has merged and the controller has refreshed `main`.
- Every sub-agent receives exactly one bounded task. When it reports
  that task complete, fails it or reaches its stopping condition, retire it. Do
  not give any sub-agent a second task.
- Give the worker a compact, controller-authored brief containing the complete
  ticket contract, applicable parent constraints, relevant domain language,
  repository instructions, validation commands and explicit delivery boundary.
  Do not copy the accumulated frontier conversation into the worker context.
- End the worker immediately after its single task result is delivered. Durable
  frontier knowledge remains with the controller and repository artifacts.

If Terra-high is unavailable, use a fresh SOL-high worker for that one task.
Model availability never lowers the worker contract or validation bar.

## Trigger

This is an explicitly started, one-shot workflow. It is not a recurring
schedule.

## Preflight

The SOL-high controller performs preflight itself:

1. Read `AGENTS.md`, `CONTEXT.md`, relevant ADRs, parent PRD #88, all open
   implementation tickets #89–#98 and their comments.
2. Inspect the working tree and preserve every pre-existing user change. Never
   absorb unrelated work into a ticket branch or discard it.
3. Ensure this workflow and its supporting research are governed on `main`
   before ticket implementation. If a setup change is still unmerged, publish
   and merge it as a distinct setup pull request first.
4. Confirm GitHub authentication, remote `main`, required labels, current
   assignees, open pull requests and branch ownership.
5. Refresh local `main` from `origin/main` without destructive reset.
6. Confirm a SOL-high controller, fresh SOL-high assurance workers and fresh
   Terra-high implementation workers are available. Fall back to fresh SOL-high
   implementation workers if Terra-high is unavailable; never fall back from
   SOL-high to Terra-high for assurance.
7. Create or refresh `workflows/lcwip-implementation-ledger.md`. Create a ticket
   entry when work starts; update it with blocked-branch diagnoses and retries;
   mark its merge-validation section complete only after the pull request has
   merged and refreshed `main` passes boundary validation.

## Dependency frontier

- Re-read live issue state after every merge.
- A ticket is eligible only when it is open, labelled `ready-for-agent`, has no
  conflicting owner or active implementation pull request and every declared
  prerequisite is closed.
- Select the lowest-numbered eligible ticket.
- The expected order is #89, #90, #91, #92, #93, #94, #95, #96, #97 and #98.
  Recalculate rather than blindly hard-code it if issue relationships change.
- Implement only one ticket at a time. Review agents may run in parallel only
  when they have separate read-only review tasks against the same fixed diff.
- Assign the selected ticket to the authenticated GitHub user before
  implementation.

The initial prerequisite graph is:

- #89: no child prerequisite;
- #90: #89;
- #91 and #92: #89 and #90;
- #93: #91 and #92;
- #94: #90 and #93;
- #95: #89, and it must precede consultation-draft or adoption-candidate
  publication;
- #96: #89 and existing bounded-agent foundation #59;
- #97: #89, #91, #92, #93, #94 and #95;
- #98: #89, #93 and #97.

## Controller-authored task brief

Every one-task worker brief contains:

- the exact issue body and comments;
- relevant clauses from parent PRD #88 and declared prerequisite issues;
- applicable `AGENTS.md`, `CONTEXT.md` terms and ADR constraints;
- the current base commit and exact allowed diff boundary;
- the public integration seam and explicit prohibition on private SATN compiler
  coupling;
- required acceptance criteria, negative cases, exclusions and artifacts;
- focused and full validation commands;
- a requirement to preserve unrelated working-tree changes; and
- the worker's single stopping condition and required result format.

The worker returns a concise implementation report: changed files, decisions,
tests run with results, known limitations and exact remaining failures. It does
not return accumulated reasoning or claim acceptance.

## Ticket iteration

For each selected ticket:

1. Create `codex/issue-<number>-<slug>` from refreshed `main`.
2. Spawn one fresh Terra-high implementation worker with the bounded brief.
3. Require test-driven vertical slices through the public LCWIP package/CLI
   boundary established by #89. The LCWIP layer may consume only documented
   public SATN models and artifacts; existing `satn` must remain independently
   runnable.
4. Retire the worker when its one task ends.
5. Inspect the complete diff and worker report. Reproduce focused checks and
   the ticket's negative cases under SOL-high control.
6. Run the ticket validation gate below.
7. Spawn fresh, separate SOL-high Standards and Spec reviewers against the
   fixed diff.
8. For each accepted blocking finding or failed check, spawn a fresh one-task
   SOL-high diagnostic worker and then, when code changes are required, a fresh
   Terra-high repair worker with only the evidence required for that task. Rerun
   affected checks, the full ticket gate and both reviews after repair.
9. Commit intentionally, push the branch and open one pull request whose body
   links parent #88 and closes the selected ticket.
10. Wait for all required GitHub checks. A failing check receives a fresh
    one-task SOL-high diagnostic worker; the controller selects the repair, and
    a separate fresh Terra-high worker implements it.
11. Merge only when the controller has accepted the implementation, both review
    axes are clean and every required check is green. Use a merge commit.
12. Confirm the ticket closed, refresh local `main`, rerun boundary validation
    and add the pull request, merge commit and validation evidence to the
    ledger.

## Ticket validation gate

The SOL-high controller runs, at minimum:

```shell
git diff --check
uv run ruff check .
uv run pytest
uv run pytest --browser -m browser tests/test_review_map_browser.py
uv build
```

- Install the pinned Chromium runtime when absent.
- Add every issue-specific focused test, schema round-trip, fixture,
  determinism, failure-preservation, privacy, authority and compatibility check
  required by that ticket.
- For changes to publication or browser behavior, inspect the rendered artifact
  and exercise keyboard, accessible-HTML and non-map alternatives.
- For changes to agent decisions, test no-agent behavior, stale/replayed input,
  malformed output, timeout/provider failure, prompt injection and forbidden
  authority attempts.
- For changes to evidence or lifecycle state, test lineage, fingerprints,
  chronology, historical immutability, missing/stale/contradictory evidence and
  forbidden transitions.
- Treat the pull-request CI workflow as an additional independent gate, not a
  substitute for controller-run validation.
- Never weaken, skip, xfail or rewrite an acceptance test merely to obtain a
  green result.

## Completion policy

- The run is outcome-bound, not time-bound or attempt-bound.
- Continue until all issues #89–#98 are implemented, merged and validated.
- Failures are inputs to diagnosis and repair, not ordinary stopping
  conditions.
- Validation is part of implementation, not a later optional phase.
- Routine repository and GitHub operations do not create human approval
  checkpoints. The run is authorised to branch, commit, push, open and update
  pull requests, diagnose CI, merge validated pull requests, update issues and
  continue to the next eligible ticket.
- Keep filesystem authority scoped to this repository and temporary working
  directories. Full access to unrelated files on the user's computer is neither
  required nor authorised.
- Use automatic approval review for exceptional sandbox crossings so eligible
  actions do not pause for the user.
- Stop only when an action materially exceeds the repository/workflow boundary,
  requires unavailable external human authority, risks credentials or
  destructive out-of-scope changes, or conflicts with unrecognised user work.

## Quality and validation control

- The implementation worker must run focused tests while developing and report
  the exact commands and results, but its own evidence cannot accept the ticket.
- After worker delivery, the SOL-high controller independently reproduces the
  ticket-level deterministic checks from the worker's branch.
- Only after deterministic checks pass, run independent fresh Standards and
  Spec reviewers using SOL-high. Neither reviewer may be the implementation
  worker.
- Standards review checks the complete change against repository instructions,
  domain language, architectural boundaries, maintainability and test quality.
- Spec review checks the complete issue and parent-PRD contract, acceptance
  criteria, exclusions and expected artifacts.
- The controller evaluates the review evidence, rejects every blocking finding
  back into repair, reruns affected deterministic checks and repeats independent
  review until clean.
- Give every repair pass to a fresh Terra-high worker with a compact brief
  containing only the ticket contract, current diff, exact failing evidence,
  controller diagnosis and required verification. Do not copy any prior worker
  conversation.
- Give CI diagnosis, Standards review, Spec review and every delegated
  integrated-validation slice to separate fresh SOL-high workers, each with one
  task only.
- A ticket cannot be published or merged because it is plausible, mostly
  complete, or locally green. It advances only after the controller determines
  that implementation, tests, integration behavior and both review axes are
  clean.
- After every merge, the controller refreshes `main` and verifies the accepted
  boundary before creating the next ticket's worker.

## Retry and recovery

- There is no arbitrary retry, worker, ticket or wall-clock limit.
- Never repeat an identical failed action without new evidence or a changed
  strategy.
- Every diagnosis or review retry uses a fresh one-task SOL-high worker. Every
  implementation or repair retry uses a fresh one-task Terra-high worker.
- Keep a temporarily blocked branch and pull request truthful and recoverable.
  Record the failure, evidence and attempted repairs in the ledger.
- Do not start another ticket while the selected ticket remains unmerged.
  Continue diagnosing and repairing its blocking chain until it merges or
  reaches a permitted workflow stopping condition.
- For transient GitHub, network, package or evidence-service failures, use
  bounded waits and retry after confirming service state.
- If a branch becomes unreliable, preserve its evidence and create a clean
  replacement branch from refreshed `main`; transfer only controller-verified
  commits or changes. Never use destructive reset against user work.
- Do not manufacture evidence, silently substitute synthetic data for required
  governed data, weaken mandatory conformance, merge failing checks or mark a
  human gate as satisfied by an agent.

## Final integrated validation

After #98 merges, the SOL-high controller freezes the final `main` commit and
personally runs the complete deterministic gate:

```shell
uv sync --frozen --all-groups
uv run ruff check .
uv run pytest
uv run pytest --browser -m browser tests/test_review_map_browser.py
uv build
uv run satn compile examples/fixture/council.yaml
uv run satn compile config/banes.yaml --full
```

Also run the final LCWIP commands and fixtures introduced by #89–#98. They must
exercise one continuous deterministic path through:

1. Guidance Profile and lifecycle/conformance evaluation;
2. immutable evidence registry and coverage/quality reporting;
3. cycling demand/desire-line and walking/wheeling planning;
4. audits, deficiencies and intervention packages;
5. prioritisation scenarios, sensitivity and human-approved configuration
   records;
6. governance, engagement, equality and policy records;
7. bounded-agent and no-agent modes;
8. adoption-candidate publication, citations, manifests and release diffs; and
9. delivery update, monitoring trigger and superseding release.

The fixture may use governed synthetic authority and consultation records, but
must label them as fixtures. It must not claim real B&NES consultation,
professional assurance, adoption or portability; those belong to #99.

Delegate three independent one-task audits to fresh SOL-high workers:

- an end-to-end Spec audit against #88 and #89–#98;
- an architecture, maintainability and SATN-compatibility audit; and
- an authority, privacy, provenance and adversarial-safety audit.

The controller reconciles their findings, commissions fresh Terra-high repair
workers for every blocking defect, reruns all affected ticket gates and repeats
the complete final validation and SOL-high audits until clean. The frozen
commit is not final if any repair changes it.

Each final-integration repair is committed on a fresh branch from refreshed
`main`, pushed and published through a distinct pull request. Only the SOL-high
controller may accept and authorise its merge after required checks and fresh
one-task SOL-high audits are clean. Refresh and refreeze `main` after every such
merge before repeating final validation.

## Final Brief

When and only when the final integrated validation is clean:

- post a completion comment to parent #88 without closing it, because the
  human-assurance pilot #99 remains;
- present one decision-ready Brief containing:
  - complete/blocked status;
  - links to issues #89–#98 and every merged pull request;
  - final `main` commit and ledger;
  - concise controller-run and CI validation results;
  - links to the LCWIP fixture bundle, conformance manifest, reports, maps and
    release history;
  - explicit limitations and remaining Evidence Requests;
  - confirmation that no real adoption or professional-assurance claim was
    made; and
  - #99 as the next human-led assurance boundary.

The Brief links to artifacts and evidence; it does not paste raw drafts or logs.

## Unresolved decisions

- None.
