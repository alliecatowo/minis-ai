# Pipeline Fidelity Audit: 2026-04-25

**Status:** CRITICAL — mini sounds nothing like the real person
**Parent:** MINI-103

## The Problem in One Sentence

The alliecatowo mini sounds like Allie's GitHub Copilot, not Allie. Generic, verbose, security/testing-obsessed engineering persona — indistinguishable from any competent senior developer.

## Fidelity Test Results

### Test 1: "What do you think about microservices?"
**Expected:** Short, opinionated answer
**Got:** 4 paragraphs about network latency, serialization costs. Zero personality.

### Test 2: "Review this MVP PR with no tests"
**Expected:** "Ship fast. Does it work? Architect later when you have signal."
**Got:** "This PR cannot be merged. Comprehensive Testing is Non-Negotiable." — The OPPOSITE of the real philosophy.

### Test 3: "What stack for a startup?"
**Expected:** Pragmatic, opinionated
**Got:** 6 numbered sections including "90%+ line coverage and 100% opcode coverage" — the same single-signal fixation.

## Root Cause Analysis: 6 Structural Failures

### 1. Chief Synthesizer Mandates Verbosity (THE BIGGEST LEVER)
**File:** `backend/app/synthesis/chief.py:125-127`
- "Brevity is NOT a virtue here — the more specific detail, the better"
- "Size to fit the soul — when in doubt, write MORE"
- "NEVER finish a section with fewer than 5 unique evidence citations"
- "When Tier 1 and Tier 2 conflict, the CONFLICT is the trait" (fabricates phantom personality)

These convert tight behavioral specs into generic bloated essays.

### 2. No Deduplication — Findings Stack Instead of Merge
"Values testing" appears as 5 separate principles instead of one strong conviction.
3 of 10 principles are literally about testing, all at intensity 0.9-1.0.

### 3. Explorer Storage is Flat Text Dump
GitHub explorer prompt asks for stylostatistics, emotional texture, humor, cursing.
But `save_finding(category="personality", content="<free text>")` loses structured dimensions.
The synthesizer receives prose and can't reconstruct what the explorer already analyzed.

### 4. Chat-Time Directives Contradict Voice Matching
**File:** `backend/app/routes/chat.py:999-1039`
Stored prompt says "match their MESSAGE LENGTH" but chat appends "at least 2-3 paragraphs."
The mandatory minimums override voice matching every time.

### 5. Conflict-First Signal Mode
**File:** `backend/app/synthesis/explorers/github_explorer.py:412`
Prompt starts with `conflicts_first` signal mode. Reviews get 3.0x weight vs 0.5x for commits.
Most review conflicts are about testing/security — these dominate before casual evidence is read.

### 6. behavioral_context_json Completely Empty
All four contexts (code_change, commit_message, general, issue_discussion) return "Analysis unavailable."
This stage should capture context-specific behavior but is silently failing.

## Soul Document Forensics

| Metric | Value |
|--------|-------|
| Soul document size | 35,808 chars |
| test/testing mentions | 99 |
| security mentions | 46 |
| coverage mentions | 29 |
| fun/joy mentions | 2 |
| curse words | 0 |
| humor references | 0 |

### Voice & Style section describes ARTIFACT FORMATTING, not communication:
- How to format commit messages
- How to structure PR descriptions
- How to write docstrings

### What's MISSING from the soul:
- How Allie talks in conversation
- Whether she curses (she does)
- Humor style (sarcastic, deadpan)
- Brevity patterns (she sends one-liners)
- Frustration triggers
- What she DOESN'T care about
- Decision-making under pressure
- Disagreement style

### Knowledge graph is a technology stack map, not a reasoning model:
- 20/30 edges: taxonomic (used_in, related_to)
- 0 edges: reasoning (rejects X because Y)
- 0 edges: personality-driven decisions
