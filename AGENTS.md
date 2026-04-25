# AGENTS

## Read First

Before editing, read in this order:

1. `docs/VISION.md`
2. `docs/PROGRAM.md` (if present)
3. `CLAUDE.md`
4. `AGENTS.md` workflow sections

Then apply this file as the operational layer for PRs and task execution.

## North Star

Ship only work that improves the decision-framework pipeline, evidence quality, or review-grade prediction quality for real person-of-interest outputs.

## Canonical Repo / Legacy Paths

- Canonical repo is `alliecatowo/minis-ai`.
- Do not open PRs against `alliecatowo/minis`, `alliecatowo/my-minis`, or `minis-v2` unless Linear explicitly allows it.
- Avoid legacy paths: no duplicate execution paths, no alternate code paths for the same behavior, and no silent compatibility branches.

## Linear Workflow (MINI)

- Every change is tied to a `MINI-*` ticket.
- Linear is the source of truth for strategy, sequencing, spikes, and follow-up work; do not let architecture decisions live only in chat or local notes.
- PRs must include `Linear: MINI-###` (or `Fixes MINI-###` when closing) in the PR body so automated checks pass.
- Branch names should include the issue identifier, e.g. `codex/mini-###-short-description`.
- If a task starts from a subtask, create the parent `MINI-*` ticket before implementation.

## Branch and PR Rules

- Open work as narrowly scoped PR-sized slices.
- Prefer draft PRs while iterating.
- Work from a fresh branch/worktree off latest `main`; never pile new work onto a dirty tree.
- Include expected impact in the PR summary and list exact tests run.
- Do not merge code that changes behavior without relevant test coverage.
- Never add secrets, private user evidence, local credentials, or unredacted local logs.

## Codex / Agent Config

- Codex agents should treat this `AGENTS.md` as the repo-local operating config. Do not add `.codex/config.toml` unless Codex documents repo-local config loading for this CLI; current documented config is user-level `~/.codex/config.toml`.
- Keep agent guidance compact and operational. Put durable product strategy in Linear or existing strategy docs, not new sprawling repo docs.
- Use existing `.claude/` agents, commands, skills, and worktree bundles when they fit instead of duplicating ad hoc instructions.

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
- Do not run catastrophic cleanup commands (`git reset --hard`, `git clean -fd`, broad `rm -rf`, destructive DB operations) without explicit user direction and a scoped path/target.

## Agent Fan-Out Conventions

- Keep subagent/task fan-out scoped to one bounded area with explicit acceptance criteria.
- Use isolated worktrees for parallel agent edits when file overlap risk exists.
- Each agent handoff must include touched files, ticket, tests run, and any assumptions so work can be recomposed quickly.
