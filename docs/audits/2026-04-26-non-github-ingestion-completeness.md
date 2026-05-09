# Non-GitHub Ingestion Completeness Audit (2026-04-26)

Scope audited: `claude_code`, `blog`, `hackernews`, `stackoverflow`, `devblog`, `website` sources under `backend/app/plugins/sources/` and corresponding explorers under `backend/app/synthesis/explorers/`.

## Shared storage contract (applies to all six sources)
- `Evidence` rows can store envelope/provenance fields (`source_uri`, `author_id`, `audience_id`, `scope_json`, `raw_context_json`, `provenance_json`, `external_id`, `evidence_date`, `last_fetched_at`, `source_privacy`, etc.) (`backend/app/models/evidence.py:42-77`).
- Pipeline upsert maps `EvidenceItem` fields into those columns and always sets `last_fetched_at`/`content_hash` (`backend/app/synthesis/pipeline.py:370-441`).
- Explorer tools expose `source_privacy` and `provenance_envelope` via `browse_evidence`/`read_item` (`backend/app/synthesis/explorers/tools.py:236-257`, `backend/app/synthesis/explorers/tools.py:618-639`).
- Incremental fetch currently uses only `since_external_ids` (`get_latest_external_ids`) in pipeline fetch (`backend/app/ingestion/delta.py:17-40`, `backend/app/synthesis/pipeline.py:988-1001`). `get_max_last_fetched_at` exists but is not wired in fetch flow (`backend/app/ingestion/delta.py:43-71`, `backend/app/synthesis/pipeline.py:22-23`, `backend/app/synthesis/pipeline.py:988-1001`).

## Source: `claude_code`
- **Fetched now:** one `EvidenceItem` per parsed user turn from JSONL files, with `external_id=session:{session_uuid}#{turn_idx}`, `item_type=session`, `context=private_chat` (`backend/app/plugins/sources/claude_code.py:130-183`).
- **Stored now:** metadata includes `session_uuid`, `turn_idx`, `timestamp`, `project_cwd`, `has_personality`, `has_decision`; privacy is explicitly private (`backend/app/plugins/sources/claude_code.py:174-183`). Evidence envelope fields are available in schema but not populated by this source (inferred from omitted fields in emitted `EvidenceItem` plus nullable defaults) (`backend/app/plugins/base.py:81-97`, `backend/app/plugins/sources/claude_code.py:168-183`).
- **Hard caps/depth:** no explicit file/session cap in active `fetch_items` path (it iterates all collected `.jsonl` files) (`backend/app/plugins/sources/claude_code.py:152-156`, `backend/app/plugins/sources/claude_code.py:579-607`). Helper-only caps exist (`max_files=100`; `_filter_messages` time-bucket sampling) but are not used by active fetch path (inferred) (`backend/app/plugins/sources/claude_code.py:191-237`, `backend/app/plugins/sources/claude_code.py:509-571`, `backend/app/plugins/sources/claude_code.py:156`).
- **Metadata richness:** only turn-level metadata above; no explicit `source_uri`/`author_id`/`audience_id`/`scope`/`raw_context`/`provenance` set by source (inferred) (`backend/app/plugins/sources/claude_code.py:168-183`, `backend/app/plugins/base.py:81-89`).
- **Incremental support:** supports `since_external_ids` skip (`backend/app/plugins/sources/claude_code.py:136`, `backend/app/plugins/sources/claude_code.py:151-164`).
- **Privacy class:** private-by-default source (`backend/app/plugins/sources/claude_code.py:127-129`) and private per item (`backend/app/plugins/sources/claude_code.py:182`).
- **Coverage gaps:** active ingestion only parses `entry.type == user` + `message.role == user`; assistant/system/tool event streams are not ingested (`backend/app/plugins/sources/claude_code.py:628-632`). Tool-result blocks are explicitly skipped in content extraction (`backend/app/plugins/sources/claude_code.py:438-451`).

