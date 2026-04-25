# Decision Synthesis Fidelity Spec

## Status

Execution is **partially shipped**.

- **Shipped:** `ReviewPredictionV1` contract now emits `framework_signals`, structured policy gates (`prediction_available`, `mode`, `unavailable_reason`), and provenance-rich outputs.
- **Partial / gated:** `REVIEW_INTELLIGENCE` surfaces are now using these contracts, but several Wave-3 decision-to-patch paths are still aspirational.
- **Aspirational:** full framework-to-structure-to-code-assistant loop is still closing.

This document codifies the synthesis architecture that turns raw human evidence
into a decision-framework model, applies that model to novel work, measures the
result against real human behavior, and feeds the delta back into the framework.

It is the implementation contract behind the product claim:

> Minis clones decision frameworks, not voice.

## Product Contract

For any subject, scope, and novel decision input, Minis must be able to produce
the following chain:

```text
values
  -> motivations
  -> frameworks
  -> latent_assessment
  -> expressed_feedback
  -> outcome_deltas
  -> updated_frameworks
```

The system is not complete if it can only retrieve prior statements, imitate
tone, or summarize past work. It must infer the decision function that generated
past behavior, apply that function to new cases, and update the function from
new ground truth.

## Definitions

### Values

Stable preferences that explain what the subject protects or optimizes for.

Examples:

- explicitness over magic
- safety over speed
- domain semantics over generic abstraction
- predictable operations over novel tooling

Values are not quotes. A quote can be evidence for a value, but the value is the
generalized preference inferred across evidence.

### Motivations

The reason a value matters to the subject in context.

Motivations connect an abstract value to practical consequences:

- "explicitness over magic" because hidden behavior caused outages before
- "safety over speed" because this repo handles money movement
- "domain semantics over generic abstraction" because shared vocabulary reduces
  cross-team mistakes

Motivations are required because the same surface rule can come from different
causes. Without motivation, Minis will apply rules too broadly.

### Frameworks

Reusable decision procedures derived from values, motivations, history, and
observed behavior.

A framework is a structured policy:

- trigger: when the framework applies
- checks: what the subject evaluates
- ordering: which checks happen first
- thresholds: what causes approval, comment, or block
- exceptions: when the subject waives the rule
- evidence: provenance for the inferred policy
- confidence: calibrated certainty that this is truly the subject's framework

Frameworks are the primary model artifact.

### Latent Assessment

The private judgment Minis predicts the subject would form before deciding what
to say.

Latent assessment includes issues the subject would notice even if they would
not express all of them. It must separate:

- blockers
- non-blocking concerns
- questions
- positive signals
- ignored or intentionally deferred issues

### Expressed Feedback

The subset and wording of the latent assessment that the subject would actually
communicate to this author, in this scope, under this delivery context.

Expression is shaped by:

- audience relationship
- urgency
- trust in the author
- mentoring posture
- public vs private channel
- review bandwidth
- shipping pressure

### Outcome Deltas

Ground truth differences between a prediction and what later happened.

Deltas include:

- confirmed: the human matched the mini
- missed: the human raised something the mini did not
- overpredicted: the mini raised something the human ignored
- softened: the human agreed privately but expressed it less strongly
- escalated: the human expressed a concern more strongly than predicted
- contradicted: the human rejected the mini's inferred framework
- context-missing: the mini lacked information that changed the decision

### Updated Frameworks

The next version of the subject model after outcome deltas are incorporated.

Updates must be append-only at the evidence layer and versioned at the model
layer. The system may supersede an old framework interpretation, but it must not
erase the evidence or the prior interpretation that produced a historical eval.

## Required Architecture

### 1. Evidence Ingestion

Every source record must be preserved as append-only raw evidence before any
synthesis occurs.

Minimum evidence envelope:

