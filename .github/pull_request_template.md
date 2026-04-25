<!--
Canonical repo for the Minis Linear project: alliecatowo/minis-ai.
Do not open project PRs against alliecatowo/minis, alliecatowo/my-minis, or minis-v2 unless the Linear issue explicitly says so.
-->

Linear: MINI-___

## Summary

-
-
-

## Scope / risk

- [ ] Correct repo: `alliecatowo/minis-ai`
- [ ] PR branch is tied to the Linear issue, preferably `title-identifier`
- [ ] PR body includes `Linear: MINI-___` or `Fixes MINI-___`
- [ ] No secrets, tokens, local private evidence, or user-private data committed
- [ ] Security/privacy implications considered
- [ ] Migrations, env vars, or deploy steps documented if applicable

## Validation

- [ ] Focused tests run:
- [ ] `mise run test-unit` when backend behavior changes
- [ ] `mise run lint` when Python/backend files change
- [ ] `mise run typecheck` when frontend TypeScript changes
- [ ] E2E/manual verification when user flows change

## Notes

Use `Fixes MINI-___` only when merging this PR should close the Linear issue. Use `Linear: MINI-___` or `Refs MINI-___` when the PR is partial, exploratory, or should not auto-close the issue.
