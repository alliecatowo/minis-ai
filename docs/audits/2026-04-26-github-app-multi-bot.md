# GitHub App Multi-Bot Readiness Audit — 2026-04-26

## Scope

Full read of `github-app/`:

- Runtime: `app/main.py`, `app/webhooks.py`, `app/review.py`, `app/github_api.py`, `app/review_cycles.py`, `app/outcome_capture.py`, `app/config.py`
- Ops/docs: `README.md`, `Dockerfile`, `Procfile`, `pyproject.toml`
- Live sandbox lane: `scripts/live_sandbox_e2e.py`, `tests/test_live_sandbox_e2e.py`
- Unit tests: `tests/test_webhooks.py`, `tests/test_review.py`, `tests/test_outcome_capture.py`, `tests/test_review_cycles.py`, `tests/conftest.py`

Validation run in this audit:

- `cd github-app && UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
- Result: `126 passed in 1.66s`

## Executive Verdict

**Status: Partially ready for multi-bot operation.**

The app can already post and persist structured mini reviews for multiple reviewers on a PR, handle mention flows, dedupe by `reviewer + head_sha` marker, supersede stale bot reviews, and capture human outcome signals. The remaining risks are mostly production-hardening issues for distributed/high-volume operation, not core logic correctness.

## What Is Working Well

1. Multi-reviewer handling exists in the primary webhook path.
- `handle_pull_request_opened` resolves requested reviewers, fetches each reviewer mini, and posts one review per reviewer mini.
- Per-reviewer author-model inference is context-aware (`author_association` + permission hints).

2. Idempotency and supersede behavior are implemented at reviewer+SHA granularity.
- Hidden marker format: `<!-- minis-review:{reviewer}:{head_sha} -->`.
- Existing-review scan prevents repost on same head SHA.
- Prior bot reviews are dismissed/deleted before posting updated review text.

3. Review output contract discipline is strong.
- `render_review_prediction` enforces prediction-availability contract (`prediction_available`, `mode`, `unavailable_reason`).
- Gated/unavailable mode gives explicit constrained output instead of fabricating stance.
- Inline comments preserve backend-provided suggestion text and framework attribution metadata.

4. Outcome-capture loop is wired end-to-end.
- Reaction/reply signals map to disposition classes and PATCH trusted review-cycle state.
- Ambiguous signals are preserved as `unknown` rather than guessed.
- Issue-key disambiguation avoids false attribution in multi-comment review bodies.

5. Test coverage is broad and focused on behavior.
- Coverage includes reviewer-mode mention flow, idempotency markers, gated mode output, inline suggestions, outcome capture, and helper classification logic.

## Readiness Gaps (Priority Order)

1. Distributed idempotency race risk (highest).
- `_last_posted_sha_cache` is in-memory only.
- Marker checks rely on reading existing reviews before posting; concurrent workers/replicas can still race and double-post for same reviewer/SHA.
- Impact: duplicate bot reviews in multi-instance deploys or burst webhook retries.

2. GitHub API resilience is thin for high-volume fan-out.
- `app/github_api.py` calls have no shared retry/backoff/rate-limit handling.
- Multi-bot fan-out increases API call count per event (diff + files + reviews + permissions + post per reviewer).
- Impact: transient failures/rate limits can drop some reviewer outputs without controlled retry policy.

3. Webhook durability is best-effort only.
- Webhook handlers are fire-and-forget `asyncio.create_task(...)` in-process.
- No external queue, replay, or durable retry if process crashes after 200 response.
- Impact: missed reviews/outcome signals under deploy restarts or runtime faults.

4. Security misconfiguration can silently downgrade protection.
- If `github_webhook_secret` is unset, signature verification is bypassed (dev-mode behavior).
- This is convenient locally but dangerous if accidentally deployed.

5. Bot identity matching is configuration-sensitive.
- Supersede logic depends on `settings.github_bot_login` + body signature.
- Wrong `github_bot_login` can leave stale prior bot reviews undisposed.

## Multi-Bot Behavior Notes

- Team reviewer objects are intentionally skipped in `review_requested` path (only `User`), which is acceptable for current per-human-mini model.
- Mention regex supports hyphenated usernames and suffix-based mini addressing (`@username-mini`).
- Review-cycle external IDs are reviewer-specific (`owner/repo#pr:reviewer`), enabling parallel per-reviewer history.

## Recommended Next Actions

1. Move idempotency to a durable guard keyed by `(installation_id, repo, pr_number, reviewer_login, head_sha)` before posting review.
2. Add retry/backoff + 429 handling for GitHub API client calls (shared helper, bounded retry).
3. Add a small durable job/queue layer (or webhook redelivery reconciliation worker) for post-200 processing reliability.
4. Enforce production startup checks: fail fast when `github_webhook_secret` or `trusted_service_secret` is missing.
5. Add one explicit integration test for concurrent duplicate webhook delivery across reviewer fan-out.

## Overall Assessment

Core multi-bot product behavior is implemented and test-backed. The remaining work is operational hardening for scale/reliability in distributed production conditions.
