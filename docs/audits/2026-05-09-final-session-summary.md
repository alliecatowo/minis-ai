# 2026-05-09 Final Session Summary — ULTRATHINK

> Single canonical record at session end. Reconciled with reality: v9 regen actually COMPLETED (62 min, terminal status=ready) BUT the final embeddings INSERT crashed on a schema mismatch — so the mini is "synthesized but not saved." Two-line fix unblocks demo.

## 🔴 BIGGEST UNFIXED BUG (must fix first next session)

**Embedding INSERT crash on regen completion.**

Final v9 log line: `null value in column "embedding" of relation "embeddings" violates not-null constraint`.

**Root cause hypothesis:** The `embeddings` table has BOTH `embedding` and `vector` columns. The code writes to `vector` (with the actual float array) and leaves `embedding` as `None`. But the schema enforces NOT NULL on `embedding`. Either:
- (A) Schema column rename from `embedding` → `vector` was incomplete (some migration only renamed code-side, not DB-side)
- (B) Two columns are intentional (one pgvector, one raw) and the code is writing to the wrong one

**Where to look:** `backend/app/models/embeddings.py` (model definition), `backend/alembic/versions/*embeddings*.py` (recent embedding-related migrations), `backend/app/synthesis/pipeline.py` `_generate_embeddings()`.

**Likely fix:** either drop the NOT NULL constraint on `embedding` (if vector is the new column), OR write to both columns, OR drop the dead column. Any of these is a 1-2 line fix.

## Current state (verified 12:25 PT)

