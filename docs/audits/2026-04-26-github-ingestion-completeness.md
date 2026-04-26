# GitHub Ingestion Completeness Audit (2026-04-26)

Scope: `/home/Allie/develop/minis-hackathon` GitHub ingestion and explorer path.

## Status: FETCHED / PARTIAL / NOT FETCHED table

| Data type | Status | Depth + storage + metadata + incremental audit | Citations |
|---|---|---|---|
| User profile (bio, stars, follows, location, pinned/README) | PARTIAL | Fetches `/users/{username}` profile blob only. Stored only in ingestion cache JSON (`IngestionData`), not emitted as `EvidenceItem` rows. No explicit profile README/pinned extraction. Incremental skip does not apply because no profile evidence rows. | `backend/app/ingestion/github.py:707-710`; `backend/app/plugins/sources/github.py:110-117,167`; `backend/app/plugins/sources/github.py:248-839` |
| Owned repos (every repo vs top-N) | PARTIAL | Fetches owner repos up to cap (`GITHUB_MAX_REPOS`, default 1000), GraphQL path hard-caps first 100. Repo list saved in cache JSON, not per-repo Evidence rows (except language summary + repo metadata attached to other items). Incremental skip applies only to emitted evidence items. | `backend/app/ingestion/github.py:51-55,575-577,599-601,715,730-735`; `backend/app/plugins/sources/github.py:130-131,167-169,840-867`; `backend/app/synthesis/pipeline.py:923-935` |
| Forked repos | PARTIAL | Fork repos can exist in fetched owner repo list (`isFork`/`fork` fields present), but local clone fan-out explicitly excludes forks; no dedicated fork evidence rows. | `backend/app/ingestion/github.py:583,683,733`; `backend/app/synthesis/explorers/github_explorer.py:97-99` |
| Starred repos | NOT FETCHED | No `/users/{username}/starred` or equivalent query path; no star-list evidence item type. | `backend/app/ingestion/github.py:705-842` |
| Watched repos | NOT FETCHED | No `/subscriptions`/watching fetch path and no watch evidence item type. | `backend/app/ingestion/github.py:705-842` |
| All commits with full diffs | PARTIAL | Commits fetched via search with cap (`GITHUB_MAX_COMMITS`, default 2000). Diff details fetched per returned commit; formatter truncates to first 12 files and per-file patch to 2500 chars. Rows are stored as `commit` + `commit_diff` Evidence with provenance/scope/date and incremental external IDs. | `backend/app/ingestion/github.py:52,749-760,378-401`; `backend/app/plugins/sources/github.py:319-380,1049-1071`; `backend/app/synthesis/pipeline.py:341-368,375-411` |
| All PRs authored (body + all review comments + all inline comments with diff hunks) | PARTIAL | Authored PRs fetched from search capped by `GITHUB_MAX_PRS` (default 1000). Body truncated to 8000 chars. Review comments per PR are paginated but optional per-PR caps (`GITHUB_MAX_REVIEW_COMMENTS_PER_PR`, default unlimited). Thread formatter truncates thread comments (20) and diff hunk length (1000 in content, 4000 in metadata). Stored as `pr`, `review`, `pr_review_thread`, `pr_review`. | `backend/app/ingestion/github.py:51,763-781,441-497,56`; `backend/app/plugins/sources/github.py:24-26,382-452,504-573,635-723,1075-1107`; `backend/app/synthesis/pipeline.py:341-398` |
| All PRs reviewed for others | PARTIAL | Finds PRs where subject is commenter (`commenter:{username} type:pr`) and excludes authored PRs. Pulls discussions/review threads/review states for those PRs, capped by `GITHUB_MAX_ISSUES` and `GITHUB_MAX_PRS`. | `backend/app/ingestion/github.py:53,808-842,818-825,831`; `backend/app/plugins/sources/github.py:574-633,635-723,781-838` |
| All issues authored | NOT FETCHED | No `type:issue` authored issue search; issue path is only PR issue-comments/discussion threads. | `backend/app/ingestion/github.py:763-770,468-483,808-815` |
| All issue comments | PARTIAL | Pulls issue comments only for selected PRs (`/repos/{repo}/issues/{number}/comments`) plus recent events feed. Not full authored issue-comment corpus. Stored as `issue_comment` and `issue_thread`. | `backend/app/ingestion/github.py:468-484,787-804`; `backend/app/plugins/sources/github.py:725-838` |
| GitHub Discussions | NOT FETCHED | No Discussions API/GraphQL query and no discussion evidence item types. | `backend/app/ingestion/github.py:572-596,701-842`; `backend/app/plugins/sources/github.py:29-39` |
| Gists | NOT FETCHED | No `/users/{username}/gists` path and no gist item type. | `backend/app/ingestion/github.py:701-842`; `backend/app/plugins/sources/github.py:29-39` |
| Profile README | NOT FETCHED | No profile README endpoint or clone logic for `<username>/<username>` profile repo in ingestion. | `backend/app/ingestion/github.py:701-842`; `backend/app/synthesis/explorers/github_explorer.py:193-206` |
| Code search across repos (TODO/FIXME/HACK) | PARTIAL | There is repo-level `grep_in_repo` capability and repo-agent prompt asks for TODO/FIXME search, but repo fan-out depends on `raw_data.repos_summary.top_repos`; fetch stage currently does not populate `raw_data`, so selection input is empty unless populated elsewhere. | `backend/app/explorer/repo_tools.py:215-261`; `backend/app/synthesis/explorers/repo_agent.py:69-74`; `backend/app/synthesis/pipeline.py:978-988`; `backend/app/synthesis/explorers/github_explorer.py:193-206,232-238` |
| PR reactions / emoji | NOT FETCHED | No reactions endpoints or reaction fields persisted on PR/comment/review evidence metadata. | `backend/app/ingestion/github.py:468-535,551-569`; `backend/app/plugins/sources/github.py:445-450,558-570,705-721,829-836` |
| CHANGELOGs / release notes | PARTIAL | Possible only via local clone/read-file path (if repo fan-out runs). No dedicated release/tag API ingestion. | `backend/app/explorer/repo_tools.py:165-213`; `backend/app/ingestion/github.py:701-842`; `backend/app/synthesis/explorers/github_explorer.py:193-206` |
| Wiki pages | NOT FETCHED | No wiki git clone/API fetch path in ingestion/explorer wiring. | `backend/app/ingestion/github.py:701-842`; `backend/app/synthesis/explorers/repo_agent.py:108-158` |
| GitHub Actions workflows | PARTIAL | Could be read from cloned repo files (e.g., `.github/workflows`) via repo tools; no explicit workflow-run/config API ingestion. | `backend/app/explorer/repo_tools.py:127-163,165-213`; `backend/app/ingestion/github.py:701-842` |
| Branch protection rules | NOT FETCHED | No branch/protection endpoints and no branch-protection evidence type. | `backend/app/ingestion/github.py:701-842`; `backend/app/plugins/sources/github.py:29-39` |
| GraphQL contribution graph | NOT FETCHED | GraphQL is used only for repositories/languages/topics, not contribution calendar. | `backend/app/ingestion/github.py:572-596,599-699` |
| Org memberships / teams | NOT FETCHED | No org/team endpoints or GraphQL membership queries. | `backend/app/ingestion/github.py:701-842` |

