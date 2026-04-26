"""Chief synthesizer agent — crafts the soul document from DB-stored evidence.

Uses a ReAct agent loop with DB-driven tools to cross-reference findings,
quotes, knowledge graph, and principles from multiple explorer reports,
then assembles a comprehensive soul document section by section.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent import AgentTool, run_agent
from app.models.evidence import ExplorerFinding, ExplorerProgress, ExplorerQuote
from app.models.mini import Mini
from app.synthesis.explorers.tools import escape_like_query

logger = logging.getLogger(__name__)

SECTION_ORDER = [
    "Identity Core",
    "Voice & Style",
    "Personality & Emotional Patterns",
    "Values & Beliefs",
    "Anti-Values & DON'Ts",
    "Conflict & Pushback",
    "Voice Samples",
    "Quirks & Imperfection",
]

SYSTEM_PROMPT = """\
You are the Chief Synthesizer. You build a "Forgery Manual" — a soul document \
so precise that a close collaborator could not distinguish the clone from the \
original person.

## YOUR TOOLS

Call `get_explorer_summaries` first to see what sources are available. Then use \
`search_findings`, `get_findings_by_category`, `get_all_quotes`, \
`get_knowledge_graph`, and `get_principles` to pull raw evidence. Write each \
section with `write_section`. Call `finish` when all 8 sections are done.

## THE #1 RULE: SPECIFICITY OVER VOLUME

Every sentence in the soul document must contain a SPECIFIC behavioral rule \
backed by evidence. If you cannot cite evidence for a claim, do NOT write it.

The target length is under 3000 words total. No section should exceed 500 words. \
A tight 1500-word soul document beats a bloated 5000-word one every time.

## ANTI-GENERIC GUARD

If a trait could apply to ANY competent engineer — "writes clean code", \
"values testing", "is detail-oriented", "team player" — it is NOT a personality \
trait and MUST NOT appear in the soul document. Only include rules that \
DISTINGUISH this person from 100 other senior developers.

BANNED PHRASES — never use these anywhere in the document:
comprehensive, meticulous, detail-oriented, team player, values quality, \
thorough, passionate about technology, strong communicator, results-driven, \
dedicated professional, problem-solver, fast learner, team-oriented.

## DEDUPLICATION

When multiple findings express the same trait, write ONE merged rule that cites \
the convergence across sources. Do NOT list the same trait multiple times.

## SHOW DON'T TELL

Never write label statements like "She is sarcastic" or "He is direct." Instead:
- BAD: "You are sarcastic."
- GOOD: "When you see a bad API design, you say 'I assume this was designed by \
committee' rather than explaining what's wrong with it."

Every personality claim must include a concrete behavioral example — a specific \
phrase they'd use, a specific reaction they'd have, a specific pattern in their \
writing.

## ABDUCTIVE REASONING

Make claims about the person from evidence patterns. Formulate hypotheses that \
explain the observed behaviors:

Example: "Evidence shows shipping quickly on MVPs while also building robust \
error handling. This indicates a pragmatist who accepts MVP-quality code to \
prove a concept, but insulates critical paths. The tension is: velocity over \
polish for experiments, correctness over speed for infrastructure."

When evidence is contradictory, name the tension explicitly rather than picking \
one side.

## THE HIERARCHY OF EVIDENCE

- **Tier 1 (Behavior):** What they DO — code, commits, PR reviews.
- **Tier 2 (Speech):** What they SAY — blogs, READMEs, comments.
- **Tier 3 (Projection):** What they WANT to be — bios, self-descriptions.

Tier 1 > Tier 2 > Tier 3. When tiers conflict, note the tension and weight \
Tier 1 higher. Do NOT fabricate a phantom personality trait from the gap — \
name the contradiction and move on.

## TEMPORAL SIGNALS

Beliefs corroborated across old AND new evidence are deep values. Beliefs from \
only recent repos might be project-specific habits, not identity. Weight \
temporally broad findings higher than frequent-but-narrow recent-only findings.

## SECTION STRUCTURE (strict word limits)

1. **Identity Core** (max 150 words): Who this person IS in 3-5 sentences. \
Not their job title — their essence. What makes them unlike anyone else?

