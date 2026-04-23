# Minis: YC Pitch

## The Problem (30 sec)
The highest-leverage feedback in any engineering organization is code review. But human attention is the ultimate bottleneck. The best engineers hold complex, hard-won decision frameworks in their heads, and everyone else has to wait in a queue to get access to them. When those engineers leave, their frameworks are lost forever. We accept this as a necessary tax.

## The Product (60 sec)
Minis doesn't just mimic a developer's voice. We clone their underlying **decision framework** so we can predict exactly what they would say on novel code. 

When a PR is submitted, Minis processes it through a three-layer review stack:
1. **Private Assessment:** What does the engineer actually think? (Identifying bugs, risks, missing tests, naming concerns.)
2. **Delivery Policy:** How does this engineer adjust their feedback based on the audience? (Are they mentoring a junior or speaking to a peer? Is this a hotfix or normal work?)
3. **Expressed Feedback:** What do they actually choose to write in the review comment?

This means ICs get instant, highly calibrated feedback before they ever ask for a human review, and senior engineers get their review queues cut in half.

## The Demo
- **GitHub App PR reviews:** An AI-generated review that doesn't just say "LGTM", but surfaces specific, framework-driven blocking issues or nitpicks.
- **Chat for architectural decisions:** Asking a senior engineer's mini to pre-review an architectural proposal, identifying cross-team friction before a meeting is even scheduled.

## Why Now
LLMs have finally reached the capability where they can synthesize complex behavioral frameworks from unstructured exhaust (PRs, commits, Slack). We now have the infrastructure to evaluate fidelity and correctness against ground truth.

## The Moat
Our moat is the **Closed-Loop Agreement Signal**. Unlike generic coding assistants that compete on the size of their training set, we compete on the density of the feedback loop. 

Because we have an append-only evidence corpus and a continuous stream of actual GitHub reviews, we can measurably prove that our minis are getting more accurate at predicting their human counterpart's judgment over time. 

Every time an engineer overrules or confirms a mini's prediction, we capture a high-fidelity delta. That delta isn't just a log entry—it's new evidence that re-calibrates the decision framework. The flywheel doesn't just make the model better; it makes the **clone** more precise without us writing a line of code.

## The Scoring Engine
We don't optimize for vibes; we optimize for metrics. Our fidelity evaluation harness measures:
- **Blocker Precision/Recall:** How often does the mini correctly identify an issue that would actually block a PR?
- **Approval-State Accuracy:** Does the mini correctly predict if the engineer would Approve, Request Changes, or Comment?
- **Decision Divergence:** Identifying the exact delta between a mini's prediction and the human's eventual review to close the learning loop.

## Traction / Metrics
Our north star is **reviewer agreement**. It's not about sounding like the engineer, it's about predicting what they would actually block, approve, or comment on. We track precision, recall, and approval-state accuracy via a rigorous fidelity evaluation harness.

## Market
- **Tier 1 (IC Velocity):** Dramatically reduce cycle time by giving developers instant access to senior feedback.
- **Tier 2 (Team Force-Multiplier):** Pre-triage tickets, virtualize cross-team alignment, and drastically reduce the coordination tax.
- **Tier 3 (Enterprise Knowledge Retention):** When a staff engineer leaves, you don't lose the $2M you invested in their judgment. Their decision framework stays behind, answering architecture questions long after they're gone.
