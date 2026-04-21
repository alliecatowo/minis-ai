# Minis — Program and Execution System

> This document is the bridge between `docs/VISION.md` and day-to-day delivery.
> `VISION.md` says what the company is for.
> This document says how to decide what to build next.

---

## TL;DR

The product is **decision-framework cloning**.

That means the highest-value work is anything that improves our ability to:

1. capture the right evidence,
2. preserve it without loss,
3. extract the person's actual values, heuristics, motivations, and context shifts,
4. predict what they would say on novel inputs,
5. measure that prediction quality against reality.

Everything else is either:

- a distribution surface,
- a usability multiplier,
- or a supporting system.

Those things matter, but they are downstream of the moat.

---

## What Matters Most

When in doubt, prioritize work in this order:

1. **Evaluation truth infrastructure**
   We need to know whether the mini predicts the real engineer better after each release.
   If we cannot measure improvement, we are shipping vibes.

2. **Evidence fidelity**
   We need the right raw material:
   code review comments, decisions under conflict, goals, motivations, context-specific behavior, and private/public mode shifts.

3. **Framework extraction**
   We need structured outputs that are more legible than prose:
   principles, typology, motivations, behavioral context, decision ordering, and self-correction patterns.

4. **Application on novel inputs**
   The mini must use the extracted framework to judge new code, new tradeoffs, and new proposals.
   Retrieval alone is not enough.

5. **Productization**
   Chat UX, MCP, GitHub app, website, teams, orgs, and enterprise features matter once the core cognition loop is real.

If a proposed feature does not clearly improve one of those layers, it should either:

- be downgraded,
- be turned into a spike,
- or be cut.

---

## Program Ladder

### Layer 1 — Ground Truth

Goal:
Establish a top-line metric for whether a mini predicts the engineer's real feedback.

Success looks like:

- golden review/test cases per subject,
- repeatable eval runs,
- comparison against prior runs,
- agreement metrics that are easy to read in a release report.

What belongs here:

- fidelity harness improvements,
- review-agreement benchmarks,
- regression detection,
- curated gold datasets.

### Layer 2 — Evidence Quality

Goal:
Capture the most information-dense parts of a person's judgment and preserve them forever.

Success looks like:

- append-only raw evidence retention,
- context tags on evidence,
- quote/context survival across every pipeline path,
- AI-contamination controls,
- ingestion expansion into the surfaces where judgment actually appears.

What belongs here:

- source ingestion work,
- evidence schema improvements,
- context tagging,
- contamination detection,
- privacy-aware evidence handling.

### Layer 3 — Structured Human Model

Goal:
Represent the person in machine-usable form, not just as prose.

Success looks like:

- principles matrix,
- knowledge graph,
- typology outputs,
- motivations outputs,
- behavioral context outputs,
- later: decision ordering, self-correction history, and value drift.

What belongs here:

- extractors,
- schema contracts,
- aggregate reconstruction,
- structured persistence,
- extractor-specific evaluations.

### Layer 4 — Novel-Input Application

Goal:
Apply the model to unseen inputs and generate the person's likely response, not just retrieve similar past comments.

Success looks like:

- pre-review prediction,
- critique generation,
- approval/block reasoning,
- explanation chains from motivation → framework → judgment,
- context-aware response selection.

What belongs here:

- review tools,
- chat retrieval routing,
- code review products,
- github app behavior,
- human-in-the-loop grading flows.

### Layer 5 — Product Surfaces and Distribution

Goal:
Make the moat easy to try, easy to trust, and easy to buy.

Success looks like:

- dead-simple create-mini flow,
- compelling demo paths,
- MCP and Claude Code integration,
- clean API surface,
- team/org workflows,
- enterprise identity and retention story.

What belongs here:

- frontend polish,
- CLI/MCP/github-app productization,
- auth and ownership UX,
- billing/pricing surface,
- enterprise controls.

---

## Prioritization Rules

Prefer work that is:

- **moat-advancing** over merely impressive,
- **measurable** over plausible,
- **structured** over prose-only,
- **append-only** over destructive,
- **single-path** over dual-path,
- **reviewable in small PRs** over huge blended branches.

Deprioritize work that is:

- generic AI “assistant” behavior,
- aesthetic polish without a better demo funnel,
- architecture for architecture’s sake,
- a second implementation path for the same capability,
- research with no clear ticket trail back into product.

---

