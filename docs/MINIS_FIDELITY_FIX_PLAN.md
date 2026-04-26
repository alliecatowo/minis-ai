# Minis Fidelity Fix Plan — 2026-04-26

> **Authoritative source:** mirrored at `docs/MINIS_FIDELITY_FIX_PLAN.md` in the repo. Repo copy wins for anything codified after PR merges; this Claude plan tracks decisions and rationale across sessions.

## Context

`alliecatowo` mini sounds generic-engineer despite having 1,664 Claude Code sessions (2.8 MB) and 250 GitHub items captured in the prod Neon DB. Every fidelity test scores 4-5/10. The pipeline is producing Wikipedia output instead of personality.

**6 audits (5 codex + 2 haiku) ran in parallel and converged on the same diagnosis: the gold IS there, the rendering pipeline drops it.** Real Neon data shows 87% of extracted quotes are Allie-specific, 321 KB of evidence-backed principles exist, and the Claude Code corpus contains profanity, conviction, frustration markers, and product philosophy. None of it reaches the chat output.

This plan is the structural fix. It is ordered to deliver visible fidelity gain on the *current* stale system_prompt (Phase 1, hours) before re-running pipeline (Phase 4, days).

## Architecture: the user's correct mental model

The pipeline should mirror what we just did in this audit conversation:

```
[evidence in many sources]
        │
   ┌────┴────┐ ─────  parallel agents, one per facet/repo/source ────┐
   │ agent A │  → 1500-word essay (max-token blurb) on aspect X       │
   │ agent B │  → 1500-word essay on aspect Y                         │
   │ agent N │  → 1500-word essay on aspect Z                         │
   └────┬────┘                                                        │
        │                                                             │
   ┌────▼────┐                                                        │
   │ Chief   │ ◄──── reads N aspect-essays + structured findings      │
   │         │       composes soul document, optionally re-dispatches │
   │         │       agents to fill gaps (abductive loop)             │
   └────┬────┘                                                        │
        │                                                             │
   final soul document + structured reasoning model                   │
```

This is NOT what the current pipeline does. Current pipeline: 7 source-explorers run in parallel, each produces atomic structured findings (no essays), chief concatenates. Single pass. No feedback loop. No essay capability.

## Anti-hyperfitting principle (user-stated)

The voice fix is NOT "extract Allie's curse words and inject them as signature_phrases". That produces thin mockery and locks the model into specific phrases. It is also brittle when the next mini doesn't curse.

The right abstraction: extract the **underlying patterns** (register code-switching by audience, escalation cadence, declarative vs hedged stance, verbosity-vs-brevity per context) and let the model generalize. The schema is GENERAL across all minis; the content is specific.

**Concrete rule:** No save_* tool should require knowledge of the mini's specific phrases or behaviors. Tools must be neutral primitives that any developer mini could use. The signal lives in the *narratives* an agent writes, not in pre-defined enum values.

## System prompt architecture (user-stated)

Two distinct prompts, currently conflated as one bag:

### Universal Mini System Prompt (every mini gets this verbatim)
- "You are a mini. You are trying to predict how a specific person would respond — even on inputs they have not seen before."
- "Your goal is to PREDICT this person's behavior, not regurgitate known facts about them."
- Tool usage instructions (search_memories, search_evidence, search_principles, get_my_decision_frameworks, apply_framework, get_voice_signature_essay, etc.)
- Knowledge of personality synthesis primitives (abductive reasoning, frame-stacking, framework ordering, value trajectory)
- Frameworks and techniques for accurately predicting human responses to novel stimuli (e.g. "ask: what's their dominant decision rule for this class of input? what's the second? what's the audience filter?")

### Per-Mini Soul Prompt (what's unique per person)
- "You are Allie. You..."
- Injects: spirit content, decision frameworks (with ordering + trajectory + revisions), voice essays, audience-modulation patterns, conflict-and-repair narratives, technical-aesthetic narrative, etc.
- The actual personality cargo.

Currently these are mashed into one `Mini.system_prompt` blob. Need to split.

## Phase 1 — Surgical fixes (apply today, no pipeline re-run needed)

**REVISED 2026-04-26 after validator rejected the original mutation (-0.89pt regression).**
See `/tmp/minis-audit/11-validator-rejected-phase1.md` for the data.

### Lesson: the validator earned its keep on first run

The original Phase 1 plan would have shipped a fidelity REGRESSION. The "voice suppression" block at chat.py:1019-1029 was actually forcing `apply_framework` grounding — which is what produces confident, evidence-rich opinion responses. Removing it broke the framework-grounding path.

