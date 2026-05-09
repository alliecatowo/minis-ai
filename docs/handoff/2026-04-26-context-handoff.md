# Codex Handoff — Minis Fidelity Sprint, 2026-04-26

This doc dumps the full context of the current session so a fresh codex agent can pick up cleanly. Allie is switching agents because Claude Sonnet usage is running out.

## TL;DR

We've spent today landing ~10 waves of fidelity fixes on top of `main`. Pipeline now produces narrative-essay-based soul docs via a fan-out chief synthesizer. Fan-out runs on OpenAI gpt-5/o3/gpt-5-mini (free-tier-eligible). Frontend bug fixes shipped (first-character cutoff finally caught — async placeholder race). Several large audits landed but their implementations aren't all done. `alliecatowo` mini quality is improving but Allie still feels it's: (a) over-fitted to recent narrow projects (Lumen, ZMK), (b) regurgitates her phrases instead of synthesizing novel takes, (c) loses her typing register, (d) leaks AI tells the prompt was supposed to suppress.

The user's deepest insight today, **drives the dispatch shape**: the prompt has been growing as an accumulating denylist of "never X" rules. That pattern is wrong. Banning the visible AI tells just pushes them into other channels (Goodhart). The correct architecture is to TEACH the model an abductive authenticity loop — degrees not binaries, evidence-rate matching, AI-in-context recognition (the subject may use AI for some registers; faithfully reproduce that). The current in-flight agents are refactoring toward that.

## What's on `main` after today

Latest commit chain (newest first):
- `f450adb` — fidelity wave 6: abductive authenticity loop, embedding RAG, freshness, KG query, reasoning edges
- `abe8acf` — docs: GitHub ingestion completeness audit
- `f39a2ef` — fidelity wave 5: anti-regurgitation, breadth tagging, memory+KG audit
- `b6032f5` — spirit: remove leading-style examples (no per-mini bias in pipeline)
- `2a8abeb` — fidelity wave 4: typing register, anti-regurgitation, breadth ingestion, walkthrough UX
- `03f7fc4` — fix: async assistant placeholder race drops first streamed character (THE first-line bug, finally)
- `6d48891` — merge: tos + walkthrough alembic heads
- `704d60c` — test: lefthook hooks, postgres-style mock
- `0221393` — fidelity wave 3: prompt hardening, chat current-vs-deep, signup/TOS, CD pipeline, audits, spikes
- `1851f70` — fidelity: chief.py fan-out + ExplorerNarrative + save_narrative tool

## Major architectural changes shipped today

1. **chief.py fan-out** (`1851f70`): replaced 8-section `write_section` chief with 8-aspect parallel narrative essay generation. Each aspect agent writes a 1200-2000 word essay; a final chief synthesis pass composes the soul. New tool `save_narrative`. New table `ExplorerNarrative`. New aspects: `voice_signature`, `decision_frameworks_in_practice`, `values_trajectory_over_time`, `audience_modulation`, `conflict_and_repair_patterns`, `technical_aesthetic`, `philosophical_priors`, `architecture_worldview` + later additions `ai_usage_signature`, `framework_loves_vs_current_focus`.

2. **Reasoning edges** added to `RelationType`: `rejects_because`, `prefers_over`, `trades_off`, `decides_based_on`. Migration applied. Explorer prompts MOSTLY don't use them yet — a codex agent in flight is fixing this.

3. **Burst throttle** (`c25eb5a`): process-wide LLM request throttle (semaphore + min-gap). `LLM_MAX_CONCURRENT_REQS` default 6, `LLM_MIN_REQUEST_GAP_MS` default 50.

4. **AI-as-signal** (not noise) (`30f4c63`): `ai_authorship_likelihood` + `ai_style_markers` columns on Evidence. `app/synthesis/ai_signals.py` heuristic scorer. Pipeline scores each ingested item; chief writes an `ai_usage_signature` aspect narrative.

5. **Free-tier OpenAI defaults**: STANDARD=`gpt-5`, THINKING=`o3`, FAST=`gpt-5-mini`. Fits in tier-1 limits with the throttle.

6. **Lefthook + PostgresStyleSession mock** (`704d60c`): pre-commit hooks for lint/typecheck. Postgres-style session mock at `backend/tests/fixtures/postgres_mock.py` simulates `pg_insert(...).on_conflict_do_update(...)` for unit tests without a real DB.

7. **CD workflow** (`.github/workflows/cd.yml`): on push to main → CI passes → migrate (alembic upgrade head with multi-head guard) → fly deploy → smoke test against /api/health.

8. **Frontend signup + TOS gate**: `/signup` page, `TosGate` component, `tos_acceptance` table. Walkthrough decoupled from TOS (was tied; user reported broken UX, now a dismissable bubble after TOS accept).

9. **First-line cutoff bug** (`03f7fc4`): `useMiniChat.ts` placeholder was inserted asynchronously; first chunk arrived before placeholder existed in state, `findIndex` returned -1, chunk was dropped. Fix: `flushSync` the placeholder insertion. THIS WAS THE BUG after 3 prior wrong-target fixes.

