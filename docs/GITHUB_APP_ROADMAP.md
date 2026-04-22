# Minis GitHub App Roadmap

> Execution note: this doc is derived from `docs/VISION.md` and `docs/REVIEW_INTELLIGENCE.md`.
> It turns the north-star into a three-wave delivery ladder for the GitHub App and adjacent review surfaces.

## Purpose

Build the first product surface around the product target defined in `docs/REVIEW_INTELLIGENCE.md`:

- predict what a specific engineer would do on novel work
- model both `private_assessment` and `expressed_feedback`
- use repository context, audience context, and delivery context
- measure agreement against real human behavior

The GitHub App is the best first surface because review prediction is legible, frequent, and easy to validate.

## What This Roadmap Is

- A concrete delivery sequence for the review product
- A dependency map for the model and feedback loop
- A ticketing guide for obvious missing work

## What This Roadmap Is Not

- A general company roadmap
- A marketing narrative
- A replacement for Linear ticket planning
- A second review system path

## Three-Wave Ladder

| Wave | Name | Primary outcome | Exit criteria |
| --- | --- | --- | --- |
| 1 | Predictive review | The app can predict a reviewer's likely blockers, comments, and approval state on novel PRs | Gold cases exist, evals run repeatably, and review-agreement metrics improve release-over-release |
| 2 | Closed-loop learning | Human review outcomes are captured and folded back into the corpus and evaluator | Post-review deltas persist, disagreement is attributable, and retraining/re-extraction uses fresh truth |
| 3 | Code assistance via decision frameworks | The system helps authors shape code before review by applying the reviewer's decision framework | The same model can pre-review, explain the framework, and recommend edits that raise predicted agreement |

## Wave 1: Predictive Review

### Goal

Predict the review behavior of a specific engineer on novel code, not just mimic tone.

### Product shape

- GitHub App posts review comments and a structured review summary
- Predictions separate `private_assessment` from `expressed_feedback`
- The reviewer model is audience-aware and delivery-context-aware
- The review engine is repo-aware, not generic

### Required model outputs

- `blocking_issues`
- `non_blocking_issues`
- `open_questions`
- `positive_signals`
- `approval_state`
- `issue_ordering`
- `comment_selection`
- `tone / strictness fit`

### Required inputs

- exact diff and surrounding file context
- repo conventions and prior precedent
- reviewer history
- author identity or role
- delivery context such as hotfix, normal work, or incident

### Metrics

- blocker precision and recall
- approval-state accuracy
- issue-ordering agreement
- comment-selection agreement
- author-specific tone and strictness fit
- suggestion adoption rate

### Acceptance criteria

- The app can generate a structured prediction before prose
- The app can render human-usable review comments from that structure
- The system can compare its output to the eventual human review
- The evaluator can highlight regressions by reviewer and by repo

### Proposed ticket classes

- `review_predictor_v1`
- `review_policy_model_v1`
- `audience_context_model_v1`
- `delivery_context_model_v1`
- `repo_precedent_retrieval_v1`
- `gold_review_case_curation_v1`
- `review_agreement_eval_v1`
- `review_comment_selection_eval_v1`

## Wave 2: Closed-Loop Learning

### Goal

Capture how humans actually respond to the app's predictions and feed that truth back into the corpus.

### Learning loop

1. App predicts a review
2. Human reviewer edits, confirms, softens, or overrides it
3. The delta is stored as structured evidence
4. The corpus and extractor update
5. The next prediction uses the new truth

### What must be persisted

- original model prediction
- human final review
- comment-level deltas
- approval-state deltas
- whether the author complied, pushed back, or ignored feedback
- whether the reviewer later changed position

### Why this wave matters

Without the loop, the app is a snapshot product.
With the loop, it becomes a compounding system.

### Proposed ticket classes

- `post_review_delta_capture_v1`
- `review_disagreement_schema_v1`
- `human_override_ingestion_v1`
- `corpus_feedback_writeback_v1`
- `extractor_regression_eval_v1`
- `gold_case_refresh_job_v1`
- `reviewer_change_of_mind_tracking_v1`

### Acceptance criteria

- every reviewed PR can be linked to a prediction artifact
- disagreements are stored in a queryable way
- extractor outputs can be re-run against fresh truth
- evaluation reports can show where the model got better or worse

## Wave 3: Code Assistance Shaped by Decision Frameworks

### Goal

Move from predicting review to shaping code before review by applying the reviewer's decision framework.

This is not generic code generation. It is code assistance constrained by the same rules the reviewer uses when judging code.

### Product shape

- pre-review analysis in GitHub, MCP, or Claude Code
- code-change suggestions tied to specific framework rules
- explanations of why a change would satisfy the reviewer
- diffs rewritten to match reviewer decision order and policy

### What the assistant must know

- the reviewer's recurring rules
- the reviewer's ordering of checks
- the reviewer's self-corrections and exceptions
- when the reviewer blocks versus when they merely comment
- which audience or teammate changes the policy

### Required capabilities

- explain the decision framework in plain language
- map a change to the likely objections
- suggest revisions that reduce the predicted blocker set
- preserve repo-specific precedent
- avoid flattening reviewer style into generic best practice

### Proposed ticket classes

- `decision_framework_extraction_v1`
- `framework_ordering_model_v1`
- `framework_exception_model_v1`
- `pre_review_code_advisor_v1`
- `diff_rewrite_suggestions_v1`
- `framework_grounded_explanation_v1`
- `framework_to_patch_eval_v1`

### Acceptance criteria

- the assistant can say what would be blocked before a human review happens
- the assistant can point to the specific framework rule behind the advice
- suggested edits measurably improve review agreement on the next pass
- the system does not collapse into generic linting or Copilot-style assistance

## Obvious Missing Ticket Classes

These are not optional if the roadmap is to work end-to-end:

- reviewer identity resolution
- author identity and relationship modeling
- delivery-context labeling
- private vs expressed feedback separation
- comment-selection policy
- structured review artifact persistence
- disagreement and override logging
- evaluation harness refresh jobs
- gold-case curation for new reviewers and repos
- prompt / schema regression tests
- privacy and contamination controls for review evidence

## Sequencing Rules

1. Do not start Wave 3 before Wave 1 has stable evals.
2. Do not optimize prose before the structured prediction is trustworthy.
3. Do not add a second review path if the first can be extended.
4. Do not treat the feedback loop as analytics; it is product truth.
5. Do not ship code assistance without the decision framework model and its evaluation.

## Delivery Checkpoints

### Checkpoint A

The app predicts review behavior on a curated gold set with readable agreement metrics.

### Checkpoint B

Human review deltas are stored and re-ingested without manual cleanup.

### Checkpoint C

The assistant can pre-review and revise code according to a named reviewer framework.

## Relationship To Current Docs

- `docs/VISION.md` defines the north-star and the moat
- `docs/REVIEW_INTELLIGENCE.md` defines the review prediction contract
- this doc defines the execution ladder for the GitHub App path

If a future ticket does not improve one of the three waves above, it needs a strong justification.
