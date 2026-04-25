# Review Intelligence Model

> This document is load-bearing for every review-oriented surface in Minis:
> GitHub App, Claude Code plugin, MCP server, API routes, eval harness, and
> future code-writing assistance. If you are implementing anything that claims
> to "review like Allie," read this first.
>
> For the execution-grade synthesis loop behind this model, read
> `docs/DECISION_SYNTHESIS_FIDELITY_SPEC.md`.

## The Product Target

Minis is not trying to generate a plausible code review in someone's tone.
Minis is trying to predict the review behavior of a specific engineer on novel
work, including what they would notice, what they would ignore, what they would
block on, what they would soften, and what they would choose to say to a
specific teammate in a specific delivery context.

The unit of prediction is not:

- "What would Allie say about this diff?"
- "What is a good code review for this PR?"
- "Can we imitate the engineer's voice?"

The unit of prediction is:

- "What would this engineer choose to say to this specific person, on this
  change, in this repo, under these team and delivery constraints?"

That is the product.

Voice matters because it makes the output believable and useful. But voice is
downstream of judgment, not the thing being cloned.

## The Two-Layer Review Model

Every real review has at least two layers:

1. `private_assessment`
   What the reviewer actually thinks after reading the change. This includes
   bugs, risks, architecture concerns, naming concerns, domain-boundary issues,
   missing tests, precedent conflicts, rollout concerns, and "this feels wrong"
   intuitions.

2. `expressed_feedback`
   What the reviewer chooses to say out loud in the review. This is a filtered
   projection of the private assessment, shaped by audience, urgency,
   mentorship style, political context, shipping pressure, trust in the author,
   and the reviewer's own bandwidth.

Those layers are not identical.

An engineer might privately believe:

- there are six problems here
- two are real blockers
- two are not worth slowing the author down over
- one is something they'd mention only to a senior
- one is a teaching opportunity for a junior

But the expressed review might contain only:

- one blocking comment
- one advisory note
- one brief approval sentence

If Minis predicts only the private assessment, it over-reviews.
If Minis predicts only the expressed text, it becomes shallow and
non-generalizable.
We need both.

## The Review Stack

Review behavior is the output of multiple layers. Each layer contributes signal.

### 1. Code / repo lens

The engineer's codebase knowledge:

- repository conventions
- architectural boundaries
- ownership seams
- domain model shape
- testing norms
- performance / reliability scars
- preferred abstractions

This is why the repo explorer matters. A reviewer is not applying generic
software advice; they are applying their understanding of this codebase and how
it ought to evolve.

### 2. Review-history lens

The engineer's demonstrated review function:

- recurring objections
- approval triggers
- block conditions
- issue ordering
- severity thresholds
- how often they ask for tests vs naming vs architecture changes

This is the most direct signal for novel review prediction. Past reviews reveal
not just what they said, but the function that generated the feedback.

### 3. Values / motivations / personality lens

Why the reviewer cares about what they care about:

- pragmatism vs purity
- safety vs speed
- explicitness vs flexibility
- domain semantics vs style polish
- craftsmanship vs throughput
- desire to mentor vs desire to minimize cycle time

Personality typology, behavioral context, goals, motivations, and values are
not fluff. They explain why the same engineer keeps making the same judgment
calls.

### 4. Audience / relationship lens

Review output changes depending on who the author is:

- junior teammate
- senior peer
- trusted collaborator
- unknown OSS contributor
- manager / founder
- cross-team partner

The same private assessment may be expressed very differently to each audience.
Some reviewers protect juniors from overload. Some are sharper with peers.
Some go soft in public and sharper in private. Some avoid escalating a known
issue if they know the author is already underwater.

This layer is essential. "What would they say?" is not enough. The product is
"what would they say to you?"

### 5. Delivery-context lens

Reviews are shaped by the situation:

- hotfix vs normal feature work
- incident response vs greenfield build
- prototype vs production path
- frozen release week vs normal sprint
- large risky PR vs tiny follow-up

A good reviewer does not apply the same verbosity or strictness in every
context. Minis has to model that policy, not flatten it away.

### 6. Expression policy lens

The final stage converts latent judgment into actual review output:

- what gets surfaced now
- what gets deferred
- what becomes a blocking comment
- what becomes a question
- what becomes a suggestion
- what stays unsaid

This is the difference between a useful teammate and a hyperactive lint bot.

## The Core Prediction Contract

Every review-oriented surface should eventually produce a structured artifact
 before or alongside prose:

```json
{
  "relationship_context": {
    "reviewer_author_relationship": "trusted_peer | junior_mentorship | senior_peer | cross_team_partner | unknown",
    "trust_level": "high | medium | low | unknown",
    "mentorship_context": "reviewer_mentors_author | peer | none | unknown",
    "channel": "public_review | private_review | team_private | unknown",
    "team_alignment": "same_team | cross_team | external | unknown",
    "repo_ownership": "reviewer_owned | author_owned | shared | unowned | unknown",
    "audience_sensitivity": "low | medium | high | unknown",
    "data_confidence": "explicit | derived | unknown",
    "unknown_fields": []
  },
  "private_assessment": {
    "blocking_issues": [],
    "non_blocking_issues": [],
    "open_questions": [],
    "positive_signals": [],
    "confidence": 0.0
  },
  "delivery_policy": {
    "author_model": "junior_peer | trusted_peer | senior_peer | unknown",
    "relationship_context": {},
    "context": "hotfix | normal | exploratory | incident",
    "strictness": "low | medium | high",
    "teaching_mode": true,
    "shield_author_from_noise": true
  },
  "expressed_feedback": {
    "summary": "",
    "comments": [],
    "approval_state": "approve | comment | request_changes | uncertain"
  }
}
```

