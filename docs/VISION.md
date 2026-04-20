# Minis — The North Star

> This document is load-bearing. Every Claude Code session, every subagent, every PR is tested against whether it moves us toward this vision. If you are an agent reading this, internalize it — do not reinvent it.
>
> **Read this before reading CLAUDE.md. Read CLAUDE.md before touching code.**

---

## Table of Contents

1. TL;DR — The One-Liner
2. The Problem (make it hurt)
3. The Thesis (decision frameworks, not voice)
4. The Product — 5 Tiers
5. The Technical Moat
6. User Journeys (day-in-the-life for each tier)
7. Business Model
8. Go-To-Market
9. Competitive Landscape — a teardown
10. Guiding Principles
11. Why Now
12. Why Us
13. Risks and Mitigations
14. What This Document Is NOT
15. When Reading This As An Agent
16. Closing — To The Reader

---

## TL;DR — The One-Liner

**Minis clones the decision-making frameworks of engineers so their teams, companies, and institutions can keep leveraging those frameworks long after the engineer isn't available to apply them in person.**

Voice and personality are the demo. Decision-framework cloning is the product.

The demo is what gets a developer to try it. The framework cloning is what makes a VP of Engineering write a check. The retention story is what makes the enterprise buyer sign a multi-year contract. Each tier of the product is a fully-formed business in its own right, and each tier is strictly necessary for the tier above it to exist. The IC pitch is the front door; the enterprise pitch is the castle. You do not skip to the castle. You build the door well, and the door becomes a hallway, and the hallway becomes a floor, and eventually — after years of compounding corpus, compounding trust, compounding fidelity — the castle builds itself out of floors that were already lived in.

That is the shape of the business. That is the shape of this document.

---

## The Problem

The problem is not that engineers are slow. The problem is that the current distribution of engineering attention is so catastrophically lopsided that the top 5% of engineers in any given organization function as human bottlenecks for the other 95%, and neither the bottlenecks nor the blocked are happy about it. Every modern engineering organization is quietly running on the same broken throughput equation: one senior, some number of juniors, and a queue of decisions that only the senior has enough context to make quickly.

Let us make that concrete. Let us name names.

### Priya, the senior engineer drowning in reviews

Priya is a staff-level backend engineer at a Series-B startup. She has been there for four years. She knows which of the three notification services handles idempotency and which one silently double-fires if you retry. She knows the exact reason the payments service avoids the ORM for one specific write path. She remembers the three design meetings that ruled out GraphQL and why everybody who was there nodded, and she is the only person on the team who was there.

It is 3:47 PM on a Wednesday. Priya has been in meetings since 10:00 AM. Since she opened her laptop this morning she has read exactly seventeen lines of production code, and those were lines in a Slack thread someone pasted at her. Her calendar for tomorrow shows six meetings. Her GitHub dashboard shows fourteen PRs awaiting her review. Two of them have been open for five days. One of them is the thing blocking the mobile team's entire sprint. One of them is from a junior who has obviously not read the CONTRIBUTING.md she wrote eight months ago and who is about to get feedback — *again* — that could have been prevented by reading it.

Priya is not a bottleneck because she is slow. She is a bottleneck because she is the only person in the building who can look at a PR to the payments service and immediately see that the new write path is going to lose money under a specific retry condition. And that knowledge — the knowledge that makes her valuable — is the *same knowledge* that makes her a queue. The company cannot scale past her review bandwidth without either (a) promoting someone to her level, which takes years, or (b) accepting that the rest of the team will ship slower. They chose (b) because they didn't realize they were choosing. They just noticed, a quarter later, that velocity had declined.

Priya is not being served by Copilot. Copilot reviews for generic best practices; Priya's review is a seven-dimensional calibration against this codebase's history, this team's values, and this company's risk tolerance. Copilot cannot say "this is going to lose money on retry." Priya can. Priya is the only one who can. And she is in her third meeting of the day.

### Sarah, the IC waiting on her senior

Sarah joined the company two months ago. She is a strong engineer — she would not have gotten the offer otherwise. She is working on her fifth PR. It is 3:00 PM on a Wednesday. She just pushed. She is excited about the work; it solves a real problem, and she used a pattern she is proud of.

Her senior — Priya — will not look at the PR for at least eighteen hours. Priya is in meetings. Priya has a review queue. Priya is a wonderful mentor when she has the time, and she does not have the time today.

So Sarah sits. She does what every IC in this situation does: she picks up the next ticket, starts the next PR, and tries to hold her place in her head on the first one so that when feedback comes she can context-switch back in. Tomorrow at 9:30 AM, Priya's review will arrive. It will contain three small nits that Sarah genuinely couldn't have predicted, and one big one — "we already have a pattern for this, see `src/hooks/useDataQuery.ts`" — that Sarah absolutely could have predicted if she had known to ask. Sarah will spend forty minutes fixing the PR, push again, and wait another thirty-six hours for a follow-up review because by then Priya is in the middle of a different firefight.

Sarah's first PR shipped in eleven days. Her fifth PR will ship in nine. Her fifteenth will ship in six. At the rate she is learning Priya's frameworks by absorption, she will be reviewing at Priya's fluency sometime in year three. In year one and year two, she will be approximately half as productive as she would be with instant calibrated feedback, and nobody will notice because her teammates are all in the same boat.

Multiply Sarah by ten engineers. Multiply that by every company in the world. This is the tax.

### Dev, the VP of Engineering watching onboarding bleed

Dev is the VP of Engineering at a 300-person company. Last quarter, his staff engineer — call him Marcus — left for a competitor. Marcus had been there six years. Marcus wrote the auth service. Marcus was the reason the payments service had the idempotency guarantees it has. Marcus was the reason Dev's team could deploy on Fridays without panicking.

Marcus gave four weeks' notice. In those four weeks, Marcus did heroic work: he documented the auth service (forty pages of Markdown), recorded two hours of Loom walkthroughs, wrote up the three architectural decisions he was most worried about, and pair-programmed with his replacement for two days. It was a model offboarding. Dev was proud of it. Dev told the board it was fine.

It is not fine. Six months post-Marcus, Dev's team is still discovering things Marcus knew that nobody else knew. The new staff engineer — fresh from FAANG, genuinely talented — keeps running into walls. She asks questions Slack cannot answer. She ships a refactor that breaks an invariant Marcus established in a design meeting in 2022, a design meeting for which no notes exist, a design meeting Marcus would have referenced from memory if he were still around. The refactor costs two weeks of cleanup and a near-incident.

Dev's onboarding metric for a new staff engineer used to be six months. This year it is closer to nine. The team's velocity is down eighteen percent year-over-year. The board has started asking questions. Dev cannot say, on the record, "we lost Marcus and we are still bleeding from it" because that is not the kind of thing you can say when the board wants cost cuts. But he knows. His skip-levels know. His tech leads know. Everybody knows.

One staff engineer leaving equals approximately five person-years of institutional knowledge walking out the door. Documentation captures maybe ten percent of that. The rest is gone the moment the laptop gets returned. Every post-RTO, post-layoff, post-hype-cycle year this problem gets worse. Every company that has ever lost a key engineer knows this pain. Nobody has solved it. Docs rot. Wikis sag. Confluence is where knowledge goes to die.

### The coordination tax

Three teams need to agree on the auth migration. Auth owns the tokens, platform owns the SDK, infra owns the identity provider. Scheduling the meeting takes four days. Somebody drops, the meeting gets rescheduled. Somebody else joins who was not in the pre-read. The meeting itself is ninety minutes of catching everybody up, twenty minutes of actual discussion, ten minutes of "let's take this offline." Two weeks later, another meeting. Four weeks later, a decision.

Call this the coordination tax. It is not visible on any line of the budget. It does not appear in any OKR. It shows up as lost velocity, as "we're blocked on the auth team," as the slow erosion of ambition that happens when every cross-team project starts looking too expensive to bother with. Coordination cost scales super-linearly in the number of teams involved. Three teams is not three times worse than one team; it is closer to nine times worse, because each team has to track the others' positions, re-derive them whenever a participant changes, and absorb the context-switching cost of every async back-and-forth. By the time you get to six teams you have a standing weekly that produces nothing, and the company has implicitly decided to stop attempting cross-cutting work because it is too painful.

This is the silent killer of scale. Not bugs. Not tech debt. Coordination tax.

### Mateo, the mid-level engineer who gave up asking

Mateo has been at the company for eighteen months. He is competent. He ships. He has learned the rhythm of the codebase and the rhythm of the team. He has also learned, slowly and without ever formally deciding it, that asking questions has a cost. Every time he asks Priya something in Slack, he feels the friction — she is busy, he is interrupting, his question is small. So he stops asking. He works around the gaps in his knowledge. He makes best-guesses. He ships code that is eighty-percent-right because asking for the twenty-percent correction feels expensive.

This is invisible damage. Mateo's code ships. His metrics look fine. His manager would tell you he is a solid contributor. But every PR he writes is a little less calibrated than it could be, every design doc a little less rigorous, every architectural choice a little closer to "what I can justify" rather than "what is actually right." He is learning the framework by absorption — which is the slowest possible way to learn a framework, because it filters out everything he does not think to ask about.

The cost here is not Mateo's time. The cost is the *quality* of his output, decaying imperceptibly over months. Multiply Mateo by every mid-level engineer at every company and you have an enormous latent productivity gap that nobody talks about because nobody can measure it. Everyone is shipping. Everyone is busy. The code is slightly worse than it should be, and nobody can point to a specific decision and say "that is where it went wrong." The aggregate effect is a team that is slightly less coherent than a team with tight feedback loops would be, and the gap compounds the longer the team runs without correction.

Minis fixes Mateo not by adding another human to ask, but by making the asking cost-free. Mateo's "is this the right pattern?" question, asked to Priya's mini, costs Priya zero attention and Mateo zero social capital. The answer comes back in thirty seconds. Mateo learns. Mateo ships better. The compounding negative flips positive.

### The knowledge-retention crisis

The half-life of engineering institutional knowledge inside a modern company is now somewhere around thirty-six months, and falling. Tenure is down. Layoffs are frequent. The post-RTO, post-hype-cycle workforce is more mobile than it has been in decades. Every company that relies on senior-engineer judgment — which is every company — is watching its intellectual capital evaporate at the exact moment competitors are trying to move faster with less.

