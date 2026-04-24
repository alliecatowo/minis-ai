from __future__ import annotations

from app.models.schemas import Motivation, MotivationChain, MotivationsProfile
from app.synthesis.decision_frameworks import (
    attach_decision_frameworks,
    build_decision_frameworks_payload,
    normalize_principle_to_decision_framework,
)


def test_normalizes_principle_to_decision_framework_contract():
    framework = normalize_principle_to_decision_framework(
        {
            "trigger": "A reusable package erases domain-specific errors",
            "action": "block broad erased errors at library boundaries",
            "value": "explicitness over magic",
            "intensity": 0.82,
            "evidence_ids": ["ev-1"],
            "counter_evidence_ids": ["ev-9"],
            "counterexamples": ["Prototype code outside reusable packages"],
            "evidence_provenance": [
                {
                    "id": "ev-1",
                    "source_type": "github",
                    "item_type": "review",
                    "evidence_date": "2026-04-20T12:00:00+00:00",
                    "created_at": "2026-04-21T12:00:00+00:00",
                    "provenance_confidence": 0.96,
                }
            ],
            "source_dates": ["2026-04-20T12:00:00+00:00"],
            "source_type": "github",
            "support_count": 2,
        },
        motivation_index={},
    )

    assert framework is not None
    assert framework.condition == "A reusable package erases domain-specific errors"
    assert framework.priority == "high"
    assert framework.tradeoff == (
        "explicitness over magic prioritized when deciding whether to "
        "block broad erased errors at library boundaries."
    )
    assert framework.escalation_threshold == (
        "Escalate to blocking feedback when the condition is present."
    )
    assert framework.counterexamples == ["Prototype code outside reusable packages"]
    assert framework.counter_evidence_ids == ["ev-9"]
    assert framework.evidence_ids == ["ev-1"]
    assert framework.evidence_provenance[0].id == "ev-1"
    assert framework.temporal_span.first_seen_at == "2026-04-20T12:00:00+00:00"
    assert framework.temporal_span.last_reinforced_at == "2026-04-20T12:00:00+00:00"
    assert framework.confidence == 0.8
    assert framework.specificity_level == "contextual"
    assert framework.value_ids == ["value:explicitness_over_magic"]


def test_build_payload_links_matching_motivations():
    profile = MotivationsProfile(
        motivations=[
            Motivation(
                value="explicitness over magic",
                category="terminal_value",
                evidence_ids=["ev-2"],
                confidence=0.9,
            )
        ],
        motivation_chains=[
            MotivationChain(
                motivation="explicitness over magic",
                implied_framework="prefer visible dependencies over hidden behavior",
                observed_behavior="blocks hidden runtime coupling",
                evidence_ids=["ev-2"],
            )
        ],
        summary="Prefers explicit control flow.",
    )

    payload = build_decision_frameworks_payload(
        {
            "principles": [
                {
                    "trigger": "Hidden framework behavior changes runtime coupling",
                    "action": "ask for explicit dependencies",
                    "value": "explicitness over magic",
                    "intensity": 0.7,
                    "evidence_ids": ["ev-1"],
                    "source_type": "github",
                }
            ]
        },
        profile,
    )

    assert payload.version == "decision_frameworks_v1"
    assert len(payload.frameworks) == 1
    assert payload.frameworks[0].motivation_ids == ["motivation:explicitness_over_magic"]
    assert payload.frameworks[0].specificity_level == "scope_local"


def test_attach_decision_frameworks_preserves_legacy_principles():
    principles_json = {
        "principles": [
            {
                "trigger": "Migration shim hides follow-up work",
                "action": "comment with follow-up request",
                "value": "operational clarity",
                "intensity": 6,
                "evidence": ["ev-1"],
            }
        ]
    }

    enriched = attach_decision_frameworks(principles_json, motivations=None)

    assert enriched["principles"] == principles_json["principles"]
    assert enriched["decision_frameworks"]["version"] == "decision_frameworks_v1"
    framework = enriched["decision_frameworks"]["frameworks"][0]
    assert framework["condition"] == "Migration shim hides follow-up work"
    assert framework["priority"] == "medium"
    assert framework["evidence_ids"] == ["ev-1"]
    assert "decision_frameworks" not in principles_json


def test_empty_payload_returns_empty_profile():
    payload = build_decision_frameworks_payload(None, None)

    assert payload.frameworks == []