### Revised Phase 1 (what we actually ship)

1. **ADD** register-match block to chat.py — a NEW directive AFTER existing tool-use directives, NOT a replacement. Targets: 'wat', 'lol', short casual inputs.
2. **DROP** max_tokens 16384 → 1500 in agent.py:306, 478 — safe ceiling change. Anthropic auto-clips, so impact is small but symmetric.
3. **SKIP** voice_profile injection (until Phase 2/3 produce real voice signal — current is hollow defaults).
4. **KEEP** chat.py:1019-1042 framework directive intact.
5. **KEEP** chat.py:1001-1018 mandatory tool use intact.
6. **Lint sweep** — single F401 in tests/test_mini_258_rate_limit_fixes.py.

Validation: re-run prompt_diff_test against the revised mutation. Expected: ≥7/7 prompts at original level OR slight gain on casual prompts, no regression on opinion prompts.

## Phase 2 — Schema & contract changes (this week)

Voice profile, knowledge graph, and evidence schemas need to support the architecture. No prompt rewrites yet.

### 2.1 New `save_narrative` tool + `explorer_narratives` table
**Files:** `backend/app/models/evidence.py`, `backend/app/synthesis/explorers/tools.py`, new alembic migration
- New table: `explorer_narratives(id, mini_id, explorer_source, aspect, narrative TEXT, confidence FLOAT, created_at)`
- Index `(mini_id, aspect, created_at)`
- New tool `save_narrative(aspect: str, narrative: str, confidence: float)`
- Aspect enum (8): `voice_signature, decision_frameworks_in_practice, values_trajectory_over_time, audience_modulation, conflict_and_repair_patterns, technical_aesthetic, philosophical_priors, architecture_worldview`
- Each narrative is 800-2500 words. Token budget capped at agent level.

### 2.2 Reasoning edges in knowledge graph
**Files:** `backend/app/models/knowledge.py:23` (RelationType enum), `backend/app/synthesis/explorers/tools.py:794` (save_knowledge_edge)
- Extend `RelationType` with: `rejects_because`, `prefers_over`, `trades_off`, `decides_based_on`, `escalates_when`, `ignores_when`
- Update tool schema enums
- Add `evidence_ids: list[str]` and `reasoning_text: str` (2-3 sentence justification) to save_knowledge_edge

### 2.3 Evidence-grounded findings
**File:** `backend/app/synthesis/explorers/tools.py:607` (save_finding)
- Add `evidence_ids: list[str]`, `support_count: int`, `contradictions: list[str]` (other finding ids that contradict this), `counterevidence_ids: list[str]`
- Move `temporal_signal` from string-prefix to dedicated JSON key

### 2.4 Register-tagged quotes
**Files:** `backend/app/models/evidence.py:172-190` (ExplorerQuote), `backend/app/synthesis/explorers/tools.py:730` (save_quote)
- Add `register_level: str` enum: `casual_unfiltered | casual_filtered | technical_precise | formal_written`
- Agent infers register from source context when calling save_quote
- Critical: NOT a list of curse words — describes the REGISTER, not the literal markers

### 2.5 Split Mini system_prompt → universal + soul
**File:** `backend/app/models/mini.py`, alembic migration
- Add `Mini.soul_prompt` column (the per-mini cargo)
- Existing `Mini.system_prompt` becomes the universal mini prompt (or move to `app/synthesis/spirit.py` as a constant template)
- Chat assembly (`chat.py`) joins them: `UNIVERSAL_MINI_PROMPT + soul_prompt + voice_essay_blocks + tool_directives`

### 2.6 Deprecate cherry-picked voice coefficients

Per the anti-coefficient principle (CLAUDE.md), `save_voice_profile`'s scalar fields (`terseness`, `formality`, `humor_type`, `profanity_tolerance`, `signature_phrases`, `frustration_style`, `disagreement_style`) are cherry-picked from a much larger possible stylometric set without research backing. Replace with:

- Explorers extract voice signal via `save_narrative(aspect="voice_signature", narrative=<essay>)` only.
- `save_voice_profile` tool deprecated. The schema field stays on `Mini` for legacy compatibility but writes are blocked. Reads return `None` after migration N+1.
- Aspect narrative for voice MUST describe: register code-switching by audience, escalation cadence, declarative vs hedged stance, verbosity-vs-brevity per context. NOT a list of phrases.

