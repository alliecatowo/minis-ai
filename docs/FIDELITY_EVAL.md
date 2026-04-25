# Fidelity Eval — CI Gate & Local Usage

## What it measures

The fidelity eval sends golden-turn prompts to live mini chat endpoints and LLM-judges each response against:

- **Overall score** (1–5): holistic answer quality
- **Voice score**: does it sound like the real person?
- **Factual score**: are project/tech facts correct?
- **Framework score**: does it apply the person's decision patterns?
- **Agreement scorecard** (when a held-out review is present): blocker/comment precision, recall, F1; verdict match

Subjects: `alliecatowo`, `jlongster`, `joshwcomeau`.

## PR comment

When a PR touches `backend/app/synthesis/**`, `backend/eval/**`, `backend/app/review_cycles.py`, or `backend/app/agreement_scorecard.py`, the `Fidelity Eval` workflow posts (or updates) a sticky bot comment.

On ordinary PRs the live eval is **skipped by design** so CI cannot burn LLM keys. The PR comment still renders with an explicit skipped reason and a workflow link. Manual and nightly runs execute the live eval and generate the full scorecard:

- Per-subject score tables
- Delta from the last baseline (≥2 pp change is highlighted)
- Rubric breakdown per turn

The job is **non-blocking** — it will never prevent a merge. A regression surfaces as a visible yellow annotation, not a red gate. Once the eval stabilizes we'll flip `continue-on-error: false`.

## Running locally

```bash
# 1. Start the backend (in a separate terminal)
cd backend
uv run uvicorn app.main:app --reload

# 2. Run the eval
cd backend
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo,jlongster,joshwcomeau \
  --base-url http://localhost:8000 \
  --out eval-report.md

# 3. Compare against a prior run (regression detection)
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo \
  --prior eval-report.json \   # previous run's JSON output
  --out eval-report-new.md
```

The script writes two files side-by-side:
- `eval-report.md` — human-readable Markdown (same content as the PR comment)
- `eval-report.json` — machine-readable; use as `--prior` on the next run

Exit code `2` means a regression > 0.3 overall average points was detected when `--prior` is provided.

## Required secrets (CI)

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Purpose | Required |
|---|---|---|
| `GEMINI_API_KEY` | Judge model + mini LLM | Yes |
| `DATABASE_URL` | PostgreSQL connection for local backend | Yes (unless `FLY_EVAL_URL` set) |
| `SERVICE_JWT_SECRET` | Mint eval bearer tokens; must match backend | Yes (unless `DEV_AUTH_BYPASS=true`) |
| `FLY_EVAL_URL` | Hosted backend URL; skips local backend startup | Optional |

`GITHUB_TOKEN` is injected automatically by Actions and needs no manual configuration.

## CI budget gates

- `pull_request`: comment-only; live provider/database secrets are not injected into the job.
- `workflow_dispatch`: live eval runs only when `run_live=true` and required secrets are present.
- `schedule`: nightly live eval, one worker, 20-minute timeout, concurrency cancellation.
- Missing secrets produce an explicit skipped scorecard with the exact admin action instead of failing later with opaque auth/LLM errors.

## Baseline caching strategy

The workflow caches `eval-baseline.json` under the key `fidelity-eval-baseline-main-<run_id>`, restored by prefix `fidelity-eval-baseline-`. On every scheduled daily run (and on merges to main) the cache is overwritten with the latest report. Live manual/nightly runs restore the most recent baseline and pass it as `--prior` to surface deltas.