Notes on envelope quality and incrementality (applies to fetched rows):
- Fetched GitHub evidence is stored as per-item `Evidence` rows with envelope fields (`source_uri`, `author_id`, `audience_id`, `target_id`, `scope_json`, `raw_*`, `provenance_json`, `external_id`, `evidence_date`, `source_privacy`) and hash/upsert behavior. `backend/app/synthesis/pipeline.py:341-411`; `backend/app/models/evidence.py:42-77`.
- GitHub source marks all emitted items `privacy="public"`; no private classification path in current emitter. `backend/app/plugins/sources/github.py:316,379,451,502,572,633,723,779,838`.
- Incremental fast path exists via `since_external_ids` and external-id upsert, but output sampling can still drop older items by recency ratio. `backend/app/synthesis/pipeline.py:923-935`; `backend/app/plugins/sources/github.py:945-957`.

## Per-PR Depth

- PR title + body + labels + milestone: PARTIAL (`title/body/state` captured; labels/milestone not persisted). `backend/app/plugins/sources/github.py:391-403,445-450`.
- Every review (approval/changes-requested) with body: PARTIAL (review events fetched and stored; global PR cap applies; body may be empty but preserved as explicit empty marker). `backend/app/ingestion/github.py:499-535`; `backend/app/plugins/sources/github.py:585-595,1132-1151`.
- Every inline review comment with file_path + diff_hunk + line numbers: PARTIAL (fetched/threaded; diff hunks and displayed content truncated; optional per-PR comment cap env). `backend/app/ingestion/github.py:485-493,56`; `backend/app/plugins/sources/github.py:650-673,711-717,528,1091-1094`.
- Every issue-thread comment: PARTIAL (per selected PR only; formatter truncates thread content at 30 comments). `backend/app/ingestion/github.py:468-483`; `backend/app/plugins/sources/github.py:1120-1128`.
- Every reaction on every comment: NO (no reactions fetch/persist path). `backend/app/ingestion/github.py:468-535`; `backend/app/plugins/sources/github.py:705-721`.
- The commits in the PR: YES (commit SHA lists ingested and persisted as `pr_commits`). `backend/app/ingestion/github.py:537-569`; `backend/app/plugins/sources/github.py:454-503`.
- Merge state, base/head SHA, merge method: PARTIAL (`state` only in PR evidence; no explicit base/head/merge-method persistence). `backend/app/plugins/sources/github.py:394-400,433-437,445-450`.
- Time-to-merge, time-to-first-review: NO (timestamps exist on rows but no computed metrics captured). `backend/app/plugins/sources/github.py:417-418,588-597`; `backend/app/models/evidence.py:73`.

