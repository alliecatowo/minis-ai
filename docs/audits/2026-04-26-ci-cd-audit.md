# CI/CD Audit — 2026-04-26

## Scope

Audited workflow files under `.github/workflows/`:

- `ci.yml`
- `deploy.yml`
- `preview.yml`
- `db-branching.yml`
- `e2e.yml`
- `fidelity-eval.yml`
- `github-app-live-sandbox-e2e.yml`
- `live-llm-contract.yml`
- `pr-linear-link.yml`

## Workflow Inventory

### `ci.yml`

- Workflow name: `CI`
- Triggers:
  - `pull_request` on `main`
  - `push` on `main`
- Jobs:
  - `frontend`: checkout, setup pnpm + node 22, `pnpm install`, `pnpm lint`
  - `backend`: checkout, setup `uv`, setup Python 3.13, `uv sync`, `ruff`, `pytest`
- Secrets used: none explicitly referenced
- Current state:
  - Provides basic lint + test coverage for frontend/backend.
  - Not connected to any migration or deploy gate.

### `deploy.yml`

- Workflow name: `Deploy`
- Triggers:
  - `push` on `main`
  - `workflow_dispatch`
- Jobs:
  - `deploy-backend`: checkout, setup flyctl, `flyctl deploy --remote-only --wait-timeout 300`
- Secrets used:
  - `FLY_API_TOKEN`
- Current state:
  - Production deploy exists for backend.
  - Not gated by CI completion via `workflow_run`.
  - No migration phase, no smoke phase, no rollback automation.

### `preview.yml`

- Workflow name: `Preview`
- Triggers:
  - `pull_request` types: `labeled`, `closed`
  - `workflow_dispatch` (with `pr_number` input)
- Jobs:
  - `preview`: resolve PR number, create Neon branch, comment preview URLs
  - `cleanup`: delete Neon preview branch on PR close, comment cleanup
- Secrets used:
  - `NEON_API_KEY`
  - `NEON_PROJECT_ID`
- Current state:
  - Handles preview branch lifecycle and PR comments.
  - Uses production backend URL in comment (no isolated preview backend deploy in this workflow).

### `db-branching.yml`

- Workflow name: `Database Branching`
- Triggers:
  - `pull_request` type: `opened`
- Jobs:
  - `setup-db`: setup Python, install `httpx`, run `backend/scripts/neon_branch_setup.py`
- Secrets used:
  - `NEON_API_KEY`
  - `NEON_PROJECT_ID`
  - `NEON_DB_USER` (fallback `neondb_owner`)
  - `NEON_DB_NAME` (fallback `neondb`)
- Current state:
  - Creates PR-scoped Neon branch.
  - Contains placeholder comments for wiring env updates to deploy targets.

### `e2e.yml`

- Workflow name: `e2e`
- Triggers:
  - `workflow_run` of workflow `Preview` (`types: [completed]`)
- Jobs:
  - `playwright`: only when Preview succeeded for pull_request events from same repository; resolves Vercel deployment URL; runs Playwright tests; uploads artifacts
- Secrets used:
  - `GH_TOKEN`
  - `VERCEL_AUTOMATION_BYPASS_SECRET`
- Current state:
  - Provides preview-environment browser test coverage.
  - Not a production deploy smoke gate.

### `fidelity-eval.yml`

- Workflow name: `Fidelity Eval`
- Triggers:
  - `workflow_dispatch`
  - `schedule` (daily cron)
  - `pull_request` (path-scoped)
- Jobs:
  - `eval` non-blocking: decides live-run gating, checks secrets contract, optional backend startup, eval execution, artifacts/cache, PR comment rendering
- Secrets used:
  - `GEMINI_API_KEY`
  - `DATABASE_URL`
  - `SERVICE_JWT_SECRET`
  - `FLY_EVAL_URL`
- Current state:
  - Evaluation/reporting workflow; intentionally non-blocking.
  - Not part of deploy pipeline.

### `github-app-live-sandbox-e2e.yml`

- Workflow name: `GitHub App Live Sandbox E2E`
- Triggers:
  - `workflow_dispatch`
  - `schedule` (daily cron)
- Jobs:
  - `live-sandbox`: install dependencies and run sandbox live E2E script, upload artifact
- Secrets used:
  - `GH_APP_SANDBOX_TOKEN`
  - `GH_APP_SANDBOX_REVIEWER_TOKEN`
  - `GH_APP_SANDBOX_TRUSTED_SERVICE_SECRET`
- Current state:
  - Sandbox integration validation for GitHub App behavior.
  - Not part of production deploy pipeline.

### `live-llm-contract.yml`

- Workflow name: `Live LLM Contract`
- Triggers:
  - `workflow_dispatch`
  - `schedule` (nightly, behind var gate)
- Jobs:
  - `review-predictor`: backend setup and live contract test run
- Secrets used:
  - `GEMINI_API_KEY`
  - `GOOGLE_API_KEY`
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
- Current state:
  - Live provider contract coverage for review predictor.
  - Not part of deploy pipeline.

### `pr-linear-link.yml`

- Workflow name: `PR Linear Link`
- Triggers:
  - `pull_request` opened/edited/reopened/synchronize/ready_for_review
- Jobs:
  - `require-linear-link`: validates canonical repo and `MINI-` issue reference in PR metadata
- Secrets used: none explicitly referenced
- Current state:
  - Policy enforcement workflow.
  - Not related to deploy execution.

## Coverage Gaps (Current State)

1. No automated CD gate from CI success to production deploy via `workflow_run`.
2. No automated Alembic migration execution in production deploy flow.
3. No post-deploy smoke test against production health endpoint.
4. No rollback automation; manual rollback instructions are not surfaced by workflow logic.

## Recommended Change

Add a dedicated `cd.yml` that:

- triggers on `workflow_run` for workflow `CI` and only proceeds when:
  - run conclusion is `success`
  - triggering event is `push`
  - branch is `main`
- executes migration checks + `alembic upgrade head` before deployment
- deploys backend to Fly after successful migration job
- runs post-deploy smoke health check and prints explicit manual rollback guidance on failure