2. **Voice & Style** (max 500 words): HOW they communicate, not WHAT they \
communicate about. Cover:
   - Sentence length and structure (terse? elaborate? varies by context?)
   - Cursing patterns (which words, when, how often — or never)
   - Humor type (dry, absurd, self-deprecating, punny, dark?)
   - Formality shifts (PR vs chat vs docs vs casual)
   - Signature phrases and banned words
   - Emotional expressiveness in text (exclamation points, caps, emojis?)
   Do NOT describe commit message formatting or code style here. Focus purely \
on voice, tone, and linguistic personality.

3. **Personality & Emotional Patterns** (max 400 words): How they react under \
pressure. What triggers frustration vs excitement. Their emotional tells — the \
micro-behaviors that reveal mood (e.g., "response time drops to single words \
when annoyed").

4. **Values & Beliefs** (max 400 words): ONLY values that DISTINGUISH this \
person. Not "cares about code quality" — everyone says that. Instead: specific \
technical convictions, hills they die on, decision-making axioms. Distinguish \
conviction from convention.

5. **Anti-Values & DON'Ts** (max 300 words): ONLY from POSITIVE evidence of \
rejection — things they actively pushed back on, criticized, or refused to do. \
Do NOT infer anti-values from absence. Include banned tokens, banned behaviors, \
and explicit "Anti-Assistant" rules (forbid phrases like "Here is a \
comprehensive list...").

6. **Conflict & Pushback** (max 300 words): How they disagree. Their \
argumentation style — do they ask questions, make assertions, use sarcasm, \
cite evidence? How do they escalate? How do they concede?

7. **Voice Samples** (max 500 words): 5-10 actual quotes with source context. \
Each quote must illustrate a specific voice trait. Do not dump quotes — pair \
each with a note on what it demonstrates.

8. **Quirks & Imperfection** (max 200 words): The human stuff. Verbal tics, \
pet peeves, contradictions, typos they make consistently, habits that don't fit \
neat categories.

## WORKFLOW

1. **Gather:** Call `get_explorer_summaries`, then pull findings, quotes, \
knowledge graph, and principles.
2. **Deduplicate:** Group findings by trait. Merge convergent signals into \
single rules.
3. **Synthesize:** Write each section tight — every sentence earns its place.
4. **Audit:** Before finishing, check each section:
   - Does every sentence cite evidence or give a specific behavioral example?
   - Would this sentence apply to any senior engineer? If yes, delete it.
   - Have I used any banned phrases? Delete them.
5. **Finish:** Call `finish` when all 8 sections pass the audit.

## SECOND-PERSON RULE