Files: `backend/app/synthesis/explorers/tools.py` (deprecate save_voice_profile), `backend/app/synthesis/spirit.py` (read voice from narratives, not voice_profile column), explorer prompts.

## Phase 3 — Prompt and synthesis rewrites (this week / next)

Implements the architecture once schemas exist.

### 3.1 Universal Mini Prompt template
**New file:** `backend/app/synthesis/universal_prompt.py`
- Constants for the universal mini prompt: identity, prediction goal, tool list, abductive reasoning instructions
- Used by every mini at chat time, prepended to soul_prompt

The Universal Mini Prompt explicitly tells the model: voice and personality emerge from how the person reasons about novel input, NOT from quoted phrases. The mini's job is to apply the person's framework to a novel situation, in a register and voice consistent with the aspect narratives. Coefficients in the prompt are arbitrary; narratives are the ground truth.

### 3.2 Soul prompt rewrite (replaces current `spirit_content`)
**File:** `backend/app/synthesis/spirit.py`
- Reorder: decision frameworks FIRST, then values trajectory, then audience-modulation, then technical aesthetic, then voice (as an embedded essay, not bullet phrases)
- Inject narratives from `explorer_narratives` table by relevance to message (3-tier sideloading)
- Stop collapsing `decision_order` to single token (line 79); render as ordered checklist

### 3.3 Chief synthesizer rewrite
**File:** `backend/app/synthesis/chief.py`
- Add `get_narratives(aspect?)` tool
- Replace 8-section prose contract with: read N essays + N principles + N quotes → write soul_prompt as derived view of structured reasoning model
- Add "would this sentence be true of 80% of senior engineers? if yes, discard it" rubric
- Allow chief to dispatch a focused second-pass agent if it identifies a gap (`invoke_specialist_explorer(query, hypothesis)` tool)

### 3.4 Per-aspect narrative agents
**New file:** `backend/app/synthesis/aspect_agents.py`
- 8 agents, one per aspect, each writes a single narrative essay via `save_narrative`
- They run AFTER per-source explorers complete (so they have findings/quotes/principles to draw from)
- Run in parallel, but each agent gets read-access to all findings, not just one source's
- Token budget: ~3000 input, ~2500 output per agent

### 3.5 Per-repo essay agent (uses existing local-clone primitives)
**File:** `backend/app/synthesis/explorers/repo_agent.py` (already exists; expand)
- For each top-N repo (clone already exists), agent writes a 1500-word "voice in this repo" + "decision frameworks visible in this repo" essay via save_narrative
- Drives signal density beyond REST API metadata

### 3.6 Claude Code explorer signal_mode upgrade
**File:** `backend/app/synthesis/explorers/claude_code_explorer.py:42`
- Add `signal_mode` guidance (`conflicts_first`, `reversals_first`, `frustrations_first`)
- Currently weakest explorer despite richest source — fix this first within Phase 3

### 3.7 Behavioral context fix verification
**File:** `backend/app/synthesis/behavioral_context.py`
- Commit `8ccc87e` already replaced broken pydantic_ai.Agent with llm_completion()
- Verify with a fresh pipeline run. If still empty, debug the LLM call directly.
- Move contradictions out of summary string into typed `contradictions[]` field (per audit 01)

## Phase 4 — Pipeline architecture (next sprint)

Systemic — only after Phase 1-3 are stable.

### 4.1 GitHub ingestion depth (root-caused)

The 250-item cap is structural. Stacked hard caps in `backend/app/ingestion/github.py`:

| Issue | File:line | Fix |
|---|---|---|
| Reviewed PRs sliced `[:5]` | `github.py:562` | Remove slice; paginate full commenter search |
| Commit search 50 first-page only | `github.py:489, :495` | Paginate via `gh_request` |
| Authored PRs 30 first-page only | `github.py:503, :509` | Paginate via `gh_request` |
| PR discussion/review limited to 15 PRs × 2 pages | `github.py:18-19, :232, :243, :262` | Raise to env-configurable defaults; paginate fully |
| Commit diff hard cap of 20 | `github.py:17, :159` | Raise to 200+ via env var |
| `gh_request` retry helper NOT USED | `github.py:51` direct httpx calls | Route ALL calls through `github_http.py:66` `gh_request` |
| Issues entirely missing | `github.py:507` filters `type:pr` only; `GitHubData` has no issue fields (`:25`) | Add `fetch_user_issues()` querying `/search/issues?q=involves:{user}+type:issue` paginated, plus `/issues/{n}/comments` per issue |
| Reactions never fetched | absent | Add reactions ingestion via REST reactions endpoints (P1) |
| Discussions absent | absent | GraphQL `discussions` connection (P1) |
| Releases absent | absent | `/releases` REST (P2) |
| Diff hunks embedded in review item body | `sources/github.py:561, :459` | New `pr_hunk` evidence type with `parent_external_id` linkage |
| `EvidenceItem` has no `parent_external_id` | `plugins/base.py:75` | Add field; populate on `pr_hunk` and on existing `review` items pointing to owning PR |
| Local git diff enrichment unused | `explorer/clone_manager.py:184`, `repo_tools.py:291` | Use `open_diff` as fallback when REST patch payload is empty/truncated |

