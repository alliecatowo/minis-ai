# GitHub Hybrid Bootstrap + Live Pulse (Spike)

## Objective
Use GitHub migration archive export as high-volume bootstrap, then keep minis fresh with incremental live ingestion.

## Architecture
- Bootstrap (async heavy): migration export/archive -> parse -> normalize -> append-only Evidence (`source_type=github_archive`).
- Live pulse (continuous light): API + selective clone ingestion for deltas and archive gaps.
- Reconciliation: link archive/live equivalents without deleting rows; retrieval can prefer best-linked row.

## Onboarding Flow
State machine:
1. `queued`
2. `running/exporting`
3. `running/downloading`
4. `running/parsing`
5. `running/normalizing`
6. `running/reconciling`
7. `ready` (or `failed`/`stopped`)

Status UX:
- Keep mini in `processing` until ready.
- Emit durable phase updates with counts and coarse ETA.

## Data Contract
- Append-only evidence only.
- Archive rows carry provenance: migration id, archive hash, snapshot timestamp, archive member/family.
- Live rows keep API/cursor provenance.
- Reconcile via link metadata; never destructive rewrite.

## Coverage
Archive-covered primitives (phase 1 target):
- pull requests, PR reviews, review comments, issue comments, issue events, commit comments.

Live pulse gap fillers:
- reactions
- discussions
- timeline completeness
- stars/watches/gists/profile deltas
- recent commit/diff depth via clone

## Job Model (Durable)
Additive tables:
- `ingestion_jobs`
- `ingestion_job_events`
- `ingestion_cursors`
- `evidence_reconciliation_links`

## Failure + Retry
Stop reason codes:
- `auth_scope_missing`, `export_not_allowed`, `export_timeout`, `download_failed`, `archive_corrupt`, `parse_schema_unknown`, `normalization_failed`, `reconcile_failed`, `rate_limited`, `budget_exhausted`, `killed_by_flag`, `user_cancelled`.

Retry policy:
- phase-local retries with backoff/jitter
- checkpoint resume (phase/cursor/member offset)

## Cost/Rate Strategy
- Spend heavy budget once in bootstrap.
- Keep pulse bounded and incremental.
- No sampling for high-signal review primitives.
- Persist explicit cap/stop telemetry.

## Rollout
Feature flags:
- `GH_MIGRATION_BOOTSTRAP_ENABLED`
- `GH_MIGRATION_DOWNLOAD_ENABLED`
- `GH_LIVE_PULSE_ENABLED`
- `GH_RECONCILE_ENABLED`

Phases:
1. Shadow parse/normalize
2. Internal canary
3. 5-10% rollout with telemetry gates
4. Full rollout

## Implementation Slices
1. Durable job tables + status streaming from job events.
2. Export orchestration (start/poll/download) with stop reasons.
3. Archive normalize path (`github_archive`) integrated in pipeline.
4. Reconciliation link model + retrieval preference.
5. Live pulse scheduler + cursor checkpoints.
6. Gap fillers (reactions/discussions/timeline deltas).
7. Cost/rate guardrails and completeness telemetry.
8. Runbooks, kill switches, rollback.