## Private Repo Path

Current GitHub evidence emits `privacy="public"` for all items, even when authenticated requests are used. `backend/app/plugins/sources/github.py:316,379,451,502,572,633,723,779,838`. A permission-authorized private path can build on existing auth plumbing (`Authorization: Bearer ...`) and clone-token support (`GITHUB_TOKEN` in clone URL) by adding explicit private-scope fetch modes and tagging emitted rows with `source_privacy="private"` plus `source_authorization` metadata already supported in the schema. `backend/app/ingestion/github.py:117-119`; `backend/app/explorer/clone_manager.py:149-151,170-174`; `backend/app/models/evidence.py:47,52-55`.

## Failure Modes

- Rate-limit degradation can silently reduce completeness: helper retries only 3 times, then returns the response; callers often treat rate-limit/422 as `None`/break instead of hard-fail. `backend/app/ingestion/github_http.py:27,82-107,137-139`; `backend/app/ingestion/github.py:125-133,153-160`.
- Pagination/item caps can truncate corpus without explicit audit artifact in evidence: caps are env-driven (`GITHUB_MAX_*`, per-PR comment caps). `backend/app/ingestion/github.py:51-57,169-181,221-228,446-447`.
- Additional recency sampling drops historical/mid items after fetch (50% mid, 25% historical), so stored corpus is intentionally incomplete. `backend/app/plugins/sources/github.py:26-27,945-957`.
- Fork repos are excluded from repo-agent fan-out, reducing code-signal completeness for users who work mainly in forks. `backend/app/synthesis/explorers/github_explorer.py:97-99`.
- Repo code exploration path may be inert because fetch stage no longer sets `IngestionResult.raw_data.repos_summary`, while explorer expects it for fan-out selection. `backend/app/synthesis/pipeline.py:978-988`; `backend/app/synthesis/explorers/github_explorer.py:193-206`.
- Token-scope insufficiency is not preflight-validated; GraphQL failures fall back to REST, but private/org/team-specific data is never requested explicitly. `backend/app/ingestion/github.py:614-616,629-641,649-651,729-735`.
- Empty PR/review bodies are retained (not dropped), so completeness risk is low here. `backend/app/plugins/sources/github.py:393-403,585,1147-1151`.

## MISSING DATA (priority list)

1. PR reactions/emoji and sentiment micro-signals (no reactions ingestion). (`backend/app/ingestion/github.py:468-535,551-569`; `backend/app/plugins/sources/github.py:705-721`)
2. Authored issues corpus (separate from PR issue threads). (`backend/app/ingestion/github.py:763-770,808-815`)
3. Starred/watched repos (taste and attention graph). (`backend/app/ingestion/github.py:705-842`)
4. Org memberships/teams (audience and responsibility context). (`backend/app/ingestion/github.py:701-842`)
5. Discussions/Gists/Profile README. (`backend/app/ingestion/github.py:701-842`; `backend/app/ingestion/github.py:572-596`)
6. Branch protection/workflow/release/wiki artifacts. (`backend/app/ingestion/github.py:701-842`; `backend/app/explorer/repo_tools.py:127-163,165-213`)
7. Contribution graph and longitudinal activity topology. (`backend/app/ingestion/github.py:572-596,599-699`)
8. Private-repo privacy classification pipeline (`private` rows not emitted). (`backend/app/plugins/sources/github.py:316,379,451,502,572,633,723,779,838`)

## PARTIAL DATA (priority list)

