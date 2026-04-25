"""Shared view helper for decision-framework serialisation.

A single ``_format_decision_framework`` converts a raw framework dict (from
``principles_json["decision_frameworks"]["frameworks"]``) into the canonical
wire shape returned by the chat tool, the public ``/frameworks`` route, and
any future surface that needs the same representation.

Wire shape::

    {
        "framework_id": str,
        "trigger":      str,   # the ``condition`` field
        "action":       str,   # first item of ``decision_order`` or tradeoff
        "value":        str,   # first value_id stripped of "value:" prefix
        "confidence":   float,
        "revision":     int,
        "badge":        str,   # "" | "HIGH CONFIDENCE" | "LOW CONFIDENCE"
    }
"""

from __future__ import annotations

from typing import Any

_HIGH_CONFIDENCE_THRESHOLD = 0.7
_LOW_CONFIDENCE_THRESHOLD = 0.3


def _format_decision_framework(fw: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw framework dict to the canonical chat/API wire shape.

    Args:
        fw: A dict representing a single entry from
            ``principles_json["decision_frameworks"]["frameworks"]``.
            Unknown or missing keys are handled gracefully.

    Returns:
        A dict with keys: framework_id, trigger, action, value, confidence,
        revision, badge.
    """
    try:
        confidence = float(fw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    try:
        revision = int(fw.get("revision", 0))
    except (TypeError, ValueError):
        revision = 0

    # Normalise trigger (condition field)
    trigger = ""
    if isinstance(fw.get("condition"), str):
        trigger = fw["condition"].strip()

    # Normalise action — first decision_order entry, else tradeoff
    action = ""
    decision_order = fw.get("decision_order")
    if isinstance(decision_order, list) and decision_order:
        first = decision_order[0]
        if isinstance(first, str):
            action = first.strip()
    if not action and isinstance(fw.get("tradeoff"), str):
        action = fw["tradeoff"].strip()

    # Normalise value — first value_id stripped of "value:" prefix
    value = ""
    value_ids = fw.get("value_ids")
    if isinstance(value_ids, list) and value_ids:
        raw_vid = value_ids[0]
        if isinstance(raw_vid, str):
            value = raw_vid.removeprefix("value:").replace("_", " ").strip()

    # Badge string
    if confidence >= _HIGH_CONFIDENCE_THRESHOLD:
        badge = "HIGH CONFIDENCE"
    elif confidence < _LOW_CONFIDENCE_THRESHOLD:
        badge = "LOW CONFIDENCE"
    else:
        badge = ""

    return {
        "framework_id": fw.get("framework_id") or "",
        "trigger": trigger,
        "action": action,
        "value": value,
        "confidence": round(confidence, 4),
        "revision": revision,
        "badge": badge,
    }


def format_decision_frameworks(
    principles_json: dict[str, Any] | None,
    *,
    min_confidence: float = 0.0,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return a confidence-ranked list of formatted framework dicts.

    Args:
        principles_json: The mini's ``principles_json`` blob.
        min_confidence:  Only include frameworks with confidence >= this value.
        limit:           Maximum number of results to return.

    Returns:
        List of dicts in wire shape, sorted by confidence desc then revision desc.
    """
    if not isinstance(principles_json, dict):
        return []

    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return []

    raw_frameworks = df_payload.get("frameworks")
    if not isinstance(raw_frameworks, list):
        return []

    formatted = [
        _format_decision_framework(fw)
        for fw in raw_frameworks
        if isinstance(fw, dict)
    ]

    # Filter by min_confidence
    if min_confidence > 0.0:
        formatted = [f for f in formatted if f["confidence"] >= min_confidence]

    # Sort: confidence desc, revision desc
    formatted.sort(key=lambda f: (-f["confidence"], -f["revision"]))

    return formatted[:limit]
