# Upstream Contract Fixtures

MINI-224 adds a test-only harness for recorded upstream HTTP contracts. The
goal is to let integration tests exercise real provider/API-shaped responses
without calling live services on every run.

## Modes

- `replay` is the default. Tests read checked-in JSON fixtures and fail on any
  unexpected request, request order, or request body drift.
- `record` calls the live upstream and overwrites the fixture on transport
  close. It is skipped unless `UPSTREAM_CONTRACT_LIVE=1` is set and any required
  provider secrets are present.
- `live` calls the live upstream without writing a fixture. It has the same
  explicit gate as `record`.

Use `UPSTREAM_CONTRACT_MODE=replay|record|live` when wiring a test to the
environment. Keep CI on replay unless a job is intentionally configured with
provider secrets.

## Redaction Discipline

The harness redacts common secret headers and fields, including
`Authorization`, cookies, `token`, `api_key`, `secret`, and known provider env
values such as `GITHUB_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, and `GOOGLE_API_KEY`. It refuses to write fixtures containing
common unredacted token markers.

Before committing a new recording, inspect the JSON fixture and verify it
contains no private user evidence, credentials, cookies, or local logs.

## Current Coverage

The first checked-in fixture is
`backend/tests/fixtures/upstream/github/repos_graphql_success.json`. It replays
a GitHub GraphQL repositories response through the real `fetch_user_repos_graphql`
mapper, covering provider-shaped response parsing deterministically.

## No-Fallback Follow-Up

This slice keeps no-fallback testing scoped to the fixture harness itself:
replay mode fails loudly when the upstream request contract changes instead of
silently falling back to mocks. The next MINI-220 slice should route higher-level
no-fallback integration tests through these fixtures for the full GitHub ingest
path and any LLM judge/provider calls that currently rely on broad mocks.