## Source: `blog`
- **Fetched now:** RSS/Atom feed posts discovered from URL/feed links/common feed paths (`backend/app/plugins/sources/blog.py:131-179`), parsed as RSS/Atom entries (`backend/app/plugins/sources/blog.py:226-335`), yielded as `item_type=post`, `context=blog_post` (`backend/app/plugins/sources/blog.py:115-123`).
- **Stored now:** metadata includes `title`, `date`, `tags`, `link`; privacy public (`backend/app/plugins/sources/blog.py:121-123`).
- **Hard caps/depth:** max 50 posts and 4000 chars/post (`backend/app/plugins/sources/blog.py:37-40`, `backend/app/plugins/sources/blog.py:250-252`, `backend/app/plugins/sources/blog.py:280`, `backend/app/plugins/sources/blog.py:327`).
- **Metadata richness:** parser extracts `author` and `word_count`, but emitted metadata drops both (coverage gap) (`backend/app/plugins/sources/blog.py:272-285`, `backend/app/plugins/sources/blog.py:321-332`, `backend/app/plugins/sources/blog.py:121`). Also does not map URL into `source_uri` field (inferred) (`backend/app/plugins/sources/blog.py:121`, `backend/app/plugins/base.py:81`).
- **Incremental support:** `since_external_ids` check on `blog_post:{slug}` (`backend/app/plugins/sources/blog.py:53-61`, `backend/app/plugins/sources/blog.py:94-96`).
- **Privacy class:** public (`backend/app/plugins/sources/blog.py:122`).
- **Coverage gaps:** no `evidence_date` assignment from parsed date string and no provenance envelope fields populated beyond flat metadata (inferred) (`backend/app/plugins/sources/blog.py:101`, `backend/app/plugins/sources/blog.py:115-123`, `backend/app/plugins/base.py:80-89`).

## Source: `hackernews`
- **Fetched now:** Algolia API comments (`hitsPerPage=100`) and stories (`hitsPerPage=50`) for user (`backend/app/plugins/sources/hackernews.py:99-109`, `backend/app/plugins/sources/hackernews.py:101-103`). Yields `item_type=story` and `item_type=comment` (`backend/app/plugins/sources/hackernews.py:59-67`, `backend/app/plugins/sources/hackernews.py:88-96`).
- **Stored now:** story metadata: `title`,`url`,`points`; comment metadata: `story_title`,`points`; public privacy (`backend/app/plugins/sources/hackernews.py:65-67`, `backend/app/plugins/sources/hackernews.py:94-96`).
- **Hard caps/depth:** API query limits 100 comments / 50 stories per run (explicit) (`backend/app/plugins/sources/hackernews.py:101-103`).
- **Metadata richness:** story `num_comments` is included in content text but not metadata; comment provenance fields (`source_uri`, author ids, scope) not populated (inferred) (`backend/app/plugins/sources/hackernews.py:49-57`, `backend/app/plugins/sources/hackernews.py:65`, `backend/app/plugins/base.py:81-89`).
- **Incremental support:** `since_external_ids` skip on `hn:{objectID}` (`backend/app/plugins/sources/hackernews.py:27-33`, `backend/app/plugins/sources/hackernews.py:43-45`, `backend/app/plugins/sources/hackernews.py:73-75`).
- **Privacy class:** public (`backend/app/plugins/sources/hackernews.py:66`, `backend/app/plugins/sources/hackernews.py:95`).
- **Coverage gaps:** no fetch pagination beyond first API page for either endpoint; no `evidence_date` mapping from HN timestamps; no durable thread/story URI envelope fields (inferred).

## Source: `stackoverflow`
- **Fetched now:** resolves user id then fetches top-voted answers (`pagesize=50`, `sort=votes`, with body) plus batch question titles (`backend/app/plugins/sources/stackoverflow.py:88-140`, `backend/app/plugins/sources/stackoverflow.py:118-126`, `backend/app/plugins/sources/stackoverflow.py:142-163`). Emits `item_type=answer`, `context=stackoverflow_answer` (`backend/app/plugins/sources/stackoverflow.py:72-78`).
- **Stored now:** metadata includes `answer_id`, `question_title`, `tags`, `score`, `is_accepted` (`backend/app/plugins/sources/stackoverflow.py:78-85`).
- **Hard caps/depth:** max 50 answers via `_PAGE_SIZE` (`backend/app/plugins/sources/stackoverflow.py:16`, `backend/app/plugins/sources/stackoverflow.py:125`).
- **Metadata richness:** does not populate source URI/permalink, answer creation date, or envelope provenance fields (inferred) (`backend/app/plugins/sources/stackoverflow.py:72-86`, `backend/app/plugins/base.py:81-89`).
- **Incremental support:** `since_external_ids` check on `so:{answer_id}` (`backend/app/plugins/sources/stackoverflow.py:36-42`, `backend/app/plugins/sources/stackoverflow.py:53-55`).
- **Privacy class:** public (`backend/app/plugins/sources/stackoverflow.py:85`).
- **Coverage gaps:** only top-voted answer slice is ingested (not recency or full history); no question comments or edits; no timestamps for timeline analysis.

