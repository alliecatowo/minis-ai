"""Decision framework normalizer (ALLIE-503).

This module builds the first code-level decision-framework representation from
the structured artifacts we already have: explorer principles and motivations.
It intentionally does not apply frameworks to predictions yet.

Outcome-delta loop (framework-confidence-delta-loop):
  apply_review_outcome_deltas() consumes delta_metrics.issue_outcomes from a
  finalized ReviewCycle and updates confidence scores on matched frameworks.
  Matching is token-overlap, fully deterministic, no embeddings.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Literal

from app.models.schemas import (
    ConfidenceHistoryEntry,
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

# ---------------------------------------------------------------------------
# Drift-alert thresholds (used by writeback callers to emit structured logs)
# ---------------------------------------------------------------------------

#: Confidence below this value is in the "low" band (matches LOW badge convention)
CONFIDENCE_BAND_LOW: float = 0.3

#: Confidence above this value is in the "high" band (matches HIGH badge convention)
CONFIDENCE_BAND_HIGH: float = 0.7

#: Absolute shift magnitude that triggers a drift alert even without a band change
DRIFT_ALERT_THRESHOLD: float = 0.1


def confidence_band(c: float) -> Literal["low", "neutral", "high"]:
    """Return the confidence band label for a given confidence value."""
    if c <= CONFIDENCE_BAND_LOW:
        return "low"
    if c >= CONFIDENCE_BAND_HIGH:
        return "high"
    return "neutral"


def detect_band_change(prev: float, new: float) -> tuple[str, str] | None:
    """Return ``(prev_band, new_band)`` if the band changed, else ``None``."""
    prev_band = confidence_band(prev)
    new_band = confidence_band(new)
    if prev_band != new_band:
        return (prev_band, new_band)
    return None


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


# ---------------------------------------------------------------------------
# Outcome-delta loop
# ---------------------------------------------------------------------------

#: Confidence shift per outcome type (full magnitude; sparse-data guard applies)
_OUTCOME_DELTAS: dict[str, float] = {
    "confirmed": +0.05,
    "missed": -0.08,
    "overpredicted": -0.03,
    "escalated": +0.02,
}

#: Minimum evidence items required to apply the full delta magnitude
_SPARSE_EVIDENCE_THRESHOLD = 5

#: Maximum delta applied when evidence count is below threshold
_SPARSE_DELTA_CAP = 0.03

#: Minimum absolute net shift required to bump the framework revision counter
_REVISION_BUMP_THRESHOLD = 0.02


@dataclass
class DeltaConfidenceUpdate:
    """Audit record returned by apply_review_outcome_deltas."""

    framework_id: str
    issue_key: str
    outcome_type: str
    prior_confidence: float
    new_confidence: float
    net_delta: float
    revision_bumped: bool
    cycle_id: str
    sparse_guard_applied: bool


def apply_review_outcome_deltas(
    principles_json: dict[str, Any],
    cycle_id: str,
    issue_outcomes: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[DeltaConfidenceUpdate]]:
    """Update framework confidence scores from review-cycle outcome deltas.

    Matches each issue_outcome to candidate frameworks by token-overlap on the
    framework condition text and the issue key / summaries.  Applies a signed
    confidence delta per outcome type, subject to a sparse-data guard:

    - If the framework has < 5 supporting evidence items, the magnitude is
      capped at 0.03 regardless of the prescribed delta.
    - If the net shift on a framework exceeds 0.02, the revision counter is
      incremented and a ConfidenceHistoryEntry is appended.

    Args:
        principles_json: The mini's current principles_json blob (mutated in-place).
        cycle_id: The UUID of the ReviewCycle being finalized (for audit entries).
        issue_outcomes: The ``delta_metrics["issue_outcomes"]`` list from the cycle.

    Returns:
        (updated_principles_json, list_of_DeltaConfidenceUpdate)
    """
    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return principles_json, []

    raw_frameworks = df_payload.get("frameworks")
    if not isinstance(raw_frameworks, list):
        return principles_json, []

    # Parse into typed objects — we'll mutate and re-serialise
    frameworks: list[DecisionFramework] = []
    for raw in raw_frameworks:
        if isinstance(raw, dict):
            try:
                frameworks.append(DecisionFramework.model_validate(raw))
            except Exception:
                pass

    if not frameworks:
        return principles_json, []

    updates: list[DeltaConfidenceUpdate] = []
    now_iso = datetime.now(UTC).isoformat()

    for outcome_item in issue_outcomes:
        if not isinstance(outcome_item, dict):
            continue

        outcome_type = _text(outcome_item.get("outcome"))
        if outcome_type not in _OUTCOME_DELTAS:
            continue  # skip new_issue / downgraded / resolved_before_submit / not_raised

        issue_key = _text(outcome_item.get("issue_key"))
        predicted_summary = _text(outcome_item.get("predicted_summary"))
        query_tokens = _tokenize(issue_key) | _tokenize(predicted_summary)
        if not query_tokens:
            continue

        raw_delta = _OUTCOME_DELTAS[outcome_type]

        for fw in frameworks:
            if not _tokens_overlap(query_tokens, _tokenize(fw.condition)):
                continue

            evidence_count = len(fw.evidence_ids)
            sparse_guard = evidence_count < _SPARSE_EVIDENCE_THRESHOLD
            if sparse_guard and abs(raw_delta) > _SPARSE_DELTA_CAP:
                effective_delta = _SPARSE_DELTA_CAP * (1.0 if raw_delta > 0 else -1.0)
            else:
                effective_delta = raw_delta

            prior = fw.confidence
            new_conf = _clamp(round(prior + effective_delta, 4))
            net = round(new_conf - prior, 4)

            revision_bumped = abs(net) > _REVISION_BUMP_THRESHOLD
            if revision_bumped:
                fw.revision += 1

            fw.confidence = new_conf
            history_entry = ConfidenceHistoryEntry(
                revision=fw.revision,
                prior_confidence=prior,
                new_confidence=new_conf,
                delta=net,
                outcome_type=outcome_type,
                issue_key=issue_key,
                cycle_id=cycle_id,
                applied_at=now_iso,
            )
            fw.confidence_history.append(history_entry)

            updates.append(
                DeltaConfidenceUpdate(
                    framework_id=fw.framework_id,
                    issue_key=issue_key,
                    outcome_type=outcome_type,
                    prior_confidence=prior,
                    new_confidence=new_conf,
                    net_delta=net,
                    revision_bumped=revision_bumped,
                    cycle_id=cycle_id,
                    sparse_guard_applied=sparse_guard and abs(raw_delta) > _SPARSE_DELTA_CAP,
                )
            )

    # Re-serialise updated frameworks back into the payload
    updated_json = dict(principles_json)
    updated_df = dict(df_payload)
    updated_df["frameworks"] = [fw.model_dump(mode="json") for fw in frameworks]
    updated_json["decision_frameworks"] = updated_df
    return updated_json, updates


def _tokenize(text: str) -> set[str]:
    """Lower-case word tokens from a string; stopwords filtered out."""
    if not text:
        return set()
    tokens = re.findall(r"[a-z]+", text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


def _tokens_overlap(query: set[str], candidate: set[str]) -> bool:
    """Return True if at least one non-trivial token is shared."""
    return bool(query & candidate)


_STOP_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "is", "it", "as", "be", "by", "if", "do", "we", "he",
        "she", "they", "this", "that", "are", "was", "has", "have", "not",
        "no", "so", "from", "when", "than", "then", "into", "over", "after",
        "before", "between", "about", "up", "out", "per", "via",
    }
)


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
