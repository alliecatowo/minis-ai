# Memory/KG Retrieval Design (2026-04-26)

## Goal
Ensure newly ingested evidence is actually consumed during synthesis/chat/review, not stranded in storage.

## Current Choke Points
1. Memory flattening into blob can hide provenance and ranking quality.
2. Retrieval paths are inconsistent across chat/review and may underuse embeddings/KG.
3. KG risks write-only behavior if not queried at runtime.
4. Freshness semantics are weak when prior memory findings accumulate.

## Contract
1. Retrieval is hybrid and explicit: embedding + lexical + provenance/recency weighting.
2. Evidence payload into model is chunked/ranked, not full-blob injected.
3. KG is queryable at runtime with typed edge filters and neighborhood expansion.
4. Memory facts link back to evidence IDs (and KG node IDs when available).

## Retrieval Pipeline
1. Query normalization.
2. Candidate generation from:
- embeddings table,
- lexical/index fallback,
- KG neighborhood expansion.
3. Scoring with weighted features:
- relevance,
- recency,
- source quality,
- provenance confidence,
- scope/perspective compatibility.
4. Budgeting + chunk assembly.
5. Render-time citation payload attached for auditability.

## Freshness Semantics
1. Maintain append-only evidence rows.
2. For synthesized memory projections, version snapshots and mark active projection version.
3. Replace-on-regenerate should swap active projection pointer, not mutate historical rows.

## Acceptance Criteria
1. Chat/review retrieval codepath uses same hybrid retrieval contract.
2. KG queries contribute measurable retrieved context.
3. Responses can trace major claims to evidence IDs.
4. Reingest updates retrieval quality without stale-memory dominance.