## Source: `devblog`
- **Fetched now:** Dev.to article listing paginated until limit, then per-article detail fetch (`backend/app/plugins/sources/devblog.py:95-120`, `backend/app/plugins/sources/devblog.py:122-144`). Emits `item_type=article`, `context=devto_article` (`backend/app/plugins/sources/devblog.py:78-84`). Explorer is mapped via `DevToExplorer` with `source_name="devblog"` (`backend/app/synthesis/explorers/devto_explorer.py:13-17`).
- **Stored now:** metadata includes `article_id`,`title`,`published_at`,`tags`,`reactions` (`backend/app/plugins/sources/devblog.py:84-90`), privacy public (`backend/app/plugins/sources/devblog.py:91-92`).
- **Hard caps/depth:** max 30 articles, excerpt truncation at 1500 chars (`backend/app/plugins/sources/devblog.py:21-23`, `backend/app/plugins/sources/devblog.py:45`, `backend/app/plugins/sources/devblog.py:66-67`, `backend/app/plugins/sources/devblog.py:119`).
- **Metadata richness:** drops `comments_count` from metadata despite extracting it, and does not map article URL/permalink to `source_uri` (inferred) (`backend/app/plugins/sources/devblog.py:64`, `backend/app/plugins/sources/devblog.py:84-90`, `backend/app/plugins/base.py:81`).
- **Incremental support:** `since_external_ids` skip on `devto:{article_id}` (`backend/app/plugins/sources/devblog.py:36-42`, `backend/app/plugins/sources/devblog.py:54-56`).
- **Privacy class:** public (`backend/app/plugins/sources/devblog.py:91`).
- **Coverage gaps:** excerpting truncates long articles; no `evidence_date` datetime mapping; no provenance envelope fields beyond flat metadata.

## Source: `website`
- **Fetched now:** discover pages via sitemap fallback to same-domain internal links, then trafilatura extraction (`backend/app/plugins/sources/website.py:113-157`, `backend/app/plugins/sources/website.py:203-255`). Emits `item_type=page`, `context=website_page` (`backend/app/plugins/sources/website.py:97-103`).
- **Stored now:** metadata includes `title`,`url`; privacy public (`backend/app/plugins/sources/website.py:103-105`).
- **Hard caps/depth:** max 50 pages and 4000 chars/page (`backend/app/plugins/sources/website.py:26-27`, `backend/app/plugins/sources/website.py:52`, `backend/app/plugins/sources/website.py:130`, `backend/app/plugins/sources/website.py:153-154`, `backend/app/plugins/sources/website.py:239`).
- **Metadata richness:** extraction computes `word_count` but emitted metadata drops it; URL is not mapped into `source_uri` envelope field (inferred) (`backend/app/plugins/sources/website.py:240-248`, `backend/app/plugins/sources/website.py:103`, `backend/app/plugins/base.py:81`).
- **Incremental support:** `since_external_ids` skip on `website:{page_slug}` (`backend/app/plugins/sources/website.py:41-49`, `backend/app/plugins/sources/website.py:81-83`).
- **Privacy class:** public (`backend/app/plugins/sources/website.py:104`).
- **Coverage gaps:** no crawl depth semantics beyond URL list cutoff; no page fetch timestamp/evidence_date; provenance envelope fields mostly empty.

