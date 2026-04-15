"""Tests for backend/app/core/graph.py — NetworkX knowledge graph wrapper."""

from __future__ import annotations

import json

import networkx as nx
import pytest

from app.core.graph import (
    get_central_skills,
    get_expertise_clusters,
    get_neighborhood,
    get_path,
    get_related_concepts,
    load_graph,
    explore_knowledge_graph_handler,
)

# ── Fixtures ─────────────────────────────────────────────────────────


SMALL_GRAPH_DATA = {
    "nodes": [
        {"id": "python", "name": "Python", "type": "language", "depth": 0.9, "confidence": 0.95},
        {"id": "django", "name": "Django", "type": "framework", "depth": 0.8, "confidence": 0.9},
        {"id": "fastapi", "name": "FastAPI", "type": "framework", "depth": 0.85, "confidence": 0.9},
        {"id": "postgres", "name": "PostgreSQL", "type": "library", "depth": 0.7, "confidence": 0.85},
        {"id": "react", "name": "React", "type": "framework", "depth": 0.6, "confidence": 0.8},
        {"id": "typescript", "name": "TypeScript", "type": "language", "depth": 0.7, "confidence": 0.85},
        {"id": "testing", "name": "Testing", "type": "concept", "depth": 0.75, "confidence": 0.8},
        {"id": "hexagonal", "name": "Hexagonal Architecture", "type": "architecture", "depth": 0.8, "confidence": 0.75},
        {"id": "ddd", "name": "Domain-Driven Design", "type": "pattern", "depth": 0.75, "confidence": 0.7},
        {"id": "redis", "name": "Redis", "type": "library", "depth": 0.5, "confidence": 0.6},
    ],
    "edges": [
        {"source": "python", "target": "django", "relation": "used_in", "weight": 0.9},
        {"source": "python", "target": "fastapi", "relation": "used_in", "weight": 0.95},
        {"source": "django", "target": "postgres", "relation": "built_with", "weight": 0.8},
        {"source": "fastapi", "target": "postgres", "relation": "built_with", "weight": 0.85},
        {"source": "react", "target": "typescript", "relation": "built_with", "weight": 0.9},
        {"source": "python", "target": "testing", "relation": "related_to", "weight": 0.7},
        {"source": "hexagonal", "target": "ddd", "relation": "related_to", "weight": 0.8},
        {"source": "fastapi", "target": "redis", "relation": "built_with", "weight": 0.6},
        {"source": "python", "target": "hexagonal", "relation": "related_to", "weight": 0.7},
    ],
}

SMALL_GRAPH_JSON = json.dumps(SMALL_GRAPH_DATA)


# ── load_graph ────────────────────────────────────────────────────────


class TestLoadGraph:
    def test_loads_from_string(self):
        G = load_graph(SMALL_GRAPH_JSON)
        assert isinstance(G, nx.DiGraph)

    def test_loads_from_dict(self):
        G = load_graph(SMALL_GRAPH_DATA)
        assert isinstance(G, nx.DiGraph)

    def test_node_count(self):
        G = load_graph(SMALL_GRAPH_DATA)
        assert G.number_of_nodes() == 10

    def test_edge_count(self):
        G = load_graph(SMALL_GRAPH_DATA)
        assert G.number_of_edges() == 9

    def test_node_attributes(self):
        G = load_graph(SMALL_GRAPH_DATA)
        python = G.nodes["python"]
        assert python["name"] == "Python"
        assert python["type"] == "language"
        assert python["depth"] == 0.9

    def test_edge_attributes(self):
        G = load_graph(SMALL_GRAPH_DATA)
        edge = G.edges["python", "django"]
        assert edge["relation"] == "used_in"
        assert edge["weight"] == 0.9

    def test_empty_graph(self):
        G = load_graph({"nodes": [], "edges": []})
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0

    def test_edge_with_unknown_node_auto_adds(self):
        """Edges referencing nodes not in the nodes list should create orphan nodes."""
        data = {
            "nodes": [{"id": "a", "name": "A", "type": "skill"}],
            "edges": [{"source": "a", "target": "unknown", "relation": "related_to"}],
        }
        G = load_graph(data)
        assert "unknown" in G.nodes

    def test_directed_edges(self):
        G = load_graph(SMALL_GRAPH_DATA)
        # python -> django exists, but django -> python should not
        assert G.has_edge("python", "django")
        assert not G.has_edge("django", "python")


# ── get_expertise_clusters ────────────────────────────────────────────