```json
{
  "evidence_id": "ev_...",
  "subject_id": "subject:...",
  "source_type": "pull_request_review | review_comment | issue_comment | commit | design_doc | chat | manual_correction | eval_delta",
  "source_uri": "https://...",
  "scope": {
    "type": "repo | team | org | global",
    "id": "..."
  },
  "timestamp": "2026-04-23T00:00:00Z",
  "author_id": "...",
  "audience_id": "...",
  "visibility": "public | repo | team | private | eval_only",
  "content_hash": "sha256:...",
  "raw_excerpt": "...",
  "surrounding_context_ref": "blob/pr/thread/hunk/document id",
  "ai_contamination_confidence": 0.0,
  "provenance_confidence": 1.0
}
```

Rules:

- Evidence must keep original timestamp, author, audience, scope, and source.
- Exact text must be recoverable or traceable to a stable source reference.
- Derived summaries must never replace raw evidence.
- AI-generated or AI-assisted evidence must be labeled, not silently mixed into
  human-authored evidence.
- Manual corrections are first-class evidence with their own provenance.

### 1.1 Evidence completeness rule

For this spec to be operational, an evidence record is considered complete only when
`evidence_id`, `source_type`, `source_uri`, `author_id`, `scope`, `timestamp`,
`raw_excerpt`, and at least one supporting evidence/context link are present.
Incomplete records are a known-failure path and should be excluded from synthesis until fixed.

### 2. Value Extraction
The value extractor reads evidence and emits candidate values with support and
counter-support.

Minimum value artifact:

```json
{
  "value_id": "value:explicitness_over_magic",
  "subject_id": "subject:...",
  "statement": "Prefers explicit control flow and visible dependencies over implicit framework magic.",
  "scope": { "type": "repo", "id": "repo:..." },
  "supporting_evidence_ids": ["ev_1", "ev_2"],
  "counter_evidence_ids": ["ev_3"],
  "first_seen_at": "2025-01-10T00:00:00Z",
  "last_reinforced_at": "2026-04-12T00:00:00Z",
  "confidence": 0.78
}
```

Extraction requirements:

- Prefer conflict evidence over neutral prose when inferring values.
- Preserve uncertainty when values are weak, stale, or contradicted.
- Distinguish global values from repo-local or team-local values.
- Track value drift instead of flattening old and new beliefs.

### 3. Motivation Synthesis

The motivation synthesizer explains why the value appears to matter.

Minimum motivation artifact:

```json
{
  "motivation_id": "motivation:explicitness_prevents_hidden_runtime_failures",
  "value_id": "value:explicitness_over_magic",
  "statement": "The subject resists hidden framework behavior because prior failures were caused by invisible runtime coupling.",
  "causal_evidence_ids": ["ev_4", "ev_5"],
  "scope": { "type": "repo", "id": "repo:..." },
  "confidence": 0.64
}
```

Requirements:

- Motivations must cite evidence that contains reasoning, conflict, or outcome.
- If the system cannot infer motivation, it must say so rather than invent one.
- Motivations must be allowed to differ by scope.

### 4. Framework Construction

Framework construction turns values and motivations into reusable decision
procedures.

Minimum framework artifact:

```json
{
  "framework_id": "framework:library_error_types",
  "subject_id": "subject:...",
  "scope": { "type": "repo", "id": "repo:..." },
  "trigger": "A library boundary introduces or changes error handling.",
  "decision_order": [
    "Is the error visible to callers?",
    "Is the error domain-specific?",
    "Can callers recover differently by variant?",
    "Does the implementation erase type information?"
  ],
  "approval_policy": "Approve typed domain errors with clear caller semantics.",
  "block_policy": "Block broad erased errors at reusable library boundaries unless the boundary is explicitly experimental.",
  "expression_policy": "Usually concise and direct; explain caller impact when author is junior or new to the repo.",
  "exceptions": [
    "Prototype code outside a reusable package",
    "Temporary migration shim with follow-up ticket"
  ],
  "value_ids": ["value:explicitness_over_magic"],
  "motivation_ids": ["motivation:explicitness_prevents_hidden_runtime_failures"],
  "evidence_ids": ["ev_1", "ev_2", "ev_6"],
  "counter_evidence_ids": ["ev_7"],
  "confidence": 0.81,
  "version": "framework-model-v1"
}
```

