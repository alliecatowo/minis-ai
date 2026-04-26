from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.agent import AgentResult
from app.models.evidence import Evidence, ExplorerFinding
from app.models.mini import Mini
from app.synthesis.chief import run_chief_synthesizer
from tests.fixtures.postgres_mock import PostgresStyleSession, make_session_factory


def _finding_payload(content: str, *, breadth: str, recency: str, temporal: str) -> str:
    return json.dumps(
        {
            "content": content,
            "breadth_tag": breadth,
            "recency_tag": recency,
            "temporal_signal": temporal,
            "evidence_ids": [],
            "support_count": 1,
            "contradicts_finding_ids": [],
        }
    )


@pytest.mark.asyncio
async def test_chief_prompt_biases_temporal_identity_not_narrow_label():
    mini = Mini(id="mini-breadth-1", username="breadth-user", principles_json={"principles": []})

    findings: list[ExplorerFinding] = []
    for i in range(1000):
        findings.append(
            ExplorerFinding(
                mini_id=mini.id,
                source_type="github",
                category="technical_preferences",
                content=_finding_payload(
                    f"Recent firmware/embedded project signal {i}",
                    breadth="deep",
                    recency="recent",
                    temporal="CONCENTRATED",
                ),
                confidence=0.70,
            )
        )

    for i in range(50):
        findings.append(
            ExplorerFinding(
                mini_id=mini.id,
                source_type="github",
                category="architecture",
                content=_finding_payload(
                    f"Long-range frontend/web portfolio signal {i}",
                    breadth="portfolio",
                    recency="historical",
                    temporal="SPREAD",
                ),
                confidence=0.99,
            )
        )

    for i in range(50):
        findings.append(
            ExplorerFinding(
                mini_id=mini.id,
                source_type="github",
                category="systems",
                content=_finding_payload(
                    f"Long-range backend portfolio signal {i}",
                    breadth="portfolio",
                    recency="historical",
                    temporal="SPREAD",
                ),
                confidence=0.98,
            )
        )

    language_summary = Evidence(
        mini_id=mini.id,
        source_type="github",
        item_type="language_diversity_summary",
        content="Language diversity summary: 6 distinct languages across 42 repos.",
        metadata_json={
            "distinct_languages": 6,
            "repos_with_languages": 42,
            "language_totals": {"Rust": 400000, "TypeScript": 350000, "Python": 250000},
        },
    )

    session = PostgresStyleSession(initial_records=[mini, language_summary, *findings])
    original_execute = session.execute

    async def execute_with_ai_short_circuit(stmt):
        if "ai_authorship_likelihood" in str(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result
        return await original_execute(stmt)

    session.execute = execute_with_ai_short_circuit

    captured_system_prompts: list[str] = []
    captured_user_prompts: list[str] = []

    async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
        captured_system_prompts.append(system_prompt)
        captured_user_prompts.append(user_prompt)

        if tools:
            aspect = system_prompt.split("Aspect:", 1)[1].splitlines()[0].strip()
            save_tool = next(t for t in tools if t.name == "save_narrative")
            await save_tool.handler(
                aspect=aspect,
                narrative=(f"Narrative for {aspect}. " * 40),
                confidence=0.8,
            )
            return AgentResult(
                final_response="aspect done",
                tool_outputs={"save_narrative": [{"aspect": aspect}]},
                turns_used=1,
            )

        return AgentResult(final_response="# IDENTITY\nSynthesized", tool_outputs={}, turns_used=1)

    with (
        patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent),
        patch("app.synthesis.chief._global_session_factory", make_session_factory(session)),
    ):
        await run_chief_synthesizer(mini_id=mini.id, db_session=session)

    combined_prompts = "\n".join(captured_user_prompts)
    assert "breadth_tag=portfolio" in combined_prompts
    assert "recency_tag=historical" in combined_prompts

    final_system_prompt = captured_system_prompts[-1]
    assert "X-flavored generalist currently deep on Y" in final_system_prompt
    assert "firmware developer" not in final_system_prompt.lower()