The prose review is derived from this structure, not the other way around.

Relationship context is an explicit artifact, not a guess. If the system does
not know trust, mentorship, channel visibility, team alignment, repo ownership,
or audience sensitivity, the field must be `unknown` and listed in
`unknown_fields`. Existing coarse `author_model` values may derive only the
corresponding relationship signal, while unrelated team/channel/ownership data
must stay unknown. Delivery policy may use public/cross-team sensitivity,
mentorship, trust, and repo ownership to decide what stays private versus what
is expressed.

## What the GitHub App Should Become

The GitHub App is the first flagship product surface, because review prediction
is the clearest proof that the clone is useful.

GitHub App V1 should do at least six things:

1. Resolve the correct mini for the requested reviewer.
2. Build repo-aware context for the PR, not just title/body/diff.
3. Predict `private_assessment` before generating prose.
4. Apply reviewer policy for the author and delivery context.
5. Emit human-usable review comments with accurate severity and tone.
6. Capture post-hoc human review deltas as feedback memory.

Status split:

- **Shipped:** structured review prediction output plus explicit availability gating (`prediction_available`, `mode`, `unavailable_reason`) is in the current contract.
- **Partial / gated:** review outcome capture is in place via `#117` and trusted-service owner writeback, with feature control needed before full closed-loop coverage.
- **Aspirational:** Wave 3 code-assistance distribution remains a later phase and should reuse the same framework-signals envelope.

## Why MCP / Claude Code Still Matter

The GitHub App proves the value in a narrow, legible loop.
Claude Code and MCP turn that loop into a daily developer workflow:

- "pre-review this diff as Allie before I request review"
- "what would Alice block on here?"
- "rewrite this change so Bob won't complain about domain boundaries"
- "generate the private assessment, then show me the three comments she'd
  actually leave"

That is the bridge from review prediction to code-writing assistance.
Long-term the mini should not only predict feedback. It should help produce code
that already satisfies the engineer's framework before the human ever reads it.

## The Eventual Coding Product

The long-term product is not limited to review text.

The coding surface becomes:

1. predict the engineer's review
2. explain the underlying decision framework
3. revise the code to satisfy that framework
4. eventually generate code under that framework from scratch

Review is the proving ground because it is easier to evaluate.
Coding is the expansion surface because it captures more value.

If a mini cannot predict the review, it should not be trusted to write the code.
If it can predict the review reliably, code-writing becomes a tractable next
step.

## Retrieval and Synthesis Requirements

To support the product target, the system needs to preserve and retrieve:

- raw evidence, append-only
- exact review comments with authorship and timestamps
- comment threads and disagreement chains
- diff hunks and file context
- repo conventions and code patterns
- who the comment was directed at
- whether feedback was blocking or advisory
- whether the author complied, pushed back, or ignored it
- what the human reviewer later added, removed, or softened

Lossy flattening destroys the review function.

## Metrics That Actually Matter

The top-line metric is not "sounds like them."
The top-line metric is agreement on novel work.

Primary metrics:

- blocker precision / recall
- approval-state accuracy
- issue-ordering agreement
- comment-selection agreement
- author-specific tone / strictness fit
- suggestion adoption rate

Secondary metrics:

- voice fidelity
- citation quality
- perceived usefulness
- latency and cost

Voice matters. Agreement matters more.

## Anti-Goals

Do not drift into these traps:

- generic "good code review" assistant behavior
- persona cosplay without predictive utility
- over-literal extraction of prior quotes
- flattening private and public contexts together
- treating all authors the same
- surfacing every possible issue instead of modeling reviewer policy
- building multiple product paths that do the same thing differently

If a design adds a second legacy review pathway, stop and refactor instead.

## Questions Every Review Feature Must Answer

Before shipping any review-oriented feature, answer:

1. What exact unit of prediction is being optimized?
2. Are we modeling private assessment, expressed feedback, or both?
3. What audience / relationship information is available?
4. What delivery-context information is available?
5. How is repo-specific precedent injected?
6. How does the output get measured against real human behavior?
7. What feedback from the human gets persisted back into the corpus?

If those answers are weak, the feature is probably demo polish rather than moat.

## Immediate Program Implications

Near-term work should bias toward:

- GitHub App end-to-end correctness
- `review_predictor_v1`
- reviewer-policy modeling
- audience-aware review prediction
- prediction-feedback persistence
- richer review evidence schemas
- MCP / Claude Code distribution that exposes the same structured review engine

Everything else is supporting infrastructure.
