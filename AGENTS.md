# AGENTS

## Read First

Before editing, read in this order:

1. `docs/VISION.md`
2. `docs/PROGRAM.md` (if present)
3. `CLAUDE.md`

Then apply this file as the operational layer for PRs and task execution.

## North Star

Ship only work that improves the decision-framework pipeline, evidence quality, or review-grade prediction quality for real person-of-interest outputs.

## Canonical Repo / Legacy Paths

- Canonical repo is `alliecatowo/minis-ai`.
- Do not open PRs against `alliecatowo/minis`, `alliecatowo/my-minis`, or `minis-v2` unless Linear explicitly allows it.
- Avoid legacy paths: no duplicate execution paths, no alternate code paths for the same behavior, and no silent compatibility branches.

## Linear Workflow (MINI)

- Every change is tied to a `MINI-*` ticket.
- PRs must include `Linear: MINI-###` (or `Fixes MINI-###` when closing) in the PR body so automated checks pass.
- Branch names should include the issue identifier, e.g. `codex/mini-###-short-description`.
- If a task starts from a subtask, create the parent `MINI-*` ticket before implementation.

## Branch and PR Rules

- Open work as narrowly scoped PR-sized slices.
- Prefer draft PRs while iterating.
- Include expected impact in the PR summary and list exact tests run.
- Do not merge code that changes behavior without relevant test coverage.
- Never add secrets, private user evidence, local credentials, or unredacted local logs.

## Raw Evidence and Data Discipline

- Evidence collection is append-only by default.
- Prefer additive schema/migration updates over in-place rewrites of historical evidence.
- Keep source and provenance fields intact (`source`, `item_type`, `external_id`, hashes, timestamps) when touching evidence logic.

## Validation

- Backend code changes: run `mise run lint` and focused `mise run test-unit`.
- Frontend changes: run `cd frontend && pnpm lint` and targeted UI tests when touched.
- If chat/review output quality is changed, run focused fidelity checks where practical.
- Live LLM and full E2E checks are optional/last-mile only when environments and upstream services are available; note clearly if skipped.

## Safe Cleanup

- Clean generated artifacts from local/dev runs (clones, temp files, logs) using non-destructive tooling first.
- Avoid deleting shared evidence or DB rows without a migration and explicit consent path.
- Before cleanup of external review/deploy resources, confirm branch/state is no longer needed.

## Agent Fan-Out Conventions

- Keep subagent/task fan-out scoped to one bounded area with explicit acceptance criteria.
- Use isolated worktrees for parallel agent edits when file overlap risk exists.
- Each agent handoff must include touched files, ticket, tests run, and any assumptions so work can be recomposed quickly.

