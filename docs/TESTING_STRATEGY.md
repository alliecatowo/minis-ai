# Testing Strategy

This document defines the path from stubbed tests to review-grade live confidence
without turning CI into an expensive or flaky external-service harness.

The goal is not "more live tests." The goal is a tiered signal ladder where each
tier catches the failures it is best suited to catch, and live tests are reserved
for provider integration, sandbox installation, and preview behavior that fakes
cannot prove.

## Principles

- Default CI remains deterministic, fast, and cheap.
- Live tests are opt-in except for scheduled and protected-branch gates.
- External calls must have explicit budgets, timeouts, retry limits, and redacted
  logging.
- Recorded fixtures are contracts, not golden truth for model quality.
- No test may depend on private user evidence or unredacted local logs.
- No fallback paths are allowed to silently turn unavailable prediction into
  generic review output.

## Tier 0: Unit Tests With Fakes

Purpose: prove local behavior, schema validation, policy gates, and no-fallback
invariants without network access.

Runs:

- Every PR and push to `main`.
- Local development via `mise run test-unit`.

Allowed dependencies:

- In-memory fakes.
- Static fixtures committed to the repo.
- Monkeypatched LLM/GitHub clients.

Coverage expectations:

- `DISABLE_LLM_CALLS=true` returns an explicit unavailable/gated result where
  the contract requires it.
- Review prediction code emits `prediction_available=false`, `mode="gated"`,
  and a non-empty `unavailable_reason` when LLM invocation is blocked or fails.
- GitHub App formatting preserves unavailability as "prediction unavailable"
  and never posts generic reviewer prose in its place.
- API routes keep status codes, response envelopes, and provenance fields stable.
- Playwright product smoke tests can still use route-level mocked backend data.

Non-goals:

- Provider authentication.
- GitHub webhook delivery.
- Model quality.
- Vercel preview integration.

## Tier 1: Contract Tests With Recorded Fixtures

Purpose: detect drift between our adapters and upstream service contracts without
calling upstream services on every PR.

Runs:

- Every PR for touched adapter/client areas.
- Required before changing GitHub API, LLM adapter, review-prediction envelope,
  or webhook handling code.

Fixture policy:

- Fixtures must be generated from sandbox/test accounts only.
- Fixtures must be normalized before commit: remove tokens, installation IDs
  that are not needed, email addresses, private repo names, raw user evidence,
  volatile timestamps, and request IDs.
- Fixtures should preserve provider shape, status codes, rate-limit headers,
  pagination cursors, and error bodies because those are the actual contract.
- Fixture updates must be reviewable as contract changes, not hidden inside
  broad implementation PRs.

LLM contract fixtures:

- Record request envelopes after prompt assembly with stable redaction for API
  keys and private evidence.
- Record minimal provider responses for success, schema-invalid response,
  rate-limit response, auth failure, and timeout.
- Do not snapshot full natural-language model output as exact truth. Assert
  parseability, required fields, gating behavior, and provenance shape.

GitHub App contract fixtures:

- Record webhook payloads for pull request opened, synchronize, issue comment
  mention, pull request review, review comment, and reaction events.
- Record REST/GraphQL responses for app installation token creation, pull request
  fetch, changed files, review posting, comment posting, and rate-limit failure.
- Assert idempotency keys and duplicate-delivery behavior with replayed payloads.

Replay and recording:

- Replays are default in CI.
- Recording is manual only, for maintainers with sandbox credentials.
- A recording run must write a manifest with command, date, sandbox account,
  upstream API versions, and redaction checklist.

## Tier 2: Live LLM Gated Tests

Purpose: prove that real provider credentials, model routing, schema parsing,
kill switches, and budget controls work together.

Runs:

- `workflow_dispatch` on demand.
- Nightly on `main`.
- Protected-branch pre-merge only for PRs that change LLM invocation,
  review-prediction contracts, model routing, compaction, or fidelity eval code.
- Never on untrusted fork PRs.

Required GitHub Actions secrets:

- `GEMINI_API_KEY` for current default provider coverage.
- Provider-specific optional keys when testing Anthropic/OpenAI routing.
- `LIVE_LLM_TESTS_ENABLED=true` as an explicit environment gate.
- `LIVE_LLM_MAX_USD`, defaulting to a small per-run cap.

Budget and rate-limit controls:

- Use the cheapest model tier that still exercises the real provider path unless
  the changed code is tier-specific.
- Cap total live prompts per run. Recommended initial cap: 3 smoke prompts and
  1 schema-invalid/timeout simulation path.
- Set hard client timeouts and at most one retry for transient provider errors.
- Abort the live job when the estimated spend reaches `LIVE_LLM_MAX_USD`.
- Emit a cost summary as a job annotation/artifact.

Determinism:

- Prompts must be short, stable, and synthetic.
- Assertions must target contract fields and semantic invariants, not exact
  prose.
- Temperature should be zero or the provider's most deterministic setting.
- If a provider response is malformed, the expected result is a gated/unavailable
  contract, not a fallback review.

No-fallback invariant:

- LLM unavailable path: run with `DISABLE_LLM_CALLS=true` or missing test key and
  assert `prediction_available=false`, `mode="gated"`, non-empty
  `unavailable_reason`, and no generated review comments.
- LLM available path: run with the sandbox key and assert
  `prediction_available=true`, `mode="llm"`, schema-valid review fields, and
  provenance/framework fields present when the fixture mini contains framework
  evidence.
- Transition path: force a provider timeout/rate-limit and assert the public API
  and GitHub App output still expose unavailability instead of local smoke or
  generic-review prose.

