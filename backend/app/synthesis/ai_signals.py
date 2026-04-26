"""Heuristic AI-authorship signals for evidence tagging."""

from __future__ import annotations

import re
from typing import Any


_HEDGING_PHRASES = (
    "it is important to note",
    "it is worth noting",
    "generally speaking",
    "in conclusion",
    "it should be noted",
    "this can vary depending on",
)


def _count_regex(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))


def _word_count(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def score_ai_authorship(text: str, baseline_style: dict | None = None) -> tuple[float, dict]:
    """Return (ai_authorship_likelihood, style_markers) for one evidence item.

    Heuristic-only first pass. This is intentionally additive and non-blocking.
    """
    source_text = text or ""
    lowered = source_text.lower()
    words = _word_count(source_text)

    em_dash_count = source_text.count("—")
    em_dash_density = em_dash_count / words
    here_is_preamble = bool(re.match(r"^\s*here\s+(is|are)\b", lowered))
    nested_bullets = _count_regex(r"^\s{2,}[-*]\s+", source_text) > 0
    oxford_clause_hits = _count_regex(r",\s+[^,\n]{1,40},\s+and\s+", source_text)
    hedging_hits = [phrase for phrase in _HEDGING_PHRASES if phrase in lowered]
    let_me_know_closing = bool(
        re.search(r"(let me know if|let me know whether|feel free to ask)\b", lowered)
    )

    baseline_em_dash_density = None
    if isinstance(baseline_style, dict):
        candidate = baseline_style.get("em_dash_density")
        if isinstance(candidate, int | float):
            baseline_em_dash_density = max(0.0, float(candidate))

    score = 0.05
    score += min(0.20, em_dash_density * 12.0)
    if here_is_preamble:
        score += 0.18
    if nested_bullets:
        score += 0.15
    if oxford_clause_hits >= 2:
        score += 0.16
    elif oxford_clause_hits == 1:
        score += 0.08
    if hedging_hits:
        score += min(0.18, 0.08 + (0.04 * len(hedging_hits)))
    if let_me_know_closing:
        score += 0.16

    # If the person already uses em-dashes heavily, discount this marker.
    if baseline_em_dash_density is not None and baseline_em_dash_density >= em_dash_density:
        score -= 0.06

    score = max(0.0, min(1.0, round(score, 4)))

    markers: dict[str, Any] = {
        "em_dash_count": em_dash_count,
        "em_dash_density": round(em_dash_density, 4),
        "here_is_preamble": here_is_preamble,
        "nested_bullets_detected": nested_bullets,
        "oxford_clause_hits": oxford_clause_hits,
        "formal_hedging_hits": hedging_hits,
        "let_me_know_closing": let_me_know_closing,
        "register_markers": {
            "formality": "high" if len(hedging_hits) >= 2 else "mixed",
            "structure": (
                "assistant_scaffolded"
                if (here_is_preamble or nested_bullets or let_me_know_closing)
                else "freeform"
            ),
        },
    }

    # TODO: LLM-based scorer can augment/override this heuristic pass.
    return score, markers
