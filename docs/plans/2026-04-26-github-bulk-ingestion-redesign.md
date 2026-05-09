# GitHub Primitive Map + Bulk Ingestion Redesign (2026-04-26)

## Goal
Maximize fidelity signal per rate unit by ingesting the highest-value GitHub primitives in bulk, with complete provenance and explicit org-data opt-in.

## Product Contract
- Primary identity key remains `mini_id`.
- Ingestion must preserve evidence envelope fields and authorization metadata.
- Org/team data is never fetched unless explicit opt-in is enabled for the run.

## Current Gaps (Must Fix)
1. Missing primitives: Discussions, non-PR issues corpus, reactions, full timeline primitives, org/team context.
2. Private/org classification drift: many emitted rows default to `privacy=public`.
3. Lossy sampling affects review-quality corpus (mid/historical sampling).
4. Duplicate fetch fanout on inline comments wastes rate budget.
5. Org opt-in helper exists but is not enforced in fetch planning.

## Primitive Classes
1. Collaboration primitives (API canonical): PR reviews/states/threads/comments/issues/discussions/reactions/timelines.
2. Code-evolution primitives (clone canonical): commits, hunks, patches, file history.
3. Graph/taste primitives (API bulk): stars/watches/profile metadata.
4. Context primitives (opt-in): org/team memberships and role context.

## Bulk-First Strategy
1. API-bulk for collaboration/timeline primitives.
2. Local-clone bulk for commit/diff depth by default, API as fallback.
3. No sampling on high-signal review primitives; sampling allowed only on lower-signal taste surfaces.
4. Remove duplicate pulls comments fetch path.

## Provenance + Policy Requirements
Required on every GitHub evidence row:
- `source_uri`, `author_id`, `target_id`, `scope_json`, `raw_context_json`, `provenance_json`.
- `source_privacy`, `source_authorization`, `access_classification` set correctly.
- Add org/consent keys: `org_opt_in_state`, `org_scope`, `token_scope`, `installation_id`, `permission_basis`.

## Migration Plan
1. Additive schema + indexes for provenance/completeness telemetry.
2. Collector rollout:
- enforce org opt-in at plan phase,
- add missing primitives,
- remove duplicate fetches,
- fix privacy classification.
3. Bulk switch:
- clone-first for commit/diff corpus,
- API canonical for social/review corpus.
4. Backfill and policy hardening:
- infer provenance where safe,
- fail closed for export when authorization metadata is missing.

## Acceptance Criteria
1. Missing primitive coverage map is green for review/discussion corpus.
2. Review/diff evidence completeness improves without increased silent truncation.
3. Run summary contains phase completeness and stop reasons.
4. Org-data remains fully gated by opt-in flag.
