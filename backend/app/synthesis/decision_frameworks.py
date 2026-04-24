"""Decision framework normalizer (ALLIE-503).

This module builds the first code-level decision-framework representation from
the structured artifacts we already have: explorer principles and motivations.
It intentionally does not apply frameworks to predictions yet.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.schemas import (
    DecisionFramework,
    DecisionFrameworkEvidenceProvenance,
    DecisionFrameworkProfile,
    DecisionFrameworkTemporalSpan,
    Motivation,
    MotivationChain,
    MotivationsProfile,
)


_PRIORITIES = {"low", "medium", "high", "critical"}
_SPECIFICITY_LEVELS = {"global", "scope_local", "contextual", "case_pattern"}


def build_decision_frameworks_payload(
    principles_json: dict[str, Any] | None,
    motivations: MotivationsProfile | dict[str, Any] | None = None,
) -> DecisionFrameworkProfile:
    """Convert current principles/motivations artifacts into framework schemas."""
    principles = _principles_from_payload(principles_json)
    motivation_profile = _parse_motivations(motivations)
    motivation_index = _build_motivation_index(motivation_profile)

    frameworks: list[DecisionFramework] = []
    for index, principle in enumerate(principles):
        framework = normalize_principle_to_decision_framework(
            principle=principle,
            motivation_index=motivation_index,
            fallback_index=index,
        )
        if framework is not None:
            frameworks.append(framework)

    return DecisionFrameworkProfile(frameworks=frameworks)


def normalize_principle_to_decision_framework(
    principle: dict[str, Any],
    motivation_index: dict[str, dict[str, list[str]]] | None = None,
    fallback_index: int = 0,
) -> DecisionFramework | None:
    """Normalize a single legacy principle into a DecisionFramework."""
    condition = _text(principle.get("condition")) or _text(principle.get("trigger"))
    action = _text(principle.get("action"))
    value = _text(principle.get("value"))
    if not (condition or action or value):
        return None

    evidence_provenance = [
        DecisionFrameworkEvidenceProvenance.model_validate(item)
        for item in _dict_list(principle.get("evidence_provenance"))
    ]
    evidence_ids = _dedupe(
        _string_list(principle.get("evidence_ids"))
        + _string_list(principle.get("evidence"))
        + [item.id for item in evidence_provenance if item.id]
    )
    counter_evidence_ids = _dedupe(_string_list(principle.get("counter_evidence_ids")))
    counterexamples = _dedupe(
        _string_list(principle.get("counterexamples"))
        + _string_list(principle.get("exceptions"))
    )
    source_dates = _source_dates(principle, evidence_provenance)
    source_type = _text(principle.get("source_type"))
    intensity = _normalize_intensity(principle.get("intensity"))
    confidence = _normalize_confidence(
        raw_confidence=principle.get("confidence"),
        intensity=intensity,
        support_count=_support_count(principle, evidence_ids, evidence_provenance),
        evidence_count=len(evidence_ids),
        provenance_count=len(evidence_provenance),
        counter_count=len(counter_evidence_ids) + len(counterexamples),
    )
    matched_motivations = _match_motivations(value, motivation_index or {})

    decision_order = _string_list(principle.get("decision_order"))
    if not decision_order:
        decision_order = _dedupe([condition, action])

    framework_id = _text(principle.get("framework_id")) or _framework_id(
        condition=condition,
        value=value,
        fallback_index=fallback_index,
    )
    return DecisionFramework(
        framework_id=framework_id,
        condition=condition or "Condition inferred from existing principle.",
        priority=_normalize_priority(principle.get("priority"), intensity),
        tradeoff=_tradeoff(principle, action, value),
        escalation_threshold=_escalation_threshold(principle, action, value),
        counterexamples=counterexamples,
        temporal_span=DecisionFrameworkTemporalSpan(
            first_seen_at=source_dates[0] if source_dates else None,
            last_reinforced_at=source_dates[-1] if source_dates else None,
            source_dates=source_dates,
        ),
        evidence_ids=evidence_ids,
        evidence_provenance=evidence_provenance,
        counter_evidence_ids=counter_evidence_ids,
        confidence=confidence,
        specificity_level=_specificity_level(principle, source_type, counterexamples),
        value_ids=[_value_id(value)] if value else [],
        motivation_ids=matched_motivations["motivation_ids"],
        decision_order=decision_order,
        approval_policy=_optional_text(principle.get("approval_policy")),
        block_policy=_optional_text(principle.get("block_policy")),
        expression_policy=_optional_text(principle.get("expression_policy")),
        exceptions=_string_list(principle.get("exceptions")),
        source_type=source_type or None,
    )


def attach_decision_frameworks(
    principles_json: dict[str, Any] | None,
    motivations: MotivationsProfile | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return principles_json with a sibling decision_frameworks payload."""
    payload = dict(principles_json or {})
    profile = build_decision_frameworks_payload(payload, motivations)
    payload["decision_frameworks"] = profile.model_dump(mode="json")
    return payload


def _principles_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    principles = payload.get("principles")
    if not isinstance(principles, list):
        return []
    return [item for item in principles if isinstance(item, dict)]


def _parse_motivations(raw: MotivationsProfile | dict[str, Any] | None) -> MotivationsProfile | None:
    if raw is None:
        return None
    if isinstance(raw, MotivationsProfile):
        return raw
    if isinstance(raw, dict):
        try:
            return MotivationsProfile.model_validate(raw)
        except Exception:
            return None
    return None