10. **Streaming flushSync**: chunk-handler setMessages calls wrapped in `flushSync` to defeat React 18 batching that was collapsing per-chunk renders into one.

## Audits committed (read these to ground further work)

- `docs/audits/2026-04-26-sprint-cleanup-audit.md` — codebase rot. Top finding: legacy 8-section chief path still alive alongside fan-out (dead code surface). Shared `db_session` in repo-agent fan-out (same async-session bug we fixed in chief).
- `docs/audits/2026-04-26-ci-cd-audit.md` — CI gaps + new cd.yml.
- `docs/audits/2026-04-26-github-app-multi-bot.md` — GitHub App is multi-bot at the @username level but: zero onboarding, zero permission enforcement, single shared bot identity, no idempotency on webhook re-delivery, no lifecycle handlers.
- `docs/audits/2026-04-26-github-ingestion-completeness.md` — top gaps: PR reviews authored for OTHERS (highest-leverage critique corpus, ZERO ingested today), inline review comments at diff-hunk level, starred/watched repos, gists/discussions, commits stored as JSON blob not per-Evidence rows with diffs.
- `docs/audits/2026-04-26-memory-and-knowledge-graph.md` — memory is flat blob fully injected at chat time; `search_memories` is keyword ILIKE not semantic; KG is write-only at chat time; no freshness semantics; no chunked-evidence RAG. Top 5 leverage tickets identified.

## Spikes committed

- `docs/spikes/2026-04-26-codex-device-auth.md` — feasibility verdict on using OpenAI Codex CLI's device-flow OAuth for free compute. **Verdict: BYOC per-user only**, not a primary cost strategy. The Codex token hits `chatgpt.com/backend-api/`, not `api.openai.com`, so PydanticAI's OpenAI provider can't drop it in.
- `docs/spikes/2026-04-26-multi-bot-actors.md` — multi-bot identity model. Phase 1: add `display_name`, `avatar_url`, `voice_color`, `api_token_hash` columns to Mini. `MiniAccessGrant` join table for org/team sharing.
- `docs/spikes/2026-04-26-api-cli-revamp.md` — /api/v1/ migration with 3-month sunset. Standardize error envelope. Cursor pagination. CLI device-flow auth. MCP split (user MCP vs review MCP).

## In-flight codex agents (as of handoff time)

These are running in parallel on `main`. Each commits its own work when its sandbox allows, otherwise leaves files in worktree and reports back.

| Agent | Task | Status |
|---|---|---|
| `ad08d665b2` | Synthesis-not-retrieval (redirected to teach principle, not coerce tool count) | running |
| `aa382843414d2f02d` | Memory + KG audit | DONE — committed `f39a2ef` |
| `a2d60be3ba13595b2` | Memory: embedding RAG + chunked evidence | DONE — committed in `f450adb` |
| `ad0576fce29267e3b` | Memory freshness (replace-on-regenerate) | DONE — committed in `f450adb` |
| `a6a4f1eeffd32b30f` | KG chat-time query tool + reasoning edge population | running (was paused on branch confusion, told to stay on main) |
| `ab3c8e33f642d94e5` | Prompt-architecture refactor (denylists → abductive authenticity loop) | DONE — committed in `f450adb` (the `_ABDUCTIVE_AUTHENTICITY_LOOP_BLOCK` in spirit.py) |
| `a3eebcb76cc02a3e8` | Fix ALL failing tests + lint (~24 broken tests) | running, large job (lots of integration tests need real DB or postgres-mock UPSERT extensions) |
| `a1d7c3a738564630` | Voice fidelity round 2 (Answer prefix + voice slip) | running |
| `ac878bab30b3590cf` | All-non-GitHub-sources audit (esp claude_code) | just dispatched |
| `a76e1a4288605a154` | GitHub ingestion completeness — IMPLEMENT audit findings | just dispatched |
| `a96ae958df8daba83` | Typing register | DONE — committed in `2a8abeb` |
| `a917c362e8afac811` | First-line cutoff (4th attempt) | DONE — committed in `03f7fc4` (placeholder race) |
| `a05b62c49992dd555` | Walkthrough UX decoupling | DONE — committed in `0221393` |
| `a304af34d9ebbddc8` | Breadth-not-depth ingestion (recent/mid/historical tagging) | DONE — committed in `f39a2ef` |

## Known issues / loose ends

1. **Test drift after fan-out + RAG refactors**: ~16 unit tests + the integration suite under `tests/integration/` and `tests/ingestion/` are failing in CI. Not regressions in product behavior — they're tests that need updating to match the new code paths (embedding RAG signature changes, prompt block renames, postgres-mock UPSERT for `explorer_progress`). Codex agent `a3eebcb76` is in flight on this. **CD won't fire until these are green.**

2. **prompt_diff_test stale**: `backend/scripts/prompt_diff_test.py` was the cheap A/B validator. After the prompt refactors it's broken; not a priority but worth fixing if there's quota left.

