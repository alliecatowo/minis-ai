"""NetworkX knowledge graph wrapper for Mini knowledge graphs.

Provides graph construction and traversal utilities used by the
explore_knowledge_graph chat tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import networkx as nx
from networkx.algorithms import community

logger = logging.getLogger(__name__)


# ── Graph construction ───────────────────────────────────────────────


def load_graph(knowledge_graph_json: str | dict) -> nx.DiGraph:
    """Parse a knowledge graph JSON blob and build a NetworkX DiGraph.

    Each KnowledgeNode becomes a node with all its attributes stored as
    node data. Each KnowledgeEdge becomes a directed edge with relation
    type and weight.

    Args:
        knowledge_graph_json: JSON string or already-parsed dict from
            ``Mini.knowledge_graph_json``.

    Returns:
        Directed graph with node/edge attributes populated.
    """
    if isinstance(knowledge_graph_json, str):
        data = json.loads(knowledge_graph_json)
    else:
        data = knowledge_graph_json

    G: nx.DiGraph = nx.DiGraph()

    for node in data.get("nodes", []):
        node_id = node["id"]
        G.add_node(
            node_id,
            name=node.get("name", node_id),
            type=node.get("type", "other"),
            depth=node.get("depth", 0.5),
            confidence=node.get("confidence", 0.5),
            evidence=node.get("evidence", []),
            metadata=node.get("metadata", {}),
        )

    for edge in data.get("edges", []):
        source = edge["source"]
        target = edge["target"]
        # Auto-add nodes referenced only in edges (defensive)
        if source not in G:
            G.add_node(source, name=source, type="other")
        if target not in G:
            G.add_node(target, name=target, type="other")
        G.add_edge(
            source,
            target,
            relation=edge.get("relation", "related_to"),
            weight=edge.get("weight", 1.0),
            evidence=edge.get("evidence", []),
            metadata=edge.get("metadata", {}),
        )

    return G


# ── Analysis functions ───────────────────────────────────────────────


def get_expertise_clusters(G: nx.DiGraph) -> list[dict]:
    """Detect expertise clusters using Louvain community detection.

    Runs Louvain on the undirected projection of the graph (since
    community detection is defined for undirected graphs).

    Args:
        G: Knowledge graph produced by ``load_graph``.

    Returns:
        List of cluster dicts, each with:
        - ``cluster_id`` (int)
        - ``size`` (int)
        - ``nodes`` (list of dicts with id, name, type, depth)
        - ``dominant_type`` (most common node type in cluster)
    """
    if G.number_of_nodes() == 0:
        return []

    undirected = G.to_undirected()
    try:
        partitions = community.louvain_communities(undirected, seed=42)
    except Exception:
        # Fall back to connected components if Louvain fails (e.g. empty graph)
        partitions = list(nx.connected_components(undirected))

    clusters: list[dict] = []
    for idx, node_set in enumerate(partitions):
        members = []
        type_counts: dict[str, int] = {}
        for node_id in node_set:
            node_data = G.nodes[node_id]
            members.append(
                {
                    "id": node_id,
                    "name": node_data.get("name", node_id),
                    "type": node_data.get("type", "other"),
                    "depth": node_data.get("depth", 0.5),
                }
            )
            node_type = node_data.get("type", "other")
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        dominant_type = max(type_counts, key=type_counts.__getitem__) if type_counts else "other"
        members.sort(key=lambda n: n["depth"], reverse=True)

        clusters.append(
            {
                "cluster_id": idx,
                "size": len(node_set),
                "nodes": members,
                "dominant_type": dominant_type,
            }
        )

    # Sort clusters by size descending so the most significant appear first
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


def get_central_skills(G: nx.DiGraph, top_n: int = 10) -> list[dict]:
    """Identify the most central skills/concepts using PageRank and betweenness.

    Combines PageRank (influence) and betweenness centrality (bridging
    importance) into a composite score.

    Args:
        G: Knowledge graph produced by ``load_graph``.
        top_n: Number of top nodes to return.

    Returns:
        List of dicts (sorted by composite score descending), each with:
        - ``id``, ``name``, ``type``, ``depth``
        - ``pagerank`` (float)
        - ``betweenness`` (float)
        - ``composite_score`` (float, equal-weight average of normalised scores)
    """
    if G.number_of_nodes() == 0:
        return []

    # Use the NumPy-based PageRank (avoids scipy dependency which isn't installed)
    from networkx.algorithms.link_analysis.pagerank_alg import _pagerank_numpy

    pagerank: dict[str, float] = _pagerank_numpy(G, weight="weight")

    # betweenness on undirected for better coverage in sparse graphs
    undirected = G.to_undirected()
    betweenness: dict[str, float] = nx.betweenness_centrality(undirected, normalized=True)

    # Normalise both scores to [0,1] so they contribute equally
    max_pr = max(pagerank.values()) or 1.0
    max_bt = max(betweenness.values()) or 1.0

    results: list[dict] = []
    for node_id, node_data in G.nodes(data=True):
        pr = pagerank.get(node_id, 0.0)
        bt = betweenness.get(node_id, 0.0)
        composite = 0.5 * (pr / max_pr) + 0.5 * (bt / max_bt)
        results.append(
            {
                "id": node_id,
                "name": node_data.get("name", node_id),
                "type": node_data.get("type", "other"),
                "depth": node_data.get("depth", 0.5),
                "pagerank": round(pr, 6),
                "betweenness": round(bt, 6),
                "composite_score": round(composite, 6),
            }
        )

    results.sort(key=lambda x: x["composite_score"], reverse=True)
    return results[:top_n]


def get_path(G: nx.DiGraph, source: str, target: str) -> list[str]:
    """Find the shortest path between two concepts.

    Searches the undirected projection so that direction of edges does
    not block path discovery.

    Args:
        G: Knowledge graph produced by ``load_graph``.
        source: ID of the starting node.
        target: ID of the destination node.

    Returns:
        Ordered list of node IDs from source to target (inclusive).
        Returns an empty list if either node is absent or no path exists.
    """
    if source not in G or target not in G:
        return []

    undirected = G.to_undirected()
    try:
        return nx.shortest_path(undirected, source=source, target=target)
    except nx.NetworkXNoPath:
        return []


def get_neighborhood(G: nx.DiGraph, node: str, depth: int = 2) -> dict:
    """Multi-hop subgraph traversal returning nodes and edges up to *depth* hops.

    Traverses both in- and out-edges (i.e. undirected neighbourhood) so
    that the caller gets the full local context.

    Args:
        G: Knowledge graph produced by ``load_graph``.
        node: ID of the centre node.
        depth: Number of hops to traverse (default 2).

    Returns:
        Dict with:
        - ``center`` (str): the requested node ID
        - ``nodes`` (list[dict]): all nodes in the subgraph (id, name, type, depth)
        - ``edges`` (list[dict]): all edges in the subgraph (source, target, relation, weight)
        Returns ``{"center": node, "nodes": [], "edges": []}`` if the node
        is absent.
    """
    if node not in G:
        return {"center": node, "nodes": [], "edges": []}

    # Collect all nodes within `depth` hops using BFS on undirected graph
    undirected = G.to_undirected()
    visited: set[str] = set()
    frontier = {node}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            neighbours = set(undirected.neighbors(n)) - visited - frontier
            next_frontier.update(neighbours)
        visited.update(frontier)
        frontier = next_frontier
    visited.update(frontier)

    subgraph = G.subgraph(visited)

    nodes_out: list[dict] = []
    for n_id, n_data in subgraph.nodes(data=True):
        nodes_out.append(
            {
                "id": n_id,
                "name": n_data.get("name", n_id),
                "type": n_data.get("type", "other"),
                "depth": n_data.get("depth", 0.5),
            }
        )

    edges_out: list[dict] = []
    for src, tgt, e_data in subgraph.edges(data=True):
        edges_out.append(
            {
                "source": src,
                "target": tgt,
                "relation": e_data.get("relation", "related_to"),
                "weight": e_data.get("weight", 1.0),
            }
        )

    return {"center": node, "nodes": nodes_out, "edges": edges_out}


def get_related_concepts(G: nx.DiGraph, node: str) -> list[dict]:
    """Return direct neighbours (in + out) with their edge labels.

    Args:
        G: Knowledge graph produced by ``load_graph``.
        node: ID of the node to query.

    Returns:
        List of dicts, each with:
        - ``id``, ``name``, ``type`` (neighbour node attributes)
        - ``relation`` (str): the edge relation label
        - ``direction``: ``"outgoing"`` or ``"incoming"``
        - ``weight`` (float)
        Returns empty list if node is absent.
    """
    if node not in G:
        return []

    results: list[dict] = []

    for successor in G.successors(node):
        edge_data = G.edges[node, successor]
        n_data = G.nodes[successor]
        results.append(
            {
                "id": successor,
                "name": n_data.get("name", successor),
                "type": n_data.get("type", "other"),
                "relation": edge_data.get("relation", "related_to"),
                "direction": "outgoing",
                "weight": edge_data.get("weight", 1.0),
            }
        )

    for predecessor in G.predecessors(node):
        edge_data = G.edges[predecessor, node]
        n_data = G.nodes[predecessor]
        results.append(
            {
                "id": predecessor,
                "name": n_data.get("name", predecessor),
                "type": n_data.get("type", "other"),
                "relation": edge_data.get("relation", "related_to"),
                "direction": "incoming",
                "weight": edge_data.get("weight", 1.0),
            }
        )

    return results


# ── Formatting helpers ───────────────────────────────────────────────


def _format_clusters(clusters: list[dict]) -> str:
    if not clusters:
        return "No clusters found."
    parts: list[str] = []
    for c in clusters[:5]:  # Show top 5 clusters
        top_nodes = ", ".join(n["name"] for n in c["nodes"][:5])
        parts.append(
            f"Cluster {c['cluster_id']} ({c['dominant_type']}, {c['size']} nodes): {top_nodes}"
        )
    return "\n".join(parts)


def _format_central_skills(skills: list[dict]) -> str:
    if not skills:
        return "No skills found."
    parts: list[str] = []
    for s in skills:
        parts.append(
            f"- **{s['name']}** ({s['type']}, depth: {s['depth']:.1f},"
            f" score: {s['composite_score']:.3f})"
        )
    return "\n".join(parts)


def _format_path(path: list[str], G: nx.DiGraph) -> str:
    if not path:
        return "No path found between those concepts."
    names = [G.nodes[n].get("name", n) if n in G.nodes else n for n in path]
    return " → ".join(names)


def _format_neighborhood(result: dict, G: nx.DiGraph) -> str:
    if not result["nodes"]:
        return f"No neighborhood found for '{result['center']}'."
    center_name = G.nodes.get(result["center"], {}).get("name", result["center"])
    node_names = [
        f"{n['name']} ({n['type']})"
        for n in result["nodes"]
        if n["id"] != result["center"]
    ]
    edge_lines = [
        f"  {e['source']} --[{e['relation']}]--> {e['target']}"
        for e in result["edges"][:20]
    ]
    parts = [
        f"Neighborhood of **{center_name}** ({len(result['nodes'])} nodes, {len(result['edges'])} edges):",
        "Nodes: " + ", ".join(node_names[:10]),
    ]
    if edge_lines:
        parts.append("Edges:\n" + "\n".join(edge_lines))
    return "\n".join(parts)


# ── Chat tool handler ────────────────────────────────────────────────


async def explore_knowledge_graph_handler(
    knowledge_graph_json: str | dict | None,
    query: str,
    traversal_type: str = "search",
) -> str:
    """Handler for the explore_knowledge_graph chat tool.

    Args:
        knowledge_graph_json: Raw knowledge graph data from the Mini model.
        query: Search term, node ID, or ``"source->target"`` path expression.
        traversal_type: One of ``"search"``, ``"path"``, ``"cluster"``,
            or ``"neighborhood"``.

    Returns:
        Human-readable string with the results.
    """
    if not knowledge_graph_json:
        return "No knowledge graph available for this mini."

    try:
        G = load_graph(knowledge_graph_json)
    except Exception as exc:
        logger.warning("Failed to load knowledge graph: %s", exc)
        return "Knowledge graph data is corrupted or unreadable."

    if G.number_of_nodes() == 0:
        return "The knowledge graph is empty."

    traversal_type = traversal_type.lower().strip()

    # ── cluster ────────────────────────────────────────────────────────
    if traversal_type == "cluster":
        clusters = get_expertise_clusters(G)
        return "**Expertise Clusters**\n" + _format_clusters(clusters)

    # ── path ───────────────────────────────────────────────────────────
    if traversal_type == "path":
        # Parse "source->target" or "source -> target"
        sep = "->" if "->" in query else " to "
        parts_split = query.split(sep, 1)
        if len(parts_split) != 2:
            return (
                "For 'path' traversal, provide query as 'source->target' "
                "(e.g. 'python->django')."
            )
        source_q, target_q = parts_split[0].strip(), parts_split[1].strip()
        # Resolve node IDs by name match (case-insensitive)
        source_id = _resolve_node_id(G, source_q)
        target_id = _resolve_node_id(G, target_q)
        if not source_id:
            return f"Node '{source_q}' not found in knowledge graph."
        if not target_id:
            return f"Node '{target_q}' not found in knowledge graph."
        path = get_path(G, source_id, target_id)
        return f"**Path**: {_format_path(path, G)}"

    # ── neighborhood ───────────────────────────────────────────────────
    if traversal_type == "neighborhood":
        node_id = _resolve_node_id(G, query)
        if not node_id:
            return f"Node '{query}' not found in knowledge graph."
        result = get_neighborhood(G, node_id, depth=2)
        return _format_neighborhood(result, G)

    # ── search (default) ───────────────────────────────────────────────
    query_lower = query.lower()
    keywords = [w for w in query_lower.split() if len(w) > 1]
    if not keywords:
        keywords = [query_lower]

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for node_id, node_data in G.nodes(data=True):
        name_lower = node_data.get("name", "").lower()
        type_lower = node_data.get("type", "").lower()
        score = sum(1.0 for kw in keywords if kw in name_lower or kw in type_lower)
        if score > 0:
            scored.append((score, node_id, node_data))

    if not scored:
        # Fall back to central skills when no text match
        skills = get_central_skills(G, top_n=5)
        return (
            f"No nodes matching '{query}'. Top central skills:\n"
            + _format_central_skills(skills)
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    parts: list[str] = []
    for _, node_id, node_data in scored[:10]:
        related = get_related_concepts(G, node_id)
        related_strs = [
            f"{'→' if r['direction'] == 'outgoing' else '←'} {r['name']} [{r['relation']}]"
            for r in related[:5]
        ]
        line = (
            f"**{node_data.get('name', node_id)}** "
            f"({node_data.get('type', 'other')}, depth: {node_data.get('depth', 0.5):.1f})"
        )
        if related_strs:
            line += "\n  " + "  ".join(related_strs)
        parts.append(line)

    return "\n\n".join(parts)


def _resolve_node_id(G: nx.DiGraph, query: str) -> str | None:
    """Resolve a name or ID query to a node ID (case-insensitive)."""
    query_lower = query.lower()
    # Exact ID match first
    if query in G:
        return query
    # Case-insensitive ID match
    for node_id in G.nodes:
        if node_id.lower() == query_lower:
            return node_id
    # Name match
    for node_id, node_data in G.nodes(data=True):
        if node_data.get("name", "").lower() == query_lower:
            return node_id
    # Partial name match
    for node_id, node_data in G.nodes(data=True):
        if query_lower in node_data.get("name", "").lower():
            return node_id
    return None
