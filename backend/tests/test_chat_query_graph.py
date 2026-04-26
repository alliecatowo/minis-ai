from __future__ import annotations

import uuid
from unittest.mock import MagicMock


def _make_mini(knowledge_graph_json: dict | None = None) -> MagicMock:
    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "graphdev"
    mini.status = "ready"
    mini.visibility = "public"
    mini.system_prompt = "You are graphdev."
    mini.memory_content = None
    mini.evidence_cache = None
    mini.knowledge_graph_json = knowledge_graph_json
    mini.principles_json = None
    mini.motivations_json = None
    mini.owner_id = str(uuid.uuid4())
    mini.display_name = "graphdev"
    return mini


def test_query_graph_returns_edges():
    from app.routes.chat import query_graph_from_knowledge_graph

    knowledge_graph_json = {
        "nodes": [
            {"name": "Vue"},
            {"name": "React"},
            {"name": "bundle size"},
            {"name": "library selection"},
        ],
        "edges": [
            {"from_node": "Vue", "to_node": "React", "relation": "prefers_over"},
            {
                "from_node": "bundle size",
                "to_node": "library selection",
                "relation": "decides_based_on",
            },
            {"from_node": "Vue", "to_node": "bundle size", "relation": "related_to"},
        ],
    }

    result = query_graph_from_knowledge_graph(
        knowledge_graph_json=knowledge_graph_json,
        node_name="Vue",
        relation="prefers_over",
        depth=1,
    )

    assert result["edges"] == [
        {"from_node": "Vue", "to_node": "React", "relation": "prefers_over"}
    ]
    assert "React" in result["nodes"]


def test_query_graph_in_chat_tool_list():
    from app.routes.chat import _build_runtime_chat_tools

    mini = _make_mini(knowledge_graph_json={"edges": []})
    tools = _build_runtime_chat_tools(mini)

    assert any(tool.name == "query_graph" for tool in tools)
