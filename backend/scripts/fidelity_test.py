#!/usr/bin/env python3
"""Before/after fidelity test for personality quality.

Sends personality-probing prompts to a mini's chat endpoint and scores
each response for authentic voice vs generic AI filler.

Usage:
    cd backend
    MINIS_TOKEN=$(cat ~/.config/minis/mcp-token) \\
        uv run python scripts/fidelity_test.py \\
            --mini-id dc94a4f5-bf23-4e13-96bb-9fe63d8e53de \\
            --token $MINIS_TOKEN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

_BACKEND_DIR = Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

PROMPTS = [
    "what do you think about microservices?",
    "review this PR for me: the dev added a 200-line function with no tests, no docs, and used console.log for error handling. they said its MVP and theyll clean it up later.",
    "whats your process when you hit a really gnarly bug you cant figure out?",
    "what drives you crazy about other devs?",
    "if you were building a startup from scratch today, what stack would you pick and why?",
    "tell me about a time you were wrong about something",
    "whats your hot take that most engineers would disagree with?",
]

BANNED_GENERIC = [
    "comprehensive testing",
    "non-negotiable",
    "first-class citizen",
    "meticulous",
    "paramount",
    "impeccable",
    "unwavering commitment",
    "crucial",
    "it's important to",
    "best practices",
    "robust and maintainable",
    "comprehensive documentation",
    "clear and concise",
    "at the end of the day",
]

PERSONALITY_CURSING = ["fuck", "shit", "garbage", "trash", "hell", "damn"]
PERSONALITY_CASUAL = ["lol", "honestly", "look", "tbh", "ngl", "i don't give a", "who cares"]
PERSONALITY_OPINION = [
    "ship",
    "ship it",
    "move fast",
    "overkill",
    "waste of time",
    "non-starter",
    "hot take",
]
PERSONALITY_SELF_DEPRECATING = ["i'm terrible", "i suck at", "i have no idea"]

ALL_PERSONALITY_MARKERS = (
    PERSONALITY_CURSING + PERSONALITY_CASUAL + PERSONALITY_OPINION + PERSONALITY_SELF_DEPRECATING
)

API_BASE = "https://minis-api.fly.dev"


@dataclass
class ResponseMetrics:
    prompt: str
    response_text: str
    word_count: int = 0
    sentence_count: int = 0
    generic_hits: list[str] = field(default_factory=list)
    personality_hits: list[str] = field(default_factory=list)
    score: float = 0.0
    score_label: str = ""


def count_sentences(text: str) -> int:
    sentences = re.split(r"[.!?]+", text)
    return len([s for s in sentences if s.strip()])


def find_generic_phrases(text: str) -> list[str]:
    lower = text.lower()
    return [phrase for phrase in BANNED_GENERIC if phrase in lower]


def find_personality_markers(text: str) -> list[str]:
    lower = text.lower()
    return [marker for marker in ALL_PERSONALITY_MARKERS if marker in lower]


def compute_score(
    word_count: int,
    sentence_count: int,
    generic_hits: list[str],
    personality_hits: list[str],
) -> tuple[float, str]:
    score = 5.0

    score -= len(generic_hits) * 1.0
    score += len(personality_hits) * 0.8

    if word_count > 500:
        score -= 1.0
    elif word_count > 300:
        score -= 0.3
    elif word_count < 20:
        score -= 1.0

    avg_sentence_len = word_count / max(sentence_count, 1)
    if avg_sentence_len > 30:
        score -= 0.5

    score = max(1.0, min(10.0, score))

    if score >= 8:
        label = "authentic, opinionated"
    elif score >= 6:
        label = "decent personality"
    elif score >= 4:
        label = "mixed, some generic filler"
    elif score >= 2:
        label = "verbose, generic, no personality"
    else:
        label = "completely generic"

    return round(score, 1), label


async def send_chat(
    client: httpx.AsyncClient,
    mini_id: str,
    prompt: str,
    token: str,
    base_url: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    url = f"{base_url}/api/minis/{mini_id}/chat"
    payload = {"message": prompt}

    collected: list[str] = []

    async with client.stream("POST", url, json=payload, headers=headers, timeout=120.0) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "event-stream" in content_type:
            current_event = ""
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    if current_event == "chunk":
                        collected.append(raw)
                    elif current_event == "done":
                        break
                    else:
                        try:
                            event = json.loads(raw)
                            if isinstance(event, dict):
                                et = event.get("type", "")
                                if et == "chunk":
                                    collected.append(event.get("data", ""))
                                elif et == "done":
                                    break
                        except json.JSONDecodeError:
                            if not raw.startswith("{"):
                                collected.append(raw)
        else:
            body = await resp.aread()
            try:
                data = json.loads(body)
                if isinstance(data, dict):
                    collected.append(data.get("response", data.get("message", str(data))))
                else:
                    collected.append(str(data))
            except json.JSONDecodeError:
                collected.append(body.decode())

    return "".join(collected).strip()


def analyze_response(prompt: str, response_text: str) -> ResponseMetrics:
    words = response_text.split()
    word_count = len(words)
    sentence_count = count_sentences(response_text)
    generic_hits = find_generic_phrases(response_text)
    personality_hits = find_personality_markers(response_text)
    score, label = compute_score(word_count, sentence_count, generic_hits, personality_hits)

    return ResponseMetrics(
        prompt=prompt,
        response_text=response_text,
        word_count=word_count,
        sentence_count=sentence_count,
        generic_hits=generic_hits,
        personality_hits=personality_hits,
        score=score,
        score_label=label,
    )


def print_test_result(idx: int, metrics: ResponseMetrics) -> None:
    truncated = metrics.prompt[:50] + ("..." if len(metrics.prompt) > 50 else "")
    print(f'\nTest {idx}: "{truncated}"')
    print(f"  Response: {metrics.word_count} words, {metrics.sentence_count} sentences")

    if metrics.generic_hits:
        phrases = ", ".join(f'"{p}"' for p in metrics.generic_hits)
        print(f"  Generic phrases: {len(metrics.generic_hits)} ({phrases})")
    else:
        print("  Generic phrases: 0")

    if metrics.personality_hits:
        markers = ", ".join(f'"{m}"' for m in metrics.personality_hits)
        print(f"  Personality markers: {len(metrics.personality_hits)} ({markers})")
    else:
        print("  Personality markers: 0")

    print(f"  Score: {metrics.score}/10 ({metrics.score_label})")


def print_summary(results: list[ResponseMetrics]) -> None:
    total_words = sum(r.word_count for r in results)
    avg_sentences = sum(r.sentence_count for r in results) / max(len(results), 1)
    total_generic = sum(len(r.generic_hits) for r in results)
    total_personality = sum(len(r.personality_hits) for r in results)
    avg_score = sum(r.score for r in results) / max(len(results), 1)

    print("\n=== Summary ===")
    print(f"Total words: {total_words}")
    print(f"Avg sentences per response: {avg_sentences:.1f}")
    print(f"Generic phrases: {total_generic}")
    print(f"Personality markers: {total_personality}")
    print(f"Overall score: {avg_score:.1f}/10")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Before/after fidelity test for mini personality quality."
    )
    parser.add_argument("--mini-id", required=True, help="Mini UUID")
    parser.add_argument("--token", required=True, help="Bearer auth token")
    parser.add_argument("--base-url", default=API_BASE, help=f"API base URL (default: {API_BASE})")
    parser.add_argument("--prompts", type=int, default=0, help="Run only first N prompts (0 = all)")
    args = parser.parse_args()

    prompts = PROMPTS[: args.prompts] if args.prompts > 0 else PROMPTS

    print("=== Fidelity Test Results ===")
    print(f"Mini: {args.mini_id}")
    print(f"Prompts: {len(prompts)}")

    results: list[ResponseMetrics] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, prompt in enumerate(prompts, 1):
            print(f"\nSending test {i}/{len(prompts)}...", flush=True)
            try:
                response_text = await send_chat(
                    client, args.mini_id, prompt, args.token, args.base_url
                )
            except Exception as exc:
                print(f"\nTest {i}: FAILED — {exc}")
                results.append(
                    ResponseMetrics(
                        prompt=prompt,
                        response_text="",
                        score=0.0,
                        score_label=f"request failed: {exc}",
                    )
                )
                continue

            metrics = analyze_response(prompt, response_text)
            results.append(metrics)
            print_test_result(i, metrics)

    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
