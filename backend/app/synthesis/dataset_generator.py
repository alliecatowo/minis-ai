"""Dataset generator for QLoRA fine-tuning data.

Produces DPO-style (instruction, chosen, rejected) pairs from a mini's soul and memory
documents. The chosen response is spirit-aligned (the user's voice); the rejected response
is generic AI voice. Used as the foundation for ALLIE-89/90/91.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

# ── Constants ────────────────────────────────────────────────────────────────

GENERIC_AI_SYSTEM_PROMPT = """You are a helpful, harmless, and honest AI assistant. \
Your goal is to provide accurate, informative, and comprehensive responses to user \
inquiries. You approach every question with balanced objectivity, taking care to \
present multiple perspectives where relevant. You communicate in clear, professional \
language that is accessible to a broad audience. You always strive to be thorough, \
considerate, and constructive in your replies, and you avoid expressing strong personal \
opinions that might alienate or mislead users. When discussing technical topics, you \
explain concepts step by step, ensuring clarity for readers of all experience levels. \
You prioritize helpfulness above all else and endeavor to leave the user with a \
complete and satisfying answer to their question. If you are uncertain about something, \
you note your uncertainty and suggest that the user consult additional sources. You do \
not take sides in debates and prefer to present the pros and cons of each approach so \
the user can make an informed decision. Your responses are well-structured, often using \
headers and bullet points to improve readability and comprehension."""

IDENTITY_QUESTIONS: list[str] = [
    "How do you approach learning a new programming language?",
    "What's your philosophy around software architecture?",
    "How do you handle disagreements with teammates on technical decisions?",
    "What does good code look like to you?",
    "How do you think about technical debt?",
    "What's your take on documentation — necessary evil or essential?",
    "How do you decide when to refactor versus rewrite?",
    "What's your debugging process when you're completely stuck?",
    "How do you feel about code reviews?",
    "What technologies are you most excited about right now?",
    "How do you balance shipping fast versus doing it right?",
    "What's your relationship with open source?",
    "How do you think about mentoring junior developers?",
    "What's the worst kind of technical interview question?",
    "How do you stay current with the field without drowning in content?",
    "What's a common engineering practice you think is overrated?",
    "How do you approach system design problems?",
    "What's your opinion on test-driven development?",
    "How do you handle burnout or low motivation periods?",
    "What's the most important non-technical skill for a developer?",
    "How do you think about work-life balance as an engineer?",
    "What's your biggest engineering regret or lesson learned?",
    "How do you evaluate whether a technology is worth adopting?",
    "What kind of problems do you find most satisfying to solve?",
    "What would you tell your junior developer self?",
]

CODE_REVIEW_SCENARIOS: list[str] = [
    "Review this function: it opens a DB connection inside a loop to fetch user records.",
    "This PR adds 800 lines of new abstraction for a feature used in exactly one place.",
    "Someone submitted a class with 12 constructor parameters and no docs.",
    "A junior dev's PR rewrites an existing utility in a framework no one else knows.",
    "This code catches all exceptions with a bare `except: pass`.",
    "Review a PR that adds feature flags nested 4 levels deep.",
    "Someone copy-pasted 200 lines from Stack Overflow with no attribution or understanding.",
    "A PR introduces a global mutable singleton for caching.",
    "Review this: all business logic is in a 600-line God class.",
    "This PR adds async/await to a function that does no I/O.",
    "Review code that stores passwords in plaintext in a config file.",
    "A PR that uses recursion with no base case on user-supplied input.",
    "This function has 14 boolean parameters and no named arguments.",
    "Review a PR where every method is a one-liner wrapped in an unnecessary class.",
    "Someone added 40 lines of comments explaining what the code does, not why.",
    "This PR introduces a custom ORM to replace SQLAlchemy for 'simplicity'.",
    "Review a commit that deletes all tests 'because they were flaky'.",
    "A PR that uses `eval()` on user input for 'dynamic configuration'.",
    "Review code that hardcodes production credentials in the source.",
    "This PR introduces 3 new npm packages to replace a 5-line helper function.",
]

ARCH_DEBATE_PROMPTS: list[str] = [
    "Microservices vs monolith — where do you land?",
    "GraphQL vs REST for a new public API?",
    "Is Kubernetes worth the operational complexity for a small team?",
    "SQL vs NoSQL: when does each make sense?",
    "Server-side rendering vs client-side rendering in 2025?",
    "Should you write your own auth or always use a third-party service?",
    "Event sourcing: engineering discipline or over-engineering?",
    "Is TypeScript worth the overhead for a small startup?",
    "Serverless vs always-on: what drives your choice?",
    "Shared database vs per-service database in a service-oriented architecture?",
    "How much should a team invest in internal tooling vs shipping product?",
    "Feature flags: engineering best practice or source of permanent tech debt?",
    "When does a message queue actually solve your problem vs add complexity?",
    "Monorepo vs polyrepo for a growing engineering team?",
    "Should you abstract your LLM provider or lock in to one?",
]

COMM_STYLE_PROMPTS: list[str] = [
    "How do you write a good technical RFC or design doc?",
    "What makes a good commit message?",
    "How do you give feedback that actually lands?",
    "What do you put in a PR description?",
    "How do you run a productive engineering meeting?",
    "What does a good bug report look like?",
    "How do you communicate a technical problem to non-technical stakeholders?",
    "How do you handle a situation where you disagree with your manager's technical call?",
    "What's your approach to async communication on a distributed team?",
    "How do you onboard a new engineer to a complex codebase?",
    "How do you push back on unrealistic deadlines?",
    "What's your preferred format for sharing technical context in Slack/Discord?",
    "How do you document an architecture decision?",
    "What makes a technical blog post worth reading?",
    "How do you keep stakeholders informed without writing a novel every week?",
]

# ── Models ────────────────────────────────────────────────────────────────────


class DatasetGenerationConfig(BaseModel):
    mini_id: str
    num_pairs: int = Field(default=80, ge=10, le=200)
    base_llm: str = "claude-3-5-haiku-latest"
    temperature: float = Field(default=0.85, ge=0.0, le=2.0)
    output_dir: Path | None = None


class QAPair(BaseModel):
    instruction: str
    chosen: str
    rejected: str
    skill_type: str
    source: str = "synthetic"
    example_id: str | None = None


class SoulProfile(BaseModel):
    communication_style: str = ""
    values: list[str] = []
    technical_identity: str = ""
    quirks: list[str] = []
    example_phrases: list[str] = []


# ── Soul document parsing ─────────────────────────────────────────────────────

_SECTION_ALIASES: dict[str, list[str]] = {
    "communication_style": [
        "communication style",
        "communication protocol",
        "how they communicate",
        "style",
        "voice",
        "writing style",
        "how they write",
        "tone",
    ],
    "values": [
        "values",
        "core values",
        "engineering values",
        "principles",
        "what they believe",
        "beliefs",
    ],
    "technical_identity": [
        "technical identity",
        "technical persona",
        "engineering identity",
        "who they are",
        "identity",
        "personality",
        "technical profile",
    ],
    "quirks": [
        "quirks",
        "tics",
        "verbal tics",
        "habits",
        "signature behaviors",
        "characteristic phrases",
        "behavioral quirks",
        "imperfections",
    ],
    "example_phrases": [
        "example phrases",
        "sample phrases",
        "signature phrases",
        "example quotes",
        "voice samples",
        "speech patterns",
        "catchphrases",
    ],
}


class SoulDocumentParser:
    """Parses a Markdown spirit/soul document into a structured SoulProfile."""

    def parse(self, spirit_content: str) -> SoulProfile:
        sections = self._split_sections(spirit_content)
        profile = SoulProfile()

        for field_name, aliases in _SECTION_ALIASES.items():
            for title, body in sections.items():
                if any(alias in title.lower() for alias in aliases):
                    if field_name == "values":
                        profile.values = self._extract_list_items(body)
                    elif field_name == "quirks":
                        profile.quirks = self._extract_list_items(body)
                    elif field_name == "example_phrases":
                        profile.example_phrases = self._extract_list_items(body)
                    elif field_name == "communication_style":
                        profile.communication_style = body.strip()
                    elif field_name == "technical_identity":
                        profile.technical_identity = body.strip()
                    break  # first matching section wins for this field

        return profile

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _split_sections(text: str) -> dict[str, str]:
        """Split a Markdown doc into {section_title: body} dict.

        Handles H1 (# ...) and H2 (## ...) headings; lower headings are kept
        as body text of their parent section.
        """
        sections: dict[str, str] = {}
        current_title = "__preamble__"
        current_lines: list[str] = []

        for line in text.splitlines():
            heading_match = re.match(r"^#{1,2}\s+(.+)$", line)
            if heading_match:
                if current_lines:
                    sections[current_title] = "\n".join(current_lines)
                current_title = heading_match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_lines:
            sections[current_title] = "\n".join(current_lines)

        return sections

    @staticmethod
    def _extract_list_items(text: str) -> list[str]:
        """Extract bullet / numbered list items from a block of text."""
        items: list[str] = []
        for line in text.splitlines():
            m = re.match(r"^\s*[-*•]\s+(.+)$", line)
            if m:
                items.append(m.group(1).strip())
                continue
            m = re.match(r"^\s*\d+\.\s+(.+)$", line)
            if m:
                items.append(m.group(1).strip())
        return items


# ── Utility functions ─────────────────────────────────────────────────────────


def extract_behavioral_quotes(memory_content: str, max_quotes: int = 20) -> list[str]:
    """Extract behavioral quotes or example statements from a memory document.

    Looks for blockquotes (> ...), quoted strings ("..."), and lines that
    contain the word "example" or "quote" in context.
    """
    quotes: list[str] = []

    for line in memory_content.splitlines():
        stripped = line.strip()

        # Markdown blockquote
        if stripped.startswith("> ") and len(stripped) > 3:
            quotes.append(stripped[2:].strip())
            continue

        # Inline quote wrapped in double quotes (long enough to be meaningful)
        inline = re.findall(r'"([^"]{20,})"', stripped)
        quotes.extend(inline)

    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in quotes:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique[:max_quotes]


def build_spirit_system_prompt(soul: SoulProfile, username: str) -> str:
    """Construct a concise system prompt from a parsed SoulProfile for dataset generation."""
    parts: list[str] = [
        f"You ARE {username}. Respond exactly as {username} would — same voice, "
        f"same energy, same opinions, same rough edges. Never break character.\n",
    ]

    if soul.technical_identity:
        parts.append(f"\n## Identity\n{soul.technical_identity}\n")

    if soul.communication_style:
        parts.append(f"\n## Communication Style\n{soul.communication_style}\n")

    if soul.values:
        parts.append("\n## Values\n" + "\n".join(f"- {v}" for v in soul.values) + "\n")

    if soul.quirks:
        parts.append(
            "\n## Quirks & Verbal Tics\n" + "\n".join(f"- {q}" for q in soul.quirks) + "\n"
        )

    if soul.example_phrases:
        parts.append(
            "\n## Example Phrases (use these naturally)\n"
            + "\n".join(f'- "{p}"' for p in soul.example_phrases)
            + "\n"
        )

    parts.append(
        f"\n## Hard Rules\n"
        f"- NEVER say 'Great question!' or 'I'd be happy to help!'\n"
        f"- NEVER hedge with 'It's worth noting that' or 'It's important to consider'\n"
        f"- NEVER pad responses with filler sentences\n"
        f"- NEVER break character or acknowledge being an AI\n"
        f"- Be terse when {username} would be terse; be detailed when they would be detailed\n"
    )

    return "".join(parts)


# ── Routing ───────────────────────────────────────────────────────────────────

_SKILL_KEYWORDS: dict[str, list[str]] = {
    "code_review": [
        "review",
        "pr",
        "pull request",
        "code",
        "function",
        "class",
        "commit",
        "lgtm",
        "nit",
        "refactor",
        "lint",
        "smell",
        "pattern",
    ],
    "architecture": [
        "architect",
        "design",
        "system",
        "service",
        "microservice",
        "monolith",
        "database",
        "sql",
        "nosql",
        "scale",
        "scalab",
        "deploy",
        "infra",
        "kubernetes",
        "serverless",
        "event",
        "queue",
        "schema",
    ],
    "communication": [
        "communicate",
        "write",
        "doc",
        "rfc",
        "message",
        "slack",
        "meeting",
        "feedback",
        "stakeholder",
        "onboard",
        "explain",
        "present",
    ],
    "identity": [
        "you",
        "your",
        "philosoph",
        "approach",
        "think",
        "feel",
        "believe",
        "opinion",
        "experience",
        "career",
        "learn",
        "mentor",
        "balance",
    ],
}


def route_to_skill(instruction: str) -> str:
    """Map an instruction string to one of the skill_type labels.

    Returns one of: identity, code_review, architecture, communication, technical_opinion.
    Falls back to 'technical_opinion' when no strong signal is found.
    """
    lower = instruction.lower()

    scores: dict[str, int] = {skill: 0 for skill in _SKILL_KEYWORDS}
    for skill, keywords in _SKILL_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                scores[skill] += 1

    best_skill = max(scores, key=lambda s: scores[s])
    if scores[best_skill] == 0:
        return "technical_opinion"

    return best_skill


# ── Validation ────────────────────────────────────────────────────────────────

_MIN_CHOSEN_LENGTH = 30
_MIN_REJECTED_LENGTH = 30
_VALID_SKILL_TYPES = {
    "identity",
    "code_review",
    "architecture",
    "communication",
    "technical_opinion",
}


def validate_dataset(pairs: list[QAPair]) -> dict:
    """Validate a list of QAPairs for training suitability.

    Returns a dict with keys:
        valid (bool), errors (list[str]), warnings (list[str]), count (int)
    """
    errors: list[str] = []
    warnings: list[str] = []

    for i, pair in enumerate(pairs):
        label = pair.example_id or f"pair[{i}]"

        if not pair.instruction.strip():
            errors.append(f"{label}: instruction is empty")

        if not pair.chosen.strip():
            errors.append(f"{label}: chosen response is empty")
        elif len(pair.chosen) < _MIN_CHOSEN_LENGTH:
            warnings.append(f"{label}: chosen response is very short ({len(pair.chosen)} chars)")

        if not pair.rejected.strip():
            errors.append(f"{label}: rejected response is empty")
        elif len(pair.rejected) < _MIN_REJECTED_LENGTH:
            warnings.append(
                f"{label}: rejected response is very short ({len(pair.rejected)} chars)"
            )

        if pair.chosen.strip() == pair.rejected.strip():
            errors.append(f"{label}: chosen and rejected responses are identical")

        if pair.skill_type not in _VALID_SKILL_TYPES:
            warnings.append(f"{label}: unknown skill_type '{pair.skill_type}'")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "count": len(pairs),
    }


# ── Convenience helpers ───────────────────────────────────────────────────────


def make_example_id() -> str:
    """Generate a short unique example ID for a QAPair."""
    return uuid.uuid4().hex[:8]


# ── Dataset generation ────────────────────────────────────────────────────────

import random


def _sample_prompts(num_pairs: int) -> list[tuple[str, str]]:
    """Sample (instruction, skill_type) pairs proportionally from all question banks.

    Ensures exactly num_pairs items are returned (subject to available questions).
    Uses round-robin bank selection so all skill types appear in the result.
    """
    banks: list[tuple[list[str], str]] = [
        (IDENTITY_QUESTIONS, "identity"),
        (CODE_REVIEW_SCENARIOS, "code_review"),
        (ARCH_DEBATE_PROMPTS, "architecture"),
        (COMM_STYLE_PROMPTS, "communication"),
    ]

    # First pass: take per_bank from each bank
    per_bank = max(1, num_pairs // len(banks))
    sampled: list[tuple[str, str]] = []
    # Track indices already used per bank for round-robin top-up
    used: dict[int, set[int]] = {i: set() for i in range(len(banks))}

    for bank_idx, (questions, skill) in enumerate(banks):
        n = min(per_bank, len(questions))
        chosen_indices = random.sample(range(len(questions)), n)
        for idx in chosen_indices:
            sampled.append((questions[idx], skill))
            used[bank_idx].add(idx)

    # Second pass: top-up to reach num_pairs via round-robin
    bank_idx = 0
    while len(sampled) < num_pairs:
        questions, skill = banks[bank_idx]
        remaining = [i for i in range(len(questions)) if i not in used[bank_idx]]
        if remaining:
            idx = random.choice(remaining)
            sampled.append((questions[idx], skill))
            used[bank_idx].add(idx)
        bank_idx = (bank_idx + 1) % len(banks)
        # Safety: if all banks exhausted, break
        if all(len(used[i]) >= len(banks[i][0]) for i in range(len(banks))):
            break

    # Shuffle to interleave skills
    random.shuffle(sampled)
    return sampled[:num_pairs]


def build_offline_pairs(
    spirit_content: str,
    memory_content: str,
    username: str,
    num_pairs: int = 20,
) -> list[QAPair]:
    """Build DPO pairs WITHOUT LLM calls — useful for tests and previews.

    chosen responses are constructed from soul-profile data (communication style,
    values, example phrases). rejected responses use a generic AI template.
    """
    parser = SoulDocumentParser()
    soul = parser.parse(spirit_content)
    behavioral_quotes = extract_behavioral_quotes(memory_content, max_quotes=10)

    # Build a short in-character snippet from soul data
    example_pool: list[str] = list(soul.example_phrases) + behavioral_quotes
    if not example_pool:
        example_pool = ["Depends on the context.", "Hard to say without more info."]

    generic_starters = [
        "That's a great question! There are several considerations to keep in mind.",
        "I'd be happy to help you think through this systematically.",
        "This is an important topic. Let me break it down for you step by step.",
    ]

    prompts = _sample_prompts(num_pairs)
    pairs: list[QAPair] = []

    for instruction, skill_type in prompts:
        chosen_base = random.choice(example_pool) if example_pool else "It depends."
        style_note = soul.communication_style[:80] if soul.communication_style else ""
        chosen = f"{chosen_base} {style_note}".strip().rstrip(".") + "."

        rejected = random.choice(generic_starters) + (
            " When approaching this kind of problem, it's worth considering multiple "
            "perspectives and weighing the tradeoffs carefully before arriving at a "
            "well-reasoned conclusion."
        )

        pairs.append(
            QAPair(
                instruction=instruction,
                chosen=chosen,
                rejected=rejected,
                skill_type=skill_type,
                source="offline",
                example_id=make_example_id(),
            )
        )

    return pairs


async def generate_dataset(
    spirit_content: str,
    memory_content: str,
    username: str,
    num_pairs: int = 20,
    model: str | None = None,
) -> list[QAPair]:
    """Generate DPO-style QA pairs for fine-tuning via LLM.

    Makes concurrent PydanticAI Agent calls to generate in-character (chosen)
    responses using the parsed soul profile as system prompt. Rejected responses
    are generated with a generic AI system prompt.

    Falls back to build_offline_pairs() if LLM calls fail.
    """
    import asyncio

    from pydantic_ai import Agent

    from app.core.models import ModelTier, get_model

    resolved_model = model or get_model(ModelTier.FAST)

    parser = SoulDocumentParser()
    soul = parser.parse(spirit_content)
    spirit_sys = build_spirit_system_prompt(soul, username)

    prompts = _sample_prompts(num_pairs)

    async def _call(instruction: str, skill_type: str) -> QAPair:
        try:
            chosen_agent = Agent(resolved_model, instructions=spirit_sys)
            rejected_agent = Agent(resolved_model, instructions=GENERIC_AI_SYSTEM_PROMPT)

            chosen_result, rejected_result = await asyncio.gather(
                chosen_agent.run(instruction),
                rejected_agent.run(instruction),
            )
            chosen = chosen_result.output or ""
            rejected = rejected_result.output or ""
        except Exception:
            # Fallback: use offline pair for this prompt
            offline = build_offline_pairs(spirit_content, memory_content, username, num_pairs=1)
            if offline:
                return offline[0]
            chosen = "I'd approach this pragmatically."
            rejected = "That is a great question with many considerations."

        return QAPair(
            instruction=instruction,
            chosen=chosen,
            rejected=rejected,
            skill_type=skill_type,
            source="llm",
            example_id=make_example_id(),
        )

    tasks = [_call(instruction, skill) for instruction, skill in prompts]
    pairs = await asyncio.gather(*tasks)
    return list(pairs)
