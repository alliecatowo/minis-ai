#!/usr/bin/env python3
"""Fan-out soul regeneration proof-of-concept.

Bypasses chief.py. Fans out 8 parallel aspect-narrative agents, then a chief
integrates the narratives into a fresh soul document. Proves the Phase 3
fan-out architecture target.

Usage:
    cd backend
    uv run python scripts/regen_via_fanout.py   # dry-run, alliecatowo
    uv run python scripts/regen_via_fanout.py --no-dry-run --write-soul-to-db

Exit codes: 0=ok  1=env/DB/API error  2=bad args
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import asyncpg
except ImportError:
    print("asyncpg required: uv add asyncpg", file=sys.stderr); sys.exit(1)
try:
    from anthropic import AsyncAnthropic, APIConnectionError, APIStatusError, RateLimitError
except ImportError:
    print("anthropic SDK required: uv add anthropic", file=sys.stderr); sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
DEFAULT_MINI_ID = "dc94a4f5-bf23-4e13-96bb-9fe63d8e53de"
DEFAULT_NEON_URL = (
    "postgresql://neondb_owner:npg_kW1UAJjE6ING"
    "@ep-noisy-king-ai4zxs01-pooler.c-4.us-east-1.aws.neon.tech"
    "/neondb?sslmode=require"
)
MODEL = "claude-sonnet-4-5"
ASPECT_MAX_TOKENS = 4000
CHIEF_MAX_TOKENS = 8000
MAX_FINDINGS = 2000
CC_SAMPLE = 30
GH_SAMPLE = 20

# ── Aspect definitions ───────────────────────────────────────────────────────
# Each tuple: (aspect_name, guidance_for_agent)
ASPECTS: list[tuple[str, str]] = [
    ("voice_signature",
     "How they code-switch register by audience, sentence rhythm, declarative vs hedged stance, "
     "escalation cadence, verbosity-vs-brevity by context. NOT coefficient scores. Instead show "
     "dynamics: 'In private CC sessions register collapses to staccato imperatives; the same "
     "frustration in a PR review surfaces as a single sharp sentence + fix proposal.'"),
    ("decision_frameworks_in_practice",
     "Trigger→action→value rules, ORDERING (what they check first/second/third), revisions over "
     "time. Show the FUNCTION, not facts. What does the decision tree look like under pressure? "
     "When confident? When disagreeing with a peer?"),
    ("values_trajectory_over_time",
     "How stated values have updated. Mind-changes are gold: 'Used to think X; after Y now thinks Z.' "
     "Look for explicit revision, contradiction, growth. Where have they moved furthest from an earlier self?"),
    ("audience_modulation",
     "Junior vs peer vs senior; PR vs Slack vs Claude Code; formal vs casual. "
     "Map the CONTEXT MATRIX: what changes across registers, what stays invariant?"),
    ("conflict_and_repair_patterns",
     "How they disagree, escalate, de-escalate, repair. Concrete arcs: disagreement → "
     "held the line (or didn't) → resolution or residue. What is their floor — the thing they won't concede?"),
    ("technical_aesthetic",
     "What makes code feel right to them. Anti-aesthetic too — what they reject. "
     "Cite actual rejected patterns, preferred idioms. Is it legibility? Minimalism? Where do these come from?"),
    ("philosophical_priors",
     "Meta-beliefs that ground concrete decisions. 'Ship fast', 'build right from the ground up', "
     "product/research/ethics priors. These are the axioms they rarely question — "
     "surface them and test against contradictions."),
    ("architecture_worldview",
     "Systems-level thinking: monolith vs microservices, abstraction hygiene, SDK philosophy, "
     "where they draw boundaries and why. Find the theory of the system they are always implicitly building."),
]

# ── Prompts ──────────────────────────────────────────────────────────────────
ASPECT_SYSTEM = """\
You are an aspect-narrative agent for the Minis pipeline.
Write a 1200-2000 word essay describing ONE aspect of this person.

Anti-hyperfitting: describe BEHAVIORAL DYNAMICS and REGISTER PATTERNS —
not literal phrases or coefficient scores. Coefficients are bullshit.
Anchor every claim in concrete evidence (quote it, cite source).
Flowing prose only. No bullet lists. No sub-headers.
End with one sentence that names the load-bearing pattern for this aspect."""

CHIEF_SYSTEM = """\
You are the chief synthesizer. Eight narrative essays about a single person,
each covering one aspect. Write a 4000-5000 word soul document integrating them.

