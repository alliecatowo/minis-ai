# CLI DX Spec for Long-Running Reingest (2026-04-26)

## Goal
Make common reingest operations reliable via `mise run ...` wrappers while preserving explicit control over fresh/full runs.

## Existing Strengths
- `ingest-full`, `ingest-resume`, `ingest-status`, `ingest-quick-check` already exist.
- Pipeline emits error codes and ingestion stop telemetry.

## Gaps
1. No durable run ID/history model.
2. Resume is mode-based, not checkpoint-based.
3. Status is mini-scoped more than run-scoped.
4. No single terminal machine-readable run summary.

## Command Contract
1. `ingest run <username> [--mode incremental|fresh|full] [--cache use|bypass] [--sources csv] [--json]`
2. `ingest resume <username> [--run-id <id>|--latest] [--from fetch|explore|synthesize|save|auto] [--json]`
3. `ingest status <username> [--run-id <id>|--latest] [--watch] [--json]`
4. `ingest stop <username> [--run-id <id>|--latest] [--reason ...] [--json]`

## Stop Reason Contract
Terminal reason must be exactly one code:
- `completed`, `cancelled_by_operator`, `timeout_exceeded`, `interrupted_signal`,
- `failed_fetch`, `failed_explore`, `failed_synthesize`, `failed_save`,
- `token_budget_exceeded`, `precondition_failed`.

Source-level reasons remain in per-phase telemetry details.

## `mise` Wrapper Contract
Expose stable wrappers for common operations:
1. `mise run ingest-full -- <username>`
2. `mise run ingest-resume -- <username>`
3. `mise run ingest-status -- <username>`
4. `mise run ingest-stop -- <username>`

## Acceptance Criteria
1. Long runs can be resumed from checkpoints without ambiguity.
2. Operators can always retrieve run status and terminal reason.
3. Full fresh mode is explicit and does not depend on opaque cache behavior.
