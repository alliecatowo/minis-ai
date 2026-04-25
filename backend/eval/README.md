# Minis Fidelity Evaluation Harness

Quantitative scoring of AI mini chat responses against golden reference answers
drawn from the subject's actual writing. Designed for A/B-testing the explorer
pipeline (ALLIE-373 and beyond) and prompt iterations.

## Structure

```
eval/
  subjects/          # Who we're evaluating (one YAML per subject)
  golden_turns/      # 3+ reference prompts + answers per subject
  judge.py           # LLM-as-judge: (reference, rubric, response) -> ScoreCard
  runner.py          # Orchestrates HTTP calls to mini chat + judge scoring
  report.py          # Renders Markdown + JSON output

scripts/
  run_fidelity_eval.py   # CLI entrypoint

tests/eval/
  test_judge.py          # Unit tests for scorer (mocked LLM)
  test_runner.py         # Unit tests for runner (mocked HTTP + judge)
```

## Running

```bash
# Local (dev bypass auth)
cd backend
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo,jlongster,joshwcomeau \
  --base-url http://localhost:8000 \
  --out eval-report.md

# With service JWT (CI)
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo \
  --base-url https://minis.fly.dev \
  --token "$SERVICE_JWT" \
  --out eval-report.md
```

Output: `eval-report.md` + `eval-report.json`.

## Scoring

Each turn is scored by an LLM judge (STANDARD tier model) on:

| Dimension | Scale | Meaning |
|---|---|---|
| `overall_score` | 1–5 | Combined fidelity |
| `voice_match` | 1–5 | Tone / personality match |
| `factual_accuracy` | 1–5 | Factual correctness vs reference |
| Per rubric criterion | 1–5 | Each specific check |

**Score guide:** 3 = average, 4 = mostly correct, 5 = genuinely impressive.

## Adding Subjects

1. Add `eval/subjects/<username>.yaml` (see schema below)
2. Add `eval/golden_turns/<username>.yaml` (3–10 turns with reference answers)
3. Verify reference answers against source material — mark paraphrased sections

### Subject YAML schema

```yaml
username: jlongster
display_name: James Long
why_selected: |
  Why this person is a useful test subject.
expected_voice_markers:
  - marker 1
  - marker 2
```

### Golden turns YAML schema

```yaml
subject: jlongster
turns:
  - id: unique_turn_id
    prompt: "The question to ask the mini"
    reference_answer: |
      # Source attribution (blog URL, talk, etc.)
      # Mark "paraphrased, needs verification" if not verbatim
      The actual reference text...
    case_type: baseline  # optional: baseline | adversarial
    rubric:
      - criterion_name: "What to check for"
```

Review-prediction turns can add an optional `held_out_review` block so the same
chat harness can score agreement on a real held-out review outcome:

```yaml
  - id: held_out_review
    prompt: "Review this change."
    reference_answer: |
      Concise reference summary of the human review.
    rubric:
      - review_policy: "Blocks on missing tests"
    held_out_review:
      verdict: request_changes
      blocker_candidates:
        - id: missing_tests
          summary: "Needs regression coverage for the new branch"
          expected: true
        - id: feature_flag
          summary: "Needs a rollout guard"
          expected: false
      comment_candidates:
        - id: rename_helper
          summary: "Rename helper for clarity"
          expected: true
```

For turns with `held_out_review`, the judge maps the mini response onto the
fixed candidate IDs and the harness computes:

- verdict match
- blocker precision / recall / F1
- comment-selection precision / recall / F1
- overall review agreement as the average of verdict accuracy and available F1s

Adversarial cases should set `case_type: adversarial`. Reports track adversarial
pass/fail separately using `overall_score >= 4` as the pass threshold.

## Gold Review Cases

`eval/gold_review_cases/` holds structured review-prediction calibration cases.
These are not product copy; they are gold labels for measuring whether a mini
predicts what an engineer would privately assess and what they would actually
say for novel work.

The initial fixture is:

```text
eval/gold_review_cases/alliecatowo.yaml
```

Each case must include:

- `case_type`: one of `architecture_domain_boundary`,
  `pragmatic_shipping_tradeoff`, `audience_context_sensitive_suppression`,
  `recency_vs_durable_framework`, or `novel_work_generalization`.
- `input`: the review-prediction request shape, including `author_model` and
  `delivery_context`.
- `target_audience`: the audience/surface context that controls feedback
  suppression.
- `expected_private_assessment`: blocking issues, non-blocking issues, open
  questions, positive signals, and confidence before expression filtering.
- `expected_expressed_feedback`: approval state, comments the reviewer would
  actually leave, and private signal keys that should stay suppressed.
- `evidence_references`: provenance for every gold label. Prefer durable repo
  docs, existing source-attributed golden turns, review outcomes, or exact PR
  comments. Do not use private logs or unredacted user evidence.
- `scoring_dimensions`: named, weighted rubrics. Weights must sum to `1.0`, and
  any `expected_signal_keys` must reference private-assessment signal keys.

Minimal case shape:

```yaml
version: 1
subject: alliecatowo
cases:
  - id: domain_boundary_example
    title: "Domain boundary example"
    case_type: architecture_domain_boundary
    intent: "What this case measures."
    target_audience:
      author_model: trusted_peer
      delivery_context: normal
      reviewer_surface: github_app
      notes: "Why this audience changes expression."
    input:
      artifact_type: pull_request
      repo_name: alliecatowo/minis-ai
      title: "Example PR"
      diff_summary: "What changed."
      author_model: trusted_peer
      delivery_context: normal
    expected_private_assessment:
      confidence: 0.8
      blocking_issues:
        - key: domain-boundary-leak
          summary: "What the reviewer privately notices."
          rationale: "Why it matters."
          confidence: 0.9
          evidence_refs: [ev-1]
      non_blocking_issues: []
      open_questions: []
      positive_signals: []
    expected_expressed_feedback:
      approval_state: request_changes
      summary: "What the reviewer would actually say."
      comments:
        - type: blocker
          disposition: request_changes
          issue_key: domain-boundary-leak
          summary: "The expressed comment."
          rationale: "Why this comment is surfaced."
          evidence_refs: [ev-1]
      suppressed_private_signal_keys: []
    evidence_references:
      - id: ev-1
        source: docs/REVIEW_INTELLIGENCE.md
        item_type: product_spec
        external_id: review-two-layer-model
        note: "Why this evidence supports the label."
    scoring_dimensions:
      - name: blocker_recall
        weight: 1.0
        rubric: "Selects the expected blocker."
        expected_signal_keys: [domain-boundary-leak]
```

Run fixture validation with:

```bash
cd backend
uv run pytest tests/eval/test_review_cases.py
```

## Regression Guard

Pass `--prior eval-report.json` to compare against a previous run:

```bash
uv run python scripts/run_fidelity_eval.py \
  --subjects alliecatowo \
  --prior eval-report.json \
  --out eval-report-new.md
```

A warning is printed if overall average drops by > 0.3 points.

## Baseline Status

The golden turns are now expanded to 10 source-annotated turns per subject
(ALLIE-385). A prod baseline run is **deferred pending ALLIE-389** (RepoAgent
flag rollout). Prod is currently running pre-RepoAgent code; baseline scores
from that build would not be comparable to scores captured after ALLIE-389 ships.
Run the baseline once ALLIE-389 is in production using the CI command above.

## Follow-up

- **ALLIE-384**: Add regression guard to CI on `backend/app/synthesis/` changes
- **ALLIE-389**: RepoAgent flag rollout — run prod baseline eval after this ships