## Spike Protocol

A spike is a first-class deliverable, not a side conversation.

### When to use a spike

Use a spike when the question is any of:

- what is the right architecture?
- what is the right product model?
- what does the literature say?
- what is the right API/object model?
- what are the candidate implementation paths and tradeoffs?

### What a spike produces

A spike must produce:

1. a **Linear doc** or equivalent durable write-up,
2. a clear recommendation,
3. rejected alternatives,
4. concrete follow-up tickets,
5. a proposed sequencing order.

If a spike ends with “interesting” but no downstream tickets, it failed.

### What a spike must not do

A spike must not:

- silently become implementation work,
- ship speculative architecture directly to `main`,
- stop at broad observations,
- die inside chat history.

---

## Ticket Taxonomy

Use tickets aggressively and explicitly.

### Implementation ticket

Use for bounded, shippable work.

Expected output:

- one PR-sized slice,
- tests,
- clear dependency notes,
- no hidden “and also” scope creep.

### Spike ticket

Use for uncertainty reduction.

Expected output:

- durable write-up,
- recommendation,
- follow-up tickets.

### Epic / north-star ticket

Use for multi-PR programs where the actual work should be decomposed into several slices.

Expected output:

- sub-ticket map,
- sequencing order,
- explicit success metric.

---

## PR and Worktree Discipline

The default operating mode is:

1. create a fresh worktree from `main`,
2. make one bounded change,
3. run focused validation,
4. open a draft PR,
5. keep branches unmerged until they are reviewed and dependency order is clear.

This is preferred over:

- piling unrelated changes into one dirty tree,
- merging speculative work immediately,
- allowing local state to become the source of truth.

The PR queue is part of the project memory.

---

## Definitions of Done

### A foundation PR is done when

- the contract is explicit,
- tests prove it,
- later work can build on it without re-litigating structure.

### An extractor PR is done when

- it persists structured outputs,
- it has focused tests,
- it does not duplicate existing chief or spirit prose,
- it clearly improves the human model.

### An evaluation PR is done when

- it produces a comparable metric,
- it can be rerun,
- regressions are easy to spot.

### A product PR is done when

- it clearly helps someone try, trust, or buy the product,
- and it does not obscure the core moat.

---

## Current Strategic Gaps

At the time of writing, the most important unresolved gaps are:

1. **Review-prediction measurement is still not central enough**
   The vision is explicit, but the scorecard is not yet the center of release discipline.

2. **Identity semantics are still underspecified**
   The project still needs a clear answer to:
   what object is “my mini of you” versus “your mini of you” versus a canonical public mini?

3. **Context-aware application is incomplete**
   We now extract more context, but routing and retrieval still need to apply it properly at chat/review time.

4. **Product surfaces lag the cognitive core**
   MCP, GitHub app, API, frontend, and enterprise flows still need a more coherent story once the moat improves.

5. **Research must keep feeding implementation**
   Neuroscience / personality / ToM / decision-framework research is only useful if it becomes tickets and shipping slices.

---

## Canonical Next Steps

The default next-wave sequence should usually look like:

1. improve measurement,
2. improve evidence quality,
3. improve structured extractors,
4. improve novel-input application,
5. improve product surfaces.

In practice, that means:

- evaluation harness and review-agreement metrics,
- evidence/context/quote fidelity,
- typology / motivations / behavioral context / contamination / decision-ordering extractors,
- context-aware review and chat routing,
- API identity model, plugin surfaces, website/demo polish, team/org workflows.

---

## Anti-Goals

We are not trying to build:

- a generic coding chatbot,
- a prompt-engineered fake personality,
- a search engine over old quotes,
- a legacy-heavy platform with two ways to do the same thing,
- a research graveyard full of unshipped ideas.

We are trying to build:

- the best system in the world at predicting how a specific engineer would judge a new piece of work,
- and then scaling that up from individuals to teams, businesses, and institutions.

---

## For Future Agents

If you are choosing between:

- a feature that looks good in a demo,
- and a feature that improves review prediction or evidence fidelity,

choose the second one unless the first is a direct distribution unlock.

If you are unsure whether work is worth doing, ask:

1. Does this improve the model of the person?
2. Does this improve application of that model to new inputs?
3. Does this improve our ability to measure whether we got better?
4. Does this improve the path for a user or buyer to experience that value?

If the answer to all four is “no,” it is probably not important yet.
