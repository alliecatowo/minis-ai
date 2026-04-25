"""Shared formatter for decision frameworks (ALLIE-519).

Provides:
- ``CONFIDENCE_BAND_LOW`` / ``CONFIDENCE_BAND_HIGH`` constants
- ``confidence_band(confidence)`` helper
- ``format_decision_frameworks(principles_json)`` — public-facing formatter
  that strips retired frameworks and returns a list of formatted dicts

Used by:
- The public ``by-username/{username}/decision-frameworks`` route
- The owner-only ``frameworks-at-risk`` route
- ``spirit._render_decision_frameworks`` (delegates filtering here)
"""

from __future__ import annotations

from typing import Any

CONFIDENCE_BAND_LOW: float = 0.3
CONFIDENCE_BAND_HIGH: float = 0.7


def confidence_band(confidence: float) -> str:
    """Return the string band label for a confidence score.

    Returns one of: ``"LOW"``, ``"MEDIUM"``, or ``"HIGH"``.
    """
    if confidence < CONFIDENCE_BAND_LOW:
        return "LOW"
    if confidence >= CONFIDENCE_BAND_HIGH:
        return "HIGH"
    return "MEDIUM"


def _get_frameworks(principles_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract the raw framework list from a principles_json blob.

    Returns an empty list if the blob is absent or malformed.
    """
    if not isinstance(principles_json, dict):
        return []
    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return []
    raw = df_payload.get("frameworks")
    if not isinstance(raw, list):
        return []
    return [fw for fw in raw if isinstance(fw, dict)]


def format_decision_frameworks(
    principles_json: dict[str, Any] | None,
    *,
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """Return a cleaned, sorted list of decision frameworks for public-facing use.

    Each returned dict contains:
        framework_id, condition, action, value, tradeoff, confidence,
        confidence_band, revision, confidence_history, priority,
        temporal_span, evidence_ids, specificity_level, retired

    Retired frameworks are excluded unless ``include_retired=True``.
    Sorted by confidence desc, revision desc.
    """
    raw_frameworks = _get_frameworks(principles_json)
    result: list[dict[str, Any]] = []

    for raw in raw_frameworks:
        retired: bool = bool(raw.get("retired", False))
        if retired and not include_retired:
            continue

        try:
            conf = float(raw.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        try:
            rev = int(raw.get("revision", 0))
        except (TypeError, ValueError):
            rev = 0

        # Derive a human-readable action/value pair from various raw shapes
        action = _coerce_str(raw.get("action")) or _first_str(raw.get("decision_order"))
        value_ids = raw.get("value_ids") or []
        value = (
            value_ids[0].replace("value:", "").replace("_", " ")
            if isinstance(value_ids, list) and value_ids
            else ""
        )

        result.append(
            {
                "framework_id": _coerce_str(raw.get("framework_id")) or "",
                "condition": _coerce_str(raw.get("condition")) or "",
                "action": action,
                "value": value,
                "tradeoff": _coerce_str(raw.get("tradeoff")) or "",
                "confidence": round(conf, 4),
                "confidence_band": confidence_band(conf),
                "revision": rev,
                "confidence_history": raw.get("confidence_history") or [],
                "priority": _coerce_str(raw.get("priority")) or "medium",
                "temporal_span": raw.get("temporal_span") or {},
                "evidence_ids": raw.get("evidence_ids") or [],
                "specificity_level": _coerce_str(raw.get("specificity_level")) or "case_pattern",
                "retired": retired,
            }
        )

    result.sort(key=lambda fw: (-fw["confidence"], -fw["revision"]))
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_str(value: Any) -> str:
    """Return the first string element of a list, or empty string."""
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip()
    return ""