**Prod**
- backend health: ✅ 200 (no recent deploy needed)
- frontend: ✅ Vercel deploys flowing
- mini.alliecatowo: ❌ 404 (DB still `processing` since 2026-04-27 — v9 didn't reach the SAVE-mini-as-ready step due to embedding crash)
- joshwcomeau/jlongster: ✅ ready (untouched)
- **CD pipeline**: unwedged (deploys fire on every main merge)
- **Langfuse**: secrets in GH+Fly, will trace fully on next deploy with PR #217

**Regen v9 (final state)**
- Started 10:53 PT, ended 11:55 PT (62 min)
- `terminal status=ready terminal_stop_reason=completed duration_seconds=3732.1` per pipeline
- BUT embedding write failed → no mini revision row → no `status=ready` flip on Mini table
- **5+ aspect narratives degraded** because `output_tokens_limit=8192` was killing them mid-write (PR #221 fixes this)
- Cost: ~95+ OpenAI completions × ~12k tokens avg = roughly $0.50-1.00 in GPT-5 spend

**Open PRs (4 of 6 mergeable as I write this)**

| PR | Title | State | Risk |
|----|-------|-------|------|
| #221 | Remove chief output_tokens cap + cheap-model stack | DIRTY (conflicts) | Low |
| #220 | GraphQL co-fetch bundles (W4.1) | CLEAN | Live GraphQL field names unverified |
| #219 | Bare-except sweep round 2 | CLEAN | Low |
| #218 | Lefthook pre-push + sprint-status | unknown | Low |
| #217 | Langfuse v4 + mise auto-env + CLAUDE.md sync | unknown | Low |
| #215 | W4.2 strict additive cache | unknown | Test failed earlier |

## What landed today (canonical list)

17+ PRs merged across Wave 0 (unwedge CD), Wave 1 (branch hygiene), Wave 2A-E (fidelity wiring), Wave 3A-E (ingestion depth), Wave 4 partial (DX + bulk-ingestion).

Code-impact summary:
- **Net LOC:** roughly negative (Wave 2C -275, Wave 2D -1500, sweeps small net negative)
- **Tests:** ~2050 passing (up from 805 baseline pre-session)
- **Branches:** 196 → manageable (worktree-agent leftovers still inert)
- **GH issues opened:** 12+ (audit-driven + demo-blocker)
- **Linear:** untouched (capped)

See `docs/audits/2026-05-09-session-learnings.md` for the full table.

## Execute-this list for next session (in order)

```bash
# 1. Sync main
cd /home/Allie/develop/minis-hackathon
git checkout main && git fetch origin && git reset --hard origin/main

# 2. Diagnose embedding crash (15 min)
grep -rn "embedding\|vector" backend/app/models/embeddings.py backend/alembic/versions/ | grep -i "not.null\|nullable\|column" | head -20
grep -A 5 "INSERT INTO embeddings\|Embedding(" backend/app/synthesis/pipeline.py

# 3. Fix embedding NOT NULL (1-2 line fix, then commit + PR)
# Either: drop NOT NULL constraint on embedding column OR write to both OR drop dead column

# 4. Rebase + merge PR #221 first (chief cap removal — CRITICAL)
gh pr view 221 --json mergeable,mergeStateStatus
# If DIRTY: pull branch, rebase on main, push --force-with-lease

# 5. Merge greens in order: 221 → 219 → 215 → 217 → 218 → 220
for pr in 221 219 215 217 218 220; do gh pr merge $pr --squash --delete-branch -R alliecatowo/minis-ai; done

# 6. Wait for CD to deploy (watch gh run list -w Deploy -L 1)

# 7. Restart regen (with all merged code: caps removed, GraphQL co-fetch, additive cache, langfuse v4)
cd backend && set -a && source .env && set +a && \
  nohup env DEFAULT_PROVIDER=openai PYTHONPATH=. \
    uv run python scripts/regen_mini.py alliecatowo \
    > /tmp/regen-alliecatowo-v10-final.log 2>&1 &
disown

# 8. Wait ~30 min, check completion
tail -5 /tmp/regen-alliecatowo-v10-final.log
curl -s -o /dev/null -w "%{http_code}\n" https://minis-api.fly.dev/api/minis/alliecatowo
# Expect 200

# 9. Smoke-test chat
curl -X POST https://minis-api.fly.dev/api/minis/alliecatowo/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"what do you actually think about microservices vs monolith?"}'
# Read the response. Sound like Allie? If yes → demo ready.

# 10. (Optional) Run fidelity eval
cd backend && uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo --base-url https://minis-api.fly.dev \
  --out /tmp/eval-2026-05-XX.md
```

## Decision gates next session must hit

1. **Cheap stack vs gpt-5/o3 for fidelity quality?** PR #221 ships gpt-4.1-nano/gpt-5/o4-mini (cost-optimized). If first regen-v10's chat output sounds generic, swap STANDARD back to gpt-5 (already on PR #221 — just keep it). If voice quality is poor with cheap mix, DON'T sacrifice demo for cost — bump back up.

2. **Mini chat model that user flagged.** "Mini inference model should be a gpt one, old minis aren't responding." Investigate `backend/app/routes/chat.py` model resolution. The chat tier may have been left on Anthropic or Gemini default while regens use OpenAI. Possibly the chat code uses a stale model identifier. Quick fix: ensure `chat.py` uses `get_model(ModelTier.STANDARD)` consistently with whatever provider Fly env says.

3. **Install GitHub App vs CLI fallback for demo step 7?** Per project audit: install on alliecatowo/minis-ai itself (5 min via GitHub Settings). If complications, document the `mise run mini-review` CLI path as the fallback.

4. **Frontend SSR profile page — ship or defer?** Per codebase audit critical #3: 1 day of work, demo polish. Defer if any of #1-#3 above need attention.

## Hard-won learnings (encode these)

1. **Agency-first.** Saved at `~/.claude/projects/.../memory/feedback_agency_first.md`. NO artificial agent caps (`request_limit`, `max_output_tokens`, `max_turns`). The `output_tokens_limit=8192` on chief aspects silently dropped entire narrative essays — exactly the worst failure mode. Cap cost via TokenBudget; trust the agent.

2. **No legacy paths.** Wave 2D deletion of legacy chief synthesis (-1500 LOC) was ONE refactor today. Same pattern: when new path lands, delete old.

3. **PR-driven discipline.** Even the 2-line lint unblock went through PR. Worth it for the trail.

4. **Worktree isolation for agents.** Sharing the main working tree → agents stomp each other's edits. fid-2e flagged this. Fix: always `isolation: "worktree"`.

5. **try/except hides bugs.** `from chief import run_chief_synthesis` was deleted by Wave 2D, but `try: import / except: raise NotImplementedError` masked it for 3 regens. Anti-pattern.

6. **GH rate limit kills heartbeats.** 5000/hr exhausted by polling. Use sparse cron; gh CLI calls are expensive.

7. **Sqlite mocks in postgres-only codebase = pain.** Migrate to testcontainers Postgres.

8. **CI synchronize event flaky on agent branches.** Added workflow_dispatch (#207) + push trigger for agent branch patterns (#212). Both essential.

9. **Rolling deploy can nuke a running regen.** Hold merges during regens until separate worker machines exist (CI.3 in TASKS.md).

10. **Linear free-tier ticket cap is real.** TASKS.md → GH issues migration in flight. Use `gh issue list --label fidelity --state open` as backlog query going forward.

## Stack reference

- **Backend:** Python 3.13 + uv + FastAPI + SQLAlchemy + asyncpg (Postgres only) + PydanticAI + pgvector
- **Frontend:** Next.js 16 + React 19 + Tailwind v4 + shadcn/ui + pnpm 9 (pinned — pnpm 10 has the `pnpm-workspace.yaml` confusion)
- **Infra:** Fly.io (backend, app=`minis-api`) + Vercel (frontend) + Neon Postgres + Langfuse + GH Actions
- **Tooling:** mise (auto-loads `backend/.env` after PR #217), lefthook (pre-push ruff after PR #218)
- **LLM stack (post #221):** OpenAI gpt-5 STANDARD / gpt-4.1-nano FAST / o4-mini THINKING / text-embedding-3-small EMBED. ~70% cheaper than initial gpt-5/o3 setup.

## Files to read first in next session

Required:
- `docs/audits/2026-05-09-final-session-summary.md` ← this file
- `docs/handoff/2026-05-09-session-handoff.md` ← companion handoff
- `docs/audits/2026-05-09-session-learnings.md` ← full session record
- `~/.claude/projects/.../memory/MEMORY.md` ← + linked feedbacks (agency-first, dispatch-protocol, no-legacy-paths)

Reference:
- `docs/VISION.md` — north star
- `CLAUDE.md` — repo guide (recently updated)
- `docs/MINIS_FIDELITY_FIX_PLAN.md` — Phase 1-5 fidelity plan
- `docs/spikes/2026-05-09-bulk-additive-ingestion.md` — Wave 4 architecture
- `docs/audits/2026-05-09-codebase-health.md` — 3 critical + 7 high
- `docs/audits/2026-05-09-project-health.md` — vision parity + demo blockers
- `docs/audits/2026-05-09-agent-dx-meta.md` — 12 friction points + top 5 fixes
- `docs/audits/2026-05-09-regen-v9-baseline.md` — first measured regen
- `docs/audits/2026-05-09-openai-pricing.md` — model pricing audit

## YC Demo readiness scorecard (today vs goal)

| Area | Today | Goal | Gap |
|------|-------|------|-----|
| Tier 1 IC velocity (chat works on Allie) | ❌ | ✅ | embedding-crash fix + regen v10 |
| Tier 2 framework cloning visible in soul doc | ❌ | ✅ | post-cap-removal regen v10 will have full 11 narratives |
| Tier 3 team multi-mini features | partial | partial | acceptable for YC |
| Tier 4 GitHub App live | not deployed | install on 1 repo | 5 min |
| Tier 5 enterprise | not started | acceptable | NA |
| Demo step 1 landing | ✅ | ✅ | none |
| Demo step 2 profile page | unknown | ✅ | verify SSR rendering of soul/narratives |
| Demo step 3 review prediction | ✅ via CLI | ✅ | document CLI as fallback if app not installed |
| Demo step 4 scorecard UI | unknown | ✅ | verify post-Wave-2 schema render |
| Demo step 5 calibration metric | partial | ✅ | partial OK |
| Demo step 6 outcome loop | partial | partial | acceptable |
| Demo step 7 CTA / GH App install | not deployed | ✅ | 5 min install or CLI fallback |
| Observability (Langfuse for cost transparency) | half (need #217 deploy) | full | merge #217 + redeploy |
| Cost per regen | ~$1 | < $0.50 | post #221 cheap stack |
| Per-regen FETCH duration | ~10 min | < 3 min | W4.1 GraphQL #220 will hit this |
| Per-regen SYNTHESIZE duration | ~30 min | < 15 min | cap removal + cheap stack |

## TL;DR for next session opening

1. Read this doc + the handoff.
2. Check status: `tail /tmp/regen-alliecatowo-v9-gpt5-credits-2026-05-09.log` and `curl https://minis-api.fly.dev/api/minis/alliecatowo`.
3. Fix the embedding NOT NULL crash (1-2 lines).
4. Rebase + merge PR #221 first.
5. Bulk merge greens 219/215/217/218/220.
6. Restart regen v10.
7. Verify alliecatowo `ready` on prod.
8. Smoke-test chat.
9. Demo.