3. **Reasoning edges**: enum exists, save_knowledge_edge accepts them, but explorers historically only emit taxonomic edges. Codex `a6a4f1ee` is in flight to update explorer prompts to emit `prefers_over`/`rejects_because`/`trades_off`. Won't take effect until next regen.

4. **Memory chat-time injection**: the embedding-RAG agent slimmed system prompt by removing full memory blob. Verify chat still has a fallback if embeddings table is empty for a mini (regen needed first to populate embeddings for alliecatowo).

5. **Codex agent quota**: agents running in parallel are heavy. User explicitly said usage is running out — minimize new dispatches, finish what's in flight first.

## Currently running regen

`bc81z0iq6` — alliecatowo regen with DEFAULT_PROVIDER=openai, post-wave-6 code. Will use abductive authenticity loop, replace-on-regenerate freshness, and the ai_usage_signature aspect.

If regen fails (token limits, rate limits, DB issue), retry steps:
1. `cd backend && set -a && source .env && set +a && uv run alembic upgrade head` (in case migrations drift)
2. `set -a && source .env && set +a && DEFAULT_PROVIDER=openai PYTHONPATH=. uv run python scripts/regen_mini.py alliecatowo`

## Allie's directives during this session (load-bearing)

- "Voice + framework BOTH matter. Voice is the demo; framework cloning is the moat."
- "No legacy paths. Pre-0.0.1 app can't afford coexistence. Delete old paths when new path works."
- "File tickets liberally. Linear is full → use TASKS.md."
- "Spikes are first-class deliverables — produce write-ups + follow-up tickets."
- "Use codex agents heavily because they don't burn Anthropic quota."
- "No PRs, do local commits + merges."
- "Idc if you do it on prod we don't have a single user." (re: applying alembic to prod Neon directly)
- **Critical late-session insight**: "We aren't anti-coefficient — narrative first, then research-backed coefficients downstream."
- **Critical late-session correction**: "We don't hardcode 'lowercase i or apostrophe-elisions' — that's encoding the human's read of THIS user, which is hyperfitting. Pipeline must extract register from corpus per-mini, never prescribe."
- **Critical architectural insight**: "Tool count is a Goodhart's-law indicator, not a goal. Teach the model the synthesis goal, not enforce a procedure."
- **Critical product insight**: "The hottest opinion should be GENERALIZED PHILOSOPHY/TASTE, not stack-specific. 'You don't need a serverless stack for 2 users' — synthesizing values applied to a novel framing, not retrieving from corpus."

## Recommended next moves (priority order)

1. **Wait for in-flight agents to land**, especially `a3eebcb76` (test fix) and `a6a4f1ee` (KG reasoning edges). Push commits as they trickle in. CD will fire once tests are green.
2. **Verify alliecatowo regen** (`bc81z0iq6`) completes cleanly. If yes, go test the chat at https://my-mini.me — should now have abductive authenticity loop applied + reasoning edges populated + freshness wiped stale rows.
3. **Implement memory + KG top-leverage tickets** that aren't already in flight (chunked-evidence RAG was implemented; chat-time KG query was implemented; what's left is fully wiring the freshness clean-slate into the chat experience).
4. **Implement the GitHub ingestion top 5** (codex `a76e1a4288` is on this).
5. **Audit + implement claude_code source completeness** (codex `ac878bab30` is auditing; implementation will be a follow-up).
6. **Distribution surfaces**: GitHub App multi-bot onboarding (per spike) and Claude Code plugin (per `~/.claude/projects/.../memory/`). Allie wants distribution surfaces tested with the new improved agents.
7. **YC-readiness loop** (per `~/.claude/plans/check-out-the-linear-purring-swing.md` Phase 2): demo script, seed YC demo workspace, refresh eval fixture, fix MINI-230 SSE done event on streaming error.

## Files that are likely to need attention next

- `backend/app/synthesis/spirit.py` — `_ABDUCTIVE_AUTHENTICITY_LOOP_BLOCK` is at line 29; the rest of `build_system_prompt` may have legacy negative blocks not yet purged. Cross-check.
- `backend/app/synthesis/chief.py` — `AUTHENTICITY_LOOP_SYNTHESIS_BLOCK` exists; verify all 3 prompt templates (ASPECT_AGENT_SYSTEM_PROMPT, CHIEF_FINAL_SYNTHESIS_PROMPT, SYSTEM_PROMPT) substitute `{authenticity_loop_block}` cleanly.
- `backend/app/routes/chat.py` — likely still has stale "current vs deep loves" + "anti-regurgitation" blocks that should be merged into the abductive loop's degree-matching frame.
- `backend/app/synthesis/explorers/repo_agent.py` — flagged in sprint-cleanup-audit for shared db_session fan-out misuse.
- `backend/scripts/prompt_diff_test.py` — broken after refactor.

## Useful one-liners

- `mise run regen-anthropic alliecatowo` (rebuilds mini)
- `mise run pipeline-replay` (cassette test, no token burn)
- `mise run test-unit` / `mise run test-integration`
- `mise run setup-hooks` (lefthook install)

Good luck. Allie is sharp and patient with iteration; she calls out hyperfitting and Goodhart fast — listen when she does.
