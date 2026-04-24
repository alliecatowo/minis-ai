# Minis: Demo Script

## 1. Create a mini (30s)
*Action: Trigger the creation of a mini from a GitHub profile in the UI/CLI.*
**Talking Track:** 
"We start by ingesting the evidence that actually shapes review behavior: commits, PRs, review comments, and repo context. This is not a personality demo. Our pipeline builds a reviewer model that learns what this engineer tends to notice, what they ignore, what they block on, and how they tailor feedback to different authors."

## 2. Ask "hottest engineering take?" (30s)
*Action: Query the newly created mini in the chat interface: "What is your hottest engineering take?"*
**Talking Track:**
"Voice is the demo, but preserved judgment is the product. When we ask for a hot take, we are really testing whether the model can explain the reviewer's underlying framework: maybe they bias toward explicit types, narrow abstractions, or heavy test coverage. The point is not tone matching. The point is whether it can surface the reasoning pattern that will show up later in review."

## 3. Get a PR review prediction (60s)
*Action: Show a PR in GitHub where the Minis GitHub App has posted a review.*
**Talking Track:**
"This is the flagship loop. A junior engineer opens a PR and the mini predicts the review before the human reviewer arrives. Notice the structure:
First, the **Private Assessment** captures what the reviewer actually thinks after reading the diff.
Second, the **Delivery Policy** decides how much of that to say out loud for this specific author and context.
Finally, the **Expressed Feedback** becomes the public review comment. It is not generic lint and it is not a persona roleplay. It is a prediction of this engineer's actual review function on novel work."

## 4. Ask about an architectural decision (30s)
*Action: In the chat or a design doc, ask the mini to weigh in on migrating an auth service.*
**Talking Track:**
"This is where pre-review turns into workflow acceleration. Before scheduling a meeting with three different teams, we ask their minis to review an auth migration proposal. The infra mini flags a Terraform state issue based on past incidents, while the mobile mini asks for rollout lead time. We resolve most of the predictable disagreement asynchronously and escalate only the decisions that still need real human judgment."

## 5. The Agreement Scorecard (30s)
*Action: Show a terminal or dashboard displaying the output of `backend/scripts/calculate_review_agreement.py`.*
**Talking Track:**
"We do not optimize for vibes; we optimize for agreement. This is the Agreement Scorecard. For every mini, we track how often its prediction matches the human engineer's eventual review. We measure Approval Accuracy, Blocker Precision, and Comment Overlap. When the human overrules the mini, that delta becomes new evidence for the next synthesis. That closed loop is how we improve prediction quality without replacing the reviewer."