**Realistic alliecatowo math after fix:**
- ~500 reviewed PRs × 4 review artifacts avg = 2,000
- ~500 authored PRs/commits × 3 items avg = 1,500
- ~300 issues × 3 items avg = 900
- PR hunks across top repos = 500–2,000
- Reactions/discussions/releases = ~300
- **Total: 5,000–7,000 items, a 20–28x increase over current 250**

Goal: 250 → ~5,000+ items for alliecatowo. PR review comments tied to specific hunks via `parent_external_id` chain. Issue threads with full comment chains. Commits with diff context.

### 4.2 Add abductive feedback loop to EXPLORE
**File:** `backend/app/synthesis/pipeline.py:1036-1206`
- After explorers complete, detect contradictions in findings
- Launch second-round agents with targeted prompts: "Evidence shows X and Y in tension. Re-examine for which is primary."
- Turns EXPLORE into 2-3 pass instead of single-pass

### 4.3 Promote personality agents into the loop
**File:** `backend/app/synthesis/pipeline.py:1300-1377`
- Move `infer_personality_typology`, `infer_behavioral_context`, `infer_motivations` BEFORE chief synthesis
- Have them write narratives (they're already structured agents — just promote them)
- Chief reads their narratives during synthesis, not after

### 4.4 Eval gate in CI
**File:** `.github/workflows/fidelity-eval.yml`
- Run fidelity_test on alliecatowo mini after every synthesis-touching PR
- Block merge if score drops below threshold (start: 6/10, raise as we improve)
- Log score history to track trajectory

## Phase 5 — Anti-hyperfitting hardening

Across the codebase. No specific phase, but a discipline applied to every PR in 1-4.

- No save_* tool may require knowledge of the mini's specific phrases
- Voice extraction asks for register patterns, NOT literal phrases
- "signature_phrases" field deprecated in voice_profile (or repurposed as "*examples* of register, not seed phrases")
- Personality typology framework labels (MBTI, Big Five) gated as optional enrichment, not core synthesis budget

## Verification matrix

| Phase | Test |
|---|---|
| 1 | `mise run dev` → chat with alliecatowo mini using "wat" prompt → expect short casual reply (not 3 paragraphs) |
| 1 | Same chat but ask "what do you think about microservices?" → expect direct opinion grounded in evidence, NOT 4-paragraph network-latency lecture |
| 2 | `uv run alembic upgrade head` → verify new tables/columns present |
| 2 | save_narrative writes a 1500-word row to explorer_narratives |
| 2 | save_knowledge_edge accepts `relation="rejects_because"` without enum error |
| 3 | Re-run pipeline against alliecatowo → fresh `spirit_content` includes structured reasoning model + narrative essays |
| 3 | Fidelity test → ≥7/10 |
| 4 | After GitHub depth fix, re-ingest alliecatowo → evidence count >2000 (vs 250) |
| 4 | abductive loop fires at least once per pipeline run; logged turn count >1 for at least one explorer |
| 4 | CI eval gate blocks a deliberately-bad PR |

## Linear ticket creation

After plan approval, file Linear tickets MINI-260 through MINI-275 (estimate) covering:
- One ticket per Phase 1 fix (5 tickets)
- One ticket per Phase 2 schema change (5 tickets)
- One ticket per Phase 3 prompt rewrite (7 tickets)
- One ticket per Phase 4 architecture change (4 tickets)
- One epic ticket linking all (MINI-260)

## Status

- 2026-04-26 — Plan drafted from 6 parallel audits + 1 pending
- 2026-04-26 — Awaiting GitHub ingestion depth audit (codex agent afa2392e)
- 2026-04-26 — Pending user approval before Phase 1 implementation
