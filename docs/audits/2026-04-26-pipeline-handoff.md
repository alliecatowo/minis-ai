# Pipeline Handoff: Minis AI Personality Clone Fidelity

**Date:** 2026-04-26  
**Subject:** alliecatowo mini (`dc94a4f5-bf23-4e13-96bb-9fe63d8e53de`)  
**Status:** BLOCKED — Gemini API quota exhausted, pipeline cannot execute  
**Severity:** CRITICAL — the mini sounds generic, verbose, and nothing like the real person  

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Current State of the Database](#current-state-of-the-database)
4. [What Was Done (Chronological)](#what-was-done)
5. [The Fundamental Problem](#the-fundamental-problem)
6. [Active Blockers](#active-blockers)
7. [Known Bugs Fixed But Not Yet Verified](#known-bugs-fixed-but-not-yet-verified)
8. [Known Bugs NOT Yet Fixed](#known-bugs-not-yet-fixed)
9. [Architecture Problems That Need Systemic Fixes](#architecture-problems-that-need-systemic-fixes)
10. [Key Files Map](#key-files-map)
11. [How to Run the Pipeline](#how-to-run-the-pipeline)
12. [How to Verify Results](#how-to-verify-results)
13. [The User's Vision](#the-users-vision)

---

## Executive Summary

The Minis AI platform ingests developer evidence (GitHub repos, Claude Code sessions, blogs) and produces an AI personality clone that should be **indistinguishable from the real person** in chat. The alliecatowo mini currently fails this test catastrophically — it produces verbose, generic, encyclopedia-like responses that sound nothing like the real Allie, who communicates casually, directly, and with profanity.

The pipeline has 2,796 findings from 1,914 evidence items (250 GitHub + 1,664 Claude Code), but the extraction and synthesis stages have structural flaws that lose personality information and produce generic output. Additionally, the Gemini API key is quota-exhausted, preventing any pipeline execution or verification.

---

## System Architecture

```
Evidence Sources          Pipeline Stages              Output
─────────────            ─────────────────            ───────

GitHub API ──┐                                               
             │                                               
Claude Code ─┼──▶ FETCH ──▶ EXPLORE ──▶ SYNTHESIZE ──▶ Mini Record
   JSONL    │    (ingest    (agents       (chief          (system_prompt
             │     into      browse       synthesizer      = 34K chars
Blog/etc. ──┘     Evidence   evidence     writes soul      of identity
                   table)     via tools,   document)       directives)
                              save findings)
```

### Pipeline Flow (detail)

1. **FETCH**: Source plugins pull data from GitHub API / local JSONL files → insert into `evidence` table
2. **EXPLORE**: Explorer agents (one per source) browse evidence via DB-backed tools, call `save_finding()`, `save_quote()`, `save_knowledge_node()`, `save_voice_profile()`, etc. Findings go to `explorer_findings` table.
3. **SYNTHESIZE**: Chief synthesizer reads all findings, writes a soul document. Personality typology (MBTI, Big Five, DISC, Enneagram) is inferred. Behavioral context analysis runs per context type. Motivations are extracted.
4. **SAVE**: Everything is written to the `minis` row. The `system_prompt` field (34K chars) is what the chat endpoint uses at runtime.

### Tech Stack

- **Backend**: Python FastAPI on Fly.io (`minis-api.fly.dev`)
- **Database**: Neon Postgres (`ep-noisy-king-ai4zxs01-pooler.c-4.us-east-1.aws.neon.tech`)
- **LLM**: Google Gemini 2.5 Flash (via `google-gla:` provider in pydantic_ai v1.82.0)
- **Agent framework**: pydantic_ai Agent with tool calling
- **Frontend**: Next.js (not relevant to this problem)

---

## Current State of the Database

### Mini Record

| Field | Value |
|-------|-------|
| `id` | `dc94a4f5-bf23-4e13-96bb-9fe63d8e53de` |
| `owner_id` | `a9856295-c210-4595-89a6-97aed04e7dd0` |
| `status` | `ready` |
| `spirit_content` | **0 chars (EMPTY)** |
| `system_prompt` | 34,320 chars |
| `metadata_json` | `{"github": {"items_skipped": 197}, "claude_code": {"items_skipped": 1664}}` |

### Evidence Inventory

| Source | Items | Characters | Notes |
|--------|-------|------------|-------|
| github | 250 | ~232K | PR reviews, issues, commits, code changes |
| claude_code | 1,664 | ~481K | Claude Code JSONL session transcripts |
| **Total** | **1,914** | **~713K** | |

### Explorer Findings

| Category | Count | Notes |
|----------|-------|-------|
| knowledge_node | 807 | Too many — mostly technology taxonomy, not reasoning |
| knowledge_edge | 665 | Mostly taxonomic (used_in, related_to), not reasoning |
| values | 263 | Dominated by testing/security mentions |
| communication_style | 200 | Better — but describes formatting, not conversational voice |
| skills | 167 | Technology list |
| principle | 113 | Actionable but many are trivial ("use conventional commits") |
| technical_identity | 88 | |
| personality | 71 | Far too few relative to technical findings |
| problem_solving_style | 64 | |
| voice_profile | 51 | These are the structured voice dimensions |
| memory:* | 160 | Various categories |
| Other | ~73 | decision_making, emotional_patterns, etc. |
| **Total** | **2,796** | |

### What's Broken in the Data

1. **`behavioral_context_json`**: All 5 contexts (code_change, commit_message, general, issue_discussion, private_chat) return `"Analysis unavailable"` — this is 100% empty. The fix was committed (`8ccc87e`) but never successfully re-run.

2. **`personality_typology_json`**: Exists but generic — ENTJ, OCEAN O=1.00/C=1.00/E=0.87/A=0.00/N=0.67. These are plausible but were inferred from findings that are themselves generic.

3. **Knowledge graph**: 807 nodes, 665 edges. BUT: 20/30 top edges are taxonomic (`used_in`, `related_to`). Zero reasoning-pattern edges (like `rejects_because`, `prefers_X_over_Y`). This is a technology stack map, not a reasoning model.

4. **Explorer progress**: Only 171/1,664 claude_code items were explored before the explorer failed. The github explorer completed but produced mostly technical findings.

5. **`spirit_content`** (soul document) is EMPTY — 0 chars. The system_prompt (34K chars) was built from a previous successful run. Every pipeline re-run since has failed to produce a new soul document.

---

## What Was Done (Chronological)

### Session 1: Auth & Infrastructure

- Exchanged GitHub token for Minis JWT, saved to `~/.config/minis/mcp-token`
- Fixed MCP server URL: `minis.fly.dev` (dead) → `minis-api.fly.dev`
- Uploaded 2,133 Claude Code JSONL files to production

### Session 2: Pipeline Crash Fix (PR #191, merged)

- **Root cause**: `run_agent()` doesn't accept `tool_choice_strategy` or `finish_tool_name` kwargs — 4 callers were passing them, causing `TypeError` on every pipeline run
- **Files fixed**: `base.py`, `chief.py` (x2), `repo_agent.py`
- Also added failure_reason capture to `mini.metadata_json`

### Session 3: DB Migrations

- Ran 6 pending alembic migrations against Neon DB

### Session 4: Pipeline Fidelity Overhaul (PR #192, merged)

- Rewrote chief synthesizer prompt — killed "write MORE" mandate, added specificity/dedup/anti-generic guards, capped sections at 500 words
- Fixed chat verbosity — removed mandatory "2-3 paragraphs" and "6-8 search calls"
- Changed signal balance from `conflicts_first` → `high_signal_first`
- Added structured voice profile tool (`save_voice_profile`/`get_voice_profile`)

### Session 5: Comprehensive Audit

- Launched 4 audit agents analyzing soul document, explorer prompts, chief synthesizer, chat system prompt
- Created `docs/audits/2026-04-25-fidelity-audit.md`
- Created 5 Linear docs with findings and fix plans

### Session 6: Fidelity Test Script

- Created `backend/scripts/fidelity_test.py` — sends 7 prompts, scores for generic vs personality markers
- Score: 3.9/10 → 4.9/10 after pipeline overhaul

### Session 7: Additional Fixes (committed, pushed to main)

| Commit | What |
|--------|------|
| `0e8d87c` | Fix `result_type` → `output_type` for pydantic_ai API compat |
| `b870935` | Fix `result.data` → `result.response` for pydantic_ai 1.82 |
| `a66b7d0` | Add retry with backoff for Gemini 429 rate-limit errors |
| `72aefdf` | Increase pydantic_ai Agent retries from 1 to 3 |
| `8ccc87e` | **Fix `behavioral_context.py`**: replace broken `pydantic_ai.Agent` calls with `llm_completion()` — was causing all 5 behavioral contexts to return "Analysis unavailable" |
| `22d17b4` | **Fix `agent.py`**: (1) add `model_settings={"max_tokens": 16384}` to prevent empty model responses that trigger output validation death spiral, (2) filter extra kwargs in `_build_tools` so model hallucinations like `evidence_ids` don't crash `save_finding()` |

### Session 8: Reverted Bad Fixes

- Agent added banned-phrases list to `spirit.py` and regex replacements to `chief.py` — reverted as whack-a-mole hacks

### What Has NOT Been Verified

None of the commits from `8ccc87e` onward have been successfully run through the pipeline. The Gemini API key hit its quota during testing and has been 429'ing ever since. **The pipeline has never run end-to-end with all fixes applied.**

---

## The Fundamental Problem

The user (Allie) describes it as: **"persona + decision frameworks are inseparable — they're one and the same, multiple aspects of a person."**

The current pipeline treats them as separate concerns and loses both. Here's why:

### Problem 1: Explorers Extract Technology, Not Personality

The explorer agents browse evidence using tools like `browse_evidence` and `search_evidence`. When they find a PR review that says:

> "This is fucking garbage, you're not testing the error path. Ship it but add a follow-up ticket."

...the explorer saves:
- `save_finding(category="values", content="Values testing in error paths")`
- `save_finding(category="communication_style", content="Uses direct language in reviews")`

What it SHOULD extract:
- The **curse word** indicates frustration tolerance and informal communication
- The **"ship it but"** pattern indicates a ship-fast-with-follow-up decision framework
- The **specific callout** of error paths indicates deep testing conviction
- The **tone** is directive, not collaborative — indicating a leadership communication pattern

### Problem 2: Findings Are Flat Text, Losing Structure

`save_finding()` dumps everything into a single `content` text field. There's no structured representation of:
- What dimension this finding covers (personality vs values vs style)
- How strong the evidence is (1 mention vs 50 mentions)
- What context it applies in (code review vs casual chat vs architecture decision)
- Whether it contradicts another finding

The result: 263 "values" findings, many duplicating the same "testing is important" observation.

### Problem 3: No Abductive Reasoning

The chief synthesizer should be doing abductive reasoning:
> "Allie advocates for quality AND ships fast. This isn't a contradiction — it's a specific decision framework: quality matters in architecture decisions, but speed matters for iteration. The tension itself is the personality."

Instead, it just concatenates findings into sections.

### Problem 4: Voice Is Context-Dependent

Allie's voice varies by context:
- **PR reviews**: Formal, structured, directive, technical
- **Claude Code sessions**: Casual, direct, cursing, meta-cognitive
- **Friends**: Different again (we don't have this evidence)
- **Slack**: Different again (we don't have this evidence)

The pipeline doesn't distinguish these contexts. The `behavioral_context_json` is supposed to handle this but has been empty ("Analysis unavailable") on every run.

### Problem 5: Single-Signal Dominance

The GitHub evidence is dominated by code review data, which is dominated by testing and security comments. This is because:
1. Code reviews surface disagreements more than agreements
2. The old `conflicts_first` signal mode overweighted these (now fixed to `high_signal_first`)
3. Testing/security are the most common review topics

Result: 99 "testing" mentions and 46 "security" mentions in the soul document, but 2 "fun/joy" mentions, 0 curse words, and 0 humor references.

---

## Active Blockers

### BLOCKER 1: Gemini API Quota Exhausted (CRITICAL)

**Symptom**: Every `agent.run()` call returns 429 RESOURCE_EXHAUSTED. Simple `llm_completion()` calls work (e.g., "Say hello" returns "Hello"), but agent calls with tools fail.

**Root cause**: The `GEMINI_API_KEY` (`AIzaSyB6Mx...ZYlc`) has hit its quota. This appears to be a **free tier** or low-tier key. The repeated pipeline testing over 2 days consumed the budget.

**Evidence**:
- Simple pydantic_ai Agent with no tools: WORKS
- Simple pydantic_ai Agent with 2 tools: WORKS
- pydantic_ai Agent with 13 tools (explorer tools): 429
- This suggests the issue is token consumption per request, not request count

**Fix options**:
1. Get a new/paid Gemini API key (BEST)
2. Switch to a different provider (Anthropic, OpenAI) by changing `DEFAULT_PROVIDER` env var
3. Wait for quota reset (hasn't worked after 16+ hours)

**File to change for provider switch**: `backend/.env` → `DEFAULT_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=sk-...`

### BLOCKER 2: Claude Code Files Not Found Locally

**Symptom**: `Claude Code path not found: data/uploads/a9856295-c210-4595-89a6-97aed04e7dd0/claude_code — yielding nothing`

**Root cause**: The 1,233 JSONL files are on the Fly.io server at that path, but when running locally, the path doesn't exist. However, this doesn't matter — the evidence is already in the DB (1,664 items). The fetch stage just skips (0 items inserted, 0 updated, 1,664 skipped = already cached).

**Impact**: None for pipeline re-runs. Evidence is already in the DB. Only matters for fresh ingestion.

### BLOCKER 3: Explorers Run in Parallel, Doubling Token Consumption

**Symptom**: Both github and claude_code explorers start simultaneously, each making API calls

**Root cause**: `pipeline.py:1092` uses `asyncio.gather(*explorer_tasks)` — parallel execution

**Fix**: Could serialize explorers to reduce peak token usage, but this is a band-aid. The real fix is a proper API key.

---

## Known Bugs Fixed But Not Yet Verified

These commits are pushed to `main` but have NEVER been successfully run through the pipeline:

| Commit | Fix | Expected Impact |
|--------|-----|-----------------|
| `8ccc87e` | `behavioral_context.py`: Replace broken `pydantic_ai.Agent` with `llm_completion()` | All 5 behavioral contexts should now return actual analysis instead of "Analysis unavailable" |
| `22d17b4` | `agent.py`: Add `max_tokens=16384` model_settings | Prevents empty model responses that cause "Exceeded maximum retries for output validation" death spiral |
| `22d17b4` | `agent.py`: Filter kwargs in `_build_tools` | Prevents `TypeError: save_finding() got unexpected keyword argument 'evidence_ids'` when model hallucinates params |
| `72aefdf` | `agent.py`: Increase pydantic_ai retries from 1 to 3 | More tolerance for transient failures |

---

## Known Bugs NOT Yet Fixed

### BUG 1: Explorer Output Validation Death Spiral (PARTIALLY FIXED)

The `max_tokens` fix (`22d17b4`) addresses one cause (empty responses due to no token budget). But pydantic_ai v1.82's `CallToolsNode` also triggers retries when the model returns only thinking tokens with no text or tool calls. This can still happen if:
- Gemini's thinking budget consumes all output tokens
- The model gets confused after conversation compaction (40 messages → summarize to 10)

**File**: `backend/app/core/agent.py`
**Status**: Mitigated but not eliminated

### BUG 2: Knowledge Graph Is a Technology Taxonomy, Not a Reasoning Model

807 nodes, 665 edges — but they're things like "Rust → used_in → Cranelift" and "TypeScript → related_to → React". What's missing:
- `rejects_because` edges ("Allie rejects microservices because operational complexity")
- `prefers_over` edges ("prefers monorepos over polyrepos")
- `trades_off` edges ("ships fast but follows up with tests")
- `decides_based_on` edges ("chooses technology based on ecosystem maturity, not hype")

**Files**: `backend/app/synthesis/explorers/tools.py` (edge types), explorer prompts
**Status**: Not started

### BUG 3: No Deduplication of Findings

"testing is important" appears as 5+ separate findings. The chief synthesizer gets all of them and doesn't deduplicate, so the soul document has 99 testing mentions.

**Files**: `backend/app/synthesis/chief.py`
**Status**: Partially addressed in PR #192 (added dedup instruction to prompt) but not verified

### BUG 4: `save_finding()` Loses Context

Findings are saved with just `category`, `content`, `confidence`. There's no:
- `evidence_ids` (which evidence items support this finding)
- `context` (code review vs casual chat vs architecture decision)
- `contradicts` (does this finding contradict another?)
- `strength` (how many times was this observed vs one-off?)

The `save_principle` tool has richer schema (trigger, action, value, intensity, evidence_ids) but `save_finding` doesn't.

**Files**: `backend/app/synthesis/explorers/tools.py:586-610`
**Status**: Not started

---

## Architecture Problems That Need Systemic Fixes

### Problem A: Single-Pass Exploration

The explorers run once, browse evidence, and save findings. There's no:
1. **Abductive reasoning loop** — "I noticed X and Y. Let me search for evidence that contradicts or explains this tension."
2. **Iterative deepening** — "I found strong evidence for testing values. Let me look harder for communication style evidence since that's underrepresented."
3. **Cross-source correlation** — "GitHub says formal, Claude Code says casual. These are the same person. What's the context-dependent pattern?"

The user's original vision was "8-10 agents, each able to spawn agents, ingesting every aspect of personality, abductive reasoning loop of synthesizing claims."

### Problem B: Chief Synthesizer Is a Concatenator

The chief synthesizer receives all findings and writes sections. It doesn't:
1. Identify tensions between findings and resolve them
2. Weight findings by evidence strength (1 mention vs 50 mentions)
3. Prioritize personality/voice findings over technical findings
4. Produce a reasoning model ("Allie does X because Y")

### Problem C: No Feedback Loop From Chat to Pipeline

The fidelity test script exists but isn't integrated into the pipeline. There's no:
1. Automated quality gate ("does the chat response pass the personality test?")
2. Iterative refinement based on chat output quality
3. A/B testing of different prompt strategies

### Problem D: Evidence Browsing Is Inefficient

The explorer agents browse evidence page by page (20 items per page). With 1,664 claude_code items, that's 83 pages. The agent may run out of turns before seeing the most valuable evidence. The `signal_mode` parameter helps (high_signal_first, conflicts_first, etc.) but the agent doesn't know which signal modes to use for which personality dimensions.

---

## Key Files Map

| File | What It Does | Recent Changes | Status |
|------|-------------|----------------|--------|
| `backend/app/synthesis/pipeline.py` | Main pipeline orchestration: FETCH → EXPLORE → SYNTHESIZE → SAVE | Error capture, kwargs fix | Stable |
| `backend/app/synthesis/chief.py` | Chief synthesizer — writes soul document from explorer findings | Prompt rewrite PR#192 | Needs re-run |
| `backend/app/synthesis/spirit.py` | Builds chat system prompt from soul doc + memory + profile | Chat verbosity fix PR#192 | Needs re-run |
| `backend/app/synthesis/explorers/base.py` | Base explorer class, runs agent loop | kwargs fix PR#191 | Stable |
| `backend/app/synthesis/explorers/github_explorer.py` | GitHub evidence explorer | Signal balance fix PR#192 | Needs re-run |
| `backend/app/synthesis/explorers/claude_code_explorer.py` | Claude Code session explorer | **NOT MODIFIED** | Needs prompt rewrite |
| `backend/app/synthesis/explorers/tools.py` | Explorer tools: save_finding, browse_evidence, save_voice_profile, etc. | Voice profile added PR#192 | Stable |
| `backend/app/synthesis/behavioral_context.py` | Context-specific behavior analysis | **FIXED** (llm_completion) commit `8ccc87e` | **Needs re-run** |
| `backend/app/synthesis/personality.py` | MBTI, Big Five, DISC, Enneagram inference | Not modified | Works |
| `backend/app/synthesis/motivations.py` | Motivation extraction | Not modified | Works |
| `backend/app/core/agent.py` | LLM agent wrapper: run_agent, run_agent_streaming | **FIXED** (max_tokens, kwargs filter) commit `22d17b4` | **Needs re-run** |
| `backend/app/core/llm.py` | Simple LLM completion wrapper | Not modified | Works |
| `backend/app/core/models.py` | Model tier system (fast/standard/thinking) | Not modified | Works |
| `backend/app/core/compaction.py` | Conversation compaction for long agent runs | Not modified | Works |
| `backend/app/routes/chat.py` | Chat endpoint — appends tool_use_directive | Verbosity fix PR#192 | Needs re-run |
| `backend/app/plugins/sources/claude_code.py` | Claude Code JSONL ingestion source | Not modified | Works |
| `backend/app/plugins/sources/github.py` | GitHub API ingestion source | Not modified | Works |
| `backend/scripts/fidelity_test.py` | Before/after fidelity test (7 prompts, personality scoring) | New | Works |
| `docs/audits/2026-04-25-fidelity-audit.md` | Full audit findings | New | Reference |

---

## How to Run the Pipeline

### Prerequisites

1. Gemini API key must have quota (or switch provider — see BLOCKER 1)
2. `backend/.env` must have `GEMINI_API_KEY` and `NEON_DATABASE_URL`

### Run Locally (Recommended for Iteration)

```bash
cd /home/Allie/develop/minis-hackathon/backend

# Run with both sources
uv run python -c "
import asyncio, logging, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s', stream=sys.stdout)
for lib in ['httpx','httpcore','pydantic_ai','google','grpc','urllib3','aiosqlite','sqlalchemy.engine']:
    logging.getLogger(lib).setLevel(logging.WARNING)
from dotenv import load_dotenv; load_dotenv()
from app.db import async_session
from app.plugins.loader import load_plugins
from app.synthesis.pipeline import run_pipeline
load_plugins()
asyncio.run(run_pipeline(
    'alliecatowo', async_session,
    sources=['github', 'claude_code'],
    owner_id='a9856295-c210-4595-89a6-97aed04e7dd0',
    mini_id='dc94a4f5-bf23-4e13-96bb-9fe63d8e53de',
))
"
```

### Run via API (Production)

```bash
# Using the CLI
python backend/cli.py create alliecatowo --source github --source claude_code --wait

# Or via curl
curl -X POST https://minis-api.fly.dev/api/minis \
  -H "Authorization: Bearer $MINIS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "alliecatowo", "sources": ["github", "claude_code"]}'
```

### Switch Provider (If Gemini Quota Is Dead)

Add to `backend/.env`:
```
DEFAULT_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Or:
```
DEFAULT_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

---

## How to Verify Results

### Fidelity Test

```bash
cd /home/Allie/develop/minis-hackathon/backend
MINIS_TOKEN=$(cat ~/.config/minis/mcp-token) uv run python scripts/fidelity_test.py \
  --mini-id dc94a4f5-bf23-4e13-96bb-9fe63d8e53de \
  --token "$MINIS_TOKEN"
```

This sends 7 personality-probing prompts and scores responses:
- **8+**: Authentic, opinionated, sounds like the real person
- **6+**: Decent personality showing through
- **4+**: Mixed, some generic filler
- **2+**: Verbose, generic, no personality
- **Current score**: ~4.9/10

### Manual Check Queries

```sql
-- Check soul document
SELECT length(spirit_content), length(system_prompt), status FROM minis WHERE id = 'dc94a4f5-bf23-4e13-96bb-9fe63d8e53de';

-- Check behavioral contexts (should NOT be "Analysis unavailable")
SELECT jsonb_path_query(behavioral_context_json, '$.contexts[*].summary') FROM minis WHERE id = 'dc94a4f5-bf23-4e13-96bb-9fe63d8e53de';

-- Check findings distribution
SELECT source_type, category, count(*) FROM explorer_findings WHERE mini_id = 'dc94a4f5-bf23-4e13-96bb-9fe63d8e53de' GROUP BY source_type, category ORDER BY count(*) DESC;

-- Check explorer progress
SELECT source_type, total_items, explored_items, findings_count, status FROM explorer_progress WHERE mini_id = 'dc94a4f5-bf23-4e13-96bb-9fe63d8e53de';
```

---

## The User's Vision

These are direct quotes from the user about what the product should be:

> "persona + decision frameworks are inseparable — they're one and the same, multiple aspects of a person"

> "ship fast move fast and break things, as soon as you get signal or start deciding to actually take it from experiment to real code, that's when you architect"

> "my voice in PR reviews is obviously different than I talk to AIs, is different than I talk to friends, is different than I talk on Slack"

> The original plan had "8 to 10 agents, each able to spawn agents, ingesting every aspect of my personality, abductive reasoning loop of synthesizing claims"

> "I want it to sound like me. Not like a fucking Wikipedia article about me."

---

## Immediate Next Steps (Priority Order)

1. **Fix the API quota problem** — get a paid Gemini key, or switch to Anthropic/OpenAI. Without this, nothing else can be tested.

2. **Run the pipeline with all fixes applied** — the commits from `8ccc87e` and `22d17b4` have never been verified. Run it and check:
   - Do explorers complete with findings? (tokens_in > 0, tokens_out > 0)
   - Do behavioral contexts return actual analysis?
   - Does the soul document get written? (spirit_content > 0)

3. **Run fidelity test** — check if score improves from 4.9/10

4. **Fix the claude_code explorer prompt** — it's the richest evidence source (1,664 items, 481K chars of casual Allie-with-AI conversations) but has never been modified. It needs personality extraction instructions similar to what was done for github_explorer in PR#192.

5. **Add structured findings** — extend `save_finding()` with `evidence_ids`, `context`, `contradicts` fields so the chief synthesizer can do actual reasoning instead of text concatenation.

6. **Implement abductive reasoning in chief synthesizer** — currently it concatenates findings into sections. It needs to identify tensions, resolve contradictions, and produce a reasoning model.

7. **Fix deduplication** — "testing is important" should be one strong finding, not 5 separate ones.

---

## Key Credentials & URLs

| Resource | Value |
|----------|-------|
| Neon DB | `postgresql://neondb_owner:npg_kW1UAJjE6ING@ep-noisy-king-ai4zxs01-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require` |
| Backend API | `https://minis-api.fly.dev` |
| Mini ID | `dc94a4f5-bf23-4e13-96bb-9fe63d8e53de` |
| Owner ID | `a9856295-c210-4595-89a6-97aed04e7dd0` |
| Auth token | `~/.config/minis/mcp-token` |
| Gemini API Key | `AIzaSyB6Mx...ZYlc` (in `backend/.env` as both `GEMINI_API_KEY` and `GOOGLE_API_KEY`) |
| Fly machine | `683696eb157318` on app `minis-api` |
| Repo | `alliecatowo/minis-ai` (canonical) |
