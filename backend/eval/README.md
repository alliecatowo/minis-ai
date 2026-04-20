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
    rubric:
      - criterion_name: "What to check for"
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

## Follow-up

- **ALLIE-383**: Populate 10 turns per subject (currently 3)
- **ALLIE-384**: Add regression guard to CI on `backend/app/synthesis/` changes
- **ALLIE-385**: Wire eval results to Linear as automated test artifacts