1. PR corpus depth is capped + sampled; not guaranteed “all PRs/all comments”. (`backend/app/ingestion/github.py:51,56,446-447`; `backend/app/plugins/sources/github.py:945-957,1095-1107,1120-1128`)
2. Commit diff fidelity is truncated (files/patch length caps). (`backend/app/plugins/sources/github.py:1049-1071`)
3. Repo code content coverage is top-N only (default 5) and currently dependent on missing `raw_data.repos_summary` path. (`backend/app/synthesis/explorers/repo_agent.py:45-47`; `backend/app/synthesis/pipeline.py:978-988`; `backend/app/synthesis/explorers/github_explorer.py:193-206`)
4. Merge analytics (time-to-first-review/time-to-merge) not materialized. (`backend/app/plugins/sources/github.py:417-418,588-597`; `backend/app/models/evidence.py:73`)
5. Issue comments only for selected PR-linked threads, not full issue universe. (`backend/app/ingestion/github.py:468-484,787-804`)

## QUALITY GAPS (priority list)

1. PR evidence metadata omits labels/milestone/base/head SHA/merge method. (`backend/app/plugins/sources/github.py:445-450`)
2. Review/comment evidence omits reactions/audience linkage beyond basic IDs. (`backend/app/plugins/sources/github.py:705-721,829-836`; `backend/app/ingestion/github.py:468-535`)
3. GitHub source hardcodes public privacy labels; no private/public correctness guarantee. (`backend/app/plugins/sources/github.py:316,379,451,502,572,633,723,779,838`)
4. Source-level completeness telemetry is weak (caps/sampling effects not persisted as explicit completeness metadata per run). (`backend/app/ingestion/github.py:51-57`; `backend/app/plugins/sources/github.py:945-957`; `backend/app/synthesis/pipeline.py:982-987`)

## Implementation Tickets (12-18)

### MUST-HAVE-NOW

- `MINI-XXX` Add PR reactions ingestion (S): Fetch and persist reactions for PR bodies, review comments, issue comments.
- `MINI-XXX` Persist PR structural metadata (S): Add labels, milestone, base SHA, head SHA, merge-commit/method fields into PR evidence metadata.
- `MINI-XXX` Emit authored issues corpus (M): Add `author:{user} type:issue` fetch and issue-thread evidence mapping.
- `MINI-XXX` Fix repo fan-out input wiring (S): Populate `IngestionResult.raw_data.repos_summary.top_repos` in fetch stage.
- `MINI-XXX` Private-content privacy tagging (M): Introduce explicit private fetch mode and set `source_privacy/source_authorization` correctly.
- `MINI-XXX` Completeness telemetry row (M): Persist per-source run metrics (caps hit, pages fetched, sampled-out counts).

### FOLLOW-UP

- `MINI-XXX` Add starred repo ingestion (S): Pull starred repos with timestamps and map to evidence items.
- `MINI-XXX` Add watched/subscribed repo ingestion (S): Pull watched repos and watcher intent signal.
- `MINI-XXX` Add org/team membership ingestion (M): Capture org roles/teams for audience context.
- `MINI-XXX` Add profile README ingestion (S): Fetch and store `<username>/<username>` README content.
- `MINI-XXX` Add Discussions ingestion (M): Pull discussions authored/commented with thread metadata.
- `MINI-XXX` Add Gists ingestion (S): Capture gist code/comments and topical signals.

### FUTURE

- `MINI-XXX` Add Actions/workflow artifact ingestion (M): Parse `.github/workflows` + selected workflow metadata.
- `MINI-XXX` Add release/changelog/wiki ingestion (M): Capture release notes and wiki docs per repo.
- `MINI-XXX` Add contribution-graph ingestion (S): Persist GraphQL contribution-calendar summary for temporal modeling.
- `MINI-XXX` Derive PR latency metrics (S): Materialize time-to-first-review/time-to-merge per PR.

## Top 5 Highest-Leverage Tickets

1. Private-content privacy tagging: unlocks authorized private-repo signal while keeping provenance/privacy contract correct (`backend/app/plugins/sources/github.py:316,379,451,502,572,633,723,779,838`; `backend/app/models/evidence.py:47,52-55`).
2. PR reactions ingestion: closes a complete gap in current PR/comment capture (`backend/app/ingestion/github.py:468-535,551-569`; `backend/app/plugins/sources/github.py:705-721`).
3. Persist PR structural metadata: closes major per-PR depth gap (labels/milestone/base/head/merge context) (`backend/app/plugins/sources/github.py:445-450`).
4. Fix repo fan-out input wiring: restores local-clone code-signal path already built but currently underfed (`backend/app/synthesis/explorers/github_explorer.py:193-206`; `backend/app/synthesis/pipeline.py:978-988`).
5. Authored issues corpus: closes missing non-PR authored issue signal (`backend/app/ingestion/github.py:763-770,808-815`).