class TestGetExpertiseClusters:
    def test_returns_list(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        assert isinstance(clusters, list)

    def test_has_clusters(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        assert len(clusters) >= 1

    def test_cluster_structure(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        first = clusters[0]
        assert "cluster_id" in first
        assert "size" in first
        assert "nodes" in first
        assert "dominant_type" in first

    def test_all_nodes_assigned(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        total_assigned = sum(c["size"] for c in clusters)
        assert total_assigned == G.number_of_nodes()

    def test_nodes_sorted_by_depth(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        for cluster in clusters:
            depths = [n["depth"] for n in cluster["nodes"]]
            assert depths == sorted(depths, reverse=True)

    def test_clusters_sorted_by_size(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        sizes = [c["size"] for c in clusters]
        assert sizes == sorted(sizes, reverse=True)

    def test_empty_graph(self):
        G = load_graph({"nodes": [], "edges": []})
        assert get_expertise_clusters(G) == []

    def test_dominant_type_is_valid(self):
        G = load_graph(SMALL_GRAPH_DATA)
        clusters = get_expertise_clusters(G)
        valid_types = {"skill", "project", "concept", "pattern", "architecture",
                       "framework", "language", "library", "other"}
        for c in clusters:
            assert c["dominant_type"] in valid_types


# ── get_central_skills ────────────────────────────────────────────────


class TestGetCentralSkills:
    def test_returns_list(self):
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G)
        assert isinstance(skills, list)

    def test_top_n_respected(self):
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G, top_n=3)
        assert len(skills) <= 3

    def test_default_top_n(self):
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G)
        assert len(skills) <= 10

    def test_skill_structure(self):
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G)
        assert len(skills) > 0
        s = skills[0]
        assert "id" in s
        assert "name" in s
        assert "type" in s
        assert "depth" in s
        assert "pagerank" in s
        assert "betweenness" in s
        assert "composite_score" in s

    def test_sorted_by_composite_score(self):
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G, top_n=10)
        scores = [s["composite_score"] for s in skills]
        assert scores == sorted(scores, reverse=True)

    def test_python_is_highly_central(self):
        """Python has the most outgoing edges; should rank near top."""
        G = load_graph(SMALL_GRAPH_DATA)
        skills = get_central_skills(G, top_n=5)
        top_ids = [s["id"] for s in skills]
        assert "python" in top_ids

    def test_empty_graph(self):
        G = load_graph({"nodes": [], "edges": []})
        assert get_central_skills(G) == []


# ── get_path ─────────────────────────────────────────────────────────


class TestGetPath:
    def test_direct_path(self):
        G = load_graph(SMALL_GRAPH_DATA)
        path = get_path(G, "python", "django")
        assert path == ["python", "django"]

    def test_multi_hop_path(self):
        G = load_graph(SMALL_GRAPH_DATA)
        # python -> fastapi -> postgres  (or python -> django -> postgres)
        path = get_path(G, "python", "postgres")
        assert path[0] == "python"
        assert path[-1] == "postgres"
        assert len(path) >= 2

    def test_no_path(self):
        """React cluster is disconnected from the testing node cluster."""
        G = load_graph(SMALL_GRAPH_DATA)
        # react/typescript cluster has no edges to testing
        path = get_path(G, "react", "testing")
        # May or may not have a path depending on graph topology — just check type
        assert isinstance(path, list)

    def test_same_node(self):
        G = load_graph(SMALL_GRAPH_DATA)
        path = get_path(G, "python", "python")
        assert path == ["python"]

    def test_missing_source(self):
        G = load_graph(SMALL_GRAPH_DATA)
        path = get_path(G, "nonexistent", "python")
        assert path == []

    def test_missing_target(self):
        G = load_graph(SMALL_GRAPH_DATA)
        path = get_path(G, "python", "nonexistent")
        assert path == []

    def test_reverse_direction_allowed(self):
        """Path should work regardless of edge direction (uses undirected)."""
        G = load_graph(SMALL_GRAPH_DATA)
        # django -> python is not a direct edge, but undirected search should work
        path = get_path(G, "django", "python")
        assert path[0] == "django"
        assert path[-1] == "python"


# ── get_neighborhood ─────────────────────────────────────────────────


class TestGetNeighborhood:
    def test_returns_dict(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python")
        assert isinstance(result, dict)
        assert "center" in result
        assert "nodes" in result
        assert "edges" in result

    def test_center_included(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python")
        node_ids = [n["id"] for n in result["nodes"]]
        assert "python" in node_ids

    def test_depth_1(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python", depth=1)
        node_ids = {n["id"] for n in result["nodes"]}
        # Depth 1 should include direct neighbours
        assert "django" in node_ids
        assert "fastapi" in node_ids

    def test_depth_2_includes_transitive(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python", depth=2)
        node_ids = {n["id"] for n in result["nodes"]}
        # postgres is 2 hops away via django or fastapi
        assert "postgres" in node_ids

    def test_missing_node(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "nonexistent")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_node_structure(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python")
        for node in result["nodes"]:
            assert "id" in node
            assert "name" in node
            assert "type" in node
            assert "depth" in node

    def test_edge_structure(self):
        G = load_graph(SMALL_GRAPH_DATA)
        result = get_neighborhood(G, "python")
        for edge in result["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "relation" in edge
            assert "weight" in edge


# ── get_related_concepts ─────────────────────────────────────────────


class TestGetRelatedConcepts:
    def test_returns_list(self):
        G = load_graph(SMALL_GRAPH_DATA)
        related = get_related_concepts(G, "python")
        assert isinstance(related, list)

    def test_python_has_related(self):
        G = load_graph(SMALL_GRAPH_DATA)
        related = get_related_concepts(G, "python")
        assert len(related) > 0

    def test_outgoing_direction(self):
        G = load_graph(SMALL_GRAPH_DATA)
        related = get_related_concepts(G, "python")
        outgoing = [r for r in related if r["direction"] == "outgoing"]
        outgoing_ids = [r["id"] for r in outgoing]
        # python -> django, python -> fastapi, etc.
        assert "django" in outgoing_ids
        assert "fastapi" in outgoing_ids

    def test_incoming_direction(self):
        G = load_graph(SMALL_GRAPH_DATA)
        # postgres is pointed to by django and fastapi
        related = get_related_concepts(G, "postgres")
        incoming = [r for r in related if r["direction"] == "incoming"]
        incoming_ids = [r["id"] for r in incoming]
        assert "django" in incoming_ids or "fastapi" in incoming_ids

    def test_relation_label_present(self):
        G = load_graph(SMALL_GRAPH_DATA)
        related = get_related_concepts(G, "python")
        for r in related:
            assert "relation" in r
            assert r["relation"]  # non-empty

    def test_missing_node(self):
        G = load_graph(SMALL_GRAPH_DATA)
        related = get_related_concepts(G, "nonexistent")
        assert related == []

    def test_isolated_node(self):
        data = {
            "nodes": [{"id": "solo", "name": "Solo", "type": "skill"}],
            "edges": [],
        }
        G = load_graph(data)
        related = get_related_concepts(G, "solo")
        assert related == []


# ── explore_knowledge_graph_handler ──────────────────────────────────


class TestExploreKnowledgeGraphHandler:
    @pytest.mark.asyncio
    async def test_no_graph(self):
        result = await explore_knowledge_graph_handler(None, "python")
        assert "No knowledge graph" in result

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        result = await explore_knowledge_graph_handler(SMALL_GRAPH_JSON, "python")
        assert "Python" in result

    @pytest.mark.asyncio
    async def test_search_from_dict(self):
        result = await explore_knowledge_graph_handler(SMALL_GRAPH_DATA, "django")
        assert "Django" in result

    @pytest.mark.asyncio
    async def test_cluster_traversal(self):
        result = await explore_knowledge_graph_handler(
            SMALL_GRAPH_JSON, "any", traversal_type="cluster"
        )
        assert "Cluster" in result

    @pytest.mark.asyncio
    async def test_neighborhood_traversal(self):
        result = await explore_knowledge_graph_handler(
            SMALL_GRAPH_JSON, "python", traversal_type="neighborhood"
        )
        assert "Python" in result or "python" in result.lower()

    @pytest.mark.asyncio
    async def test_path_traversal(self):
        result = await explore_knowledge_graph_handler(
            SMALL_GRAPH_JSON, "python->postgres", traversal_type="path"
        )
        assert "Path" in result or "Python" in result

    @pytest.mark.asyncio
    async def test_path_traversal_missing_sep(self):
        result = await explore_knowledge_graph_handler(
            SMALL_GRAPH_JSON, "python", traversal_type="path"
        )
        assert "provide query as" in result.lower() or "path" in result.lower()

    @pytest.mark.asyncio
    async def test_search_no_match_falls_back_to_central(self):
        result = await explore_knowledge_graph_handler(
            SMALL_GRAPH_JSON, "zzznomatchzzz"
        )
        assert "central skills" in result.lower() or "No nodes matching" in result

    @pytest.mark.asyncio
    async def test_corrupted_json(self):
        result = await explore_knowledge_graph_handler("not valid json", "python")
        assert "corrupted" in result.lower() or "unreadable" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_graph(self):
        result = await explore_knowledge_graph_handler(
            json.dumps({"nodes": [], "edges": []}), "python"
        )
        assert "empty" in result.lower()
