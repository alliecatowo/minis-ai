# Project Health Audit — 2026-05-09

## Vision Parity
- **Tier 1 (IC velocity):** ~60%. `/mini-review` CLI exists; chat works. Wave 2/3 schema landed today; soul doc rendering needs verification.
- **Tier 2 (Senior focus):** ~40%. Decision-framework structure exists; delivery-context model + audience-aware feedback suppression incomplete.
- **Tier 3 (Team force-multiplier):** ~20%. MCP tools gated; multi-mini assembly partial.
- **Tier 4 (Business cross-team):** ~5%. GitHub App code in `github-app/` but NOT prod-deployed; closed-loop learning shipped partial.
- **Tier 5 (Enterprise):** Not started.

**Verdict:** 1-tier deep, need 2-tier credible for YC.

## Decision-Framework Cloning vs Voice
- Gold data EXISTS (1664 CC sessions, 250+ GitHub items, 321 KB principles, 87% Allie-specific quotes).
- Rendering DROPS it: chief.py wave-6 fan-out is in but soul doc still feels generic per audits.
- Phase 2/3 schema work landed today (PR #197, #198, #199) — needs regen v8b to confirm rendering improves.

## GitHub App Readiness
- Code in `github-app/` but NOT installed on any public repos. CTA at YC step 7 needs at least ONE proof installation.
- Wave 2 (closed-loop) + Wave 3 (code assistance): not shipped.

## MCP Distribution
- `mcp-server/main.py` (31KB) has tool stubs. Auth via `MINIS_AUTH_TOKEN` or device flow.
- NOT in Claude Code marketplace; manual `.claude/settings.json` wiring required.
- Device flow needs backend `/api/auth/github-device/exchange` verified.

## YC Demo Script — Beat Status
| Beat | Status |
|------|--------|
| Narrative setup | ✓ |
| 1. Landing page | ✓ |
| 2. alliecatowo profile | 🔴 unknown UI; soul doc render needs verify |
| 3. Run review prediction | ✓ CLI works; GitHub App optional |
| 4. Show scorecard | 🟡 schema may mismatch post-Wave-2 |
| 5. Calibration metric | 🟡 metric exists, UI unverified |
| 6. Outcome loop | 🟡 partially wired |
| 7. Create mini CTA | ✓ |

## Demo Blockers (must fix before pitch)
1. **Frontend soul-doc rendering** — verify it shows the post-2E `soul_prompt` and 11-aspect narratives properly.
2. **Scorecard UI contract** — verify aligned with post-Wave-2 schema.
3. **Voice fidelity** — needs regen v8b to complete + smoke test.
4. **GitHub App not in prod** — at least install on alliecatowo/minis-ai for live PR demo.
5. **PredictionFeedbackMemory wiring** — verify outcome loop actually closes.

## Stale Linear Debt to Close (free cap)
1. MINI-193 voice rendering surgery (validator-rejected; close)
2. MINI-66 multi-step agentic reasoning (merged; close)
3. Spike tickets without active PRs — archive
4. Old pre-2026-04-26 docs — move to docs/archive/
5. Duplicate ADR identity model items — consolidate

## Branding
- Codebase consistently "Minis" ✓
- Repo path is `minis-hackathon` (legacy) but canonical remote is `alliecatowo/minis-ai`. Move repo dir to match? Low priority.
- `my-mini.me` domain not verified — confirm.

## Path Forward
- 24-48h: verify frontend soul/scorecard rendering, regen v8b smoke test, install GH App on at least one repo, document CLI fallback for any flaky beat.
- Acceptable demo fallback: CLI `/mini-review` + screenshots + narrative on the soul-doc quality.
