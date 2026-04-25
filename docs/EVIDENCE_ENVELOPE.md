# Evidence Envelope

MINI-218 adds a single provenance envelope to `Evidence` rows. The goal is to
retain enough raw context to reconstruct why a mini made a review prediction
without introducing a parallel schema path.

## Fields

The existing `Evidence` row remains the source of truth. Envelope data is stored
on the same row:

- `source_uri`: stable URL or source locator for the evidence item.
- `author_id`, `audience_id`, `target_id`: actor linkage when known.
- `scope_json`: scope such as repo/team/org/global plus source-specific IDs,
  paths, or other bounded scope fields.
- `evidence_date`, `created_at`, `last_fetched_at`: source timestamp, ingest
  timestamp, and latest fetch timestamp.
- `raw_body`: exact source body when retained in DB.
- `raw_body_ref`: stable pointer to recover the raw body when it should not be
  duplicated in DB.
- `raw_context_json`: surrounding source context such as repo, path, hunk,
  thread, PR, issue, or document references.
- `provenance_json`: collector/adapter/model/version/confidence metadata.

## Missing Data

All envelope fields are nullable. Ingestion adapters must populate only values
they actually know. The model serialization returns missing values as explicit
`None`/`null`; it must not fabricate generic authors, audiences, scopes, URLs,
or provenance confidence.

For legacy/minimal evidence, `raw_excerpt` falls back to `content` because that
is the only retained raw text. This fallback is a retention fallback, not a
claim that the original source body or surrounding context is complete.

## Ingestion Contract

`EvidenceItem` carries the same nullable envelope fields. The pipeline stores
them through `_store_evidence_items_in_db()` and includes non-empty envelope
values in the content hash so changed provenance/raw context invalidates stale
exploration. Empty envelope fields are excluded from the hash to avoid churning
existing minimal evidence rows.

Source-specific adapters should prefer:

- exact raw body over summaries,
- stable source pointers over transient URLs when raw body cannot be duplicated,
- source actor IDs over display names,
- explicit scope/path/thread/hunk context where the source exposes it.