The current toolbox for this problem is pathetic. You write docs (engineers don't read them, and the ones who would are gone). You run knowledge-transfer sessions (attendance drops every week). You pair-program (works, but doesn't scale). You hope the wiki catches it (it doesn't). You accept the loss and budget an extra quarter onto every onboarding plan.

None of this is a product. All of this is prayer.

### What these problems have in common

Three problems, one shape: a small number of humans hold a disproportionate share of the judgment, and the rest of the org has to wait on them, work around them, or do without them. The bottleneck is not tooling or process. The bottleneck is human attention. The cost is compounding. The solutions on offer — Copilot for generic code review, Confluence for docs, exit interviews for knowledge transfer — are all targeting symptoms.

We are going to target the disease.

---

## The Thesis

### Decision frameworks, not voice

When you ask a human expert about something they have never seen before — a weird bug, a tricky architectural tradeoff, a novel design proposal — they do not retrieve from memory. They *apply a framework*. "I check X first. If Y, I worry about Z. I have learned to distrust A because of the time I got burned on B. When I see this pattern, I ask these three questions. If the answers are the answers I expect, I approve. If they aren't, I ask a fourth question. I have never seen exactly this situation, but I have seen six things that share three of its properties, and from those I can derive my position in forty seconds."

That is the skill. That is what makes a senior senior. It is *not* the set of answers they have given before; it is the *function* that takes novel input and produces calibrated output. Anyone can Google an answer. Only the person who has actually developed the framework can apply it correctly to a case they have not seen.

Today, Minis does retrieval-and-narrate: "In my project called X I did Y." That is useful for "what's your take on [well-trodden topic]?" but it is, functionally, search-over-quotes with a little more personality in the output. It is what GitHub Copilot Spaces will do next year. It is what any competent competitor with a vector DB and a good prompt will do within six months. It is not a moat.

What makes Minis the moat — what makes it a ten-year-defensible product rather than a one-year feature — is **producing the critique, questions, and approval criteria the person would produce on a novel input, grounded in the review function they have demonstrated on their past reviews.** It is cloning the *function*, not the *answers*. Everything else we ship is in service of that.

### Retrieve-and-narrate versus framework cloning — the concrete difference

Consider a real example. Someone asks Alice's mini about Rust.

**Retrieve-and-narrate (today, functionally):**

> Alice has worked extensively with Rust on a project called X. In that project, she used `tokio` for async IO and built a trait-based abstraction for storage backends. She has written about Rust's borrow checker in two blog posts. Her general take is that Rust is excellent for systems code but can be overkill for CRUD services.

That is a useful answer. It is not a moat. A junior with Google and thirty minutes could produce it. A vector-search-over-blog-posts system could produce it. Copilot Spaces will produce it. It is *search*.

**Framework cloning (tomorrow, the moat):**

> Before you ship this code, here is what Alice would ask:
>
> 1. "Is this trait boundary actually needed? You have one implementor. Alice has rejected three PRs in the last year for introducing a trait with a single implementor. Her rule is: traits for polymorphism; concrete types for code organization. This is the second category; make it a struct."
>
> 2. "Why `async` here? You are not doing IO; you are doing compute. Alice's framework is: `async` is a cost — it taxes call sites and forces runtime color. Only pay the cost if you have actual IO wait. You do not."
>
> 3. "Where are the error types? Alice has approximately zero tolerance for `Box<dyn Error>` in libraries. She has said so in seven PR comments and one blog post. She will ask for a typed error with `thiserror`."
>
> Alice would *also* note, if she is in a good mood, that the module structure is actually clean, and would approve the control-flow portion. But she will block on (1) and (3), probably with a terse comment on (2).

That is not search. That is *cognition*. That is the output of a system that has extracted Alice's review function from her review history — the rules she applies, the ordering in which she applies them, the cases in which she has self-corrected her position, and the evidence she produces when she applies a rule.

A junior reading this gets three things they cannot get from any current product:

- **Precision**: the specific objection, not a generic objection.
- **Calibration**: these are Alice's actual rules, not best-practices-in-the-abstract.
- **Socratic pressure**: they learn Alice's framework by having it applied to their own work, which is the only way humans actually learn frameworks.

A senior reading this gets one thing they cannot get anywhere else:

- **Force multiplication**: this pre-review is as good as the one Alice would give in the first forty seconds of her own review, and she did not have to spend those seconds.

A VP of Engineering reading this gets one thing that makes them reach for their corporate card:

- **Institutional preservation**: Alice's framework is now applied to every PR on her team, whether she is in a meeting, on PTO, or employed there at all.

### The ingredients of framework extraction

A framework is not a single thing. It is a bundle of behaviors that our synthesis pipeline extracts and assembles. The five ingredients:

**1. The review function — what rule was applied, not what was said.**

When Alice rejected PR #847 with the comment "this should be a free function, not a method," the *quote* is useful but the *rule* is the moat. The rule, extracted, is: "I reject PRs where a method has no access to instance state because the method does not belong on the class." Extract that rule from forty of Alice's review comments, and you have a framework for free-function-vs-method that will correctly grade a PR Alice has never seen.

This is the work `save_principle` and `save_finding` are doing today, but we are going to sharpen the extraction prompts substantially as part of ALLIE-425. A principle is a trigger → action → value triple, where the value is the deeper thing being served. Alice's trigger is "method without access to `self`," her action is "reject, suggest free function," and her value is "encapsulation follows data, not organization." Knowing all three lets the mini apply the rule to cases where the trigger is disguised.

**2. Their explicit values — stated preferences, updated over time.**

Alice's blog posts, her design docs, her "Things I Believe About Software" talk from 2023, the Slack threads where she defended her position against a teammate. These are the *declarations*. Type safety over runtime flexibility. Tests before abstractions. Stability over novelty. The values are the north-pole that orients the rules. Without values, rules look arbitrary. With values, rules look like applications of a worldview.

Values also update. Alice in 2019 probably had a different take on microservices than Alice in 2024. The corpus has to track the trajectory — the "I used to think X, now I think Y" moments are where values actually live, not in the frozen first-draft opinions.

**3. The framework *ordering* — sequence matters.**

This is the subtle one. Alice does not apply her rules in random order. When she reviews a PR, she checks things in a sequence:

1. Does the diff match the ticket description? (If not, block with "scope unclear.")
2. Does the test coverage for the new logic look right? (If not, block with "more tests.")
3. Is there a pattern in the codebase this should be using? (If yes, comment.)
4. Is the naming clear to an outsider? (If no, comment.)
5. Are the error types right? (If no, comment.)
6. Is there a perf concern? (If yes, comment.)

If step 1 fails, Alice never reaches steps 4–6 in the first review. She might not even read the code. Knowing this ordering lets the mini produce reviews that feel like Alice's reviews — tests before naming, scope before tests, architecture before style. A mini that surfaces an architectural concern *after* eight naming nits is not Alice; it is a checklist. The ordering is half of the framework.

**4. Their self-correction history.**

The highest-signal data we have is when someone changes their mind. The PR where Alice initially rejected, then re-reviewed after a teammate pushed back, and came around. The blog post where she said "I used to think monorepos were overkill; after two years at BigCo I now think they're the only sane default." The design doc comment that says "on reflection, Option B has a tradeoff I missed; reversing my earlier position."

These moments are the *calibration data*. They show how Alice's framework updates in response to evidence. A mini that reproduces Alice's framework *including its trajectory* is a mini that can correctly extrapolate how Alice would respond to novel evidence — because it has seen the update function in action.

**5. Evidence-of-reasoning.**

Review comments that explain *why*. Commit messages that explain *why not the other way*. Design doc comments that surface tradeoffs. The raw reasoning — "I would do X because Y, except Z, so actually X' " — is gold. Most engineers leave traces of this. Extracting it, clustering it, and reconstructing the underlying thought process is the core synthesis job.

This is where the existing `principles_json` and `knowledge_graph_json` fields on `Mini` become load-bearing. They are not side artifacts. They are the primary deliverables. The soul document and memory document are the *prose* layer on top of the structured framework — the framework is the actual product.

### The feedback loop — the virtuous cycle

When a user reviews something the mini predicted, we get ground truth. The human either confirmed the mini's verdict, extended it, or overruled it. Each of these is signal.

- Confirmed: "Yep, Alice would ask about the error type." +1 confidence on that rule.
- Extended: "Alice would also ask about the retry semantics, which the mini missed." New finding; ingest it.
- Overruled: "Actually, Alice would not block on this because [context]." Downgrade rule, note the context.

Every cycle makes the mini sharper. Over time, the mini's agreement-rate with the human on the same inputs becomes the top-line product metric — not voice similarity, not narrative quality, but *prediction accuracy*. A mini that predicts Alice's review with 87% agreement is more valuable than a mini that sounds 100% like Alice but only predicts 40% of what she would actually say.

This is why ALLIE-382 (fidelity evaluation harness) and ALLIE-425 (review-agreement metrics) are the north-star measurement infrastructure. Without fidelity measurement, we are shipping vibes. With it, we are shipping a product that gets measurably better every release.

```
  human reviews PR ─────┐
           ▲            │
           │            ▼
     mini predicts   ground truth
           ▲            │
           │            ▼
       synthesis ◀── grade result
           ▲            │
           │            ▼
        corpus ◀── feedback row
```

The corpus is append-only. The grades are append-only. Every rev of synthesis gets to train on a strictly larger set of signals than the last rev. The product gets better without us working harder.

---

## The Product — 5 Tiers

The five tiers are not pricing bundles. They are *unlocks*. Each tier is a qualitatively different product that becomes possible only because the tier below it works. The IC tier is necessary for the team tier (because team value requires per-person minis, and per-person minis are created by ICs using the free-tier product). The team tier is necessary for the business tier (because cross-team composition requires all the teams to have minis). The business tier is necessary for the enterprise tier (because the enterprise retention pitch only lands on companies that are already using minis day-to-day).

You cannot skip tiers. You can only earn them in order.

### Tier 1 — The IC

**Pitch**: "Don't push slop your senior already rejected three times."

The IC opens a PR. Before it ever reaches the senior, the IC's local mini of their senior reviews the PR. The mini flags things the senior will flag: "you are using `useEffect` for data fetching, but this codebase has a `useDataQuery` hook for exactly this — see `src/hooks/useDataQuery.ts`." The IC updates the PR. The IC pushes. When the actual senior reviews, they are looking at the IC's *third* draft, not the IC's lazy first draft.

**Day-in-the-life — Sarah, three months in.**

Sarah is finishing her feature. It is 3:45 PM. She has her PR ready. She is nervous because last week she got publicly-politely dunked on in a PR comment for missing the `useDataQuery` pattern. She does not want that again.

She runs `mini-review priya` from her terminal. The mini pre-reviews her PR.

> **Priya-mini says:**
>
> 1. [BLOCK] You're using `useEffect` for data fetching again. Use `useDataQuery`. This is a pattern I've asked for five times in the last year, including twice on your PRs. See `src/hooks/useDataQuery.ts`.
> 2. [NIT] Your variable `data` is vague. I usually ask for domain-specific names like `userProfiles` or whatever the data actually represents.
> 3. [QUESTION] The scope of this PR has grown beyond the ticket. The ticket is "add export button" but you've also refactored the filter logic. I might ask you to split this into two PRs. If there's a reason not to, put a note in the description.
> 4. [APPROVE] The actual export logic looks clean. Tests are thorough. Error handling is right.

Sarah fixes (1). She renames to `exportableRows`. She adds a note to the PR description explaining that the filter refactor is prerequisite for the export and that splitting would require double-review of the same logic. She pushes.

Priya reviews the PR the next morning. She approves it in forty seconds with one small nit that the mini did not catch. Sarah's PR ships before lunch. It is her fastest PR ever. She did not wait a day and a half for feedback. She did not get publicly corrected on a pattern she should have learned by now. She learned the pattern — this time for real — because the mini showed her the exact file and explained the rule in Priya's voice.

In six months, Sarah's PR-to-merge time is half what it was at month three. Her confidence is higher. Her relationship with Priya is better because their interactions are substantive — architecture, hard tradeoffs, the interesting stuff — rather than pattern-correction that both of them find tedious.

**The emotional payoff:** Sarah stops being embarrassed. Sarah starts learning faster. Sarah feels like she has a calibrated study partner who is available at 3:45 PM on a Wednesday, which is the precise moment she needs one and her actual senior is unavailable.

**The economic payoff:** Sarah's cycle time drops by ~40%. Compounded across a team of ten ICs, that is four full-time-equivalents of output recovered. Compounded across a company of a hundred ICs, that is forty. We have not added a single human. We have just stopped wasting the ones we have.

### Tier 2 — The Senior

**Pitch**: "Write code. Your mini does the first pass on everything else."

The senior has a stack of PRs to review. Their mini pre-reads each one, flags concerns with confidence scores and supporting evidence ("this is similar to PR #847 where you asked for X"), and the senior either LGTMs on the strength of the pre-read or dives deeper. When the senior does dive deeper and overrules the mini, we capture the overruling as training signal for the next synthesis.

**Day-in-the-life — Priya, one month after her team adopts Minis.**

It is 9:15 AM. Priya is at her desk. Her calendar shows a 10:00 AM standup and a clear stretch from 10:30 to 12:30. Her dashboard shows fourteen PRs. She dreads the next seventy-five minutes, which is the amount of time this used to take.

She opens the Minis dashboard. Each PR has a pre-review attached.

- **12 PRs: low-risk, mini-approved.** Priya skims each one in thirty seconds, clicks approve. Ten minutes total.
- **2 PRs: mini flagged medium-risk, specific concerns listed.** Priya reads the mini's concerns, agrees with them, LGTMs with the concerns quoted so the author sees them. Fifteen minutes total.
- **2 PRs: mini blocked, concerns listed with high confidence.** Priya reads carefully. On one, she agrees with the mini and writes a one-line comment. On the other, she disagrees — the mini didn't know about a conversation she had with the author yesterday about scope. She unblocks with an explanation.

Total time: forty minutes. Priya got thirty-five minutes back. More importantly, she got thirty-five minutes of *unbroken* time back, which compounds differently than thirty-five minutes scattered across her day.

What did Priya just do, from the mini's perspective? She generated:

- 12 agreement signals (the mini was right; the PRs were approvable).
- 2 extension signals (the mini's concerns were correct but incomplete — Priya added detail the mini missed).
- 1 overruling signal (the mini was right in the abstract but missed conversational context).
- 1 confirmation signal (the mini was right and Priya did not need to add anything).

Every one of these is training signal. The next synthesis of Priya's mini is sharper than the last. The feedback loop is closed. The mini is a better pre-reviewer in week four than in week one, and will be better still in week eight.

**The emotional payoff:** Priya stops feeling like a bottleneck. Priya stops resenting her review queue. Priya has Fridays back for deep work, which she has been trying to carve out for two years and never been able to.

**The economic payoff:** Priya's output goes up because her context-switching tax goes down. The team's velocity goes up because PR latency drops. Junior ICs improve faster because their early feedback is crisper and more consistent.

### Tier 3 — The Team

**Pitch**: "Minis of everyone. Force multiplier for the team."

Every team member has a mini. Not just the senior. The junior ICs have minis. The tech lead has a mini. The designer who writes occasional frontend code has a mini. The whole team is *represented* in the system.

What this unlocks:

- **Automated code review in the team's voice.** Not generic Copilot suggestions — suggestions that sound like this team's specific opinions, grounded in this team's past decisions.
- **Ticket dispatch.** A new ticket gets filed. The team's minis collectively triage it: which engineer would naturally own this? Which similar tickets have been filed before? What is the likely technical approach? By the time a human looks at the ticket, there is a draft-owner recommendation, a draft approach, and a dependencies list. The human decides; they do not derive.
- **Async backfill.** Someone is OOO or just in a meeting. A question comes in on Slack. The person's mini answers in-thread, tagged as a mini-response, with a "the human would confirm this but here is the likely answer." For trivial questions, the mini is enough. For substantive questions, it surfaces the context so the human can respond quickly when they get back.

**Day-in-the-life — Priya as tech lead of an eight-person team, one quarter post-adoption.**

Sprint planning, Monday morning. Priya opens Linear. Fifteen new tickets were filed last week. Each one has a mini-triage attached:

- Owner recommendation (based on who has worked on similar code before)
- Rough estimate (based on similar tickets' actual cycle times)
- Dependencies (based on which other tickets or repos will be touched)
- Suggested approach (if the minis have high confidence) or "human decision needed" (if they don't)

The team walks into sprint planning with the plan 80% assembled. The forty-five minutes they used to spend re-deriving ownership and scope, they now spend arguing the interesting cases — the tickets where the minis disagreed, the tickets where the approach is genuinely novel, the tickets where priorities conflict. Sprint planning is thirty minutes instead of ninety. The decisions are better because the discussion is focused on the 20% that requires human judgment.

Tuesday afternoon. Mateo, one of Priya's ICs, is working on a feature that touches the auth service. He posts in #eng-auth: "hey, quick Q, is this the right pattern for adding a new scope?" He gets a mini-response within thirty seconds: "Based on the three previous scope additions (link, link, link), the pattern is X. Priya would probably want to know about this specifically, so I'll tag her."

Priya sees the thread forty minutes later, between meetings. She scans the mini-response, confirms it is right, drops a +1. Mateo ships his PR the same day. Without Minis, Mateo would have waited two hours for Priya's attention, or worked from a half-remembered pattern, or Slack-DM'd three different people hoping one would answer.

**The emotional payoff:** The team feels like a team, not a set of parallel workers funneling through a bottleneck. Juniors feel autonomous. Seniors feel supported. Priya gets to be a mentor instead of a router.

**The economic payoff:** Team velocity goes up ~30% based on drag-reduction alone. New-hire ramp-up time halves. The team can take on larger, more complex projects because coordination overhead is no longer the limiting factor.

### Tier 4 — The Business (cross-team)

**Pitch**: "Virtualize cross-team collaboration. Minis meet before humans meet."

This is where the product starts to look genuinely science-fiction. The use case: a proposal touches three teams — auth, platform, infra. The old-world motion is: schedule a meeting, catch everybody up, argue for ninety minutes, agree to circle back, schedule another meeting, argue for sixty more minutes, land on a decision, write it up, forget to share it, re-derive it six weeks later when somebody else asks.

The Minis motion: the proposer tags the three teams. Each team's collective mini (its senior engineers' minis, composed) reads the proposal asynchronously. Each mini produces:

- A summary of the proposal from that team's perspective.
- The team's likely objections, grounded in that team's past positions.
- The team's likely requests (e.g., "infra would want a rollback plan," "auth would want the token-lifetime question answered").
- A confidence score on the team's likely verdict.

The proposer reads the three team-minis' responses. They see, before ever scheduling a meeting:

- Where the three teams already agree (skip that part of the meeting).
- Where they disagree (focus the meeting on resolving the disagreement).
- Where the proposal has a gap the proposer didn't see (fix the gap before the meeting).

**Day-in-the-life — Architect Raj, proposing an auth migration across six teams.**

Monday. Raj drafts the proposal in a doc. He tags six teams.

Tuesday morning. The six minis have each produced a written response, attached to the doc. Raj reads them:

- Auth team mini: "We broadly support this. Our concern is the migration period — last year's SSO migration took nine months and we don't want that again. We want a rollback plan and a weekly migration-health metric." Confidence: 0.8 supportive.
- Platform team mini: "We would want the SDK API reviewed before the backend change. We have three public SDKs and we don't want to break them mid-migration. We'll need a compat layer for six months." Confidence: 0.6 supportive with conditions.
- Infra team mini: "We'd block this unless the rollout plan accommodates our Terraform state. The last three auth changes each required manual state manipulation and we're not doing that again." Confidence: 0.3 supportive, strong condition.
- Payments team mini: "We have a dependency on the current auth for one specific idempotency flow. We'll need the new auth to support equivalent semantics before we can migrate. Not a blocker; a scheduling constraint." Confidence: 0.5 neutral.
- Mobile team mini: "We need six months' lead time minimum. Our release cycle can't absorb this inside of a quarter." Confidence: 0.4 supportive with timing.
- Data team mini: "Doesn't affect us directly. FYI we'd appreciate new identity claims exposed in the events stream." Confidence: 0.9 supportive with an ask.

Raj reads these. He updates his proposal to include: a rollback plan, an SDK-compat layer, Terraform automation, an idempotency-parity requirement, a six-month lead time for mobile, and an identity-claims extension for data. The updated proposal addresses five of the six teams' concerns preemptively.

Wednesday. Raj sends an updated proposal. The six minis re-read and update. Five are now 0.8+. Infra is still at 0.5 because the Terraform plan has a detail the mini isn't confident about. Raj schedules a thirty-minute meeting with just infra to resolve that one detail.

Thursday. The thirty-minute meeting happens. The humans walk in already knowing the shape of the problem. The meeting lands at "yes, with these three tweaks." Total meeting time: thirty minutes. Old-world equivalent: three meetings across six teams across three weeks, with probably six-plus hours of synchronous time and immeasurable async drag.

**The emotional payoff:** Cross-team work stops feeling like a penalty. Ambitious proposals get filed because the coordination cost is no longer prohibitive. The humans who do meet are engaged because the meetings are substantive.

**The economic payoff:** The coordination tax collapses. Companies that previously could not attempt cross-cutting work can attempt it. The highest-leverage projects — the ones that require multiple teams — become tractable.

### Tier 5 — The Enterprise (institutional knowledge retention)

**Pitch**: "You invested millions in their brain. Keep it when they leave."

This is the YC-catnip, moonshot, "edgy but undeniable" pitch. It is the tier that makes the enterprise buyer reach for the multi-year contract. It is the pitch that shows up in the board deck. It is the one that, handled well, defines the category.

An employee spends five years at your company. In that time they build up:

- A GDrive full of design docs.
- A Slack history full of tradeoff debates.
- A GitHub comment history full of code-review frameworks.
- A Confluence, a Notion, a Jira/Linear history of ticket discussions.
- 1:1 notes, meeting transcripts (where consented), email threads.
- Architecture review notes, incident post-mortems, RFC comments.

You paid for every minute of that knowledge formation. They were on the clock. The fraction of the knowledge that lives in *their head* is the fraction that the company cannot currently recover when they leave. That fraction is, conservatively, 60–80% of their value.

They leave.

Today: docs rot, Slack goes unread, new hires can't ask questions, and the company quietly absorbs a multi-year productivity crater. Post-mortem culture mostly captures *what happened*, not *what this person believed and why*. Knowledge-transfer sessions capture the top-of-stack, not the framework underneath.

With Minis at the enterprise tier: a mini of the employee — ingested with their consent during their tenure, across every tool on the company's accounts and the employee's professional exhaust — continues to serve the company for years after the employee is gone. The mini:

- Answers architecture questions grounded in decisions the employee was part of.
- Surfaces the "why" behind configurations and patterns that look arbitrary.
- Applies the employee's framework to new decisions the employee never saw.
- Acts as virtual institutional counsel: "before we do this, what would [departed senior] have asked?"

**The blunt version: it is an HR product disguised as a dev tool.** The buyer is the VP of Engineering in partnership with HR. The budget line is either "engineering tooling" or "knowledge management." The ROI is measured in onboarding-time reduction, incident-prevention, and the retained value of ex-employee judgment.

**Day-in-the-life — VP Dev, one year after adopting enterprise Minis.**

Marcus left six months ago. Marcus's mini has been running for eighteen months — the last twelve of his tenure, then the six months since.

A new staff engineer, Olu, joined two months ago. Olu is working on a refactor of the auth service. Olu drafts a design doc. Olu asks Marcus's mini to review.

> **Marcus-mini says:**
>
> 1. [QUESTION] This removes the sequence-number guarantee on the token-refresh path. I know that sequence number looks arbitrary in the current code, but it exists because of an incident in March 2022 where we had a double-refresh race that double-charged a customer. See the post-mortem (linked). If you're certain the new path doesn't have that race, document it. If you're not, keep the sequence number.
>
> 2. [FRAMEWORK] When I worked on this service, I had a rule: never remove an invariant without proving the invariant is actually unnecessary. "It looks unused" isn't a proof. The test for this one is specifically a race; unit tests will not catch it. You'd need a soak test with concurrent refresh calls.
>
> 3. [APPROVE, with conditions] The rest of the refactor looks clean. The module split is sensible. I would approve after (1) and (2) are addressed.

Olu reads this. Olu goes back, reads the March 2022 post-mortem, finds that the race absolutely matters, keeps the sequence number, writes a comment explaining why. Olu ships the refactor without an incident. The company avoided, at minimum, one repeat of the March 2022 incident — which cost the company ~$40K in refunds and two weeks of engineer time.

Without Marcus's mini, the most likely outcome is: Olu removes the sequence number, the refactor ships, the race happens on a high-traffic Friday, the on-call gets paged, the company loses money, the post-mortem concludes "we should have documented this better." Everyone feels bad. Nothing changes. The cycle repeats.

Marcus's mini is the documentation that was never written because the thing that needed documenting was not knowable until it was too late. Marcus's mini is a virtual institutional counsel who answers the phone at 3:00 PM on a Wednesday.

**The bus-factor math.** A staff engineer with five years of tenure represents, conservatively, five person-years of institutional knowledge. At loaded comp of ~$400K/year, that is $2M of sunk investment in knowledge formation. If the employee leaves and the company loses 80% of that knowledge immediately, the company has just taken a $1.6M write-down. Minis, if it can retain even 50% of that knowledge, is worth $800K per retained senior. Enterprise pricing at $5–20K per seat per year for the retention addon is, at those numbers, an obvious yes.

And — critically — the retained mini compounds. Every new hire interacting with Marcus's mini leaves a trace ("I asked X, got Y, shipped Z") that *augments* Marcus's mini with the company's post-Marcus institutional memory. The mini that starts as "Marcus" eventually becomes "Marcus plus the three hundred decisions the team has made using Marcus's framework since he left." The company's institutional memory does not die with Marcus. It accretes.

**The legal and consent framing — addressing it head-on.**

This is where we need to be crisp, because it is the part that scares people. Here is the framing:

- **Consent is explicit and granular.** Employees opt in at hire to Minis ingestion, with a clear scope document: "Your mini will ingest code, reviews, tickets, design docs, public Slack channels. It will not ingest private DMs, salary discussions, HR conversations, or anything marked personal. You can review and delete any individual ingested item at any time."
- **Ownership is dual.** The mini, while employed there, is jointly owned: the company owns the operational rights, the employee owns the right to a personal copy on departure.
- **Deletion rights are preserved.** On departure or on demand, employees can elect to delete their mini entirely, delete specific classes of data (e.g., all Slack), or allow continued operation with audit visibility.
- **Scope is explicit.** The mini never ingests from systems the employer does not already have access to. If the employer has access to the data under its own policies, the mini's access is a subset of that. If not, the mini cannot touch it.
- **The employee benefits too.** The mini is portable. The employee takes a personal copy with them to their next job. Their framework is preserved for their own benefit. The employee is not being strip-mined; they are being backed up.

This is not a fig leaf. This is the actual design. The product cannot ship without it, both for legal reasons and because a product that feels exploitative will not retain users. The ethics and the business model are aligned: a consensual, transparent, employee-beneficial Minis is the only Minis worth building. Anything else will not survive contact with Glassdoor, let alone the courts.

The edgy framing ("Arasaka soul-kill") is useful because it captures attention and because the real product, when it lands, is going to feel uncanny whether we joke about it or not. Better to own the uncanniness honestly than to hide from it. We are not secretly building a dystopia. We are openly building an employee-beneficial retention tool that happens to solve the enterprise-retention problem as a side effect. The blunt framing communicates the scale of the ambition; the consent framing communicates the way we actually intend to land it.

**The virtual institutional counsel framing.**

For the enterprise buyer, the way we package this is: *every decision your org makes should be testable against your institutional framework, including the frameworks of the people who built the company and are no longer here.* Your institutional framework is your competitive advantage. Losing it is the single largest risk to your long-term technical coherence. Minis is the insurance policy plus the asset.

This pitch is directly analogous to how enterprises think about legal counsel, financial audit, and institutional continuity. General Counsel does not write every contract; GC establishes the framework and the organization applies it. Minis does the same thing for technical decisions. It is institutional continuity as a service.

### Tier composition

The five tiers compose. A company running Tier 5 is, automatically, running Tiers 1–4 — every IC is pre-reviewing with their senior's mini, every senior is using their mini as a first-pass reviewer, every team is using collective minis for triage, every cross-team initiative is using mini-swarms for pre-meeting alignment. Tier 5 is the *sum* of everything below it, plus the retention layer on top.

This matters for pricing and for narrative. We do not sell "Tier 5" as a bundle; we sell it as *everything you already have, plus the knowledge-retention capstone.* Customers ladder up as they experience the value of each layer. By the time the CFO looks at the line item for the enterprise tier, the line item is already defensible on the strength of the four tiers beneath it, and the retention layer is the cherry that turns a nice-to-have into a strategic imperative.

---

## The Technical Moat

A product this ambitious has to be defensible, or someone else will build the same thing with more money and eat us alive. The moat is not the prompt. Prompts are copyable. The moat is a set of compounding investments in infrastructure, data, and synthesis that get harder to replicate the longer we run them.

### Per-repo local-clone explorers (ALLIE-373)

Shallow REST metadata extraction produces shallow minis. If all you have is "this user has ten repos, three in Python, most recent commit on Tuesday," you can produce a paragraph of fluff but nothing close to a framework. A framework requires *code reading* the way Claude Code reads a codebase: browsing directories, following imports, grepping for patterns, understanding conventions, reading README and CONTRIBUTING in context, picking up on comment density and test coverage.

The architectural consequence: one explorer agent per repo, operating on a local `git clone` with full filesystem access. This is what ALLIE-373 shipped (M1 + M2 fan-out, 2026-04-20). It is also what ALLIE-389 just made the only path — we deleted the legacy REST explorer because maintaining two paths was diluting investment.

Why REST metadata cannot touch this:

- REST gives you file names. Local clone gives you imports, call graphs, and lexical context.
- REST gives you commit messages. Local clone gives you commit messages *plus the diffs they reference*, which is where the reasoning lives.
- REST rate-limits aggressively. Local clone is local; we can read every line.
- REST cannot grep. A local explorer can grep for a pattern across 47 call sites and discover that it is, in fact, a team-wide convention.

The cost of local-clone explorers is operational complexity (disk, temp management, git auth, size limits) and that cost is exactly the right cost to pay — it raises the barrier to anyone trying to clone us. Every competitor with a weekend project can plug a vector DB into the GitHub REST API. None of them will want to own the ops of running per-user repo clones at scale. We will, because it is the moat.

### Incremental append-only ingestion (ALLIE-374 / ALLIE-418)

Raw evidence is APPEND-ONLY FOREVER. We never prune. We never TTL. We never garbage-collect. The only deletions are consent-driven GDPR deletes, and those are marked explicitly in the schema.

This is a policy choice, not a technical one, and it is the single highest-leverage product decision in this entire document.

Why append-only ingestion is the flywheel:

1. Every pipeline improvement (better extraction prompt, better synthesis model, better ordering heuristic) gets to re-extract from the *full accumulated corpus*, without re-fetching. The corpus earns interest.
2. Every new source (Stack Overflow, Linear comments, design docs, meeting transcripts) layers on top of the existing evidence without invalidating it. The corpus deepens.
3. Every fidelity-improvement cycle — the mini predicts, the human grades, the grade is stored — adds a ground-truth row that future synthesis can train against. The corpus learns.

A competitor starting from scratch on day zero has an empty corpus. A competitor with one year of per-user corpus has roughly our day-365 state. A competitor with three years of per-user corpus has roughly our day-1095 state. The only way to beat us on corpus depth is to have started earlier or to pay exorbitantly to back-fill, which — because of rate limits and source restrictions — is often structurally impossible. The corpus is the asset. The corpus is the moat.

ALLIE-374 M1 shipped the incremental ingestion schema + hashing + delta helpers. ALLIE-418 is the retention-policy layer (what to keep, what to mark for GDPR-aware deletion, how long to retain which source-types). This is not glamorous work. It is the plumbing that makes the flywheel real.

### Decision-framework extraction (ALLIE-425)

This is the hardest technical problem in the entire product, and it is the one where the deepest investment pays the longest dividends. Every other moat component is infrastructure. This one is synthesis.

The extraction pipeline today does "what did they say" reasonably well. It does not do "what rule did they apply" well enough yet. The jump from one to the other is the jump from retrieval to cognition, and it is the jump we are actively climbing with ALLIE-425.

Concretely, the extraction changes look like:

- Explorer prompts upgraded to extract the *trigger* of a rule, not just the action. ("You said X because Y saw Z. What general condition triggers this reaction?")
- `principles_matrix` promoted from optional side-output to required primary deliverable with coverage metrics ("did we extract at least N principles for this subject?").
- Every `finding` annotated with a confidence-weighted classification: narrative / rule / value / self-correction. Only rules and self-corrections feed the framework-application path at synthesis time.
- A new "framework ordering" extraction step that tries to derive the sequence in which a person applies their rules to a class of input (PR review, architecture proposal, bug triage, ticket triage).
- A meta-evaluator that takes a held-out PR from the person's history and asks "if the mini had reviewed this before the person did, would its output match the person's actual output?" This is the fidelity metric that grades the extraction.

The hard part is that frameworks are not in any single document. They are distributed across review comments, commit messages, blog posts, and design docs. Extraction is a synthesis across sources, which is why the append-only corpus and the per-repo local-clone infrastructure are strict prerequisites. Without the data, the extraction is impossible. With the data, the extraction is hard-but-tractable, and it gets better every release.

### Feedback-loop training (ALLIE-425 sub)

The second-order moat: every time a user reviews something the mini predicted, we have ground truth. We store the prediction, the human's verdict, and the delta between them. Over time this grading dataset becomes a per-user, per-framework fine-tuning signal that we can feed into the next synthesis revision.

Note: we are NOT training custom models. We are not fine-tuning LoRAs. We are not shipping on-device weights. The feedback goes into the corpus, where it shows up as ground-truth rows in future syntheses, which means the next rev of the synthesis prompt sees the prediction-outcome pairs and can re-extract rules that better-match observed behavior. This is declarative, not parametric. It is cheaper, faster, and safer than fine-tuning, and it also upgrades automatically when the underlying model family improves.

ALLIE-425 owns this loop. The mechanism is prosaic: after every mini-review in Claude Code, the user's next action on the PR (which review comments they kept, which they rejected, which they added) is captured and rolled into a feedback row. The feedback rows become part of the append-only corpus. The next synthesis ingests them. The mini sharpens.

### Research substrate (ALLIE-426)

We are not a research company. We are not publishing papers. But we are operating at the research frontier, and we are dogfooding research work that materially improves the product.

The research threads we are tracking:

- **Inverse reward design (IRD):** given observed behavior, infer the latent reward function. This is the formal version of "extract the review function from review history."
- **Preference elicitation:** structured protocols for extracting explicit preferences from users when they disagree with the mini's prediction. What signal is cheap to extract, high-value, and not-annoying to the human?
- **RLHF from implicit signals:** the user does not need to explicitly grade the mini. Their *subsequent actions* (kept the comment, rejected it, edited it, added to it) are implicit grades.
- **Cognitive architectures:** how do we structure the mini's internal reasoning to apply a framework rather than retrieve a quote? There is real research on "Soar-style" agent architectures, on cognitive-tutor systems from the EdTech world, on "System 2" scaffolding for LLMs. We are borrowing selectively.
- **Theory of mind in LLMs:** what does it mean for a mini to reason about the *reasoning* of its subject? Current LLMs can do some of this; recent work on metacognition suggests it is a tractable research direction. We are watching it closely.

None of this is vaporware. ALLIE-426 is an umbrella ticket for tracking and prototyping the research sub-threads that might move the product. Most will not pay off. One or two will. Running the watch function at all is the edge.

### Fidelity evaluation (ALLIE-382)

If we cannot measure fidelity, we are shipping vibes. ALLIE-382 is the fidelity-evaluation harness: a curated set of "golden" turns (real review comments, real blog post excerpts, real design-doc contributions from real subjects) against which every release of the synthesis pipeline is scored.

The harness grades on multiple axes:

- **Rule recovery:** did the mini reproduce the rule the subject applied, as judged by a third-party evaluator (LLM or human)?
- **Ordering fidelity:** did the mini apply its rules in the order the subject would have?
- **Self-correction awareness:** if the subject has changed their mind on a given topic, does the mini reflect the updated position rather than the outdated one?
- **Voice match (tiebreaker):** does the mini sound recognizably like the subject? This is the lowest-weight axis.

ALLIE-385 already expanded the golden turns to 10 source-annotated items per subject. ALLIE-382 is the harness itself. Together, they are the "we shipped better synthesis this release" proof. Without them, every synthesis change is a coin flip on whether it helped or hurt.

### Safety posture (ALLIE-405, ALLIE-416)

Safety is not a feature. Safety is a non-negotiable baseline. Rate limits, cost caps, kill switches, per-IP throttles, usage observability — these are in the product from day one, not because we have adversarial users yet, but because the instant we do, it will be too late to add them.

ALLIE-405 shipped per-IP chat throttle, pipeline token caps, an LLM kill switch, and usage observability. ALLIE-416 layered in per-IP mini-creation and progress-SSE throttle. These were not features anyone asked for. They were the moat against the class of operational failure that kills ambitious products.

Every future product expansion — cross-team swarms, enterprise retention, executive analytics — requires a more mature safety posture, not a less mature one. We are building that posture now, while it is cheap.

```
        corpus ──┐
                 │
          [appends only]
                 │
                 ▼
   per-repo clone explorers ──► Evidence DB
                 │                    │
                 ▼                    ▼
          [framework                [fidelity
          extraction]                 eval]
                 │                    ▲
                 ▼                    │
        principles_matrix ────┐       │
                              ▼       │
                     system_prompt    │
                              │       │
                              ▼       │
                       mini responds  │
                              │       │
                              ▼       │
                    user reviews/grades ─┘
                              │
                              ▼
                  feedback rows ──► corpus (loop closed)
```

Every arrow in that diagram represents an investment. Every investment compounds. A year from now, the diagram has more arrows and deeper arrows. Five years from now, the diagram is the product.

---

## User Journeys

The tier-by-tier narratives above are the primary user journeys. Here are four more, illustrating the range of the product in its fully-realized form.

### IC Sarah ships on day one

Sarah joins BigCo on Monday. By Tuesday afternoon, she has her first PR ready. She is nervous — first-week PRs feel high-stakes. She runs the Minis plugin against her senior's mini.

The mini flags three things. Two are pattern issues ("use `useDataQuery` not `useEffect`"); one is a scope concern ("this PR touches two unrelated things; you might want to split"). Sarah fixes the patterns, adds a justification note for the scope, and pushes.

Her senior reviews in thirty seconds the next morning. LGTM. Sarah shipped her first PR on day two instead of day six. Her first impression at BigCo is "that new hire is fast and careful," not "that new hire needs a lot of hand-holding."

Six months in, Sarah has internalized BigCo's review framework in a way that, historically, took two years of bruising feedback to develop. She learned it from a private tutor who speaks in her senior's voice and is available every time she pushes code.

### Senior Marcus reviews twenty PRs in ninety minutes

Marcus used to burn four to five hours a day on reviews. With Minis, he burns ninety minutes. Every PR arrives pre-reviewed by his mini. Twelve of the twenty are straightforward — mini approved, confidence high, Marcus skims and ratifies. Six are medium — mini flagged specific concerns, Marcus reads the concerns, agrees or adds detail. Two are blocking — Marcus dives in, writes careful feedback, overrules the mini in one case because of a conversation the mini did not have access to.

Marcus got three hours back. More importantly, Marcus got *contiguous* deep-work time back. He is writing a design doc for the next quarter that he has been trying to write for a month. The compounding effect of getting senior engineers' deep-work time back is one of the largest sources of hidden ROI in the entire product.

### Team lead Priya plans a sprint in thirty minutes

Priya files fifteen tickets Sunday night. Monday morning at sprint planning, the tickets have mini-triages attached — owner recommendations, effort estimates, dependencies. The team walks in with the plan 80% assembled. The meeting focuses on the five tickets where the minis disagreed or where priorities conflict. Sprint planning takes thirty minutes. Discussion is substantive.

Old world: ninety minutes of planning, half of which was ownership-derivation. Forty-five minutes recovered. Better decisions because the discussion was focused.

### CTO Raj runs an architecture review with six teams async

Raj proposes an auth migration touching six teams. Each team's mini reads the proposal. Each produces a written response — support/concerns/conditions. Raj reads the six responses, updates his proposal to address them preemptively, re-sends. Five teams are now at high-confidence support. Raj schedules one thirty-minute meeting with the sixth team to resolve the remaining detail. The migration gets green-lit in a week instead of a quarter.

### VP Chen retains institutional knowledge through a staff engineer's departure

Chen's most valuable senior staff engineer, Marcus, leaves for a competitor. Marcus consented to his enterprise mini five years ago and has been contributing to it continuously. Post-Marcus, his mini remains active. New hires ask it questions. Architecture reviews include its perspective. Six months later, a new staff engineer avoids a repeat of a 2022 incident because Marcus's mini surfaced the invariant the incident had established.

Chen told her board, at the end of the fiscal year, that the team absorbed Marcus's departure with no meaningful productivity loss. She was right. She was the first VP in her peer group to be able to say that.

---

## Business Model

### Pricing structure — per-seat, five tiers

We price per-seat, aligning with procurement patterns for developer tools (Copilot, Notion, Linear, Slack). Per-seat beats per-mini because it encourages fuller ingestion — the more minis a seat accesses, the stickier the product, the more data flows into the corpus, the better the product gets. Per-seat has a natural upper bound (the company's headcount). Per-mini has no bound but creates friction every time someone wants to add a teammate's mini to their context.

**Free tier.**
- One mini of yourself.
- Chat, review, basic explorer access.
- Public-data ingest only (GitHub public, public blog, etc.).
- N messages/month (rate-limited).
- Self-hosted or hosted-free. The Claude Code plugin V1 (ALLIE-422) is the primary distribution vector here.

Pricing: $0. This tier exists to drive adoption. Every developer who tries the free tier becomes either a paying customer eventually or a referral to their team.

**Solo Pro tier — $20–30/month.**
- Three minis (you + up to two teammates you have consent from).
- Private-source ingest (private repos, private blog, etc.).
- Higher message cap.
- Local-first with cloud sync.

Pricing: $20–30/month. Positioned as the "power user" tier. The ROI math: if Solo Pro saves you two hours a month on PR iteration (it does), $20–30 is trivial.

**Team tier — $40–80/seat/month.**
- Whole-team mini access.
- Automated PR pre-review integration (GitHub App).
- Shared team corpus, shared framework extraction.
- Ticket-triage automation on Linear/Jira.
- Slack-integration for async-mini-responses.

Pricing: $40–80/seat/month. The ROI math: if the team tier gives each senior engineer 2+ hours/week back (it will), that is $10K+/year of reclaimed FAANG-comp time per senior. At $60/seat/month = $720/year, the ROI is >10×. For an eight-person team, the annual cost is ~$5.8K. The value unlocked is north of $50K.

**Business tier — $150–300/seat/month.**
- Everything in Team plus cross-team swarm workflows.
- Meeting-prep automation (doc → mini-pre-read → agenda).
- Org-level analytics ("which teams have the highest review friction?").
- SSO, audit logs, admin controls.
- SLA-backed support.

Pricing: $150–300/seat/month. The ROI math: if the Business tier collapses cross-team meeting time by 50% across twenty cross-team initiatives a year, for a 300-person engineering org with ~20 cross-team initiatives/year, the recovered time is in the hundreds of hours. At loaded cost of senior time, the product pays for itself inside a single quarter.

**Enterprise tier — $500–2000/seat/year (plus retention addon).**
- Everything in Business plus knowledge-retention offboarding.
- HR integration, offboarding workflows.
- SOC-2 Type II, GDPR, data residency controls.
- Legal-grade audit logs.
- Custom data-retention policies.
- Dedicated customer success.

Pricing: $500–2000/seat/year, with the knowledge-retention addon priced separately at ~$5–20K/year per retained mini (ex-employee). The ROI math is where this becomes undeniable: one staff engineer's departure loses, conservatively, five person-years of institutional knowledge. At loaded senior comp of ~$400K/year, that is $2M of value exposed. Minis at even 50% retention fidelity preserves $1M of that. The retention addon at $5–20K/year is a 50–200× ROI on a single retained senior.

### Per-seat over per-mini

Why we price per-seat, not per-mini:

- **Procurement alignment.** Enterprise buyers understand per-seat. Per-mini creates friction every procurement cycle.
- **Usage incentive.** Per-seat encourages full ingestion — every teammate becomes a mini the seat-holder can access. More minis = more corpus = better product. Per-mini would create adversarial incentives.
- **Predictable pricing.** Companies can plan budgets around headcount. Mini count is unpredictable.
- **Platform economics.** As corpus deepens across an org, each additional mini has near-zero marginal cost. Pricing per-seat lets us capture the value of the whole-org corpus without nickel-and-diming.

The counter-argument (per-mini aligns better with unit economics) is real but smaller than the alignment benefits above. If our LLM cost-per-mini ever approaches the per-seat revenue, we have a cost problem, not a pricing problem; the fix is efficient inference, not changing the pricing model.

### LTV/CAC assumptions

Back of envelope for the Team tier:

- **CAC**: Phase-1 viral (Claude Code plugin) drives near-zero-CAC acquisition for individuals. Team expansion is land-and-expand inside adopting orgs, also near-zero-CAC. Paid CAC kicks in at the Business/Enterprise tiers where we'll run a real sales motion (~$10–30K fully-loaded CAC per enterprise logo, maybe lower).
- **LTV**: Team-tier gross retention: target 90%+ (the product gets sharper over time; churn risk is flatter than average SaaS). Net-dollar-retention: target 130%+ via tier expansion (Team → Business → Enterprise) and seat expansion within orgs. At $60/seat/month, an 8-seat team retained for 5 years (typical SaaS cohort) is $28.8K gross revenue per logo, with ~75% gross margin = $21.6K contribution.
- **LTV:CAC**: for self-serve Team tier, ∞:1 effectively. For Enterprise, 20–50:1 target.

These are back-of-envelope and will update as we have real data. The shape, though, is strong unit economics with a land-and-expand motion that compounds.

### Enterprise retention addon — the real pricing game

The enterprise retention addon is where the pricing math gets strategic. The buyer is a VP of Engineering or CTO whose nightmare is senior-engineer departures. The comp: the loaded cost of one staff engineer leaving. The budget available: large enough to justify whatever retention fidelity we can prove.

Our pricing target: $5–20K/year per retained ex-employee mini. Priced against a ~$2M knowledge-loss exposure, this is a 100–400× ROI. Priced against a single avoided incident (which a mini might prevent in its first month of operation), it is break-even in days.

We are not the most expensive enterprise software the buyer owns. We are not even close. And we are aligned with the most expensive insurance they are *not* currently buying.

---

## Go-To-Market

### Phase 1 — IC viral pre-launch

**Goal:** get minis into the hands of as many individual developers as possible, for free, with as little friction as possible. Every adopted mini is a corpus row we get to train against and a referral node.

**Mechanism:** Claude Code plugin V1 (ALLIE-422). A single command — `/mini-create allie` — runs the pipeline locally, stores the mini on the user's machine, and lets them chat with it or have it review their code. Zero signup. Zero backend dependency (beyond LLM calls). Free.

**Distribution:**

- **Claude Code marketplace.** As soon as we ship V1, we list on the marketplace. Claude Code is the distribution channel for the early-adopter dev audience.
- **ShowHN launch.** Time it for a Tuesday. Lead with a screenshot of a mini predicting a specific, non-obvious review comment. Let the screenshots do the work.
- **Dev Twitter / Threads.** The bait tweet: "I made a mini of my senior engineer. Yesterday it predicted, word-for-word, the feedback he was about to give me." Attach screenshot. Retweets do the rest.
- **Claude Code skill evangelism.** Every mini created is a referral. The Claude Code community is tight; word travels.
- **Founder blog.** One long-form post per week. Title examples: "Why I'm building Minis." "My mini reviewed 50 PRs last week. Here is where it was right and where it was wrong." "What 10,000 PR comments told me about my own review framework."

**Metrics for Phase 1 success:**

- 10K minis created in the first month.
- 1K DAU on chat+review.
- 100+ inbound "can I buy this for my team?" conversations.

The metric that matters most is qualitative: does the tweet "my mini predicted the review comment exactly" happen organically, at volume, without our solicitation? If yes, the product has traction. If no, we iterate on fidelity until it does.

### Phase 2 — Team wedge

**Goal:** convert the pre-launch IC audience into paying teams, one team at a time, via the "my whole team should use this" motion.

**Mechanism:** Claude Code plugin V2 (ALLIE-423). Hosted MCP server. Minis of teammates are accessible from any Claude Code session with proper authentication. Self-serve signup at my-mini.me. Team-tier pricing ($40–80/seat/month). Payment via Stripe.

**Integrations (Phase 2 scope):**

- **GitHub App** for automated PR pre-review by team minis.
- **Linear/Jira** for ticket triage.
- **Slack** for async-mini-responses in-thread.

Each integration is high-value and decoupled. We ship the GitHub App first because PR review is the highest-ROI surface for the Team tier. Linear/Jira and Slack follow in subsequent months.

**Distribution:**

- Every Phase-1 IC user is a prospective team champion. We build an in-product "invite your team" flow that handles the consent-and-ingestion setup gracefully.
- Founder-led sales on the first 50 paying teams. Every conversation surfaces product gaps; those gaps feed the roadmap.
- Case studies. The first five teams that adopt, we interview, we write up (with permission), we publish. "How [team] cut review latency by 60%." Social proof is worth more at this stage than paid marketing.

**Metrics for Phase 2 success:**

- 100 paying teams by end of phase.
- $500K ARR.
- Net-dollar-retention measurably above 100% (teams expanding seats).

### Phase 3 — Business / SOC-2 / enterprise sales motion

**Goal:** move up-market. Land the first enterprise logo.

**Mechanism:** SOC-2 Type II (start audit early — it takes a year). GDPR posture. Data residency options. SSO, audit logs, admin controls. Enterprise-grade deployment story (single-tenant if required, or hardened multi-tenant).

**Sales motion:** manual, founder-led, relationship-driven. The first enterprise logo is probably someone who was already using Minis at the Team tier and whose VP of Eng reached out. We do not build an enterprise sales team before we have five reference customers.

**The HR/legal pitch:** when we do sell enterprise, the pitch has two tracks. The engineering-productivity track (same as Team/Business, bigger scale). And the knowledge-retention track (Tier 5 specifically). The retention track is the one that gets the multi-year contract. We partner with HR from the first conversation — they own the consent framework, we provide the tooling.

**Metrics for Phase 3 success:**

- 5 enterprise logos.
- $3M ARR.
- SOC-2 Type II certified.
- One public case study of knowledge retention working (an ex-employee's mini preventing an incident).

### Phase 4 — Org-level features

**Goal:** expand the Business/Enterprise ACV by shipping features that only make sense at org scale.

**Features:**

- **Cross-team swarm workflows.** The Tier 4 product, fully productized. Proposal in, team-minis align, meeting agenda out.
- **Executive analytics.** "Which teams have the highest review friction? Which minis are most frequently overruled, and for what reasons? Where is institutional knowledge concentrated? What is the bus factor of [this team]?"
- **Meeting-prep automation.** Calendar integration. Every meeting gets a pre-read assembled by the relevant minis.
- **Post-incident retrospective augmentation.** The relevant minis contribute "what would you have asked before this shipped?" to the post-mortem.

**Metrics for Phase 4 success:**

- Average enterprise ACV up 2×.
- 20+ enterprise logos.
- Category-leadership signal: press, analyst coverage, competitors pivoting to copy us.

---

## Competitive Landscape — a teardown

The competitive landscape is the set of companies and products that a buyer might compare Minis to. None of them are doing what Minis does at the core (decision-framework cloning), but they occupy adjacent surfaces and we need to be crisp about where we win and where we do not compete.

### GitHub Copilot / Copilot PR Review / Copilot Spaces

**What they do:** GitHub Copilot is the broadest AI developer tool in the market. Copilot PR Review (in preview/general availability depending on the quarter) runs a generic AI review over pull requests, flagging bugs, style issues, and potential improvements. Copilot Spaces (announced in 2024) offers a "personalized Copilot" scoped to a user's repos.

**What they do well:** distribution. GitHub is the default git host for most of the world. Copilot ships by default to millions of developers. Any AI feature GitHub adds gets adoption at a scale we cannot touch organically. Generic review catches generic bugs, and for a lot of teams that is a significant productivity gain.

**What they cannot do (and probably never will):** Copilot is a *generic* reviewer. Its reviews are calibrated against the global distribution of code, not against any specific reviewer's framework. It will flag "consider adding a null check" because the global model knows null checks are often missing. It will not flag "Priya would block this because it removes the March 2022 invariant" because it does not know Priya, and it does not know the March 2022 invariant, and even if it ingested everything Priya has ever written, it would not extract the framework — only the quotes.

Copilot Spaces is the closest thing to a competitive threat, but its scope is "a personalized assistant over your own repos," not "a cloned version of a specific human whose judgment you want to replicate." The difference is the difference between Google-for-my-files and a-specific-person-applying-their-judgment. Both are useful. They are not the same product.

**Where we win:** personalized framework cloning. Where we lose: we will not beat Copilot on generic best-practices coverage (that's their native strength), and we will not beat Copilot on distribution for years. We do not need to. We are a different product.

### CodeRabbit

**What they do:** CodeRabbit is an AI-powered PR review tool. It reads pull requests and produces structured reviews. It integrates with GitHub and Bitbucket. It charges per repo or per user depending on tier.

**What they do well:** product-market-fit *proof*. CodeRabbit exists, has paying customers, has a real go-to-market motion. They are evidence that the "AI-reviews-my-PRs" market is real and monetizable. When we pitch investors and prospects, CodeRabbit's existence is a green flag for the category.

**What they cannot do:** same limitation as Copilot, same ceiling. CodeRabbit reviews with a generic "what does good code review look like" prompt, augmented by repo-level rules the team configures. It does not clone specific reviewers. It does not extract frameworks from review history. It is a better generic reviewer, not a personalized one.

**Where we win:** we are the only product extracting the review function of a specific human and applying it to novel PRs. CodeRabbit tops out at "this PR has issues." We aim for "this PR has issues *that Priya specifically would flag, in the order she would flag them.*" We win on personalization and on knowledge-retention (which CodeRabbit does not attempt). CodeRabbit is the floor of our category; we are the ceiling.

**The defensive story:** when CodeRabbit or Copilot adds "personalized review" as a feature (they will), our corpus-depth moat is the structural advantage. A year of append-only corpus per user is not something a competitor can retrofit in a release cycle.

### Cursor / Windsurf / Zed

**What they do:** AI-powered IDEs or IDE-extensions. Cursor is the market leader. Windsurf and Zed are the pack. They offer AI chat in the editor, multi-file reasoning, agentic coding, and other productivity features.

**What they do well:** in-editor experience. A developer working in Cursor has an AI collaborator an Option-I away. The feedback loop is tight. For writing code, these products are excellent.

**What they cannot do:** PR review is not the surface they optimize for. They can be prompted to review a PR, but that is not the core use case. More importantly, they do not do *personalized* PR review. No Cursor user has a Cursor that thinks like their specific senior engineer.

**Where we win:** we are not competing with the in-editor experience. We are competing in the review surface — GitHub, Linear, Slack — where the reviewer's judgment matters. We are complementary to Cursor. A developer can use Cursor to write the code and Minis to review it. In fact, the ideal future is: Cursor → Minis pre-review → team review → merge.

### Glean / Guru / Clay / relationship-knowledge tools

**What they do:** enterprise knowledge retrieval. Glean indexes all your company's documents, Slack, email, and lets you search across them. Guru organizes team knowledge into cards. Clay and Relate do relationship intelligence — who knows whom, what interactions you have had.

**What they do well:** retrieval. They are genuinely useful. If you need to find the doc explaining last year's pricing decision, Glean finds it. If you need to know the last time you emailed someone, Clay knows.

**What they cannot do:** they retrieve. They do not synthesize. They do not apply frameworks. Glean will find the doc where Marcus said "we rejected GraphQL"; it will not say "before you ship this GraphQL layer, here is what Marcus would ask you to justify."

**Where we win:** synthesis over retrieval. Knowledge retention is the adjacent surface where we overlap with Glean/Guru at the enterprise tier. Our pitch: Glean helps you *find* Marcus's opinion. Minis *applies* Marcus's judgment. These are different products. We can coexist with Glean inside an enterprise; we can also replace Glean's knowledge-retention pitch with a stronger one.

### Character.ai / Replika / personality-clone consumer products

**What they do:** consumer-facing personality clones and companionship products. Character.ai lets users chat with fictional or historical personas. Replika is a companion chatbot. These are entertainment-adjacent products.

**What they do well:** consumer engagement. Character.ai reached massive scale before its recent troubles. Replika has a devoted user base.

**What they cannot do:** they are not aimed at professional utility. They do not ingest code, they do not understand engineering frameworks, they do not integrate with GitHub. They are a different product for a different audience.

**Where we win:** we are not competing. Character.ai is consumer, we are B2B. The only reason to mention them is to preempt the "isn't Minis just Character.ai for developers?" confusion. It is not. The product, the audience, the pricing, and the pitch are fundamentally different.

### Fine-tune / LoRA / "roll your own"

**What they are:** the "build it yourself" alternative. Take a base model, fine-tune it on an employee's writing corpus, deploy the result. Some companies have tried this. Most have stopped trying because the results are disappointing.

**What they do well:** nothing, in practice. Fine-tuning on a corpus of personal writing produces a model that sounds vaguely like the person but does not reason like them. The voice is imitable; the framework is not.

**What they cannot do:** fine-tuning does not extract framework. Fine-tuning optimizes for next-token-prediction against the training corpus, which is an approximation of "sound like this person" — it is not "reason like this person." The mini that results will hallucinate confidently in the person's voice, which is actively worse than a mini that reasons correctly in a generic voice.

**Where we win:** we are declarative, not parametric. We extract frameworks as data (`principles_matrix`, `knowledge_graph_json`) and apply them at inference time. When the underlying model improves, our minis automatically improve. When our extraction improves, every mini on the corpus automatically upgrades. Fine-tuning is frozen; our approach is live.

**The defensive story:** as fine-tuning tools get better, some teams will try the roll-your-own route. We win because (a) no-training-required is cheaper and faster, (b) our extraction produces structured data that is inspectable and correctable, (c) our append-only corpus is a compounding asset that rolls-your-own cannot easily replicate.

### The unnamed startups that will emerge

Three or four well-funded startups will enter this category in the next eighteen months. We should assume that and plan for it. Some will be ex-FAANG teams with strong engineering. Some will be ex-enterprise-sales teams with relationships that let them skip the IC tier entirely and land Fortune 500 contracts on the strength of the pitch.

Our defensive posture against these competitors is:

- **Corpus depth.** Every month we run, our corpus-per-user grows. A competitor starting today is a year behind in corpus for every user we have.
- **Framework-extraction quality.** We are investing hard in the synthesis layer (ALLIE-425). If we stay ahead on extraction quality for twelve months, we are likely to stay ahead indefinitely — the extraction is the hard part, and experience compounds.
- **Fidelity measurement.** We measure what we ship (ALLIE-382). Competitors who ship vibes will have to catch up on measurement infrastructure.
- **The community and the demo.** Phase 1 (viral IC adoption via Claude Code plugin) gets us known as the original. Being the original matters, especially in a category where trust is currency.

We cannot outspend a well-funded competitor on sales. We can outbuild them on product. That is the bet. That has always been the bet.

### Summary table

| Player | What they do | Where we win |
|---|---|---|
| GitHub Copilot / Copilot PR Review / Spaces | Generic AI code review + personalized assistant | Personalized framework cloning, not generic review |
| CodeRabbit | AI PR review, generic rules | We clone specific reviewers, not generic-quality |
| Cursor / Windsurf / Zed | AI-powered IDE | We're complementary; we own the review surface, not the editor |
| Glean / Guru | Enterprise knowledge retrieval | They retrieve; we synthesize + apply frameworks |
| Clay / Relate | Relationship intelligence | Different surface; we're decision intelligence |
| Character.ai / Replika | Consumer personality clones | Different market; we're B2B utility |
| Fine-tune / LoRA / DIY | Roll-your-own voice clone | Declarative + no-training + incremental = cheaper, safer, better |
| Unnamed competitors | Will emerge 2026–2027 | Corpus depth + extraction quality + fidelity measurement + first-mover community |

Our moat, in summary: **(1)** decision-framework extraction, not voice; **(2)** append-only corpus that earns interest; **(3)** per-repo deep-reading explorers; **(4)** cross-team composition (Tier 4+5); **(5)** enterprise knowledge retention as a 10× category, not a feature.

---

## Guiding Principles (for every contributor, human or agent)

These are not decorations. Every one of these is load-bearing on a decision we make every week. When a contributor violates a principle, the product degrades. When a contributor applies a principle, the product compounds.

### 1. Decision frameworks > voice

When choosing between two improvements, pick the one that makes review-agreement go up, not the one that makes the demo sound prettier.

*What this looks like in practice:* we had an argument in March about whether to spend a week on better prose-style in soul documents versus a week on sharper principle extraction. Prose-style is a demo win; principle extraction is a product win. We chose extraction. The demo took a small hit. The product is materially better. We will make this tradeoff the same way every time.

### 2. Append-only evidence

Never prune. Never TTL. Never garbage-collect. The corpus is the moat. The only deletions are consent-driven GDPR deletions, which are marked explicitly in schema.

*What this looks like in practice:* when an engineer on the team suggested we delete old evidence rows to save storage cost, the answer was no — storage is cheap, corpus is expensive. The retention policy (ALLIE-418) is the framework for how to handle the corpus; it does *not* include pruning. If storage ever becomes a real cost problem, we tier to cold storage; we do not delete.

### 3. No legacy paths

We are pre-0.0.1. We cannot afford dual paths. Flags are rollout tools, not coexistence. When a new path works, delete the old one. Yes, really delete it.

*What this looks like in practice:* ALLIE-389 (per-repo clone explorer) shipped behind a flag, ran behind the flag for two weeks, then the flag was deleted and the legacy REST-based explorer was deleted. Two weeks of flag-protected rollout is fine. Six months of flag-protected coexistence is not. The cost of maintaining the legacy path exceeds the risk of removing it once the new path is validated.

### 4. Linear is the source of truth

Every direction, idea, decision becomes a ticket. The repo materializes the tickets as commits. If it is not in Linear, it does not exist. If it is in Linear, it has an owner and a state.

*What this looks like in practice:* every commit subject references a Linear ticket. Every Claude Code session starts by checking Linear for the active ticket. Every architectural discussion results in at least one Linear ticket before the discussion ends. The ticket graph is the org chart of the work. Violating this principle produces a codebase that drifts from a plan nobody wrote down, which is exactly how products die.

### 5. File tickets liberally

Every bug, tech debt item, gap, concern, "I noticed something" — ticket it. Three minutes to file now saves hours of re-derivation later. No ticket is too small; the work to file one is the smallest unit of leverage.

*What this looks like in practice:* the repo has, at any given time, ~80 open Linear tickets. That is not a sign of disorder. It is a sign of discipline. Every ticket is a decision the team has deliberately deferred rather than forgotten.

### 6. The IC pitch is the entry; the enterprise pitch is the moonshot

Ship the entry. Build toward the moonshot. Do not skip to the moonshot; do not forget the moonshot exists.

*What this looks like in practice:* the Claude Code plugin V1 (ALLIE-422) ships before any enterprise feature. The IC pitch is the GTM. The enterprise tier is the destination. Every architectural decision is tested against: "does this make the IC experience better *and* does it compose up to the enterprise tier?" If it fails either test, we reconsider.

### 7. Security posture matters from day one

Rate limits, cost caps, kill switches, per-IP throttles, usage observability — these ship before they are needed. ALLIE-405 and ALLIE-416 shipped these before we had users who could abuse them. The instant abuse starts, it is too late to build this; we already built it.

*What this looks like in practice:* every new user-facing endpoint gets a throttle. Every LLM-backed action gets a cost cap. Every expensive operation gets an observable metric. No exceptions. The cost of building this is a few hours per feature; the cost of not building it is the product.

### 8. Fidelity is measurable

ALLIE-382 (fidelity evaluation harness) and ALLIE-425 (review-agreement metrics). Don't ship synthesis changes blind. The number-go-up culture is better than the vibe-go-up culture, and the number-go-up culture is the only way to ship a product whose value is "reproduces a person's judgment."

*What this looks like in practice:* every synthesis change is accompanied by a fidelity-harness run. If fidelity goes down, the change is reverted or iterated on. Vibes are for demos; numbers are for ship-gates.

### 9. Build like the corpus will outlast us

Every decision about schema, storage, and ingestion is made as if the corpus will live for twenty years. Because it will. A mini's corpus is a twenty-year asset; treating it like short-term scratch storage will compromise that asset's value at exactly the worst moment.

*What this looks like in practice:* schemas are versioned carefully. Migrations are tested on production snapshots. Ingestion formats are designed to be re-processable. We invest in data infrastructure as if we were the data team at a bank.

### 10. Consent is first-class, not an afterthought

Every piece of ingested data has a consent provenance. Every source has a scope document. Every user can inspect, export, and delete. This is not a nice-to-have; it is the only way the product is legitimately ownable at scale.

*What this looks like in practice:* the Evidence schema has consent annotations. The ingestion pipeline checks consent before fetching. The deletion pipeline (GDPR-flavored) exists even though we have not been asked to use it. When we do get asked, we will respond within the statutory window because the machinery is already built.

---

## Why Now

Every company has a "why now." Ours is three converging waves, any one of which would be insufficient on its own but which together make the product tractable for the first time.

### Wave 1: LLMs are just-barely good enough for framework extraction

Two years ago, GPT-3.5 could not extract a review framework from a corpus of PR comments. It could not reliably distinguish a rule from a quote. Its synthesis, even under heavy prompting, collapsed into a description of what the person said rather than what the person believed.

Today, post-Claude-Sonnet-4, post-Gemini-2.5-Flash, post-GPT-5, the models can do it. Barely, imperfectly, with a lot of scaffolding — but they can do it. The reasoning capability we need to extract "what rule is Alice applying?" from "what Alice said on PR #847" is roughly the reasoning capability that frontier models developed in the 2024–2025 window. Before that, it was not possible. After that, it becomes progressively easier.

This is the first necessary condition for Minis to exist as a product. Without it, we would be building an ambitious wrapper around a model that could not do the core synthesis job.

### Wave 2: Developers are just-barely ready to trust AI with context

Copilot launched in 2021. Cursor launched in 2022. By 2024, developer trust in AI-augmented workflows had shifted from "neat party trick" to "part of my daily stack." The tipping point was somewhere around the Claude-3 / GPT-4 era — the moment developers stopped being surprised when the AI got something right and started being surprised when it got something wrong.

This trust is not automatic and it is not transferable. Minis has to *earn* its specific slice of trust. But the background trust — "AI can be part of my workflow" — is now established. Five years ago, we would have had to fight that battle first. Today, we get to fight the narrower battle of "Minis specifically is worth trusting."

The second necessary condition. Without it, the entire category is still early-adopter-only.

### Wave 3: Enterprise is desperate for knowledge retention

Post-RTO, post-layoffs, post-hype-cycle-reshuffling, the modern workforce is more mobile than it has been since the dot-com era. Tenure at a single company has fallen. The post-COVID "great resignation" and the 2022–2024 tech layoffs together flipped the employer-employee dynamic. Engineers leave more. Knowledge leaves with them more. The pain is acute enough that VPs of Engineering talk about it at dinner parties.

And the existing solutions — docs, wikis, exit interviews — have visibly failed. The same companies that invested heavily in Confluence in 2019 are discovering, in 2025, that their Confluence is a graveyard of half-finished pages and that none of the institutional knowledge they thought they captured is actually retrievable. The moment is right for a better solution to be pitched.

The third necessary condition. Five years ago, the pain was latent. Today, the pain is acute and the buyers are actively shopping.

### And one more: the Claude Code distribution channel

A narrow but important fourth wave: Claude Code and its ecosystem. Claude Code is the first developer tool that has made "install a plugin that calls out to your specific workflow" frictionless. The Minis V1 plugin (ALLIE-422) is the wedge. Every Claude Code user is one `/mini-create` command away from becoming a Minis user. This distribution channel did not exist two years ago.

### The one-line answer

All three waves matter. But if I had to condense: **the models finally reason well enough to extract frameworks, developers finally trust AI enough to accept framework-application, and enterprises are finally desperate enough to pay for framework-retention.** Hit all three in the same twelve months and you have a company. Miss any one and you have a science project.

---

## Why Us

Founding the right company requires convergence: the right idea at the right time with the right people. Three waves align, and the idea is tractable; the third leg of the tripod is whether the specific team pulling the trigger has a reasonable shot.

Here is why we do.

### Obsession

I have been obsessing about this problem for months. Not "I think about it at work" obsessed — the real kind. The kind where the shape of the product has been rewritten in my head every week for long enough that I can tell you, in detail, which version of the architecture I tried in my head last Tuesday and why I abandoned it by Thursday. The kind where the Linear ticket graph (80+ active tickets at last count) is not a project-management artifact but a journal of thought.

Obsession matters because the product is conceptually unfamiliar. "Clone a developer's review function" is a pitch that requires sustained elaboration before it lands. A distracted founder cannot hold the thread long enough to articulate it. I can. I have for months. I will for years.

### Technical credibility

The current codebase is the artifact. ~805 tests, 70%+ coverage, shipping in a research area (autonomous-agent synthesis) that most teams would struggle to even architect. The synthesis pipeline has been rewritten four times as our understanding of what extraction requires has deepened. The model-hierarchy abstraction, the provider-agnostic compaction layer, the DB-backed explorer tool suite, the Evidence schema — every one of these is a real architectural decision made deliberately, tested rigorously, and documented.

This is not a pitch deck with no product. This is a working product with receipts. The demo lands. The code is clean. The tests pass. That is the minimum table-stakes for anyone trusting a founder with real money or real career risk.

### Operational discipline (Linear as source of truth)

Every idea we have becomes a ticket within hours. Every ticket has an owner, a state, and a link to at least one commit. The dev velocity numbers are public in the git log: multiple substantive commits per week, each referencing a ticket, each with a clear scope and a merged PR. This is not normal. Most solo founders ship messily, then have to rebuild after the first hire. We are building for the team that hasn't joined yet.

### Relentless execution

Multiple substantive PRs shipped this month alone across a dozen distinct features. Every one is small, well-scoped, tested, documented. Look at the git log. The cadence is the artifact.

### A willingness to be direct

This document's "it is an HR product disguised as a dev tool" framing. The Arasaka language for the enterprise tier. The explicit "we're a moonshot and that's the point." Not every founder is comfortable being this direct in writing. Directness is what lets a co-founder or early hire read this doc and know, within ten minutes, whether they want in. Hedging loses more candidates than it gains.

### What I am looking for (because this document is also a recruitment artifact)

If you are reading this and you are a potential cofounder, early hire, or investor: here is what would make the team better.

- **A GTM partner.** Somebody who thrives on dev-tool community-building and enterprise-sales-motion design. The product surface and the pitch are strong; the person who can turn them into a repeatable motion is the missing piece.
- **A research-heavy engineer.** Someone who can carry the ALLIE-426 research agenda forward. Not a papers-only person; someone who reads the frontier and ships the best ideas into the product every quarter.
- **A design-heavy engineer.** The product UI is currently functional. It could be transformative. Someone who understands the specific feel that a "mini of my senior" product needs to have — uncanny but not creepy, useful but not overwhelming — could add a dimension the product currently lacks.

If any of those descriptions is you, you know where to find me. The rest of the document is the pitch.

---

## Risks and Mitigations

Honesty section. Every ambitious product has risks. Pretending they do not exist is how founders get caught flat-footed. Here are ours, and our plans.

### Risk 1: Privacy backlash / legal concerns

**The risk:** Minis, especially at the enterprise tier, ingests substantial amounts of employee-generated data. If handled clumsily, this could trigger privacy lawsuits, regulatory scrutiny, union pushback, or a public-opinion disaster ("the company is making AI clones of employees and keeping them after they leave").

**Mitigations:**

- **Consent-first design.** Every ingestion point requires explicit, granular, revocable consent. The consent framework is a first-class product surface, not a checkbox in a ToS.
- **Scope transparency.** Employees can see exactly what is ingested, when, and can inspect any individual item.
- **Deletion rights.** GDPR-grade deletion built from day one, available at the granularity of individual items or the full mini.
- **Dual ownership.** The mini is jointly owned — company has operational rights while employed, employee has the right to a portable personal copy on departure.
- **Legal partnership.** When we go enterprise, we partner with employment law specialists from the first contract. Consent templates are reviewed. Data-handling procedures are audited.
- **Union-proactive positioning.** We will not position Minis as a "replace engineers" product. The framing is always force-multiplication and knowledge-retention *for the benefit of both the employee and the employer.*

### Risk 2: "The mini doesn't sound like me"

**The risk:** Users try the product, feel that their mini (or a teammate's mini) does not sound enough like the real person, and write the product off as not-yet-good-enough.

**Mitigations:**

- **Focus on framework accuracy, not voice fidelity.** Voice is the demo; framework is the product. Our marketing and product UX emphasizes "the mini predicts the review" over "the mini sounds like the person." If the framework is right, users tolerate voice mismatch; if the framework is wrong, voice fidelity doesn't save it.
- **Fidelity harness (ALLIE-382).** Measure it. Publish the numbers. If fidelity is below the bar for a given user, tell them and recommend feeding more data (Tier 1 mini has less data than Tier 3 mini, etc.).
- **Manual override and correction.** Users can correct the mini's framework directly. This increases engagement and materially improves fidelity over time.
- **Explicit scoping.** A mini is not marketed as a perfect replica. It is marketed as "what this person would likely say, grounded in their history." Tempered expectations produce better retention.

### Risk 3: Enterprise sales is hard

**The risk:** Enterprise-tier pricing requires enterprise sales. Enterprise sales requires a sales team, a security posture, a compliance roadmap, and a brand. All of that takes 2+ years and substantial capital.

**Mitigations:**

- **Start at the IC tier.** The free-tier viral motion (Claude Code plugin V1) does not require enterprise sales. It builds a user base, a brand, and a set of reference customers who grow into the Team tier organically.
- **Land-and-expand.** Every enterprise logo starts as a Team-tier customer who expands. By the time we approach enterprise pricing, we already have operational proof inside the organization.
- **Founder-led enterprise for the first 5–10 logos.** No sales team. I take every enterprise call personally. This is slow but it is also the only way to learn the enterprise motion firsthand. By logo #10, the motion is documented and repeatable.
- **SOC-2 early.** We start the SOC-2 audit before we have enterprise demand. This is unusual for a pre-seed company; it is also the move that makes the enterprise motion possible when the demand arrives.

### Risk 4: Competitors will copy

**The risk:** Once the category is proven, well-funded incumbents (GitHub, Microsoft) and well-funded new entrants will pile in. We cannot outspend them. We can outbuild them only for so long.

**Mitigations:**

- **Corpus depth.** Every month we run, our per-user corpus grows. A competitor starting one year from now is structurally a year behind in corpus-per-user for every user we share. Some of the data (e.g., private-repo evidence) is literally impossible to backfill for a competitor.
- **Framework-extraction quality.** Our synthesis layer (ALLIE-425) is our research-grade investment. If we stay ahead on extraction quality, the competitor's product is visibly less good for as long as we maintain the gap.
- **First-mover brand.** Phase 1 (viral IC adoption) establishes us as the original. In a trust-heavy category, being the original is a moat.
- **Composable ecosystem.** Claude Code plugin, GitHub App, Linear integration, Slack integration. Every integration is a place the customer touches Minis. Every integration is a switching cost for the customer to move to a competitor.
- **Community.** Every Minis user who creates a mini of themselves is a community member. Our Discord (or its equivalent) will matter. Communities migrate slowly; if ours is healthy, competitors have to poach one user at a time.

### Risk 5: LLM cost runs away

**The risk:** The product is LLM-backed. If our inference costs grow faster than our revenue, we have an unbounded-cost problem. This has happened to other AI companies.

**Mitigations:**

- **Rate limits and cost caps shipped (ALLIE-405).** Per-IP chat throttle, per-pipeline token cap, LLM kill switch, usage observability. Cost is observable and boundable at the per-user, per-org, and system-wide level.
- **Provider multi-tenancy.** Our model-hierarchy abstraction (`ModelTier` + `get_model(tier, user_override)`) lets us switch providers at any tier. If OpenAI raises prices, we route STANDARD-tier calls to Gemini. If Google changes terms, we route to Anthropic. No single provider can hold us hostage.
- **FAST-tier aggressive use.** Expensive THINKING-tier models are used only where the reasoning quality matters (soul synthesis, framework extraction). FAST-tier models handle compaction, summaries, and bulk operations. This keeps aggregate cost-per-mini well within revenue bounds.
- **Corpus reuse.** Append-only ingestion means we pay the extraction cost once per piece of evidence. Every future synthesis re-uses the prior extraction work. Costs amortize over time.
- **Cache aggressively.** Prompt caching on Anthropic, context reuse on Gemini, embedding-based retrieval to avoid re-synthesis. These are standard tools; we use all of them.

### Risk 6: The "just Character.ai for devs" confusion

**The risk:** Buyers and investors miscategorize us as a consumer personality-clone product, which depresses pricing and attracts the wrong kind of attention.

**Mitigations:**

- **Relentless pitch clarity.** Every public artifact — website, blog, docs, this document — leads with decision-framework cloning, not voice. Voice is mentioned; it is never the hook.
- **Enterprise customer references.** Once we have even two enterprise logos, the positioning problem largely solves itself. "Minis is the tool Fortune 500 engineering orgs use for knowledge retention" is a positioning that Character.ai cannot touch.
- **Technical blog content.** Founder blog posts with depth (model choice, synthesis architecture, fidelity measurement) signal to investors and prospects that this is serious infrastructure, not a toy.

### Risk 7: We ship slower than the window closes

**The risk:** All three "why now" waves create a window. Windows close. If we take three years to ship what we should have shipped in eighteen months, the window is gone and the opportunity is captured by someone else.

**Mitigations:**

- **Operational discipline.** Linear-as-source-of-truth, ticket-per-commit, visible weekly cadence. The public git log is the receipt.
- **Atomic work.** Every PR is small and shippable. We do not accumulate multi-month feature branches. We ship in weeks, not quarters.
- **No-legacy-paths principle.** We do not drag old architectures behind us. When a new path is validated, the old path is deleted. This keeps velocity high and the codebase sharp.
- **Hire for execution.** Every early hire is assessed on shipping velocity as much as on technical depth. Researchers who do not ship are a liability at this stage; builders who ship mediocre code can be mentored.

### Risk 8: A model-provider disruption

**The risk:** A frontier model provider changes their terms, pricing, or access in a way that materially harms our product. This is not hypothetical; it has happened to other AI products.

**Mitigations:**

- **Provider-agnostic core.** Our architecture supports multiple model providers transparently. No single provider is load-bearing. Today we default to Gemini for cost; we can switch to Anthropic or OpenAI with a config change.
- **Multi-provider testing.** Our CI runs a subset of tests against multiple providers. A new Claude release does not surprise us; we caught it before it broke production.
- **Open-weights readiness.** If the closed-weights ecosystem gets hostile, we have an escape valve to open-weights models (Llama, Mistral, Qwen). Quality would take a short-term hit but the product survives.

---

## What This Document Is NOT

- It is not a pitch deck. It is an internal contract.
- It is not a roadmap. The roadmap lives in Linear.
- It is not final. Edit this as the vision sharpens. But never weaken it; always tighten.
- It is not a marketing brief. Marketing writes differently; use this for positioning input.
- It is not a technical spec. Specs live in Linear tickets and RFCs. This document is *why* we build; the specs are *how*.
- It is not a feature list. Features are downstream of vision. If the vision is clear, the features derive themselves.

---

## When Reading This As An Agent

You (the agent) have limited context. You will see snippets of code and chat and tickets. You may be tempted to optimize locally — "this test is easier to write if I loosen that constraint," "this feature would be simpler if we dropped that invariant," "this refactor would be cleaner if we dropped this legacy path but we should keep the flag just in case."

Don't.

Every local optimization is tested against: does it serve the north-star above? If unclear, file a ticket with your concern and ask the orchestrator (or human). The orchestrator will apply the vision. Do not guess.

When you file tickets, reference this document's section ("Tier 3 Teams: automated triage — see VISION.md §Tier 3"). Keep the link alive. When you write commit messages, reference the Linear ticket. When you propose architecture changes, test them against every one of the Guiding Principles above.

The habits that make a great contributor are:

- Read this document before you write code.
- File tickets when you see gaps.
- Delete legacy paths when new paths work.
- Measure fidelity before claiming improvement.
- Prefer data to vibes.
- Err on the side of composability and append-only storage.

And: if you think this document is wrong, say so. File a ticket. Propose the change. But change it by tightening, not by weakening. The vision is the thing that keeps everyone aligned; dilution is a slow-motion disaster.

---

## Closing — To the Reader

If you are reading this, you are one of a small number of people who is going to shape whether Minis becomes a hackathon project that was fun for a quarter or a company that defined a category. The distance between those two outcomes is surprisingly small. It is a matter of whether the people reading this document internalize the vision hard enough that every decision they make, every line of code they write, every conversation they have — with a prospect, with a teammate, with a future hire — is aligned with the shape of the thing we are actually building.

The shape is specific. We are not building a chatbot. We are not building a better Copilot. We are not building an HR dashboard. We are building the first product that reliably preserves the decision-making frameworks of skilled humans in a form that outlives their availability — whether they are in a meeting, on PTO, on another team, or no longer with the company. That product starts as a private tutor for juniors, becomes a productivity multiplier for seniors, becomes a coordination-tax collapser for teams and cross-team initiatives, and ends as the institutional memory of every serious engineering organization on the planet. Each step earns the next.

To the future contributor: welcome. Read this document, read CLAUDE.md, and then look at the Linear ticket graph. The graph is the journal of the vision; every ticket is a thought. File your own. Ship your own. Hold the line on the principles. Do not let the product drift into a local-optimum that saves a week but costs a year.

To the future cofounder: the offer is simple. Build this with me. The idea is right, the timing is right, the market is waking up, and the only variable left is execution. I am going to execute whether or not someone joins me — but the product ships twice as fast, twice as sharp, and twice as far with a second person who sees the same shape I do. If you have read this far and you are still nodding, we should talk. Soon. This window does not stay open forever.

To the future investor: every paragraph of this document is a commitment. The waves that make this possible are real. The moat we are building is structural. The team we will assemble will be among the best in the category. You do not have to believe in all five tiers to write the check — you only have to believe that Tier 1 works (it does), that Tier 5 is directionally correct (it is), and that the team can traverse the ladder (we will). The rest is execution discipline, and the receipts are public.

To the future me, reading this in twelve months: the decisions you are about to regret are the ones where you dropped the principle to ship the thing. Do not drop the principle. The thing that feels too-expensive-to-do-right now will look obvious-to-have-done-right when you read the postmortem. You wrote this document to protect yourself from the version of you that would cut corners under pressure. Trust the document. Trust the principles. Ship the thing that tightens the vision, not the thing that loosens it.

And to whoever is reading this right now, right at this moment, for the first time: you are holding the north star of a product that, if we pull it off, will materially change how engineering institutions preserve and propagate judgment. That is not a small thing. It is worth building carefully. It is worth building fast. It is worth building *right*.

Go build.

---

*Last updated: 2026-04-20. Every future pass that expands this document's depth is a valid PR. Every future pass that dilutes it is not.*