Requirements:

- A framework must be applicable to novel inputs, not just descriptive of past
  comments.
- Frameworks must include negative space: when the rule does not apply.
- Frameworks must encode ordering. A subject who checks tests before naming is
  not equivalent to a subject who checks naming before tests.
- Frameworks must include exceptions and context waivers when evidence supports
  them.
- Frameworks must link back to values and motivations so explanations do not
  collapse into "because they said so once."
- The framework artifact must preserve `decision_order` and order-aware evidence links so
  downstream predicted ordering is auditable.

### 5. Latent Assessment Prediction

For each novel input, Minis first predicts private judgment before generating
review prose.

Minimum latent assessment artifact:

```json
{
  "prediction_id": "pred_...",
  "subject_id": "subject:...",
  "input_id": "pr_or_decision_...",
  "framework_version": "framework-model-v1",
  "private_assessment": {
    "blocking_issues": [
      {
        "issue": "The reusable package erases domain-specific errors.",
        "framework_id": "framework:library_error_types",
        "supporting_input_refs": ["file.ts:42"],
        "confidence": 0.84
      }
    ],
    "non_blocking_issues": [],
    "open_questions": [],
    "positive_signals": []
  },
  "overall_confidence": 0.77
}
```

Requirements:

- Latent assessment must cite both input evidence and framework evidence.
- The system must keep possible-but-unsurfaced concerns distinct from comments
  it plans to express.
- Low-confidence assessments must produce uncertainty, not false specificity.

### 6. Expression Policy and Feedback Generation

Expression policy converts private assessment into public behavior.

Minimum expressed feedback artifact:

```json
{
  "prediction_id": "pred_...",
  "delivery_policy": {
    "author_model": "junior_peer | trusted_peer | senior_peer | unknown",
    "context": "hotfix | normal | exploratory | incident",
    "strictness": "low | medium | high",
    "teaching_mode": true,
    "shield_author_from_noise": true
  },
  "expressed_feedback": {
    "approval_state": "approve | comment | request_changes | uncertain",
    "selected_issue_ids": ["issue_1"],
    "comments": [
      {
        "body": "I would avoid erasing this error at the package boundary. Callers need to distinguish retryable failures from validation failures here.",
        "severity": "blocking",
        "framework_id": "framework:library_error_types",
        "confidence": 0.82
      }
    ],
    "unsaid_issue_ids": []
  }
}
```

Requirements:

- Expressed feedback must be derived from latent assessment, not generated first.
- Approval state must reflect the subject's predicted threshold, not generic
  review quality.
- Comment selection must model what the subject would choose to say, including
  what they would intentionally leave unsaid.
- Tone and delivery mapping must be explicit in policy: `say`, `suppress`,
  `defer`, and `risk_threshold` must each be populated and explainable.

### 7. Outcome Delta Capture

When human ground truth arrives, the system records the prediction outcome.

Minimum delta artifact:

```json
{
  "delta_id": "delta_...",
  "prediction_id": "pred_...",
  "human_outcome_ref": "review_or_decision_uri",
  "approval_state_delta": "matched | mini_too_strict | mini_too_lenient | human_unclear",
  "issue_deltas": [
    {
      "framework_id": "framework:library_error_types",
      "delta_type": "confirmed | missed | overpredicted | softened | escalated | contradicted | context_missing",
      "human_evidence_id": "ev_...",
      "notes": "Human blocked on the same issue but explained migration risk instead of caller semantics.",
      "confidence": 0.91
    }
  ],
  "author_response": "accepted | pushed_back | ignored | unknown",
  "merge_outcome": "merged | abandoned | reverted | unknown"
}
```

Requirements:

- Deltas must preserve the human's exact response and surrounding context.
- The system must distinguish prediction error from missing context.
- Author response and merge outcome are learning signals but must not be treated
  as proof of reviewer agreement by themselves.

### 8. Framework Update

