# Bulk + Additive Ingestion Redesign (2026-05-09)

## Executive Summary

The Minis ingestion pipeline currently fetches ~250 items per GitHub user via REST fanout, with per-PR/issue API calls dominating costs. This spike proposes 6 orthogonal improvements (W4.1–W4.6) to achieve **fast + additive + cached ingestion** with single-digit request counts per re-run and 50%+ LLM cost reduction.

**Target state:** Ingest users in <5 API calls (GraphQL bulk + cached evidence), synthesis in <3 LLM calls (multi-task batches), re-runs skip unchanged items entirely.

---

## 1. GraphQL Co-Fetch Surface (W4.1)

### Current REST fanout hotspots (8 call families)

| Hotspot | Current Calls | Items Fetched | GraphQL Collapse |
|---------|---------------|---------------|------------------|
| **PR discussions** | 2/PR × N | comments, reviews | Query node(pr_id) { comments, reviews } |
| **PR details** | 1/PR | status, commit-sha list | Query pullRequests { commits { nodes } } |
| **PR reviews** | 1/PR | review state + timeline | Query node(pr_id) { reviews { nodes { state, createdAt } } } |
| **Issue threads** | 2/issue × M | comments, timeline | Query node(issue_id) { comments, timeline } |
| **Reactions** | N/A (not fetched today) | emoji + user | Query ... { reactions { nodes } } |
| **Repo languages** | 1/repo (fallback) | language breakdown | Query repository { languages { edges } } |
| **Commit details** | 1/commit × C | patch hunks, diffs | Query commits { ... files { patch } } |
| **Gist raw files** | 1/file (fallback) | file content | Query gists { files { text } } (no pagination) |

### Proposed GraphQL query shape (pseudo-schema)

```graphql
query UserPullRequests($owner: String!, $name: String!, $first: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
      edges { node {
        number title createdAt updatedAt author { login }
        commits(first: 100) { edges { node { oid message } } }
        reviews(first: 50) { edges { node { state createdAt } } }
        comments(first: 100) { edges { node { body createdAt author { login } } } }
        reactions(first: 20) { edges { node { content user { login } } } }
      } }
    }
  }
}
```

**Savings estimate:**
- Current: 5 REST calls per PR × 100 PRs = **500 calls**
- Proposed: 1 GraphQL paginated query (PR page 1), fallback pages as needed = **~5 calls** (1 call per ~100 items)
- **Reduction: 500 → 5 = 100× fewer calls for PR-centric users**

### Implementation sketch
1. Create `fetch_pull_requests_graphql()` in `backend/app/ingestion/github.py` mirroring `fetch_user_repos_graphql()`.
2. Replace the per-PR comment/review/inline-comment loops with fields inside the PR node.
3. Keep `gh_request` wrapper for single GraphQL call; it already has retry logic.
4. Fallback to current REST path on `errors` or rate-limit (via feature flag `GITHUB_GRAPHQL_PRS`).
5. Do same for issues, reviews-authored, starred (similar structure).

**Files affected:** `github.py` (add fetch function), `github_http.py` (ensure GraphQL works), `github.py` source plugin (call new function).

---

## 2. Strict Additive Cache (W4.2)

### Current state
- `get_latest_external_ids()` returns set of known item IDs per source type.
- `GitHubSource.fetch_items()` already skips external_ids seen before.
- **Gap:** If PR title/body changes, we re-fetch but don't update—Evidence row stays stale.

### Proposed contract
1. For each Evidence item, compute `content_hash = hash_evidence_content(raw_body, metadata={...})`.
2. On re-fetch: if `external_id` exists AND `hash matches`, skip insert entirely (no upsert churn).
3. If `hash differs`, mark old Evidence as `superseded_at = now()`, insert new row (append-only chain).
4. Query condition in FETCH stage: prefer latest non-superseded row.

### Implementation
- **delta.py:** Add `get_latest_evidence_with_hashes(session, mini_id, source_type) → dict[external_id, hash]`.
- **github.py:** Before converting to EvidenceItem, check hash against existing; skip if match.
- **pipeline.py FETCH stage:** When upserting Evidence, detect hash collision and set `superseded_at`.
- **hashing.py:** Already exists; ensure metadata includes PR number, issue number, commit SHA (external_id proxies).

**Savings:**
- Current re-run: re-write 250 items even if 240 unchanged.
- Proposed: skip write for 240; only write 10 deltas.
- **Reduction: 250 writes → 10 writes = 25× fewer DB operations.**

### Files affected
- `delta.py` (add `get_latest_evidence_with_hashes`)
- `github.py` source plugin (check hash before yielding EvidenceItem)
- `pipeline.py` FETCH stage (supersede logic)
- `hashing.py` (ensure metadata is canonical)

