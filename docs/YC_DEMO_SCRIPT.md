# YC Demo Script — Minis

> Total target time: 5 minutes. Every step has a hard ceiling. Do not overrun.
> The demo ends with the CTA. The Q&A is where partners probe — let them.

---

## Setup (before the meeting)

- Browser tab 1: minis.ai landing page (not the dashboard — the marketing home).
- Browser tab 2: the alliecatowo mini profile page, already loaded and signed in.
- Browser tab 3: a GitHub PR diff open in a GitHub tab (the fabricated diff from Step 3 below, or a real recent one with the Minis GitHub App installed).
- Browser tab 4: the review prediction scorecard UI for that PR.
- Browser tab 5: the agreement scorecard for alliecatowo (owner view, shows Blocker F1).
- Terminal: `backend/scripts/run_fidelity_eval.py` output ready to copy-paste if live metrics are needed.
- Fallback: if the live backend is down, have screenshots of each step saved locally.
- Do NOT pre-fill the diff in the chat box. Type it or paste it live — it reads more authentically than a pre-loaded page.

---

## The Story (narrated)

> Say this before touching the keyboard. About 30 seconds.

"Every engineering team has that one person whose review you actually want — the one who catches the thing that will bite you in production six months later, not just the style nit. The problem is they have a queue. They're in meetings. They're blocked by competing priorities. And when they leave the company, their judgment leaves with them.

Minis solves a different problem than Copilot. We're not generating code. We're cloning the decision framework of a specific engineer so we can predict — with measurable accuracy — what that engineer would say about a piece of code before they ever see it.

Let me show you."

---

## Step 1: The Product Claim (~30s)

**What you do:** Click to browser tab 1 (landing page). Scroll to the hero headline. Do not click anything yet.

**What they see:** The Minis landing page. The headline: something to the effect of "Predict the review before you request it."

**What you say:** "The claim on the page is intentional. We are not offering 'AI-powered code review' — every tool on earth says that now. We're offering a prediction: before you open that PR, before you tag a reviewer, before you schedule a review meeting — the mini tells you what your senior engineer would block on. That prediction is what we can actually measure and improve."

---

## Step 2: Navigate to the alliecatowo Mini (~30s)

**What you do:** Click to browser tab 2 (alliecatowo mini profile page).

**What they see:** The mini profile. Voice markers ("direct, architecture-first, prefers small reviewable PRs, blocks on missing tests"), the principles matrix summary, the framework highlights.

**What you say:** "This is alliecatowo's mini. The profile surfaces two distinct artifacts. First, the soul document: who this engineer is — communication style, values, what they care about deeply. Second, and more important: the decision framework. What triggers a blocker for them. What they soften for junior authors. What they let slide in a hotfix but not in a normal PR. The soul document is the demo. The decision framework is the product."

> Optional, if there's time: point to one specific principle from the matrix — e.g. "domain-boundary violations are always blockers, not suggestions."

---

## Step 3: Run a Review Prediction (~60s)

**What you do:** Click to browser tab 3 (GitHub diff or the /mini-review flow). If using the CLI or chat flow, paste or type the diff below. If using the GitHub App, navigate to a real PR with the App installed.

**Fabricated diff to use (Go, realistic):**

```diff
diff --git a/internal/webhook/handler.go b/internal/webhook/handler.go
@@ -1,12 +1,38 @@
 package webhook

+import (
+    "database/sql"
+    "encoding/json"
+    "fmt"
+    _ "github.com/lib/pq"
+)
+
+var db *sql.DB
+
 func HandleReviewEvent(w http.ResponseWriter, r *http.Request) {
     var event ReviewEvent
     if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
         http.Error(w, "bad request", 400)
         return
     }
-    log.Printf("received review event: %s", event.ID)
+
+    db, err := sql.Open("postgres", os.Getenv("DATABASE_URL"))
+    if err != nil {
+        http.Error(w, "db error", 500)
+        return
+    }
+
+    stmt, _ := db.Prepare("INSERT INTO review_events(id, payload) VALUES($1, $2)")
+    payload, _ := json.Marshal(event)
+    stmt.Exec(event.ID, payload)
+
+    w.WriteHeader(200)
 }
```

**What they see:** The prediction loading. A structured response with three sections: `private_assessment`, `delivery_policy`, `expressed_feedback`.

**What you say:** "Watch the structure. This is not a code review. It's a prediction of a code review. The private assessment is what alliecatowo actually thinks after reading the diff — the full internal monologue. Here she sees: a domain-boundary violation, the webhook handler is doing direct DB writes, that's a blocker in her framework. Missing error handling on the statement exec. And a connection opened on every request — that's a resource leak.

