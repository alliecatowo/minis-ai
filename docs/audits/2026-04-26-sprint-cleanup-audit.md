# Sprint Cleanup Audit (Read-Only)
Date: 2026-04-26
Scope: `/home/Allie/develop/minis-hackathon` at HEAD (`c2f8e9a`)
Method: static read-only audit (no DB/network/alembic/fly/vercel/gh commands)

## 1) DEAD CODE PATHS

1. Production synthesis path is fan-out; legacy 8-section path is still shipped as fallback.
- `backend/app/synthesis/chief.py:745-753` routes real `AsyncSession` to `_run_chief_synthesizer_fanout`.
- `backend/app/synthesis/chief.py:754-1199` keeps the old section-by-section writer (`write_section`, `finish`, 8-section assembly).
- `backend/app/synthesis/chief.py:1203-1423` keeps `run_chief_synthesis` legacy text-blob wrapper.
- Assessment: legacy path appears non-production in normal app flow, but is still reachable if callers pass non-`AsyncSession` mocks/objects.

2. Pipeline legacy branch is likely dead in runtime app flow, still present in code.
- `backend/app/synthesis/pipeline.py:1235-1243` uses DB-driven `run_chief_synthesizer` when `mini_id` is set.
- `backend/app/synthesis/pipeline.py:1279-1289` uses legacy `run_chief_synthesis` only when `mini_id is None`.
- `backend/app/synthesis/pipeline.py:1653-1654` hard-requires `mini_id` in `run_pipeline_with_events`.
- `backend/app/routes/minis.py:281-289` always passes `mini.id` into `run_pipeline_with_events`.
- Assessment: app runtime path strongly indicates legacy branch is test/compat-only.

## 2) CONFLICTING PROMPTS

1. Chief contains two conflicting synthesis contracts in one module.
- New narrative-first contract: `backend/app/synthesis/chief.py:140-150`, `162-218`.
- Old 8-section contract: `backend/app/synthesis/chief.py:231-380`.
- Conflicts include output length/shape: `4000-6000 words` (`:167, :194`) vs `under 3000 words total` (`:248-249`).

2. Spirit prompt says “required process for EVERY response” and “ALWAYS search”, while chat route allows no-tool short replies.
- Spirit strictness: `backend/app/synthesis/spirit.py:527-535`, `542-549`.
- Chat relaxes for short casual turns: `backend/app/routes/chat.py:1111-1121`.
- This creates instruction-level contention between baked system prompt and runtime directive.

3. `universal_prompt.py` target appears planned but absent.
- Spec says new file should exist: `docs/MINIS_FIDELITY_FIX_PLAN.md:133-136`.
- File is not present under `backend/app/synthesis/` (directory listing); therefore no direct auditable implementation.

## 3) STALE TESTS

1. Fan-out aspect count assertion is stale vs current implementation.
- Code defines 10 aspects: `backend/app/synthesis/chief.py:35-46`.
- Test still asserts 8: `backend/tests/test_chief_fanout.py:225-226`.

2. `test_chief.py` validates legacy tool-construction path, not production fan-out branch.
- Mock session helper is `MagicMock`: `backend/tests/test_chief.py:89-96`.
- Production branch guard checks `isinstance(db_session, AsyncSession)`: `backend/app/synthesis/chief.py:747`.
- Tests then assert legacy tool shapes/counts (`write_section`, `finish`, etc.): `backend/tests/test_chief.py:112-137`.
- Result: high coverage on compat path, weaker guard on production chief path semantics.

## 4) SCHEMA DRIFT

1. `ExplorerProgress.last_explored_at` is written but not read by app logic.
- Column definition: `backend/app/models/evidence.py:263-265`.
- Writes on `finish`: `backend/app/synthesis/explorers/tools.py:1052-1055`.
- No read-site found in app logic outside generic progress payloads.

2. `ExplorerProgress.started_at` is inconsistent across explorer types.
- Column exists: `backend/app/models/evidence.py:255-257`.
- Repo-agent path sets it: `backend/app/synthesis/explorers/repo_agent.py:421-423`, `446-447`.
- Standard explorer path creates progress as `pending` with no `started_at`: `backend/app/synthesis/pipeline.py:413-419`.

3. Migration metadata/order hygiene drift (chain works but is confusing).
- Timestamp inversion in chain: `20260425110000` revises `20260425120000` (`backend/alembic/versions/20260425110000_add_prediction_feedback_memories_MINI_58.py:3-5,15-17`).
- Header/body mismatch in `20260425120000`: docstring says revises two older heads, code uses `down_revision = 20260425100000` (`backend/alembic/versions/20260425120000_add_ai_contamination_verdict_provenance_MINI_208.py:3-5,15-17`).
- Another timestamp inversion: `20260426120000` depends on `20260426200000` (`backend/alembic/versions/20260426120000_unique_explorer_narrative_aspect.py:3-5,14-16`).

## 5) MISSING TESTS FOR HIGH-LEVERAGE PATHS

1. Missing explicit concurrency-safety test for repo fan-out shared-session pattern.
- Parallel fan-out with shared `db_session`: `backend/app/synthesis/explorers/github_explorer.py:218-221,242,266-271,287`.
- Existing integration tests mock behavior and assert invocation, not session-concurrency safety: `backend/tests/integration/test_github_explorer_fanout.py:34-45,109-119,142-149`.

