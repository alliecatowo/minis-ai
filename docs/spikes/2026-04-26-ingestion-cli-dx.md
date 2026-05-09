# Ingestion CLI DX Spike (2026-04-26)

## Implemented (2026-04-26, Batch2-B)

Delivered operator surface (thin wrappers over existing pipeline primitives):

1. `mise run ingest-full <username>`
   - Runs `regen_mini.py --force-github-refresh`.
   - Clears GitHub `ingestion_data` cache rows for the mini, then runs normal regen.
2. `mise run ingest-status <username>`
   - Runs `ingest_status.py` to show mini status, evidence/progress/cache counts, and key timestamps.
   - Supports watch mode: `mise run ingest-status <username> -- --watch --interval 10`.
3. `mise run ingest-quick-check <username>`
   - Runs `ingest_quick_check.py` for lightweight post-ingest pass/fail checks.
4. `mise run regen <username>`
   - Preserved and improved: now emits timestamped stage progress and docs the `--force-github-refresh` path in task description.

Not implemented in this batch:

1. `ingest-resume`
2. `--force-github-reingest` (separate from cache refresh)

## Scope
Map what already exists for ingestion/regeneration workflows and define the minimum robust operator surface for long-running reingestion.

## 1) Current Commands and Gaps

### Current operator commands

| Surface | Command | What it currently does |
|---|---|---|
| `mise` | `mise run regen <username>` | Runs `backend/scripts/regen_mini.py` with `freshness_mode=replace`, sources hardcoded to `["github","claude_code"]`. |
| `mise` | `mise run regen-anthropic <username>` | Same as `regen` but sets `DEFAULT_PROVIDER=anthropic`. |
| `mise` | `mise run fidelity-eval [subjects]` | Runs live eval harness against a running backend. |
| `mise` | `mise run fidelity-test` | Runs quick personality probe script (requires `--mini-id --token` args passed through). |
| `mise` | `mise run prompt-diff` | A/B prompt mutation harness against Neon data. |
| `mise` | `mise run pipeline-replay` | Offline cassette replay test for pipeline agent loop. |

### Major gaps

1. No explicit local ingest lifecycle commands: no first-class `status`, `resume`, or `cancel`.
2. `regen_mini.py` has no `--sources`, `--freshness-mode`, `--run-id`, `--json`, or `--timeout` flags.
3. `--force-github-refresh` only clears `IngestionData` cache rows; it does not clear `Evidence` external IDs, so it does not guarantee a true full reingest.
4. Progress visibility is fragile for long runs:
   1. Local regen only prints start/complete.
   2. Hosted `/minis/{id}/status` uses in-memory queue and a 300s wait timeout; no durable run history stream.
5. No stable operator output contract (no machine-readable run summary/artifact path, inserted/updated/skipped by source at end).

## 2) Why Current Long-Running Workflow Is Fragile

1. Observability is terminal-coupled. If the shell dies, there is no durable run handle to resume output from.
2. Resume semantics are implicit and partial. Re-running `regen` re-enters pipeline, but there is no phase checkpoint/restart control.
3. "Full refresh" is ambiguous. Cache refresh and evidence refresh are conflated, which can cause false confidence about corpus freshness.
4. No standardized timeout/retry wrapper around long jobs, so operator behavior depends on ad hoc shell usage.
5. Progress/state is split across DB status, ephemeral event queue, and logs with no single operator command.

## 3) Minimal Command Set To Add

Keep implementation minimal: reuse existing pipeline primitives, add thin CLI wrappers and one targeted forced-reingest mode.

| Command name | Exact command line | Expected behavior |
|---|---|---|
| `ingest-full` | `cd backend && PYTHONUNBUFFERED=1 PYTHONPATH=. uv run python scripts/regen_mini.py <username> --force-github-refresh` | Force GitHub cache refresh and run regen pipeline with timestamped stage progress. |
| `ingest-resume` | `cd backend && PYTHONPATH=. uv run python scripts/regen_mini.py <username> --resume` | Planned, not implemented in this batch. |
| `ingest-status` | `cd backend && PYTHONUNBUFFERED=1 PYTHONPATH=. uv run python scripts/ingest_status.py <username> --watch --interval 10` | Print mini status + key counts/timestamps; `--watch` tails until terminal state. |
| `ingest-quick-check` | `cd backend && PYTHONUNBUFFERED=1 PYTHONPATH=. uv run python scripts/ingest_quick_check.py <username>` | Lightweight post-regen sanity check (DB-backed, no backend server requirement). |
| `ingest-replay` | `cd backend && MINIS_CASSETTE_MODE=replay MINIS_CASSETTE_RUN_ID=default uv run pytest tests/test_pipeline_replay.py -v` | Deterministic offline pipeline control-plane smoke check. |

Notes:
- `ingest_status.py` and `ingest_quick_check.py` were added as new thin helper scripts.
- `--resume` and `--force-github-reingest` remain follow-up work.

## 4) Recommended Defaults For Long Jobs

1. Runtime guard: wrap long ingest runs with `timeout 60m` by default.
2. Output mode: unbuffered stdout (`PYTHONUNBUFFERED=1`) and timestamped line output.
3. Progress cadence: emit stage heartbeat every 10s and source counters at source completion.
4. Cache refresh options:
   1. Default mode: incremental (`since_external_ids` enabled).
   2. Explicit full mode: `--force-github-reingest` (bypass skip set for GitHub).
5. Failure contract: non-zero exit with stable error code; final summary always printed (success or failure).

## 5) User Flows

### Force full GitHub reingest
1. `mise run ingest-full <username>`
2. `mise run ingest-status <username> --watch`
3. `mise run ingest-quick-check <username>`

### Resume interrupted ingest
1. `mise run ingest-resume <username>`
2. `mise run ingest-status <username> --watch`

### Status only
1. `mise run ingest-status <username>`
2. Optional watch mode for long runs: `mise run ingest-status <username> --watch`

### Quick fidelity check
1. `mise run ingest-quick-check <username>`
2. Run full eval only if quick check looks healthy.

## 6) Primitive vs `mise` Wrapper Decision

| Flow | Use existing CLI primitive directly | Add/keep `mise` wrapper | Decision |
|---|---|---|---|
| Force full GitHub reingest | `regen_mini.py` with new force flag | Yes | Wrapper for consistency and discoverability. |
| Resume | `regen_mini.py` with `--resume` | Yes | Wrapper; operator should not memorize flags. |
| Status | new `ingest_status.py` | Yes | Wrapper; watch/status is frequent and should be short. |
| Quick fidelity check | `run_fidelity_eval.py` existing | Yes | Wrapper with preselected fast flags. |
| Offline replay sanity | existing pytest replay command | Keep existing `pipeline-replay` | Existing wrapper is sufficient. |

## Suggested `mise` task names

1. `ingest-full`
2. `ingest-resume`
3. `ingest-status`
4. `ingest-quick-check`

These task names are now present in `mise.toml` for operator use.