---

## 3. github_archive Auto-Wire (W4.3)

### Current state
- `backend/app/ingestion/github_archive.py` exists as a one-off bulk loader (operator script today).
- Not auto-registered in plugins registry; requires manual operator invocation.

### Proposed behavior
1. Register `github_archive` as an IngestionSource plugin.
2. CLI: `mise run ingest-archive <username> <archive.tar.gz>` or Python `GitHubArchiveSource.fetch_items(...)`.
3. Archive ingestion runs **first**, ingesting 50k+ items (PR/issues/comments/reviews).
4. Live pulse (API + clone) runs **second**, filling gaps (reactions, recent commits, deltas).
5. Reconciliation via `external_id + source_type=github_archive` link to API rows.

### Registry ergonomics
- Move `github_archive.py` → `backend/app/plugins/sources/github_archive.py` (already done).
- In `__init__.py`, import + register: `registry.register(GitHubArchiveSource())`.
- Accept boolean env flag `GITHUB_ARCHIVE_ENABLED=false` (default OFF, opt-in per user).
- CLI wrapper: `scripts/bootstrap_from_archive.py <username> <archive_path>` → calls pipeline with source filter.

**Cost model:**
- Archive parse: ~1 min (local, no API).
- Live pulse: 5–10 API calls (reactions, recent diffs, deltas).
- **Total: ~100× cheaper than full API ingest of 50k items.**