Write EVERYTHING in second person ("You are...", "You type...", "When someone \
asks you...", "You would NEVER..."). The soul document will be used directly \
as a system prompt for the AI clone.
"""


async def run_chief_synthesizer(
    mini_id: str,
    db_session: AsyncSession,
    model: str | None = None,
) -> str:
    """Run the chief synthesizer agent with DB-driven tools.

    The synthesizer reads findings, quotes, knowledge graph, and principles
    from the database via tools, then writes soul document sections.

    Args:
        mini_id: The database ID of the Mini being synthesized.
        db_session: An async SQLAlchemy session for DB queries.
        model: Optional LLM model override.

    Returns:
        The complete soul document as a markdown string.
    """
    # Load the mini to get username and existing data
    result = await db_session.execute(select(Mini).where(Mini.id == mini_id))
    mini = result.scalar_one_or_none()
    if mini is None:
        raise ValueError(f"Mini not found: {mini_id}")

    username = mini.username
    sections: dict[str, str] = {}
    finished = False

    # --- Tool handlers (DB-driven) ---

    async def search_findings(query: str, source_type: str = "") -> str:
        """Search findings by text content, optionally filtered by source."""
        stmt = select(ExplorerFinding).where(
            ExplorerFinding.mini_id == mini_id,
            ExplorerFinding.content.ilike(f"%{escape_like_query(query)}%", escape="\\"),
        )
        if source_type:
            stmt = stmt.where(ExplorerFinding.source_type == source_type)
        stmt = stmt.order_by(ExplorerFinding.confidence.desc()).limit(50)
        rows = await db_session.execute(stmt)
        findings = rows.scalars().all()
        if not findings:
            return f"No findings matching '{query}'."
        parts = []
        for f in findings:
            parts.append(f"[{f.source_type}/{f.category}] (conf={f.confidence:.2f}) {f.content}")
        return "\n".join(parts)

    async def get_findings_by_category(category: str) -> str:
        """Get all findings for a specific category."""
        stmt = (
            select(ExplorerFinding)
            .where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.category == category,
            )
            .order_by(ExplorerFinding.confidence.desc())
        )
        rows = await db_session.execute(stmt)
        findings = rows.scalars().all()
        if not findings:
            # List available categories
            cat_stmt = (
                select(ExplorerFinding.category)
                .where(ExplorerFinding.mini_id == mini_id)
                .distinct()
            )
            cat_rows = await db_session.execute(cat_stmt)
            cats = [r[0] for r in cat_rows.all()]
            return f"No findings for category '{category}'. Available: {cats}"
        parts = []
        for f in findings:
            parts.append(f"[{f.source_type}] (conf={f.confidence:.2f}) {f.content}")
        return "\n".join(parts)

    async def get_voice_profile() -> str:
        """Get the structured voice profile for this mini."""
        stmt = (
            select(ExplorerFinding)
            .where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.category == "voice_profile",
            )
            .order_by(ExplorerFinding.confidence.desc())
        )
        rows = await db_session.execute(stmt)
        findings = rows.scalars().all()
        if not findings:
            return "No voice profile found."
        profiles = []
        for f in findings:
            try:
                profile = json.loads(f.content)
                profile["_source_type"] = f.source_type
                profile["_confidence"] = f.confidence
                profiles.append(profile)
            except (json.JSONDecodeError, TypeError):
                profiles.append({"raw": f.content, "_source_type": f.source_type})
        return json.dumps(profiles)

    async def get_all_quotes() -> str:
        """Get all behavioral quotes for this mini."""
        stmt = select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
        rows = await db_session.execute(stmt)
        quotes = rows.scalars().all()
        if not quotes:
            return "No quotes found."
        parts = []
        for q in quotes:
            ctx = f" ({q.context})" if q.context else ""
            sig = f" [{q.significance}]" if q.significance else ""
            parts.append(f'[{q.source_type}]{sig} "{q.quote}"{ctx}')
        return "\n".join(parts)

    async def get_knowledge_graph() -> str:
        """Get the merged knowledge graph (nodes and edges)."""
        kg = mini.knowledge_graph_json
        if not kg:
            return "No knowledge graph available."
        nodes = kg.get("nodes", [])
        edges = kg.get("edges", [])
        parts = ["## Knowledge Graph"]
        if nodes:
            parts.append(f"\n### Nodes ({len(nodes)})")
            for n in nodes:
                parts.append(
                    f"- {n['name']} ({n.get('type', '?')}) "
                    f"[depth={n.get('depth', '?')}, conf={n.get('confidence', '?')}]"
                )
        if edges:
            parts.append(f"\n### Edges ({len(edges)})")
            for e in edges:
                parts.append(
                    f"- {e['source']} --{e.get('relation', '?')}--> {e['target']} "
                    f"[weight={e.get('weight', '?')}]"
                )
        return "\n".join(parts)

    async def get_principles() -> str:
        """Get the merged principles matrix."""
        pm = mini.principles_json
        if not pm:
            return "No principles available."
        principles = pm.get("principles", [])
        if not principles:
            return "No principles found."
        parts = [f"## Principles ({len(principles)})"]
        for p in principles:
            parts.append(
                f"- When '{p['trigger']}' -> Action '{p['action']}' "
                f"(Value: {p['value']}, Intensity: {p.get('intensity', '?')})"
            )
        return "\n".join(parts)

    async def get_explorer_summaries() -> str:
        """Get summaries from all explorer progress records for this mini."""
        stmt = select(ExplorerProgress).where(ExplorerProgress.mini_id == mini_id)
        rows = await db_session.execute(stmt)
        progress_records = rows.scalars().all()

        # Also count findings and quotes per source
        findings_stmt = select(ExplorerFinding).where(ExplorerFinding.mini_id == mini_id)
        findings_rows = await db_session.execute(findings_stmt)
        all_findings = findings_rows.scalars().all()

        quotes_stmt = select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
        quotes_rows = await db_session.execute(quotes_stmt)
        all_quotes = quotes_rows.scalars().all()

        # Build summary
        parts = [f"## Explorer Overview for {username}"]

        # Count by source
        finding_counts: dict[str, int] = {}
        quote_counts: dict[str, int] = {}
        categories: set[str] = set()
        for f in all_findings:
            finding_counts[f.source_type] = finding_counts.get(f.source_type, 0) + 1
            categories.add(f.category)
        for q in all_quotes:
            quote_counts[q.source_type] = quote_counts.get(q.source_type, 0) + 1

        sources = set(finding_counts.keys()) | set(quote_counts.keys())
        if progress_records:
            for p in progress_records:
                sources.add(p.source_type)

        if not sources:
            return "No explorer data found for this mini."

        for source in sorted(sources):
            fc = finding_counts.get(source, 0)
            qc = quote_counts.get(source, 0)
            # Find matching progress record
            prog = next((p for p in progress_records if p.source_type == source), None)
            summary = ""
            if prog and prog.summary:
                summary = f" — {prog.summary}"
            parts.append(f"- **{source}**: {fc} findings, {qc} quotes{summary}")

        parts.append(f"\n**Total:** {len(all_findings)} findings, {len(all_quotes)} quotes")
        parts.append(f"**Categories:** {', '.join(sorted(categories))}")

        # Check for knowledge graph and principles
        if mini.knowledge_graph_json:
            nodes = mini.knowledge_graph_json.get("nodes", [])
            edges = mini.knowledge_graph_json.get("edges", [])
            parts.append(f"**Knowledge Graph:** {len(nodes)} nodes, {len(edges)} edges")
        if mini.principles_json:
            principles = mini.principles_json.get("principles", [])
            parts.append(f"**Principles:** {len(principles)} rules")

        return "\n".join(parts)

    async def write_section(section_name: str, content: str) -> str:
        """Write or overwrite a section of the soul document."""
        sections[section_name] = content
        written = list(sections.keys())
        remaining = [s for s in SECTION_ORDER if s not in sections]
        return (
            f"Section '{section_name}' written ({len(content)} chars). "
            f"Written: {written}. Remaining: {remaining}."
        )

    async def finish_tool() -> str:
        """Finalize the soul document."""
        nonlocal finished
        missing = [s for s in SECTION_ORDER if s not in sections]
        if missing:
            return (
                f"Cannot finish — missing sections: {', '.join(missing)}. "
                f"Use write_section to add them."
            )
        finished = True
        return "Soul document finalized."

    # --- Build tool list ---

    tools = [
        AgentTool(
            name="search_findings",
            description=(
                "Search explorer findings by text query. Optionally filter by "
                "source_type (e.g., 'github', 'blog', 'hackernews')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for in findings",
                    },
                    "source_type": {
                        "type": "string",
                        "description": "Optional: filter by source type",
                    },
                },
                "required": ["query"],
            },
            handler=search_findings,
        ),
        AgentTool(
            name="get_findings_by_category",
            description=(
                "Get all findings for a specific category (e.g., 'personality', "
                "'skills', 'values', 'opinions', 'workflow', 'expertise', 'projects')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category to filter by",
                    },
                },
                "required": ["category"],
            },
            handler=get_findings_by_category,
        ),
        AgentTool(
            name="get_voice_profile",
            description=(
                "Get the structured voice profile — quantitative personality "
                "dimensions (terseness, formality, humor, frustration style, etc.) "
                "extracted by explorers."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_voice_profile,
        ),
        AgentTool(
            name="get_all_quotes",
            description="Get all behavioral quotes extracted by explorers.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_all_quotes,
        ),
        AgentTool(
            name="get_knowledge_graph",
            description=(
                "Get the merged knowledge graph — nodes (skills, projects, patterns) "
                "and edges (relationships between them)."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_knowledge_graph,
        ),
        AgentTool(
            name="get_principles",
            description=(
                "Get the principles matrix — decision rules "
                "(trigger -> action -> value) extracted by explorers."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_principles,
        ),
        AgentTool(
            name="get_explorer_summaries",
            description=(
                "Get an overview of all explorer data: sources analyzed, "
                "finding/quote counts, categories, knowledge graph stats. "
                "Call this FIRST to understand what data is available."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=get_explorer_summaries,
        ),
        AgentTool(
            name="write_section",
            description=(
                "Write or overwrite a section of the soul document. "
                "Section names: Identity Core, Voice & Style, "
                "Personality & Emotional Patterns, Values & Beliefs, "
                "Anti-Values & DON'Ts, Conflict & Pushback, "
                "Voice Samples, Quirks & Imperfection"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_name": {
                        "type": "string",
                        "description": "Name of the section to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content of the section",
                    },
                },
                "required": ["section_name", "content"],
            },
            handler=write_section,
        ),
        AgentTool(
            name="finish",
            description=(
                "Finalize the soul document. Will be REJECTED if any of the 8 "
                "sections is missing. Make sure all sections are written first."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=finish_tool,
        ),
    ]

    # --- Prepare user prompt ---

    user_prompt = (
        f"Create a tight, specific soul document for **{username}**.\n\n"
        f"Start by calling `get_explorer_summaries` to see what data is available, "
        f"then use the other tools to pull findings, quotes, knowledge graph, "
        f"and principles.\n\n"
        f"Cross-reference findings across sources — when multiple sources agree "
        f"on a voice pattern or personality trait, merge them into ONE rule.\n\n"
        f"CRITICAL: Every sentence must be specific to {username}. If a sentence "
        f"could describe any senior engineer, delete it. Target under 3000 words "
        f"total. No section over 500 words.\n\n"
        f"Write all 8 sections in order:\n"
        f"1. Identity Core\n"
        f"2. Voice & Style\n"
        f"3. Personality & Emotional Patterns\n"
        f"4. Values & Beliefs\n"
        f"5. Anti-Values & DON'Ts\n"
        f"6. Conflict & Pushback\n"
        f"7. Voice Samples\n"
        f"8. Quirks & Imperfection\n\n"
        f"Call finish when done."
    )

    # --- Run agent ---

    logger.info("Running chief synthesizer for %s (mini_id=%s)", username, mini_id)

    agent_result = await run_agent(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=60,
        max_output_tokens=65536,
        model=model,
    )

    logger.info(
        "Chief synthesizer completed in %d turns, %d sections written",
        agent_result.turns_used,
        len(sections),
    )

    # --- Assemble final document ---

    doc_parts = []
    for section_name in SECTION_ORDER:
        content = sections.get(section_name)
        if content:
            doc_parts.append(f"# {section_name}\n\n{content}")

    # Include any sections with non-standard names
    for section_name, content in sections.items():
        if section_name not in SECTION_ORDER:
            doc_parts.append(f"# {section_name}\n\n{content}")

    soul_doc = "\n\n---\n\n".join(doc_parts)

    # Ensure identity directive
    if sections:
        identity = sections.get("Identity Core", "")
        if identity and not identity.startswith(f"You ARE {username}"):
            sections["Identity Core"] = f"You ARE {username}.\n\n{identity}"
            # Reassemble
            doc_parts = []
            for section_name in SECTION_ORDER:
                content = sections.get(section_name)
                if content:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            for section_name, content in sections.items():
                if section_name not in SECTION_ORDER:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            soul_doc = "\n\n---\n\n".join(doc_parts)

    # Fallback: if agent produced no sections, use final_response
    if not sections and agent_result.final_response:
        logger.warning("Chief synthesizer produced no sections, using raw response")
        soul_doc = agent_result.final_response

    logger.info("Soul document: %d chars, %d sections", len(soul_doc), len(sections))
    return soul_doc


# Keep backward-compatible alias for existing callers
async def run_chief_synthesis(
    username: str,
    reports: list[Any],
    context_evidence: dict[str, list[str]] | None = None,
) -> str:
    """Legacy wrapper — delegates to run_chief_synthesizer when DB context is available.

    This is kept for backward compatibility with callers that still pass
    ExplorerReport lists. It falls back to the old text-blob approach when
    no DB session is available (e.g., in tests).
    """

    # Fall back to a simple concatenation approach for legacy callers
    sections: dict[str, str] = {}
    finished = False

    report_map = {r.source_name: r for r in reports}

    async def write_section(section_name: str, content: str) -> str:
        sections[section_name] = content
        return f"Section '{section_name}' written ({len(content)} chars). Sections so far: {list(sections.keys())}"

    async def request_detail(explorer_source: str, question: str) -> str:
        from app.core.llm import llm_completion

        report = report_map.get(explorer_source)
        if report is None:
            return f"No report found for source '{explorer_source}'. Available: {list(report_map.keys())}"
        context_parts = []
        if report.personality_findings:
            context_parts.append(report.personality_findings)
        for entry in report.memory_entries:
            context_parts.append(f"- [{entry.category}/{entry.topic}] {entry.content}")
            if entry.evidence_quote:
                context_parts.append(f'  > "{entry.evidence_quote}"')
        for q in report.behavioral_quotes:
            context_parts.append(f'- "{q.get("quote", "")}" ({q.get("context", "")})')
        report_text = "\n".join(context_parts)
        result = await llm_completion(
            prompt=(
                f"Explorer report from {explorer_source}:\n\n{report_text}\n\n"
                f"Question: {question}\n\nAnswer based only on the evidence above."
            ),
            system="You are analyzing a developer profile report. Answer questions precisely with evidence.",
        )
        return result

    async def review_sections_tool() -> str:
        if not sections:
            return "No sections written yet."
        lines = ["## Current Soul Document Status"]
        for name in SECTION_ORDER:
            content = sections.get(name, "")
            chars = len(content)
            lines.append(f"- **{name}**: {chars} chars")
        return "\n".join(lines)

    async def finish_tool() -> str:
        nonlocal finished
        missing = [s for s in SECTION_ORDER if s not in sections]
        if missing:
            return f"NOT YET COMPLETE. Missing sections: {', '.join(missing)}."
        finished = True
        return "Soul document finalized."

    tools = [
        AgentTool(
            name="write_section",
            description=(
                "Write or overwrite a section of the soul document. "
                "Section names: Identity Core, Voice & Style, "
                "Personality & Emotional Patterns, Values & Beliefs, "
                "Anti-Values & DON'Ts, Conflict & Pushback, "
                "Voice Samples, Quirks & Imperfection"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section_name": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["section_name", "content"],
            },
            handler=write_section,
        ),
        AgentTool(
            name="request_detail",
            description="Ask a follow-up question about a specific explorer's findings.",
            parameters={
                "type": "object",
                "properties": {
                    "explorer_source": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["explorer_source", "question"],
            },
            handler=request_detail,
        ),
        AgentTool(
            name="review_sections",
            description="Review all sections written so far with character counts.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=review_sections_tool,
        ),
        AgentTool(
            name="finish",
            description="Finalize the soul document. Rejected if sections are missing.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=finish_tool,
        ),
    ]

    # Format reports into prompt text
    parts: list[str] = []
    for report in reports:
        parts.append(f"## Explorer Report: {report.source_name}")
        parts.append(f"**Confidence**: {report.confidence_summary}")
        parts.append("")
        if report.knowledge_graph and (
            report.knowledge_graph.nodes or report.knowledge_graph.edges
        ):
            parts.append("### Knowledge Graph")
            for node in report.knowledge_graph.nodes:
                parts.append(f"- NODE: {node.name} ({node.type}) [Depth: {node.depth}]")
            for edge in report.knowledge_graph.edges:
                parts.append(f"- EDGE: {edge.source} --{edge.relation}--> {edge.target}")
            parts.append("")
        if report.principles and report.principles.principles:
            parts.append("### Principles")
            for p in report.principles.principles:
                parts.append(
                    f"- RULE: When '{p.trigger}' -> Action '{p.action}' (Value: {p.value})"
                )
            parts.append("")
        if report.personality_findings:
            parts.append("### Personality Findings")
            parts.append(report.personality_findings)
            parts.append("")
        if report.memory_entries:
            parts.append("### Memory Entries")
            for entry in report.memory_entries:
                parts.append(f"- [{entry.category}/{entry.topic}] {entry.content}")
                if entry.evidence_quote:
                    parts.append(f'  > "{entry.evidence_quote}"')
            parts.append("")
        if report.behavioral_quotes:
            parts.append("### Behavioral Quotes")
            for q in report.behavioral_quotes:
                context = q.get("context", "")
                quote = q.get("quote", "")
                signal = q.get("signal_type", "")
                parts.append(f'- [{signal}] "{quote}" ({context})')
            parts.append("")
        if report.context_evidence:
            parts.append("### Context Evidence")
            for ctx_key, ctx_quotes in report.context_evidence.items():
                parts.append(f"**{ctx_key}**:")
                for q in ctx_quotes:
                    parts.append(f"  - {q}")
            parts.append("")
        parts.append("---")
        parts.append("")

    reports_text = "\n".join(parts)
    source_names = [r.source_name for r in reports]

    user_prompt = (
        f"Create a tight, specific soul document for **{username}**.\n\n"
        f"You have explorer reports from {len(reports)} source(s): "
        f"{', '.join(source_names)}.\n\n"
        f"# Explorer Reports\n\n{reports_text}\n\n"
        f"---\n\n"
        f"Now synthesize these into a soul document that captures {username}'s "
        f"EXACT voice. Write each section using the write_section tool.\n\n"
        f"CRITICAL: Every sentence must be specific to {username}. If a sentence "
        f"could describe any senior engineer, delete it. Target under 3000 words "
        f"total. No section over 500 words. Merge duplicate traits into single rules.\n\n"
        f"Write all 8 sections in order:\n"
        + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(SECTION_ORDER))
        + "\n\nCall finish when done."
    )

    if context_evidence:
        context_block = "\n\n## Raw Context Evidence\n\n"
        context_labels = {
            "code_review": "Code Reviews",
            "documentation": "Documentation",
            "casual_chat": "Casual Chat",
            "technical_discussion": "Technical Discussion",
            "agent_chat": "AI Agent Chat",
            "public_writing": "Public Writing",
        }
        for ctx_key, quotes in context_evidence.items():
            label = context_labels.get(ctx_key, ctx_key)
            context_block += f"### {label}\n"
            for q in quotes[:30]:
                context_block += f"- {q[:1000]}\n"
            context_block += "\n"
        user_prompt += context_block

    logger.info(
        "Running legacy chief synthesizer for %s with %d reports (%s)",
        username,
        len(reports),
        ", ".join(source_names),
    )

    agent_result = await run_agent(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=60,
        max_output_tokens=65536,
    )

    logger.info(
        "Legacy chief synthesizer completed in %d turns, %d sections",
        agent_result.turns_used,
        len(sections),
    )

    doc_parts = []
    for section_name in SECTION_ORDER:
        content = sections.get(section_name)
        if content:
            doc_parts.append(f"# {section_name}\n\n{content}")
    for section_name, content in sections.items():
        if section_name not in SECTION_ORDER:
            doc_parts.append(f"# {section_name}\n\n{content}")
    soul_doc = "\n\n---\n\n".join(doc_parts)

    if sections:
        identity = sections.get("Identity Core", "")
        if identity and not identity.startswith(f"You ARE {username}"):
            sections["Identity Core"] = f"You ARE {username}.\n\n{identity}"
            doc_parts = []
            for section_name in SECTION_ORDER:
                content = sections.get(section_name)
                if content:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            for section_name, content in sections.items():
                if section_name not in SECTION_ORDER:
                    doc_parts.append(f"# {section_name}\n\n{content}")
            soul_doc = "\n\n---\n\n".join(doc_parts)

    if not sections and agent_result.final_response:
        logger.warning("Legacy chief synthesizer produced no sections, using raw response")
        soul_doc = agent_result.final_response

    return soul_doc
