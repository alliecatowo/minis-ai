# Minis YC Demo Script

## Purpose

This is the founder-grade demo path for YC and early design partners. It should
sell the shipped direction without implying the product is more automatic,
measured, or enterprise-ready than it is.

The claim to defend:

> Minis predicts the review judgment of specific senior engineers on novel
> work, then instruments the gap between prediction and human review so the
> decision framework can improve over time.

Do not demo this as a generic AI reviewer, personality bot, or code-generation
assistant. Voice makes the output legible. Review-grade decision prediction is
the product.

## Status Legend

| Status | Meaning | Demo rule |
| --- | --- | --- |
| Shipped | Exists on current main and can be shown from current repo surfaces | Show directly |
| PR-pending | Implemented or documented in a pending/recent PR path, but not safe to claim as universally available | Mention as gated/in review |
| Future | Needed for the full product narrative, not yet shipped | Say "this is where it goes next" |

## Product Truth Table

| Capability | Status | Current anchor | Demo phrasing |
| --- | --- | --- | --- |
| Create a mini from GitHub evidence | Shipped | UI/API/MCP `create_mini`; GitHub ingestion stores raw evidence with provenance fields such as source, item type, external id, hashes, and timestamps | "We build from the evidence that shaped this engineer's judgment." |
| Claude Code evidence ingestion | Shipped, private-data sensitive | `claude_code` ingestion source and explorer; evidence marked private | "When authorized, local Claude Code sessions are high-signal private evidence. We paraphrase private evidence; we do not quote it verbatim." |
| Chat with a mini | Shipped | Web/API/MCP `chat_with_mini` | "Chat is the easiest way to inspect the framework; it is not the end product." |
| GitHub App reviewer mode | Shipped | Requested-review auto-review, `@username-mini` PR mentions, structured review prediction call | "When a PR requests a reviewer who has a mini, the app can post that reviewer's predicted feedback." |
| Relationship-aware delivery policy | Shipped | `author_model`: `junior_peer`, `trusted_peer`, `senior_peer`, `unknown`; GitHub permission and author-association hints | "The same private assessment becomes different public feedback depending on who wrote the PR." |
| No-fallback gated review states | Shipped | `prediction_available`, `mode`, `unavailable_reason` in review prediction and MCP response | "If the system does not have enough signal, it says so instead of fabricating certainty." |
| Evidence provenance on review signals | Shipped | `framework_signals`, `evidence_provenance`, `provenance_ids` in review prediction structures | "Every claim should trace back to source evidence or stay low-confidence." |
| MCP / Claude Code pre-review path | Shipped | `mcp-server` tools `predict_review` and `get_decision_frameworks`; README Claude Code workflow | "Authors can ask for the predicted senior review before they request the human." |
| Gold fidelity evals | Shipped | `backend/eval` golden subjects and `docs/FIDELITY_EVAL.md`; non-blocking CI comment for synthesis/eval changes | "We measure framework and agreement quality on source-annotated gold cases." |
| Closed-loop GitHub outcome capture | PR-pending / gated | Human review outcome recording; `GH_APP_OUTCOME_CAPTURE` reaction and reply handlers are gated | "This is the loop we are turning on carefully: prediction, human outcome, delta, confidence update." |
| Agreement scorecard as product dashboard | Shipped metric / Future dashboard | Eval scorecards and review-cycle metrics exist; durable user-facing dashboard is not complete | "We can compute the metric; the customer-facing surface is still coming." |
| Enterprise knowledge retention | Future product tier | Vision and evidence architecture support it; enterprise controls are not complete | "The long-term buyer value is retained judgment, but we earn that by proving IC review prediction first." |

## Demo Setup

Use a seeded mini and a seeded PR. Do not rely on live ingestion during the YC
demo unless the environment has already been rehearsed.

Required artifacts:

- A mini with enough GitHub review evidence to produce non-gated review
  predictions.
- A PR or PR-shaped fixture with changed files, title, body, diff summary, and
  a requested reviewer who maps to that mini.