## Claude Code Is The Moat: Depth Check
- **Every session transcript or sampling?** Active path iterates all collected JSONL files and all parsed turns (no explicit active cap), but it ingests only user turns (`backend/app/plugins/sources/claude_code.py:152-167`, `backend/app/plugins/sources/claude_code.py:579-607`, `backend/app/plugins/sources/claude_code.py:628-632`).
- **Tool calls + args + outputs captured?** No. Content extraction only keeps `text` blocks and skips tool-result blocks (`backend/app/plugins/sources/claude_code.py:438-451`). Active parser is user-only (`backend/app/plugins/sources/claude_code.py:628-632`).
- **Teammate messages, task notifications, system messages captured?** Not in active ingestion path. Parser filters to user role entries (`backend/app/plugins/sources/claude_code.py:628-632`). A broader conversation parser exists but is not used by `fetch_items` (inferred from call graph) (`backend/app/plugins/sources/claude_code.py:156`, `backend/app/plugins/sources/claude_code.py:377-432`).
- **Conversation timeline captured (pauses/corrections/frustration signals)?** Partial. Turn order and per-turn timestamp are captured (`turn_idx`, `timestamp`) (`backend/app/plugins/sources/claude_code.py:175-178`), but no explicit pause duration/event-type timeline model.
- **File contexts captured (repo/files read/edited)?** Minimal. Only `project_cwd` is recorded (`backend/app/plugins/sources/claude_code.py:178`). No file-level read/edit events are emitted.
- **Artifacts produced (commits/branches/PRs) + linked to GitHub?** Not in current claude_code item schema; emitted metadata has no commit/branch/PR fields and does not set envelope `source_uri`/provenance fields (inferred) (`backend/app/plugins/sources/claude_code.py:174-183`, `backend/app/plugins/base.py:81-89`).

## Sparse-Context User Playbook (GitHub-only users)
1. Build a bootstrap profile package at mini creation time with:
- Profile README + pinned repos (summaries + key architectural decisions).
- Package authorship signals (npm/PyPI ownership, release cadence, changelog voice).
- Conference talk transcripts and long-form talks/podcasts.
- User-pinned "signature work" exhibits (canonical repos/PRs/design docs).
- User-pasted resume/LinkedIn and career timeline notes.
2. Store each as first-class evidence items with full provenance envelope fields (`source_uri`, `scope`, `author_id`, `audience_id`, `raw_context_json`, `provenance_json`) to keep audit-grade traceability (`backend/app/models/evidence.py:58-67`).
3. Prioritize sources that encode explicit tradeoffs (why they rejected X, accepted Y) because framework extraction depends on judgment traces, not only output artifacts.

## Top 12 Implementation Tickets (Prioritized)
1. **(L) MINI-XXX: Claude Code full-event ingestion v2** — ingest user+assistant+tool-use+tool-result+system/task events with typed event schema and timeline sequencing.
2. **(L) MINI-XXX: Claude Code provenance envelope completion** — populate `source_uri`, `scope`, `raw_context_json`, `provenance_json`, repo/file references for each turn.
3. **(M) MINI-XXX: Claude Code artifact linker** — detect commit/branch/PR mentions and cross-link to GitHub evidence via stable IDs.
4. **(M) MINI-XXX: Enable timestamp-cursor incremental fetch** — wire `get_max_last_fetched_at` into source fetch interfaces for non-ID-detectable updates.
5. **(M) MINI-XXX: Blog metadata completeness** — store author/word_count/link as envelope fields and parse `evidence_date`.
6. **(M) MINI-XXX: Website metadata completeness** — store `word_count`, canonical URL in `source_uri`, extraction provenance.
7. **(S) MINI-XXX: Devblog metadata parity** — preserve `comments_count`, canonical URL, and normalized `evidence_date`.
8. **(S) MINI-XXX: HackerNews pagination extension** — fetch beyond first page with controlled depth and rate-safe limits.
9. **(S) MINI-XXX: StackOverflow history mode** — support recency and full-history ingestion modes (not only top-voted 50).
10. **(M) MINI-XXX: Non-GitHub source date normalization** — map source-native timestamps into `evidence_date` across all six sources.
11. **(L) MINI-XXX: New source plugin — package authorship (npm/PyPI)** — ownership + release notes + issue interactions; high leverage for sparse-context users.
12. **(M) MINI-XXX: New source plugin — conference/media transcripts** — ingest talks/interviews as high-signal long-form reasoning evidence.

## Top 3 Highest-Leverage Tickets
1. **Claude Code full-event ingestion v2 (L):** biggest moat multiplier; currently tool-use cognition and assistant context are dropped.
2. **Claude Code provenance/artifact linker (L):** connects private reasoning trace to public outcomes (GitHub), enabling review-grade causal evidence.
3. **Package authorship plugin (L):** strongest sparse-context unlock for GitHub-only users; fills high-signal identity gap quickly.
