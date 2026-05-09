# GitHub Ingestion Call-Graph and Rate-Cost Audit (2026-04-26)

Scope: `backend/app/ingestion/github.py` and `backend/app/plugins/sources/github.py` only.

## 1) Current call graph from `fetch_github_data()` and `GitHubSource.fetch_items()`

### A. `fetch_github_data(username)` network call graph (current)

```text
fetch_github_data(username)
  -> GET /users/{username}
  -> fetch_user_repos_graphql()                                [1 GraphQL call]
     -> fallback REST if GraphQL fails:
        -> GET /users/{username}/repos (paginated)
        -> for each repo in top N: GET /repos/{owner}/{repo}/languages
  -> search commits: GET /search/commits (paginated)
     -> fetch_commit_diffs(commits[:max])
        -> for each commit: GET /repos/{repo}/commits/{sha}
  -> authored PRs: GET /search/issues?q=author:{username} type:pr (paginated)
     -> fetch_pr_discussions(authored_prs)
        -> per PR: GET /repos/{repo}/issues/{n}/comments
        -> per PR: GET /repos/{repo}/pulls/{n}/comments
     -> fetch_pr_reviews(authored_prs)
        -> per PR: GET /repos/{repo}/pulls/{n}/reviews
     -> fetch_pr_commit_lists(authored_prs)
        -> per PR: GET /repos/{repo}/pulls/{n}/commits
     -> fetch_inline_review_comments_for_prs(authored_prs)
        -> per PR: GET /repos/{repo}/pulls/{n}/comments      [duplicate endpoint family]
  -> GET /users/{username}/events
  -> reviewed PRs: GET /search/issues?q=commenter:{username} type:pr (paginated)
     -> fetch_pr_discussions(reviewed_prs)
     -> fetch_pr_commit_lists(reviewed_prs)
     -> fetch_pr_reviews(reviewed_prs)
  -> fetch_reviews_authored_graphql(username)                  [paged GraphQL]
  -> fetch_starred_repos(username)                             [paginated REST]
  -> fetch_gists_with_files(username)
     -> GET /users/{username}/gists (paginated)
     -> for each gist file lacking inline content: GET raw_url
```

### B. `GitHubSource.fetch_items(...)` dataflow call graph (current)

```text
fetch_items(identifier, mini_id, session, since_external_ids)
  -> resolve since set
  -> _fetch_with_cache(...) or fetch_github_data(...)
  -> build_repo_activity_summary(...)
  -> in-memory loops over each collection:
       commits, commit_diffs, reviews_authored, inline_review_comments,
       starred_repos, gists, pull_requests, pr_commits, pr_review_threads,
       pull_request_reviews, review_comments, issue_comments, issue_threads
  -> build EvidenceItem list (skip if external_id already seen)
  -> _sample_by_recency_windows(...)
  -> _enforce_repo_minimums(...)
  -> yield selected EvidenceItems
```

Key point: `fetch_items()` itself does not make more GitHub API requests once `GitHubData` is loaded; cardinality blow-up is upstream in `fetch_github_data()`.

## 2) Hotspots where request count scales with item cardinality

### Cardinality fanout hotspots

1. Commit detail fanout: `fetch_commit_diffs()` does one REST call per commit (`O(commits)`).
2. PR discussion fanout: `fetch_pr_discussions()` does 2 REST calls per PR (`O(PRs)`).
3. PR review-state fanout: `fetch_pr_reviews()` does 1 REST call per PR (`O(PRs)`).
4. PR commit-list fanout: `fetch_pr_commit_lists()` does 1 REST call per PR (`O(PRs)`).
5. Inline comment fanout duplication: `fetch_inline_review_comments_for_prs()` calls `/pulls/{n}/comments` again after `fetch_pr_discussions()` already hit the same surface.
6. Repo-language fallback fanout: when GraphQL repo query fails, loop calls `/languages` per repo (`O(repos)`).
7. Gist raw file fanout: one raw HTTP call per gist file with missing inline content (`O(gist_files)`).
8. Reviewed-PR path repeats multiple per-PR loops (discussion + commits + reviews), effectively doubling PR-surface fanout for active reviewers.

### Approximate request cost model (today)

Let:
- `R` = repos in REST fallback language loop
- `C` = commits selected for detail fetch
- `P_a` = authored PRs selected
- `P_r` = reviewed-but-not-authored PRs selected
- `Gf` = gist files requiring `raw_url` fetch

Then rough API calls are:

```text
Base fixed calls ~= profile(1) + repos_graphql(1) + events(1) + reviews_authored_graphql(paged>=1)
                 + starred(paged>=1) + gists_list(paged>=1)

Variable calls ~= repo_languages_fallback(R)
                + commit_diffs(C)
                + authored_pr_fanout(5 * P_a)
                + reviewed_pr_fanout(4 * P_r)
                + gist_file_raw(Gf)
                + search pagination overhead
```