def _build_motivation_index(
    profile: MotivationsProfile | None,
) -> dict[str, dict[str, list[str]]]:
    index: dict[str, dict[str, list[str]]] = {}
    if profile is None:
        return index

    for motivation in profile.motivations:
        key = _match_key(motivation.value)
        if not key:
            continue
        bucket = index.setdefault(key, {"motivation_ids": [], "chain_frameworks": []})
        bucket["motivation_ids"].append(_motivation_id(motivation))

    for chain in profile.motivation_chains:
        key = _match_key(chain.motivation)
        if not key:
            continue
        bucket = index.setdefault(key, {"motivation_ids": [], "chain_frameworks": []})
        bucket["motivation_ids"].append(_motivation_id(chain))
        if chain.implied_framework:
            bucket["chain_frameworks"].append(chain.implied_framework)

    for bucket in index.values():
        bucket["motivation_ids"] = _dedupe(bucket["motivation_ids"])
        bucket["chain_frameworks"] = _dedupe(bucket["chain_frameworks"])
    return index


def _match_motivations(
    value: str,
    motivation_index: dict[str, dict[str, list[str]]],
) -> dict[str, list[str]]:
    key = _match_key(value)
    if not key:
        return {"motivation_ids": [], "chain_frameworks": []}
    matches: dict[str, list[str]] = {"motivation_ids": [], "chain_frameworks": []}
    for motivation_key, bucket in motivation_index.items():
        if key == motivation_key or key in motivation_key or motivation_key in key:
            matches["motivation_ids"].extend(bucket["motivation_ids"])
            matches["chain_frameworks"].extend(bucket["chain_frameworks"])
    return {
        "motivation_ids": _dedupe(matches["motivation_ids"]),
        "chain_frameworks": _dedupe(matches["chain_frameworks"]),
    }


def _source_dates(
    principle: dict[str, Any],
    evidence_provenance: list[DecisionFrameworkEvidenceProvenance],
) -> list[str]:
    dates = _string_list(principle.get("source_dates"))
    for item in evidence_provenance:
        if item.evidence_date:
            dates.append(item.evidence_date)
        elif item.created_at:
            dates.append(item.created_at)
    return sorted(_dedupe(dates))


def _support_count(
    principle: dict[str, Any],
    evidence_ids: list[str],
    evidence_provenance: list[DecisionFrameworkEvidenceProvenance],
) -> int:
    try:
        stored_count = int(principle.get("support_count"))
    except (TypeError, ValueError):
        stored_count = 0
    return max(stored_count, len(evidence_ids), len(evidence_provenance))


def _normalize_intensity(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.5
    if parsed > 1.0 and parsed <= 10.0:
        parsed = parsed / 10.0
    return _clamp(parsed)


def _normalize_priority(raw_priority: Any, intensity: float) -> str:
    priority = _text(raw_priority).lower()
    if priority in _PRIORITIES:
        return priority
    if intensity >= 0.85:
        return "critical"
    if intensity >= 0.65:
        return "high"
    if intensity >= 0.4:
        return "medium"
    return "low"


def _normalize_confidence(
    raw_confidence: Any,
    intensity: float,
    support_count: int,
    evidence_count: int,
    provenance_count: int,
    counter_count: int,
) -> float:
    try:
        parsed = float(raw_confidence)
    except (TypeError, ValueError):
        parsed = intensity

    confidence = parsed
    confidence += min(0.15, support_count * 0.03)
    confidence += min(0.10, provenance_count * 0.02)
    confidence -= min(0.25, counter_count * 0.05)
    if evidence_count == 0:
        confidence = min(confidence, 0.45)
    return round(_clamp(confidence), 2)


def _specificity_level(
    principle: dict[str, Any],
    source_type: str,
    counterexamples: list[str],
) -> str:
    explicit = _text(principle.get("specificity_level")).lower()
    if explicit in _SPECIFICITY_LEVELS:
        return explicit
    if counterexamples:
        return "contextual"
    if source_type in {"github", "review_outcomes", "linear"}:
        return "scope_local"
    if source_type in {"blog", "website", "hackernews", "devto", "stackoverflow"}:
        return "global"
    return "case_pattern"


def _tradeoff(principle: dict[str, Any], action: str, value: str) -> str:
    explicit = _optional_text(principle.get("tradeoff"))
    if explicit:
        return explicit
    if value and action:
        return f"{value} prioritized when deciding whether to {action}."
    if value:
        return f"{value} prioritized over lower-signal alternatives."
    return "Tradeoff not yet explicit in source artifacts."


def _escalation_threshold(principle: dict[str, Any], action: str, value: str) -> str:
    explicit = _optional_text(principle.get("escalation_threshold"))
    if explicit:
        return explicit

    lowered = action.lower()
    if any(term in lowered for term in ("block", "reject", "request changes", "prevent", "stop")):
        return "Escalate to blocking feedback when the condition is present."
    if any(term in lowered for term in ("comment", "ask", "question", "warn", "call out")):
        return "Escalate to a review comment when the condition is present."
    if value:
        return f"Escalate when the condition materially threatens {value}."
    return "Escalate when the condition materially changes the decision."


def _framework_id(condition: str, value: str, fallback_index: int) -> str:
    basis = condition or value or f"framework-{fallback_index + 1}"
    return f"framework:{_slug(basis)}"


def _value_id(value: str) -> str:
    return f"value:{_slug(value)}"


def _motivation_id(motivation: Motivation | MotivationChain) -> str:
    value = motivation.value if isinstance(motivation, Motivation) else motivation.motivation
    return f"motivation:{_slug(value)}"


def _match_key(value: str) -> str:
    return _slug(value).replace("-", "_")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