Structure (markdown headers required):
# IDENTITY          — 2-3 paragraphs: most compressed description of who this is
# DECISION FUNCTION — how they decide; triggers, ordering, value-priority (show the function)
# VOICE             — register dynamics; how they code-switch (NOT a phrase list)
# WHEN THEY'RE WRONG — self-correction history; mind-changes; calibration trajectory
# WORKING WITH OTHERS — audience modulation; conflict patterns; repair
# AESTHETICS AND PRIORS — technical taste; architecture worldview; philosophical ground
# INSTRUCTIONS TO YOURSELF — second-person directives the mini reads at chat time:
  "When you respond, you do X. You never do Y. When user asks Z, you reach for W first."

Anti-rules:
- Do NOT open with "This person is a senior engineer who values…" (generic trash)
- Do NOT use coefficient language ("profanity tolerance: high")
- Do NOT bulleted-list values — argue them in prose
- Do NOT enumerate "5 key principles" — show the function in action
- DO use direct quotes the narratives cite
- DO contradict yourself if evidence contradicts itself (mind-changes are signal)
- DO let their voice bleed into your prose (mirror slightly, don't imitate)"""


# ── Data classes ─────────────────────────────────────────────────────────────
@dataclass
class Usage:
    input: int = 0; output: int = 0; cache_write: int = 0; cache_read: int = 0

    def add(self, other: "Usage") -> None:
        self.input += other.input; self.output += other.output
        self.cache_write += other.cache_write; self.cache_read += other.cache_read

    @property
    def cost_usd(self) -> float:
        # $3/Mtok input, $15/Mtok output, $3.75/Mtok cache-write, $0.30/Mtok cache-read
        return (self.input / 1e6 * 3.0 + self.output / 1e6 * 15.0
                + self.cache_write / 1e6 * 3.75 + self.cache_read / 1e6 * 0.30)


@dataclass
class Corpus:
    mini_id: str; username: str; display_name: str | None; bio: str | None
    spirit_content: str | None; system_prompt: str | None
    principles_json: Any; knowledge_graph_json: Any; motivations_json: Any
    findings: list[dict] = field(default_factory=list)
    quotes: list[dict] = field(default_factory=list)
    cc_samples: list[dict] = field(default_factory=list)
    gh_samples: list[dict] = field(default_factory=list)


# ── DB helpers ────────────────────────────────────────────────────────────────
async def pull_corpus(neon_url: str, mini_id: str) -> Corpus:
    conn = await asyncpg.connect(neon_url)
    try:
        row = await conn.fetchrow(
            "SELECT id,username,display_name,bio,spirit_content,system_prompt,"
            "principles_json,knowledge_graph_json,motivations_json FROM minis WHERE id=$1",
            mini_id)
        if not row:
            raise ValueError(f"Mini {mini_id} not found")
        corpus = Corpus(
            mini_id=mini_id, username=row["username"], display_name=row["display_name"],
            bio=row["bio"], spirit_content=row["spirit_content"],
            system_prompt=row["system_prompt"], principles_json=row["principles_json"],
            knowledge_graph_json=row["knowledge_graph_json"], motivations_json=row["motivations_json"],
        )
        findings = [dict(r) for r in await conn.fetch(
            "SELECT source_type,category,content,confidence FROM explorer_findings "
            "WHERE mini_id=$1 ORDER BY created_at DESC", mini_id)]
        corpus.findings = random.sample(findings, MAX_FINDINGS) if len(findings) > MAX_FINDINGS else findings
        corpus.quotes = [dict(r) for r in await conn.fetch(
            "SELECT quote,context,significance,source_type FROM explorer_quotes WHERE mini_id=$1", mini_id)]
        corpus.cc_samples = [dict(r) for r in await conn.fetch(
            "SELECT content,item_type,source_privacy FROM evidence "
            "WHERE mini_id=$1 AND source_type='claude_code' ORDER BY random() LIMIT $2", mini_id, CC_SAMPLE)]
        corpus.gh_samples = [dict(r) for r in await conn.fetch(
            "SELECT content,item_type FROM evidence "
            "WHERE mini_id=$1 AND source_type='github' ORDER BY random() LIMIT $2", mini_id, GH_SAMPLE)]
        log.info(f"Corpus: {len(corpus.findings)} findings, {len(corpus.quotes)} quotes, "
                 f"{len(corpus.cc_samples)} CC, {len(corpus.gh_samples)} GH")
        return corpus
    finally:
        await conn.close()


def format_corpus(c: Corpus) -> str:
    parts: list[str] = [f"=== SUBJECT ===\nUsername: {c.username}"]
    if c.display_name: parts.append(f"Display: {c.display_name}")
    if c.bio:          parts.append(f"Bio: {c.bio}")
    if c.principles_json:
        parts.append("=== PRINCIPLES ===\n" + json.dumps(c.principles_json, indent=2)[:8000])
    if c.motivations_json:
        parts.append("=== MOTIVATIONS ===\n" + json.dumps(c.motivations_json, indent=2)[:4000])
    if c.knowledge_graph_json:
        parts.append("=== KNOWLEDGE GRAPH ===\n" + json.dumps(c.knowledge_graph_json, indent=2)[:6000])
    if c.quotes:
        lines = [f'[{q["source_type"]}] "{q["quote"]}" ({q.get("context","")})' for q in c.quotes[:100]]
        parts.append("=== BEHAVIORAL QUOTES ===\n" + "\n".join(lines))
    if c.findings:
        by_cat: dict[str, list[str]] = {}
        for f in c.findings:
            by_cat.setdefault(f.get("category", "?"), []).append(f.get("content", "")[:500])
        flines = []
        for cat, items in sorted(by_cat.items()):
            flines.append(f"--- {cat} ---"); flines.extend(f"  • {i}" for i in items[:30])
        parts.append("=== FINDINGS ===\n" + "\n".join(flines))
    if c.cc_samples:
        cc = []
        for s in c.cc_samples:
            tag = "[PRIVATE — paraphrase only]\n" if s.get("source_privacy") == "private" else ""
            cc.append(f"{tag}{s.get('content','')[:600]}")
        parts.append("=== CLAUDE CODE SESSIONS ===\n" + "\n---\n".join(cc))
    if c.gh_samples:
        gh = [f"[{s.get('item_type','')}] {s.get('content','')[:600]}" for s in c.gh_samples]
        parts.append("=== GITHUB EVIDENCE ===\n" + "\n---\n".join(gh))
    return "\n\n".join(parts)


# ── Anthropic call with retry ──────────────────────────────────────────────────
async def _call(
    client: AsyncAnthropic, *, system: list[dict], user: str,
    max_tokens: int, label: str, retries: int = 3,
) -> tuple[str, Usage]:
    delay = 5.0
    for attempt in range(retries):
        try:
            r = await client.messages.create(
                model=MODEL, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
            text = "".join(b.text for b in r.content if hasattr(b, "text"))
            u = Usage(
                input=r.usage.input_tokens, output=r.usage.output_tokens,
                cache_write=getattr(r.usage, "cache_creation_input_tokens", 0) or 0,
                cache_read=getattr(r.usage, "cache_read_input_tokens", 0) or 0,
            )
            log.info(f"{label}: {u.input}in/{u.output}out/{u.cache_read}cache_read")
            return text, u
        except (RateLimitError, APIStatusError) as e:
            if getattr(e, "status_code", None) in (429, 529) and attempt < retries - 1:
                log.warning(f"{label}: HTTP {e.status_code}, retry {attempt+1} in {delay:.0f}s")
                await asyncio.sleep(delay); delay *= 2
            else:
                raise
        except APIConnectionError:
            if attempt < retries - 1:
                log.warning(f"{label}: connection error, retry {attempt+1} in {delay:.0f}s")
                await asyncio.sleep(delay); delay *= 2
            else:
                raise
    raise RuntimeError(f"{label}: exhausted retries")  # unreachable


# ── Aspect + chief agents ──────────────────────────────────────────────────────
async def run_aspect(
    client: AsyncAnthropic, aspect: str, guidance: str,
    evidence: str, out_dir: Path,
) -> tuple[str, str, Usage]:
    user_msg = (
        f"Aspect: {aspect}\n\nGuidance:\n{guidance}\n\n"
        "Evidence corpus follows. Quote liberally. 1200-2000 words. Flowing prose. "
        "No bullet lists. End with the load-bearing pattern sentence.\n\n"
        f"EVIDENCE CORPUS:\n{evidence}"
    )
    system = [{"type": "text", "text": ASPECT_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    try:
        narrative, usage = await _call(client, system=system, user=user_msg,
                                       max_tokens=ASPECT_MAX_TOKENS, label=f"aspect:{aspect}")
        (out_dir / "narratives" / f"{aspect}.md").write_text(narrative, encoding="utf-8")
        return aspect, narrative, usage
    except Exception as exc:
        log.error(f"Aspect {aspect} failed: {exc}")
        (out_dir / "narratives" / f"{aspect}.failed.md").write_text(
            f"# {aspect} — FAILED\n\nError: {exc}\n", encoding="utf-8")
        return aspect, "", Usage()


async def run_chief(
    client: AsyncAnthropic, narratives: dict[str, str], out_dir: Path,
) -> tuple[str, Usage]:
    blocks = "\n\n".join(
        f"## Aspect: {a}\n\n{t}" if t else f"## Aspect: {a}\n\n[FAILED]"
        for a, t in narratives.items()
    )
    system = [{"type": "text", "text": CHIEF_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    soul, usage = await _call(client, system=system,
                              user=f"The 8 aspect narratives:\n\n{blocks}",
                              max_tokens=CHIEF_MAX_TOKENS, label="chief")
    (out_dir / "soul.md").write_text(soul, encoding="utf-8")
    return soul, usage


# ── DB write ──────────────────────────────────────────────────────────────────
async def write_to_db(
    neon_url: str, mini_id: str, soul: str, out_dir: Path,
    old_prompt: str | None, old_spirit: str | None,
) -> None:
    backup = out_dir / "system_prompt.backup.txt"
    backup.write_text(
        f"=== system_prompt ===\n{old_prompt or ''}\n\n=== spirit_content ===\n{old_spirit or ''}",
        encoding="utf-8")
    log.info(f"Backup → {backup}")
    conn = await asyncpg.connect(neon_url)
    try:
        await conn.execute(
            "UPDATE minis SET system_prompt=$1, spirit_content=$2 WHERE id=$3",
            soul, soul, mini_id)
        log.info(f"DB updated mini {mini_id}")
        print(f"\n-- ROLLBACK SQL --\n"
              f"UPDATE minis SET system_prompt='{(old_prompt or '').replace(chr(39), chr(39)*2)}', "
              f"spirit_content='{(old_spirit or '').replace(chr(39), chr(39)*2)}' "
              f"WHERE id='{mini_id}';\n")
    finally:
        await conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────
async def main(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.output_dir or f"/tmp/regen-alliecatowo-{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "narratives").mkdir(exist_ok=True)

    neon_url = (args.neon_url or os.environ.get("NEON_DATABASE_URL") or DEFAULT_NEON_URL
                ).replace("postgresql+asyncpg://", "postgresql://")
    api_key = args.anthropic_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("No ANTHROPIC_API_KEY"); return 1

    dry_run = not args.no_dry_run
    do_write = args.write_soul_to_db and not dry_run

    log.info(f"Output: {out_dir} | dry_run={dry_run} | db_write={do_write}")

    # Step 1 — pull corpus
    corpus = await pull_corpus(neon_url, args.mini_id)
    evidence = format_corpus(corpus)
    (out_dir / "evidence_summary.txt").write_text(evidence, encoding="utf-8")
    log.info(f"Evidence summary: {len(evidence):,} chars")

    # Step 2 — fan out 8 aspect agents in parallel
    client = AsyncAnthropic(api_key=api_key)
    total = Usage()
    results = await asyncio.gather(*[
        run_aspect(client, asp, guidance, evidence, out_dir)
        for asp, guidance in ASPECTS
    ])

    narratives: dict[str, str] = {}
    for asp, narrative, usage in results:
        narratives[asp] = narrative
        total.add(usage)
    ok = sum(1 for v in narratives.values() if v)
    log.info(f"Aspects: {ok}/{len(ASPECTS)} succeeded")

    # Step 3 — chief
    soul, chief_usage = await run_chief(client, narratives, out_dir)
    total.add(chief_usage)

    # Step 4 — optional DB write
    if do_write:
        await write_to_db(neon_url, args.mini_id, soul, out_dir,
                          corpus.system_prompt, corpus.spirit_content)

    elapsed = time.monotonic() - t0
    print(f"""
╔══════════════════════════════════════════════╗
║  FAN-OUT REGEN COMPLETE                      ║
╚══════════════════════════════════════════════╝
  Mini:       {corpus.username} ({args.mini_id})
  Output:     {out_dir}
  Aspects ok: {ok}/{len(ASPECTS)}

  Tokens  in={total.input:,}  out={total.output:,}
          cache_write={total.cache_write:,}  cache_read={total.cache_read:,}
  Cost:   ${total.cost_usd:.4f} USD
  Time:   {elapsed:.1f}s
  DB:     {"WRITTEN" if do_write else "dry-run (no write)"}

Next: review {out_dir}/soul.md, then run fidelity eval.
""")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mini-id", default=DEFAULT_MINI_ID,
                   help=f"Mini UUID (default: alliecatowo={DEFAULT_MINI_ID})")
    p.add_argument("--neon-url", default=None, help="Neon connection URL")
    p.add_argument("--anthropic-key", default=None, help="Anthropic API key")
    p.add_argument("--output-dir", default=None, help="Output directory")
    p.add_argument("--no-dry-run", action="store_true", default=False,
                   help="Disable dry-run protection (still requires --write-soul-to-db for DB writes)")
    p.add_argument("--write-soul-to-db", action="store_true", default=False,
                   help="Write soul to minis table (requires --no-dry-run)")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
