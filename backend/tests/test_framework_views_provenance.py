from __future__ import annotations

from app.synthesis.framework_views import format_decision_frameworks


def test_format_decision_frameworks_surfaces_provenance_and_citation_ids():
    payload = {
        "decision_frameworks": {
            "frameworks": [
                {
                    "framework_id": "fw:prov",
                    "condition": "when migration touches audit logs",
                    "action": "preserve provenance fields",
                    "value_ids": ["value:traceability"],
                    "confidence": 0.8,
                    "revision": 2,
                    "evidence_ids": ["ev-1"],
                    "evidence_provenance": [{"id": "ev-1", "source_type": "github"}],
                    "citation_ids": ["ev-1", "ev-2"],
                }
            ]
        }
    }

    result = format_decision_frameworks(payload)
    assert len(result) == 1
    item = result[0]
    assert item["evidence_provenance"] == [{"id": "ev-1", "source_type": "github"}]
    assert item["citation_ids"] == ["ev-1", "ev-2"]
