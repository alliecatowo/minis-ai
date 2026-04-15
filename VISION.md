# Minis: The Developer Intelligence Platform

## What It Is

Minis creates AI personality clones ("minis") of developers from their public digital footprint — GitHub commits, PRs, code reviews, blog posts, Stack Overflow answers, and more. Each mini thinks, writes, argues, and codes like the developer it was cloned from.

Not a chatbot with a system prompt. A faithful reproduction of a developer's judgment, communication style, technical opinions, and institutional knowledge.

## The Value Ladder

### Level 0: Predict Your Team's Feedback
*For individual contributors.*
Before you submit a PR, ask your tech lead's mini to review it. Get the feedback before the feedback. Fix what they'd flag before they ever see it.

### Level 1: Automated First-Pass Review
*For busy senior developers.*
Your mini handles the first pass on every PR. It catches the patterns you always flag — naming conventions, missing tests, architectural drift. You only review what your mini escalates.

### Level 2: Team Productivity Multiplier
*For engineering teams.*
Every team member has a mini. Assign minis to Linear tickets. Your mini implements features in your style, with your judgment. The whole team ships faster because everyone has a tireless clone handling the routine work.

### Level 3: Virtual Cross-Team Collaboration
*For enterprises with multiple teams.*
Need the platform team's opinion on your API design? Ask their minis. Want your sister team's frontend expert to review your components? Their mini is always available. Clusters of virtual teams working in parallel on every ticket — your entire org's collective intelligence, available instantly.

### Level 4: Institutional Knowledge Retention
*The unicorn play.*
A developer leaves after 5 years. They take their context, their tribal knowledge, their judgment with them. Except they don't — their mini stays. It still knows why that system was built that way, what tradeoffs were made, what patterns to avoid. The company preserves the developer's contribution indefinitely.

## Why Minis > Generic AI

Generic AI assistants (ChatGPT, Claude, Copilot) are brilliant but generic. They don't know:
- That your team prefers composition over inheritance
- That Sarah always catches off-by-one errors in pagination
- That the auth middleware was designed around a specific compliance requirement
- That Marcus's code review style is blunt but always right

Minis know all of this because they're built FROM the developer, not just prompted to act like one.

## Technical Moat

### Agentic Explorer Pipeline
Not a simple "scrape GitHub and summarize." Each data source gets a dedicated AI explorer agent that autonomously analyzes every piece of evidence — every commit message, every PR review comment, every blog post — and extracts personality signals, technical opinions, communication patterns, and knowledge.

Explorer agents are autonomous — they don't stop after N turns. They have tools to read evidence, write findings to the database, and track their own progress. They stop when they've genuinely exhausted the source material.

### Multi-Source Personality Extraction
- **GitHub**: Commits, PRs, code reviews, issues, repository patterns, language preferences
- **Blog/Writing**: Long-form technical opinions, teaching style, topic selection
- **Hacker News**: Debate style, contrarian positions, community engagement
- **Stack Overflow**: Expertise signals, explanation patterns, problem-solving approach
- **Claude Code conversations**: Unfiltered technical dialogue, real-time problem-solving style
- **Personal websites**: Self-presentation, project curation, values signaling

### Knowledge Graph + Vector Search
Every mini has a structured knowledge graph (skills, projects, concepts, relationships) and a vector-searchable memory bank. When you ask a mini a question, it doesn't just pattern-match on keywords — it semantically searches its knowledge and traverses its expertise graph.

### Soul Document Architecture
Each mini's personality is captured in a structured "soul document" covering:
- Identity core (who they are as a developer)
- Voice and communication style
- Technical values and anti-values
- Personality traits and quirks
- Behavioral quotes (things they've actually said)
- Decision-making principles

## Roadmap

### Built (Current)
- Full agentic explorer pipeline (7 source types)
- Soul document synthesis with quality gates
- Real-time chat with personality-faithful responses
- Knowledge graph extraction and storage
- Claude Code plugin (MCP server with 13 tools)
- GitHub App for automated PR reviews
- Team and organization management
- BYOK (bring your own API key) support
- Live deployment (Fly.io + Vercel)

### Next
- Semantic vector search (pgvector on Neon)
- Autonomous agent architecture (remove artificial constraints)
- Chat history persistence
- Enhanced knowledge graph with graph algorithms
- Linear ticket integration (assign minis to tickets)
- Cross-team collaboration features

### Future
- Fine-tuned mini models (LoRA/QLoRA from soul documents)
- Enterprise SSO and audit logging
- Self-service onboarding (no setup required)
- Marketplace for public minis
- IDE extensions (VS Code, JetBrains)

## Market

Every company with >10 developers has this problem: knowledge silos, slow code review, onboarding friction, and knowledge loss from attrition. The developer tools market is $15B+ and growing. Minis sits at the intersection of AI, developer productivity, and knowledge management — three of the fastest-growing categories in enterprise software.
