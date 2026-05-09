# Prompt/Runtime Unification Design (2026-04-26)

## Goal
One renderer contract across chat/team/review surfaces; eliminate route-level prompt mutation drift.

## Problem
- Synthesis builds rich prompt in `spirit.py`.
- Chat mutates prompt at runtime.
- Team chat bypasses chat augmentations.
- Review predictor has its own overlay chain.

## Canonical Contract
Create one render module with:
1. `RenderSurface` enum: `chat`, `team_chat`, `review_predictor`.
2. `PromptSurfaceOptions` for policy toggles.
3. `RenderContext` (mini + structured artifacts + options).
4. `RenderedPrompt` output with contract version + applied sections.
5. `render_prompt(ctx)` as only assembly entrypoint.

## Design Rules
1. No endpoint-specific string surgery.
2. Surface differences are declarative options/presets.
3. Tool-profile selection lives alongside renderer preset contract.
4. Chat/team parity guaranteed unless explicitly configured otherwise.

## Migration Slices
1. Extract shared prompt helpers from route modules.
2. Move `/chat` to renderer in compatibility mode.
3. Move `/teams/*/chat` to renderer preset.
4. Move review predictor overlay to renderer-based assembly.
5. Centralize tool-surface profile mapping.
6. Remove duplicate prompt logic and add parity tests.

## Acceptance Criteria
1. Renderer is the single prompt assembly path.
2. Prompt snapshots are deterministic per surface preset.
3. `/chat` and `/team_chat` parity test passes for same options.
4. Review predictor output contract remains stable.