- A visible GitHub App comment or MCP `predict_review` output that includes
  `private_assessment`, `delivery_policy`, `expressed_feedback`,
  `prediction_available`, `mode`, and provenance/framework signals where
  available.
- One gated example where Minis refuses to predict because evidence is
  insufficient.
- One eval report or scorecard excerpt from gold cases. If the score is not
  strong, show the instrumentation rather than claiming performance.

## The Five-Minute Flow

### 1. Open on the Bottleneck, Not the Bot (30 seconds)

Action:

Show a senior engineer's review queue or a PR waiting on a named reviewer.

Talk track:

"Every engineering org has a few people whose judgment determines whether work
ships safely. The problem is not that they type review comments too slowly. The
problem is that their decision framework is trapped in their head. Juniors wait
for it, teams route around it, and when that person leaves the company loses
years of calibrated judgment."

"Minis is built to clone that decision framework, not their personality. We
start with code review because it is high-value, repeated every day, and
measurable against ground truth."

What not to say:

- Do not say "we replace senior engineers."
- Do not say "we know exactly what they would say."
- Do not say "this is trained on private data" unless the demo subject has
  explicitly authorized that data.

### 2. Show the Evidence Model (45 seconds)

Action:

Show the mini profile, graph/principles view, or MCP `get_decision_frameworks`
output. Point to source/provenance fields and confidence where visible.

Talk track:

"The model is built from evidence that actually contains judgment: commits, PR
threads, review comments, repo context, and, when authorized, private Claude
Code sessions. Raw evidence is retained with provenance. Derived summaries do
not replace the source."

"What we want out is not a pile of quotes. We extract reusable rules: what this
reviewer tends to block, what they ignore, when they soften feedback, and what
evidence supports that inference."

Risk phrasing:

"If evidence is thin, stale, private, or contaminated by AI-generated text, that
must lower confidence. The correct product behavior is to gate or caveat the
prediction, not hallucinate a senior engineer's authority."

### 3. Predict a Senior Review in GitHub (90 seconds)

Action:

Open the seeded PR. Show the GitHub App comment produced for the requested
reviewer, or trigger the same review through a `@username-mini` mention if the
webhook path is stable.

Talk track:

"This is the IC product. Before the human senior gets to the queue, the author
gets a prediction of what that senior is likely to care about on this diff."

"The important part is the structure. First, Minis forms a private assessment:
likely blockers, non-blocking concerns, open questions, and positive signals.
Then it applies a delivery policy: is the author junior, a trusted peer, a
senior peer, or unknown? Is this a hotfix or normal feature work? Finally it
renders the expressed feedback the reviewer would likely choose to say."

"That matters because good reviewers do not say everything they notice. A
senior may suppress low-value nits for a trusted peer, or turn the same concern
into a teaching comment for a junior. Minis models that policy instead of
spraying generic lint."

Product proof to point at:

- `author_model` or delivery policy in the output.
- `prediction_available: true` and `mode` when the system has enough signal.
- Framework or provenance signals behind a blocker.
- Approval state such as approve, comment, request changes, or uncertain.

### 4. Show the Gated State (30 seconds)

Action:

Switch to a reviewer or PR where the prediction is unavailable.

Talk track:

"The failure mode matters. If Minis cannot make a grounded prediction, the
right answer is not a generic review. The contract exposes
`prediction_available`, `mode`, and `unavailable_reason`, so downstream surfaces
can show 'not enough evidence' instead of laundering uncertainty into advice."

"This is also how we avoid overclaiming. We are not saying every mini is useful
on day one. We are saying usefulness should be gated by evidence and measured
by agreement."

### 5. Show the Author Workflow in Claude Code / MCP (45 seconds)

Action:

Show the MCP README prompt or run a prepared MCP `predict_review` output in
Claude Code.

Talk track:

"The GitHub App is the review surface. MCP is the author surface. Before I ask
Priya for review, I can ask: what would Priya likely block on here? That turns
senior attention into a force multiplier. Priya spends less time catching
predictable pattern violations and more time on the hard calls only she should
make."