But then the delivery policy layer kicks in. It's a normal PR from a trusted peer. She's going to say the domain-boundary violation directly. She's going to ask about error handling. She's going to suppress the connection pooling note because it's recoverable and she doesn't want to pile on.

The expressed feedback is what she would actually write in the GitHub comment. Not every concern — the filtered projection of it, shaped by who she's talking to."

---

## Step 4: Show the Scorecard (~45s)

**What you do:** Click to browser tab 4 (the review prediction scorecard UI for this PR). Point to the three structured sections.

**What they see:** A rendered scorecard with:
- `private_assessment`: blocking issues (domain-boundary-leak, missing-error-handling), non-blocking issues (connection-per-request), open questions.
- `delivery_policy`: author model = trusted_peer, delivery_context = normal.
- `expressed_feedback`: two blockers expressed, one suppressed, approval_state = request_changes.

**What you say:** "Three fields. Private assessment: everything she noticed. Delivery policy: the lens that decides what to say. Expressed feedback: what goes in the comment. The gap between the private assessment and the expressed feedback is where judgment lives. A generic AI code review collapses that gap. Minis models it explicitly, because that gap is what makes the prediction testable — we can check whether the blockers we predicted match the blockers she actually raised."

---

## Step 5: Show the Calibration Metric (~30s)

**What you do:** Click to browser tab 5 (the agreement scorecard, owner view). Point to the Blocker F1 score.

**What they see:** The agreement scorecard. Metrics: `cycles_count`, `approval_accuracy`, `blocker_precision`, `blocker_recall`, `blocker_f1`. A trend indicator.

**What you say:** "This is the number that matters. Blocker F1. It measures how well the prediction overlaps with what she actually blocked on when she later reviewed the same type of change. It's not vibes — it's precision and recall against ground truth. Every time a mini's prediction diverges from the actual review, that delta becomes new evidence. The framework gets recalibrated. The next prediction is sharper. This is the flywheel. The corpus compounds."

> If asked for a specific number: "We're currently running gold review cases with an average blocker F1 in the 0.7–0.8 range against held-out cases. The eval harness is in the repo."

---

## Step 6: The Outcome Loop — When the Real Review Comes In (~30s)

**What you do:** Stay on tab 5, or navigate to show the prediction feedback memory concept. You can describe this verbally if the UI isn't live.

**What they see:** The concept of PredictionFeedbackMemory — or if live, a summary of recent agreement deltas.

**What you say:** "Here's what happens when alliecatowo actually reviews the PR. Her real review comes in — via GitHub webhook. We compare it to our prediction. Where she blocked and we predicted she'd block: positive signal, that framework's confidence goes up. Where she let something through that we called a blocker: negative signal, we recalibrate. The prediction record is append-only. The corpus compounds. Over 10, 20, 50 review cycles, the mini's framework is tighter than what you'd extract from reading her PRs manually. The more she reviews, the better her mini gets — without her doing anything."

---

## Step 7: "Create Your Own" CTA (~30s)

**What you do:** Navigate to the sign-in / create mini flow. Do not complete it — just show the GitHub OAuth entry point and the "Create mini from @username" input.

**What they see:** GitHub sign-in button. A username input. The pipeline starting.

**What you say:** "You can create your own mini right now. Sign in with GitHub. We analyze your public commits, PRs, review comments — the actual behavioral record of how you work. The pipeline runs in a few minutes. You get a mini that can predict your review before you're even tagged. The first audience for Minis is you: cut your review queue by routing the obvious cases through your mini first, and spend your time on the decisions that actually need you."

---

## 5 Anti-Patterns — Things NOT to Say in This Demo

**1. "It's like GitHub Copilot but for code review."**
No. Copilot generates code. We predict human judgment on code. They're orthogonal products. Copilot is a writing tool. Minis is a prediction tool. Don't invite a comparison that frames us as a slower Copilot.

**2. "It learns your style."**
Style is the least interesting thing we clone. Say "decision framework" or "review judgment" instead. Style is voice. We're cloning what they block on, what they soften, who they adjust for. "Style" signals we're a persona generator, not a framework cloner.

**3. "The AI writes the review for you."**
The engineer still writes the review. The mini predicts it. These are different. We are not removing the human from the loop — we're making the loop faster and measurable. Say "predicts" not "writes."

**4. "It's trained on your data."**
We do not fine-tune. This is prompt-based synthesis over an evidence corpus. "Trained" implies a model weight update and raises compliance/IP questions that we don't have and don't need. Say "synthesized from" or "built from your behavioral evidence."

**5. "It'll get the review right every time."**
Never claim perfection. The metric is F1 score, not correctness. We're building a calibrated prediction, not an oracle. If a partner asks about accuracy, anchor on the Blocker F1 metric and the trend line — "it gets sharper over time" is a stronger claim than any fixed percentage.