Framework updates are versioned synthesis outputs over append-only evidence and
delta records.

Update rules:

- Confirmed deltas increase confidence only when the prediction was specific.
- Missed deltas create candidate checks or exceptions, not immediate hard rules.
- Overpredicted deltas reduce confidence or narrow trigger conditions.
- Contradicted deltas require explicit counter-evidence links.
- Context-missing deltas update retrieval/context requirements before changing
  the subject's framework.
- Recurring softened/escalated deltas update expression policy before changing
  private assessment.

Every update must produce:

- changed framework IDs
- prior version
- next version
- evidence IDs that caused the change
- confidence movement
- eval impact on held-out cases

## Recency Bias Control

Recency is useful but dangerous. Recent evidence may represent a real belief
update, a one-off delivery constraint, or a noisy artifact.

The system must use recency as a feature, never as an override.

Required controls:

- Track `first_seen_at`, `last_seen_at`, and `last_reinforced_at` separately.
- Weight recent evidence more only when it is consistent, repeated, or explicit
  self-correction.
- Treat one recent contradiction as counter-evidence, not automatic replacement.
- Prefer explicit "I changed my mind" evidence over implicit timestamp ordering.
- Preserve old frameworks as historical versions for reproducible evals.
- Report when a prediction depends primarily on recent evidence.

Recency classes:

- stable: old and recent evidence agree
- drifting: recent evidence weakly contradicts older evidence
- updated: explicit self-correction or repeated new behavior supersedes old
  behavior
- stale: old evidence has not been reinforced and should lower confidence
- bursty: many recent records come from one incident, project, or author and
  must not dominate the global model

## Generalization Control

The synthesis pipeline must avoid two opposite failures:

- over-specific memorization: repeating prior comments or rules only when a
  nearly identical situation appears
- over-general synthesis: inventing broad principles from narrow evidence

Required controls:

- Every framework must declare its trigger boundary and non-applicability cases.
- Extraction must separate quote, observation, rule, value, motivation, and
  framework.
- Evaluation must include mutated and held-out cases that differ from source
  evidence in stack, naming, author, scope, or delivery context.
- The model must be penalized for using exact prior wording when the novel input
  requires a different rationale.
- The model must be penalized for applying a framework outside its evidence
  scope.

Generalization test categories:

- near transfer: same repo, similar pattern, new PR
- scope transfer: different repo under same team conventions
- stack transfer: same framework in a different language or framework
- context transfer: hotfix vs normal feature vs prototype
- audience transfer: junior author vs trusted peer
- counterfactual: input resembles past evidence but contains the exception that
  should waive the rule

## Provenance Requirements

Every synthesized artifact must be auditable.

Minimum provenance contract:

- `evidence_ids` for support
- `counter_evidence_ids` for contradictions
- source timestamps
- source scopes
- extraction model/version
- synthesis model/version
- confidence
- visibility/access classification
- whether AI contamination was detected

The system must be able to answer:

1. Why do we think this subject believes this?
2. What evidence could prove this wrong?
3. Is this global, repo-local, team-local, or stale?
4. Which model version inferred it?
5. Which predictions depended on it?

If a user cannot inspect provenance, the system cannot be trusted for
YC-grade fidelity.

## Confidence Requirements

Confidence is not a vibe score. It must be calibrated against prediction
outcomes.

Confidence inputs:

- evidence volume
- evidence diversity across sources and contexts
- conflict density
- recency class
- provenance quality
- agreement with held-out examples
- contradiction count
- AI contamination risk
- scope match between evidence and current input
- expression-policy agreement history

Confidence outputs:

- per value
- per motivation
- per framework
- per latent issue
- per expressed comment
- per approval-state prediction
- per overall prediction

Calibration requirements:

- A prediction bucketed at 0.8 confidence should be right roughly 80% of the
  time over a large enough evaluation set.
- Confidence must decrease when the system crosses scope boundaries.
- Confidence must decrease when the prediction depends on stale, sparse, or
  contradicted evidence.
