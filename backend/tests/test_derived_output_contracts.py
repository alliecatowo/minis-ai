from __future__ import annotations

import datetime
from types import SimpleNamespace

from sqlalchemy import inspect


def _make_mini_source(**overrides) -> SimpleNamespace:
    now = datetime.datetime(2026, 4, 20, tzinfo=datetime.timezone.utc)
    data = {
        "id": "mini-123",
        "username": "alliecatowo",
        "display_name": "Allie",
        "avatar_url": None,
        "owner_id": "user-123",
        "visibility": "public",
        "org_id": None,
        "bio": "Builds things",
        "spirit_content": "You are...",
        "memory_content": "Knows many things",
        "personality_typology_json": None,
        "behavioral_context_json": None,
        "system_prompt": "prompt",
        "values_json": {"engineering_values": []},
        "roles_json": None,
        "skills_json": None,
        "traits_json": None,
        "metadata_json": None,
        "sources_used": ["github"],
        "status": "ready",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class TestMiniDerivedOutputColumns:
    def test_columns_exist_on_mini_model(self):
        from app.models.mini import Mini

        col_names = {c.key for c in inspect(Mini).mapper.column_attrs}
        assert "personality_typology_json" in col_names
        assert "behavioral_context_json" in col_names

    def test_mini_accepts_derived_output_payloads(self):
        from app.models.mini import Mini

        mini = Mini(
            username="alliecatowo",
            personality_typology_json={
                "summary": "Analytical and independent.",
                "frameworks": [
                    {
                        "framework": "mbti",
                        "profile": "INTJ",
                        "confidence": 0.74,
                    }
                ],
            },
            behavioral_context_json={
                "summary": "Most direct in review settings.",
                "contexts": [
                    {
                        "context": "code_review",
                        "summary": "Pushes for precision and tests.",
                        "behaviors": ["flags missing coverage", "suggests concrete changes"],
                    }
                ],
            },
        )

        assert mini.personality_typology_json["frameworks"][0]["profile"] == "INTJ"
        assert mini.behavioral_context_json["contexts"][0]["context"] == "code_review"


class TestDerivedOutputSchemas:
    def test_mini_detail_parses_structured_outputs_from_dicts(self):
        from app.models.schemas import MiniDetail

        source = _make_mini_source(
            personality_typology_json={
                "summary": "Analytical and systems-oriented.",
                "frameworks": [
                    {
                        "framework": "big_five",
                        "profile": "high_openness",
                        "dimensions": [
                            {"name": "openness", "value": "high", "confidence": 0.82}
                        ],
                    }
                ],
            },
            behavioral_context_json={
                "summary": "Varies meaningfully by context.",
                "contexts": [
                    {
                        "context": "incident_response",
                        "summary": "Narrows quickly to the most likely failure mode.",
                        "decision_style": "fast triage",
                        "stressors": ["vague ownership"],
                    }
                ],
            },
        )

        detail = MiniDetail.model_validate(source, from_attributes=True)

        assert detail.personality_typology_json is not None
        assert detail.personality_typology_json.frameworks[0].framework == "big_five"
        assert detail.personality_typology_json.frameworks[0].dimensions[0].value == "high"
        assert detail.behavioral_context_json is not None
        assert detail.behavioral_context_json.contexts[0].context == "incident_response"
        assert detail.behavioral_context_json.contexts[0].decision_style == "fast triage"

    def test_mini_public_parses_structured_outputs_from_json_strings(self):
        from app.models.schemas import MiniPublic

        source = _make_mini_source(
            spirit_content=None,
            memory_content=None,
            system_prompt=None,
            personality_typology_json="""
            {
              "summary": "Consistent across frameworks.",
              "frameworks": [
                {
                  "framework": "enneagram",
                  "profile": "5w4",
                  "confidence": 0.68,
                  "evidence": ["prefers deep technical dives"]
                }
              ]
            }
            """,
            behavioral_context_json="""
            {
              "summary": "Most collaborative during design work.",
              "contexts": [
                {
                  "context": "design_discussion",
                  "summary": "Explores tradeoffs before locking in a direction.",
                  "behaviors": ["asks clarifying questions"],
                  "motivators": ["shared understanding"]
                }
              ]
            }
            """,
        )

        public = MiniPublic.model_validate(source, from_attributes=True)

        assert public.personality_typology_json is not None
        assert public.personality_typology_json.frameworks[0].profile == "5w4"
        assert public.behavioral_context_json is not None
        assert public.behavioral_context_json.contexts[0].motivators == ["shared understanding"]

    def test_invalid_structured_output_json_falls_back_to_none(self):
        from app.models.schemas import MiniDetail

        source = _make_mini_source(
            personality_typology_json="not-json",
            behavioral_context_json="{bad json",
        )

        detail = MiniDetail.model_validate(source, from_attributes=True)

        assert detail.personality_typology_json is None
        assert detail.behavioral_context_json is None