"This is not code generation yet. It is pre-review. The author still owns the
change and the human still owns approval."

### 6. Show the Eval Loop (60 seconds)

Action:

Show a gold eval report or scorecard excerpt. If available, show one predicted
review next to the eventual human review.

Talk track:

"The metric is not vibes or voice similarity. The metric is reviewer agreement:
did we predict the blocker, the approval state, the comment selection, and the
ordering of issues the human actually cared about?"

"Gold evals give us repeatable regression checks. The closed loop goes further:
the mini predicts, the human reviews, the delta is captured, and confidence in
the underlying framework moves up or down. That is the compounding product."

PR-pending caveat:

"Some outcome capture is gated while we validate the trusted-service boundary
and avoid writing noisy outcomes into the corpus. For YC, show the loop as
instrumented and partially gated, not fully autonomous."

### 7. Close on Enterprise Retention (30 seconds)

Action:

Return to the senior engineer's queue or show the framework profile.

Talk track:

"The wedge is IC velocity: instant calibrated pre-review. The team value is
senior focus: the best engineers stop being a queue for predictable feedback.
The company value is retained judgment: once these frameworks are captured and
improved through real review outcomes, the org keeps access to institutional
knowledge when people move teams, go on leave, or eventually leave the company."

"We do not get to claim enterprise retention until review prediction is trusted.
That is why the demo starts with a PR and ends with agreement metrics."

## Risk and Ethics Language

Use this language when asked about replacement, consent, privacy, or accuracy.

- Replacement: "Minis does not approve code and does not replace the human
  reviewer. It predicts likely feedback so humans spend attention on higher
  leverage decisions."
- Consent: "Private sources such as Claude Code transcripts require explicit
  authorization. Public evidence and private evidence must stay labeled
  differently."
- Privacy: "Private evidence may inform a framework, but should not be quoted
  verbatim in user-facing output."
- Accuracy: "Predictions should expose confidence and provenance. Low-signal
  cases should gate instead of producing authoritative-sounding advice."
- Fairness to authors: "The mini should help authors prepare for review, not
  create a hidden surveillance score. Human reviewers remain accountable for
  final feedback."
- Founder overclaim guard: "Today we can show review prediction and the
  measurement loop. Full enterprise knowledge retention is the direction, not a
  current deployment claim."

## What Must Be True Before Showing YC or Users

Minimum for a YC live demo:

- A seeded PR reliably produces `prediction_available: true` for the chosen
  reviewer.
- The output includes relationship/delivery context, not just generic review
  prose.
- At least one blocker or open question has visible framework/provenance
  support.
- A separate insufficient-evidence case reliably gates.
- The eval artifact shown is from a real run or is clearly labeled as a fixture.
- The talk track distinguishes shipped, PR-pending, and future capabilities.
- No private Claude Code or local evidence is shown without explicit consent.

Minimum for an external user pilot:

- GitHub App installation and webhook flow are stable for the pilot repo.
- Reviewer identity resolution is reliable enough to avoid posting as the wrong
  mini.
- Outcome capture is either disabled or gated behind an explicit pilot flag.
- Private evidence handling is documented for the pilot user.
- The pilot has a gold or held-out review set so agreement can be measured.
- The UI or bot copy makes uncertainty and non-approval status obvious.

## Demo Blockers That Need Tickets

Filed before this doc shipped:

- `MINI-225` - Seeded YC demo workspace with one reliable non-gated PR, one
  gated PR, and one eval artifact.
- `MINI-226` - GitHub App reviewer identity hardening for demo/pilot repos,
  including explicit fallback behavior when requested reviewer lookup is
  ambiguous.
- `MINI-227` - User-facing evidence/provenance display for review predictions,
  so demo viewers can see why a blocker was predicted.
- `MINI-228` - Pilot-safe outcome-capture gate and runbook for when
  `GH_APP_OUTCOME_CAPTURE` can be enabled.
- `MINI-229` - YC demo eval fixture refresh from current gold cases with a
  dated report and "fixture vs live" labeling.