## Tier 3: GitHub App Sandbox E2E

Purpose: prove webhook delivery, app authentication, installation scoping, pull
request review posting, and no-fallback rendering against a real sandbox repo.

Runs:

- Manual `workflow_dispatch` initially.
- Nightly after the sandbox is stable.
- Protected branch only when GitHub App webhook, auth, review-posting, or review
  prediction integration changes.

Required sandbox resources:

- A dedicated GitHub organization or repository owned by the project.
- A dedicated GitHub App installation with least-privilege permissions.
- Test minis backed by synthetic/public evidence only.
- A preview or staging backend with matching `SERVICE_JWT_SECRET` and database.

Required GitHub Actions secrets:

- `GH_APP_ID`.
- `GH_APP_PRIVATE_KEY` or equivalent PEM secret.
- `GH_APP_WEBHOOK_SECRET`.
- `GH_APP_INSTALLATION_ID`.
- `GH_APP_SANDBOX_REPO`.
- `MINIS_API_URL` for preview/staging.
- `SERVICE_JWT_SECRET` if the app or test driver mints service tokens.

Scenario coverage:

- Open a sandbox PR requesting a reviewer with a mini and assert the app posts a
  structured review prediction.
- Trigger an `@username-mini` comment and assert an on-demand review is posted.
- Run with LLM disabled in staging and assert the app posts an explicit
  unavailable message instead of review prose.
- Replay duplicate webhook deliveries and assert no duplicate review spam.
- Exercise GitHub API secondary rate-limit handling with a simulated or
  low-volume forced path before attempting a live stress case.

Cleanup:

- Close sandbox PRs and delete test branches after each run.
- Keep posted app comments/reviews for traceability unless the run contains a
  secret leak, in which case rotate credentials and delete immediately.
- Never run against production customer repos.

## Tier 4: Playwright And Vercel Preview Testing

Purpose: prove deployed frontend behavior against the preview URL and selected
backend/staging flows.

Current state:

- `e2e/` tests already run against Vercel preview URLs after the Preview workflow.
- Existing specs mostly mock backend API calls through Playwright routing.

Next state:

- Keep mocked Playwright smoke tests on every PR.
- Add a separate preview-live project for flows that require real auth, backend,
  or streaming behavior.
- Run preview-live tests only on manual, nightly, or protected-branch gates until
  they are stable.

Required secrets and env:

- `E2E_BASE_URL` from the Vercel deployment.
- `E2E_LIVE_ENABLED=true` explicit gate.
- Test auth credentials or a preview-only dev auth bypass that cannot be enabled
  in production.
- Preview/staging backend URL and database branch URL when testing live create or
  review flows.

Scenario coverage:

- Landing and navigation smoke with mocked backend on every PR.
- Mini profile and chat streaming against preview/staging on gated runs.
- Create-mini flow against sandbox GitHub data and a disposable database branch.
- Review prediction UI renders both `mode="llm"` and `mode="gated"` states.
- Vercel preview URL resolution failure is reported as infrastructure failure,
  not product failure.

Determinism:

- Use seeded synthetic minis and sandbox repositories.
- Prefer assertions on visible state, contract fields, and event completion over
  arbitrary sleeps.
- Retain traces, screenshots, videos, and network logs for failures, with
  request/response redaction where secrets or private evidence could appear.

## CI Gate Matrix

| Tier | PR default | Manual | Nightly | Protected branch | Blocks merge |
|---|---:|---:|---:|---:|---:|
| Unit with fakes | Yes | Yes | Yes | Yes | Yes |
| Recorded contract fixtures | Yes, when touched | Yes | Yes | Yes | Yes |
| Live LLM gated | No | Yes | Yes | When touched | Only after stabilization |
| GitHub App sandbox e2e | No | Yes | Yes, after stabilization | When touched | Only for app-critical paths |
| Playwright mocked preview | Yes | Yes | Yes | Yes | Yes |
| Playwright preview-live | No | Yes | Yes, after stabilization | When touched | Only after flake budget met |

Initial live jobs should be non-blocking with visible annotations. A live tier can
be promoted to blocking only after 30 consecutive scheduled runs stay within:

- less than 2% infrastructure flake rate,
- no secret redaction failures,
- cost below the configured cap,
- median runtime within the job timeout budget,
- clear owner rotation for triage.

## Secrets And Safety

- Store live credentials only in GitHub Actions secrets or environment-specific
  secret stores.
- Do not expose live secrets to pull requests from forks.
- Use separate sandbox credentials from production credentials.
- Rotate sandbox app keys at least quarterly and after any failed redaction.
- Redact `Authorization`, provider keys, GitHub installation tokens, service
  JWTs, cookies, and private evidence snippets from logs and artifacts.
- Treat fixture recording as privileged. Recording commands should fail closed if
  the target repo/account is not the configured sandbox.

## Follow-Up Implementation Slices

Smallest next tickets:

1. MINI-224: add recorded LLM/GitHub contract fixture harnesses and redaction
   manifest.
2. MINI-221: add live LLM contract tests for review prediction and no-fallback
   paths.
3. MINI-12: add a GitHub App sandbox workflow that opens a disposable PR and
   validates review posting plus unavailable-mode rendering.
4. MINI-13: split Playwright into mocked preview and gated preview-live projects.
5. MINI-11 and MINI-14: keep live-test secret safeguards, budget gates, spend
   annotations, and fidelity scorecards explicit in CI.
6. MINI-219: enforce the no-fallback predictor invariant across review surfaces.

Each slice should ship independently with tests for the harness itself before
expanding scenario count.