2. Missing pipeline-level assertion that production chief route never regresses back to legacy path.
- Branching logic: `backend/app/synthesis/chief.py:745-753`.
- Current tests disproportionately exercise mock/legacy path (`backend/tests/test_chief.py:89-96,112-137`).

3. `ai_signals` tests are minimal relative to scoring surface.
- Scoring heuristics include multiple additive markers and clipping: `backend/app/synthesis/ai_signals.py:52-71`.
- Tests cover only 3 scenarios: `backend/tests/test_ai_signals.py:4-42`.
- Missing cases: boundary clipping, mixed-marker interactions, and per-marker regression matrix.

4. `save_narrative` tests do not lock chief-vs-explorer limit parity.
- Explorer tool max length is 20000: `backend/app/synthesis/explorers/tools.py:891-892`.
- Chief fan-out local tool max length is 30000: `backend/app/synthesis/chief.py:526-527`.
- Current tests do not enforce intentional divergence rationale.

## 6) CI WORKFLOW DRIFT

1. `preview.yml` declares output from non-existent step.
- Output references `steps.deploy-backend.outputs.url`: `/.github/workflows/preview.yml:25`.
- No `id: deploy-backend` step exists in that workflow.
- This is concrete workflow drift and can mislead dependent jobs/users.

## 7) DEPRECATED ENV VARS

1. Several env vars are read in code but undocumented in `backend/.env.example`.
- `TRUSTED_SERVICE_SECRET` used: `backend/app/core/config.py:52-54`, `backend/app/core/auth.py:96-100`.
- `PROMO_MINI_USERNAME` used: `backend/app/core/config.py:81`, `backend/app/routes/minis.py:188-190`.
- `REPO_AGENT_MAX`, `REPO_AGENT_CONCURRENCY`, `REPO_SIZE_LIMIT_KB` used: `backend/app/synthesis/explorers/repo_agent.py:46-52`.
- `LOGS_DIR` used: `backend/app/core/logging_config.py:10-15`.
- `LLM_CHAT_MAX_TOKENS` used: `backend/app/core/agent.py:47-53`.
- `.env.example` currently ends without these entries: `backend/.env.example:1-67`.

2. Script-only fallback env name likely stale.
- `NEON_URL` fallback in prompt diff script: `backend/scripts/prompt_diff_test.py:328-330`.
- Primary code/docs use `NEON_DATABASE_URL` (`backend/app/core/config.py:26-31`, `backend/.env.example:14-17`).

## 8) ASYNC SESSION MISUSE

1. Confirmed high-risk pattern: same `db_session` shared across parallel repo-agent tasks.
- Shared session capture: `backend/app/synthesis/explorers/github_explorer.py:218-221`.
- Parallel launch: `backend/app/synthesis/explorers/github_explorer.py:242,287`.
- Session passed into each `RepoAgent`: `backend/app/synthesis/explorers/github_explorer.py:266-271`.
- `RepoAgent` stores and reuses passed session for tool wiring: `backend/app/synthesis/explorers/repo_agent.py:305-311,337-343`.
- This matches the “single session into parallel `gather()`” bug class.

2. No equivalent pattern found in top-level pipeline explorer fan-out.
- Pipeline creates one session per top-level explorer before `gather`: `backend/app/synthesis/pipeline.py:1076-1081,1101`.

## TOP 10 QUICK-WIN CLEANUPS (Prioritized)

1. Remove/feature-flag legacy chief path; keep one synthesis contract.
- Scope: M
- Files: `backend/app/synthesis/chief.py`, `backend/app/synthesis/pipeline.py`

2. Fix shared-session parallelism in GitHub repo fan-out (per-repo session).
- Scope: M
- Files: `backend/app/synthesis/explorers/github_explorer.py`, `backend/app/synthesis/explorers/repo_agent.py`

3. Fix stale fan-out test aspect count (`8` -> dynamic/10).
- Scope: S
- Files: `backend/tests/test_chief_fanout.py`

4. Add production-path chief tests using real `AsyncSession` semantics.
- Scope: M
- Files: `backend/tests/test_chief.py`, `backend/tests/test_chief_fanout.py`

5. Resolve prompt instruction conflict (ALWAYS tools vs casual no-tools).
- Scope: M
- Files: `backend/app/synthesis/spirit.py`, `backend/app/routes/chat.py`

6. Fix workflow output drift in Preview CI (`deploy-backend` output reference).
- Scope: S
- Files: `.github/workflows/preview.yml`

7. Normalize Alembic revision metadata/comments and naming chronology.
- Scope: S
- Files: `backend/alembic/versions/20260425110000_*.py`, `20260425120000_*.py`, `20260426120000_*.py`

8. Document active env vars in `.env.example` (or delete dead ones).
- Scope: S
- Files: `backend/.env.example`, `backend/app/core/config.py`

9. Add ai_signals scoring regression matrix tests.
- Scope: M
- Files: `backend/tests/test_ai_signals.py`, `backend/app/synthesis/ai_signals.py`

10. Clarify/align `save_narrative` max-length contract across chief vs explorer tool.
- Scope: S
- Files: `backend/app/synthesis/chief.py`, `backend/app/synthesis/explorers/tools.py`, related tests