### Files affected
- `github_archive.py` source plugin (ensure IngestionSource interface compliance).
- `plugins/__init__.py` (register).
- `scripts/bootstrap_from_archive.py` (new CLI).
- `pipeline.py` (add source filter so archive + API runs don't collide on external_id).

---

## 4. OpenAI Batch API Plan (W4.4)

### Eligible call sites (latency-flexible)
| Component | Current | Batch Eligible? | Savings |
|-----------|---------|-----------------|---------|
| Explorer agents (8× github, devto, blog, etc.) | streaming chat.completions | **YES** | 50% cost |
| Aspect narrative agents (11× voice, framework, values, etc.) | streaming chat.completions | **YES** | 50% cost |
| Chief synthesizer | streaming (interactive) | **NO** (live chat) | — |
| Chat endpoint | streaming (user waiting) | **NO** (real-time) | — |
| On-PR review comment | streaming (user waiting) | **NO** (live feedback) | — |

### Batch integration shape
1. In `agent.py` (PydanticAI wrapper), add batch mode:
   ```python
   def run_agent(..., use_batch=False):
       if use_batch:
           return await batch_run_agent(...)  # Queue to OpenAI Batch API
       else:
           return await client.messages.create(...)  # Live chat
   ```
2. After pipeline EXPLORE stage, **before** SYNTHESIZE, collect all pending explorers into a single batch.
3. Submit batch via `client.beta.messages.batches.create(requests=[...])`.
4. Poll status (max 24h wait, typical ~1h).
5. Consume results in order, populate Evidence with findings.

### Feature flag
- `USE_OPENAI_BATCH_API=false` (default, safe for dev).
- `BATCH_TIMEOUT_HOURS=24` (max wait before falling back to live calls).

### Cost impact
- 8 explorers × 1000 tokens avg = 8k tokens.
- Batch: 4k tokens cost.
- **Savings: 50% per pipeline run.**

### Files affected
- `core/agent.py` (add batch submission + polling loop).
- `synthesis/pipeline.py` (call explorers with `use_batch=True` in EXPLORE stage).
- `synthesis/chief.py` (if aspect agents go batch, set `use_batch=True`).

---

## 5. Multi-Task-Per-Call Plan (W4.5)

### Current NARRATIVE_ASPECTS flow (chief.py)
```python
NARRATIVE_ASPECTS = (
    "voice_signature",
    "decision_frameworks_in_practice",
    "values_trajectory_over_time",
    "framework_loves_vs_current_focus",
    "temporal_identity",
    "audience_modulation",
    "conflict_and_repair_patterns",
    "technical_aesthetic",
    "philosophical_priors",
    "architecture_worldview",
    "ai_usage_signature",
)
```

**Today:** 11 separate LLM calls, each with ~4k context (findings, quotes, principles), each generating ~1500 words.
**Cost:** 11 calls × 4k = 44k tokens input.

### Proposed: Structured multi-task call
1. Merge 2–3 aspects with compatible grounding (e.g., voice_signature + audience_modulation share register examples).
2. Use a structured output schema:
   ```python
   class AspectNarratives(BaseModel):
       voice_signature: str  # 1500–2500 words
       audience_modulation: str  # 1500–2500 words
       conflicts_repair: str  # 1500–2500 words
   ```
3. Single call with prompt: "Write THREE essays covering voice, audience, conflict patterns" + shared grounding.
4. Unpack into 3 separate ExplorerNarrative rows.

### Groupings (trade-offs vs autonomy)
| Grouping | Aspects | Rationale | Risk |
|----------|---------|-----------|------|
| **Bundle A** | voice_signature + audience_modulation | Both respond to register/context signals | Cross-interference if one dominates |
| **Bundle B** | values_trajectory + framework_loves | Both temporal, shared value signals | Potential repetition |
| **Bundle C** | philosophy + architecture | Both "worldview"-level, shared abstraction | Acceptable risk |
| **Standalone** | conflict_repair, technical_aesthetic, ai_usage, decision_frameworks | Distinct grounding | Can stay single calls |

### Implementation
- Create `save_narrative_batch(aspect: str, narratives: dict[aspect_name, text])` in tools.py.
- In `chief.py`, group aspects before dispatching to LLM.
- Use Pydantic structured output (Claude 4.5 supported).
- **Cost savings: 11 calls → 5–6 calls = ~45% reduction.**

### Files affected
- `synthesis/explorers/tools.py` (add batch save).
- `synthesis/chief.py` (bundle aspects, update prompts).

---

## 6. Profiling Hooks (W4.6)

### What to log per pipeline stage

| Stage | Metric | Log Format | Purpose |
|-------|--------|----------|---------|
| **FETCH** | `(source, items_fetched, requests_made, api_calls_ms, bytes_in)` | `{"stage": "fetch", "source": "github", "items": 250, "requests": 45, "ms": 12000, "bytes": 5242880}` | Identify which source dominates |
| **EXPLORE** | `(explorer, findings_count, calls_count, tokens_in, tokens_out, ms)` | `{"stage": "explore", "explorer": "github_explorer", "findings": 120, "calls": 1, "tokens_in": 4000, "tokens_out": 2500, "ms": 8000}` | Per-explorer efficiency |
| **SYNTHESIZE** | `(aspect, tokens_in, tokens_out, ms, char_count)` | `{"stage": "synthesize", "aspect": "voice_signature", "tokens_in": 3000, "tokens_out": 1800, "ms": 5000, "chars": 8500}` | Which aspects are expensive |
| **Total** | `(mini_id, total_ms, total_tokens_in, total_tokens_out, total_requests)` | `{"mini_id": "...", "total_ms": 35000, "tokens_in": 25000, "tokens_out": 12000, "requests": 52}` | Pipeline-level budget tracking |

### Implementation (5-line sketch per stage)
```python
# In pipeline.py FETCH stage:
fetch_start = time.time()
items = await source.fetch_items(...)
fetch_ms = int((time.time() - fetch_start) * 1000)
logger.info("pipeline_stage", extra={
    "stage": "fetch", "source": source.name, "items": len(items), "ms": fetch_ms
})

# In pipeline.py EXPLORE stage:
for explorer in explorers:
    start_ms = time.time() * 1000
    findings = await explorer.explore(...)
    elapsed = time.time() * 1000 - start_ms
    logger.info("pipeline_stage", extra={
        "stage": "explore", "explorer": explorer.name, "findings": len(findings),
        "tokens_in": findings.tokens_in, "tokens_out": findings.tokens_out, "ms": elapsed
    })
```

### Monitoring dashboard (pseudocode)
```sql
SELECT
    source,
    AVG(requests_made) as avg_requests,
    AVG(ms) as avg_duration,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY requests_made) as p95_requests
FROM pipeline_logs
WHERE stage = 'fetch'
GROUP BY source;
```

This identifies which source fanout persists post-optimization.

### Files affected
- `synthesis/pipeline.py` (add timing + metric logging at stage boundaries).

---

## Priority Order & Ship-This-First Wave

Ranked by **signal-per-effort** (impact per engineering day):

| Rank | Task | Days | Impact | Ship Priority |
|------|------|------|--------|--------------|
| **1** | W4.2 Strict additive cache | 1 | 25× DB writes ↓; zero API change | **SHIP WEEK 1** |
| **2** | W4.6 Profiling hooks | 0.5 | Unblock all other prioritization | **SHIP WEEK 1** |
| **3** | W4.1 GraphQL co-fetch (PRs) | 3 | 100× API calls ↓ (for PR-heavy users) | **SHIP WEEK 2** |
| **4** | W4.3 github_archive auto-wire | 1.5 | Bulk bootstrap (50% cost ↓ vs API) | **SHIP WEEK 2** |
| **5** | W4.4 OpenAI Batch API | 2 | 50% LLM cost ↓; 24h latency OK | **SHIP WEEK 3** |
| **6** | W4.5 Multi-task per call | 2 | 45% LLM calls ↓; autonomy tradeoff | **SHIP WEEK 3** |

### Week 1 deliverable (W4.2 + W4.6)
- [ ] `delta.py` extend with hash-aware `get_latest_evidence_with_hashes()`.
- [ ] `github.py` source plugin: check hash before yielding.
- [ ] `pipeline.py` FETCH: supersede logic.
- [ ] `pipeline.py` all stages: add metric logging.
- [ ] Deploy with feature flag `STRICT_ADDITIVE_CACHE=true`.
- [ ] Measure: 250-item re-run should produce <20 Evidence inserts (if <20 items changed).

### Week 2 deliverable (W4.1 + W4.3)
- [ ] `github.py` add `fetch_pull_requests_graphql()`.
- [ ] `github.py` source plugin: call new function, fallback on error.
- [ ] Deploy with `GITHUB_GRAPHQL_PRS=false` (safe default).
- [ ] `github_archive.py` source plugin: finalize IngestionSource interface.
- [ ] `scripts/bootstrap_from_archive.py` CLI.
- [ ] Measure: per-PR costs drop 5× (still REST fanout on reactions, but main PR surface ✓).

### Week 3 deliverable (W4.4 + W4.5)
- [ ] `core/agent.py` batch submission + polling.
- [ ] `pipeline.py` EXPLORE: submit batch on flag.
- [ ] `explorers/tools.py` batch save support.
- [ ] `chief.py` aspect bundling + structured output.
- [ ] Deploy with `USE_OPENAI_BATCH_API=false` (safe default).
- [ ] Measure: full pipeline (FETCH + EXPLORE + SYNTHESIZE) should cost ~50% less for tokens.

---

## Acceptance Criteria

### W4.2 (additive cache)
- [ ] Re-run on unchanged user produces 0 Evidence inserts (external_id check).
- [ ] Re-run on 10% changed items produces ~10 Evidence inserts, rest superseded.
- [ ] Query behavior: retrievers prefer non-superseded rows; superseded treated as tombstone.

### W4.6 (profiling)
- [ ] Pipeline logs include per-stage timing + request counts.
- [ ] Dashboard query (above) runs without error.
- [ ] Identified: which source (github vs archive) dominates time/requests.

### W4.1 (GraphQL co-fetch)
- [ ] PR comment count matches REST baseline (parity).
- [ ] Request count: 100 PRs should take <10 calls (vs 500 today).

### W4.3 (archive auto-wire)
- [ ] `mise run ingest-archive allie archive.tar.gz` succeeds.
- [ ] Archive Evidence rows carry `source_type=github_archive`.
- [ ] Live pulse (API source) adds deltas without collision.

### W4.4 (Batch API)
- [ ] Explorers submit batch on flag; polling loop runs.
- [ ] Results match live-call baseline (quality parity).
- [ ] Token cost audit shows 50% reduction.

### W4.5 (multi-task)
- [ ] 2 bundled aspects produce 2 separate narratives (unpacked correctly).
- [ ] Char count per aspect matches single-call baseline (quality parity).

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Hash collision (different items, same hash) | Use canonical JSON + SHA-256; collision rate <1/billion. |
| GraphQL schema changes | Keep REST fallback; monitor for `errors` field. |
| Batch API timeout (24h SLA) | Fall back to live call if batch unfinished after 12h. |
| Multi-task aspect confusion | Start with low-autonomy bundles (voice + audience); measure drift. |
| Archive reconciliation failures | Keep archive and API rows separate (`source_type` pin); reconciliation is link-only, not merge. |

---

## Summary & Next Steps

**This week (W4.2 + W4.6):**
- Implement strict additive cache: skip re-writes if hash unchanged.
- Add per-stage profiling to unblock future prioritization.
- Expected outcome: 25× fewer DB writes, clear visibility into cost drivers.

**Next week (W4.1 + W4.3):**
- GraphQL co-fetch for PRs: collapse 500 REST calls → 5 per PR-heavy user.
- Archive auto-wire: enable 50% cheaper bulk bootstrap.
- Expected outcome: 100× fewer API calls for PR-centric evidence, low-cost bulk seeding option.

**Week 3 (W4.4 + W4.5):**
- OpenAI Batch API: 50% LLM cost reduction.
- Multi-task bundling: 45% fewer LLM calls.
- Expected outcome: 50% cheaper synthesis, same quality (parity tested).

**Full redesign outcome:**
- Ingest: ~50 API calls (down from 500+).
- LLM synthesis: ~6 calls (down from 11+).
- Evidence re-write: ~10 rows (down from 250).
- Cost per full run: ~70% reduction.
