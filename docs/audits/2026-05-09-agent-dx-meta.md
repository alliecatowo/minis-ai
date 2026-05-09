# Agent DX / Meta Audit — 2026-05-09

## Top Agent Friction Points

1. **Worktree explosion + stale branch locks** — 60+ worktrees, 52 locked agent branches. Disk fragmentation, git confusion. **Fix:** `.claude/worktree-gc` hook prunes worktrees + branches >7d at agent startup.
2. **CI doesn't fire on agent PRs reliably** — `pull_request.synchronize` event not fired on force-pushed branches; `workflow_dispatch` was added in #207 today. **Fix:** also wire `push` trigger for `codex/*` and `worktree-agent-*` branches.
3. **CD migrate step exits silently on failure** — no `set -euo pipefail`; deploy proceeds even when migrations fail. **Fix:** add `set -euo pipefail` + `alembic current | grep -q "head)"` assertion before deploy job.
4. **Test mocks incompatible with Postgres-only codebase** — `aiosqlite` mocks lack columns, lack UPSERT support. Multiple sessions have lost time on schema-drift errors. **Fix:** ship `Dockerfile.testdb` + auto-spin testcontainers Postgres in conftest.
5. **Worktree-shared `.env` causes provider surprises** — one agent flips `DEFAULT_PROVIDER`, next agent burns wrong quota. **Fix:** snapshot `.env` per-worktree on creation; per-agent override path.

## Harness Gaps
6. **No sprint-status command** — Allie has no AFK observability. **Fix:** `mise run sprint-status` showing active worktrees, in-flight PRs, test status, recent commits, blocked issues. Optional cron email digest.
7. **CLAUDE.md stale on roadmap** — Linear is full; TASKS.md is canonical but CLAUDE.md doesn't point there. **Fix:** add "Phase 2-4 Roadmap (see TASKS.md)" section pointer.
8. **No async migration safety for concurrent agents** — multiple parallel `mise run migrate` to same DB unsafe. **Fix:** `migrate_with_lock.py` using `pg_advisory_lock`.

## Cloud Env Wants
9. **Neon branch quota (25-branch limit)** hit twice today. **Fix:** `mise run neon-gc` lists + deletes untagged branches >N days; agents tag on create.
10. **30+ min regens tie up local box** — Allie can't demo while regen runs. **Fix:** `mise run remote-regen alliecatowo` runs on Fly builder VM, tails logs locally.

## CI/CD Ergonomics
11. **No auto-rebase for stale agent PRs** — agents force-push, CI only fires after manual workflow_dispatch. **Fix:** GH Action that on PR open/update bumps head SHA via empty commit if `synchronize` didn't trigger CI within 60s.
12. **Cassette/replay for LLM calls broken** — `tests/support/upstream_contracts.py` exists but unwired. **Fix:** wire `MINIS_CASSETTE_MODE=record|replay` env into `run_agent()`; default replay in CI when fixture exists.

## Recommended Fixes (Top 5, ship this sprint)
1. `set -euo pipefail` to cd.yml migrate step + `alembic current` assertion (1h, BLOCKS prod safety)
2. `.claude/worktree-gc` startup hook (2h, ENDS stale branch explosion)
3. `testcontainers` Postgres for tests (3h, UNBLOCKS test iteration)
4. `push` trigger for agent branches in ci.yml (1h, FIXES silent CI failures)
5. `mise run sprint-status` 1-pager (1h, IMPROVES AFK observability)

Total: ~8h of plumbing → 3-4× agent velocity multiplier.