The dominant choke points are `C`, `P_a`, and `P_r`.

## 3) What must remain API-sourced vs what should move to local clone mining

### Must remain API-sourced

1. Review conversation surfaces: PR review comments/threads, issue comments on PRs, review state transitions, reactions.
2. Collaboration metadata not in git objects: review approvals/changes-requested timeline, participants, PR state snapshots, stars/watchers, gist metadata.
3. Identity/permission scoped data: profile/org/team membership data, private-scope access checks, permission failures.

### Move to local clone mining (bulk-first)

1. Commit and diff evidence: commit message, author, touched files, patch hunks, stats.
2. PR commit-sha lists (derive from merge-base/range for fetched PR refs, or from locally available refs when clone has enough history).
3. Repo language and code-structure signals (replace per-repo `/languages` fallback fanout with local analysis when clone exists).
4. Historical code evidence breadth (older commits/files) where API search pagination is expensive.

Design rule: API for discussion/collaboration; local clone for code history and patch content.

## 4) Explicit migration plan in 3 stages (safe rollout)

### Stage 1: Observe + guard (no behavior break)

1. Add feature flags:
   - `github_bulk_mode` (default `false`)
   - `github_commit_diff_source` (`api|local|hybrid`, default `api`)
   - `github_include_org_data` (default `false`)
2. Add per-run counters and stop reasons (section 5 contract) without changing evidence schema behavior.
3. Add duplicate-call suppression for `/pulls/{n}/comments` reuse between discussion + inline flows.
4. Keep current output contract stable; local mining runs in shadow mode and emits diagnostics only.

### Stage 2: Hybrid default (local-first for commit/diff)

1. Switch commit/diff evidence generation to local clone mining when clone is available and fresh.
2. API commit-diff fetch becomes fallback-only (`fallback_used` stop-reason when triggered).
3. Keep PR discussion/reviews/issues API-sourced.
4. Add parity checks: compare local vs API commit evidence for a sampled subset before full cutover.

### Stage 3: Bulk-first production default

1. Set `github_commit_diff_source=local` default.
2. Keep targeted API fetch for non-git collaboration surfaces only.
3. Enforce explicit budgets (requests/time) with deterministic stop + resume cursor.
4. Keep API fallback path for edge repos/history gaps, but require explicit telemetry markers and capped retries.

## 5) Stop-reason telemetry contract

### Contract shape

Emit one terminal stop event per source-run and optional intermediate stop events per fetch phase:

```json
{
  "source": "github",
  "phase": "commits|authored_prs|reviewed_prs|gists|org_data",
  "stop_reason": "cursor_complete|rate_budget_exhausted|permission_denied|fallback_used|item_cap_reached|time_budget_exhausted|error",
  "cursor": "opaque-cursor-or-page",
  "requests_made": 0,
  "requests_remaining": 0,
  "items_emitted": 0,
  "items_skipped_since": 0,
  "fallback": {
    "from": "local|api",
    "to": "api|local",
    "reason": "clone_missing|clone_stale|api_403|api_429|schema_gap"
  }
}
```

### Required canonical reasons

1. `cursor_complete`
2. `rate_budget_exhausted`
3. `permission_denied`
4. `fallback_used`

Recommended additional reasons for operability: `item_cap_reached`, `time_budget_exhausted`, `error`.

## 6) Recommended default behavior for org data

Default: **OFF** unless explicit opt-in.

Recommended control contract:

1. Global flag: `github_include_org_data=false` by default.
2. Optional allowlist: `github_org_allowlist=["org-a", "org-b"]`.
3. Runtime behavior when off:
   - skip org/team/membership fetch surfaces entirely,
   - emit stop event with `phase=org_data` and `stop_reason=cursor_complete` + `items_emitted=0`.
4. Runtime behavior when on but unauthorized:
   - emit `permission_denied` with the failing scope.

This keeps default ingestion predictable for individual users, avoids accidental enterprise/org fanout, and contains rate/cost exposure.

---

## Prioritized engineering actions (top 8)

1. Remove duplicate PR-comments API fanout by unifying discussion + inline comment retrieval cache per PR.
2. Introduce stop-reason telemetry contract and persist run-level counters by phase.
3. Add `github_commit_diff_source` mode with `api/local/hybrid` and ship shadow parity checks.
4. Move commit/diff extraction to local clone mining as default in hybrid mode.
5. Add explicit request/time budgets with deterministic `rate_budget_exhausted` and resumable cursors.
6. Keep PR discussion/review-state/issue-thread ingestion API-only, but bound per-phase budgets and expose truncation reasons.
7. Add org-data explicit opt-in flag (`github_include_org_data=false` default) plus allowlist support.
8. Add fallback audit trails (`fallback_used`) that include reason and source transition (`local->api`, `api->local`).
