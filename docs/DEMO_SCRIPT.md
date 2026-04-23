# Minis: Demo Script

## 1. Create a mini (30s)
*Action: Trigger the creation of a mini from a GitHub profile in the UI/CLI.*
**Talking Track:** 
"We start by ingesting the digital exhaust of an engineer—commits, PRs, reviews, and design docs. This isn't just indexing their code. Our pipeline runs a set of parallel explorer agents that read the code, extract behavioral quotes, and build a structured knowledge graph and principles matrix. This takes just a few minutes."

## 2. Ask "hottest engineering take?" (30s)
*Action: Query the newly created mini in the chat interface: "What is your hottest engineering take?"*
**Talking Track:**
"Voice is the demo, but framework cloning is the product. When we ask for a hot take, it doesn't just retrieve a past quote. It synthesizes their extracted values—maybe their preference for explicit types over runtime flexibility, or their hatred for ORMs—and articulates the underlying framework that drives those opinions."

## 3. Get a PR review prediction (60s)
*Action: Show a PR in GitHub where the Minis GitHub App has posted a review.*
**Talking Track:**
"Here is where the magic happens. A junior engineer submits a PR. The mini predicts the review. Notice the structure:
First, the **Private Assessment** identifies three issues. 
Second, the **Delivery Policy** recognizes this is a junior developer, so it filters the feedback to avoid overwhelming them.
Finally, the **Expressed Feedback** is posted as a comment. It blocks on a missing test constraint and suggests a specific internal hook they missed. It's not a generic Copilot lint—it's exactly what the senior engineer would have said."

## 4. Ask about an architectural decision (30s)
*Action: In the chat or a design doc, ask the mini to weigh in on migrating an auth service.*
**Talking Track:**
"Finally, we can use this for cross-team coordination. Before scheduling a meeting with three different teams, we ask their minis to review an auth migration proposal. The infra mini flags a Terraform state issue based on a past incident, while the mobile mini requests a 6-month lead time. We've just resolved 80% of the cross-team friction asynchronously, without taking a single minute of human attention."