- Confidence must explicitly distinguish "the subject would privately notice
  this" from "the subject would publicly comment on this."

## YC-Grade Fidelity Metrics

YC-grade fidelity means the product can prove, with repeatable numbers, that it
predicts a real expert's judgment on novel work better than generic review,
retrieval-only memory, or voice imitation.

Primary metrics:

- blocker precision: of predicted blockers, how many the human also blocked on
- blocker recall: of human blockers, how many the mini predicted
- approval-state accuracy: approve/comment/request-changes agreement
- issue-ordering agreement: whether the mini surfaced concerns in the same
  priority order as the human
- comment-selection agreement: whether the mini chose the same subset of latent
  issues to express
- framework attribution accuracy: whether the cited framework actually explains
  the human behavior
- calibration error: whether confidence matches observed accuracy
- delta-learning uplift: whether incorporating outcome deltas improves future
  held-out performance

Secondary metrics:

- voice fidelity
- citation/provenance quality
- author-rated usefulness
- suggestion adoption rate
- latency
- cost per prediction

Minimum proof package for a credible YC demo:

- A held-out review set for at least one real subject.
- A retrieval-only baseline on the same set.
- A generic-reviewer baseline on the same set.
- A framework-synthesis run with frozen model version and frozen evidence set.
- Agreement metrics showing materially better blocker recall, approval-state
  accuracy, and issue-ordering agreement than both baselines.
- Example predictions with provenance visible down to source evidence.
- At least one outcome-delta update showing measurable uplift on later held-out
  cases without regressing earlier cases.

Suggested early bar:

- blocker precision >= 0.70
- blocker recall >= 0.60
- approval-state accuracy >= 0.75
- issue-ordering top-3 agreement >= 0.65
- comment-selection F1 >= 0.60
- calibration error <= 0.15
- retrieval-only baseline beaten by at least 15 percentage points on the primary
  aggregate score

These are not permanent product bars. They are the minimum threshold for
claiming the architecture is more than a compelling demo.

## Execution Gates

No synthesis or review feature should ship unless it can answer these gates:

1. Which values and motivations generated this framework?
2. Which evidence supports and contradicts the framework?
3. What is the framework's scope and trigger boundary?
4. What latent assessment did the system predict before expression?
5. Why did the expression policy choose these comments and omit others?
6. What confidence is attached to each layer and tone policy?
7. What is the policy when fidelity prediction is unavailable (`mode=gated`) and how do we avoid silent fallback?
8. How will human outcome deltas be captured?
9. How will those deltas update or narrow the framework?
10. Which eval proves this change improved generalization rather than
   memorization?
11. Which recency controls prevent one new event from overriding stable history?

If these answers are missing, the feature is not decision-synthesis fidelity
work. It is demo polish or generic assistant behavior.

## Anti-Goals

Do not build:

- a tone clone that cannot predict review behavior
- a vector search system that narrates old comments as if they are reasoning
- a single mutable profile blob with no provenance
- a recency-biased model that treats newest evidence as always best
- an overfit model that only works on exact repeats of prior examples
- confidence numbers that are not calibrated against outcomes
- feedback capture that stores thumbs-up/thumbs-down without structured deltas
- framework updates that overwrite historical versions needed for evals

## Implementation Slices

This spec should land as small, testable slices:

1. Evidence envelope and provenance completeness checks.
2. Value and motivation artifacts with support/counter-support.
3. Framework artifact schema with trigger boundaries, ordering, and exceptions.
4. Latent assessment artifact emitted before prose feedback.
5. Expression-policy artifact linked to selected and omitted issues.
6. Outcome-delta artifact from human review comparison.
7. Versioned framework update job over deltas.
8. Fidelity eval harness with generalization cases and baselines.
9. Confidence calibration report.
10. Release gate that blocks "fidelity improved" claims without metric uplift.

The architecture is only real when all ten slices connect into the closed loop:

```text
evidence -> synthesis -> prediction -> human outcome -> delta -> updated synthesis -> measured uplift
```
