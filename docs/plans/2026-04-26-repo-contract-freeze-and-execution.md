# Repo Contract Freeze + Execution Plan (2026-04-26)

## Purpose
Encode one repo-level contract so implementation can move quickly without adding new legacy paths.

## Identity Contract (Reconciled)
1. Primary identity unit is `MiniInstance` (owner-scoped interpretation of a target), not a forced global canonical person merge.
2. Different minis for the same human are valid when source envelope/scope/audience differ.
3. Optional cross-mini linkage is advisory only (future relation, never hard merge invariant).

## Artifact Key Contract (5-axis)
Every persisted synthesis/prediction artifact must be addressable by:
- `mini_id`
- `scope_ref`
- `perspective`
- `visibility`
- `version`

If one axis is missing, the artifact is underspecified and not a contract-complete output.

## Non-Negotiable Invariants
1. Evidence is append-only. No in-place mutation of prior evidence rows.
2. Prompt/render has a single canonical renderer entrypoint used by chat/team/review surfaces.
3. Framework/projection outputs are versioned and reproducible.
4. Prediction cycle persists latent assessment, expressed feedback, and outcome delta linkage.
5. Ingestion provenance envelope remains intact (`source`, `item_type`, `external_id`, timestamps, auth/privacy metadata).

## Known Contract Violations To Remove
1. Evidence mutation during ingest/sync (`existing.content = ...`) instead of version-append.
2. Route-level prompt string surgery causing chat/team/review divergence.
3. Partial 5-axis representation/enforcement at read time.
4. GitHub ingestion moat under-coverage (reviews/comments/discussions/gists/stars/watch/reactions/diff-hunk detail).

## Execution Topology (Dependency-Aware)

### Batch 1 (Sequential, Blocking)
Contract + design freeze docs:
1. This contract freeze + invariants checklist.
2. GitHub primitive map + bulk-first ingestion redesign spec.
3. Prompt/runtime unification design (single render pipeline).
4. Memory/KG retrieval design (ensure newly ingested breadth reaches synthesis).
5. CLI DX spec (long-running fresh reingest, resume/checkpoint, stop reasons).

Acceptance gate:
- All five docs present, cross-referenced, and reconciled with `docs/VISION.md`, `docs/PROGRAM.md`, `docs/DECISION_SYNTHESIS_FIDELITY_SPEC.md`, and `docs/ADR_002_IDENTITY_MODEL_AND_SCOPE.md`.

### Batch 2 (Parallel, after Batch 1 gate)
Implementation slices (PR-sized, disjoint ownership):
1. Append-only evidence refactor + migration(s).
2. GitHub bulk ingestion breadth implementation.
3. Unified renderer implementation and surface cutover.
4. Memory/KG retrieval path wiring.
5. CLI reingest/resume tooling hardening.

Acceptance gate:
- `mise run lint`
- Focused `mise run test-unit`
- Additional focused tests per slice.

### Batch 3 (Sequential)
1. Full fresh reingest (cache bypass/fresh mode).
2. Regenerate mini outputs.
3. Fidelity validation pass and regressions triage.

## Parallelization Rules
- Design phase may parallelize research lanes, but final contract language merges through one owning doc.
- Implementation phase parallelizes only disjoint write sets; no duplicate code paths.
- No “temporary” compatibility branch unless explicitly documented with sunset/removal ticket.

## Tracking Checklist
- [x] Contract freeze created
- [x] GitHub primitive + bulk ingestion redesign doc
- [x] Prompt/runtime unification design doc
- [x] Memory/KG retrieval design doc
- [x] CLI DX reingest/resume spec
- [ ] Fanout implementation tickets with acceptance criteria
