# Memory System + Knowledge Graph Audit (2026-04-26)

## Scope and Sources
This audit is grounded in full reads of: `backend/app/synthesis/memory_assembler.py`, `backend/app/models/mini.py`, `backend/app/routes/chat.py`, `backend/app/synthesis/explorers/tools.py`, and `backend/app/models/knowledge.py`, plus codebase grep of `search_memories` definitions/usages.

## 1) Memory System

### Construction
- Runtime memory content is DB-driven and deterministic: pipeline synthesis reads `ExplorerFinding` rows where `category LIKE "memory:%"`, parses JSON payloads, and concatenates `[context] text` lines into `memory_content` (`backend/app/synthesis/pipeline.py:1251`, `backend/app/synthesis/pipeline.py:1264`, `backend/app/synthesis/pipeline.py:1267`, `backend/app/synthesis/pipeline.py:1276`).
- Explorers create those rows through `save_memory`, which stores only `{text, context_type}` in `ExplorerFinding.content` under `memory:<category>` with fixed confidence 0.7 (`backend/app/synthesis/explorers/tools.py:683`, `backend/app/synthesis/explorers/tools.py:691`, `backend/app/synthesis/explorers/tools.py:692`, `backend/app/synthesis/explorers/tools.py:693`).
- `memory_assembler.py` defines a richer merge/format path (`assemble_memory`) with graph+principles+episodic sections, but current app runtime does not call it (inferred from code search: definition in `backend/app/synthesis/memory_assembler.py:239`; usage appears in tests only, e.g. `backend/tests/test_memory_assembler.py:186`).

### Storage
- Memory is stored as a flat text blob on `Mini.memory_content` (`backend/app/models/mini.py:65`).
- Structured knowledge is stored separately as JSON blobs on `Mini.knowledge_graph_json` and `Mini.principles_json` (`backend/app/models/mini.py:66`, `backend/app/models/mini.py:69`).
- Embeddings exist in a separate `embeddings` table with `Vector(768)` and `source_type` (`memory|evidence|knowledge_node`) (`backend/app/models/embeddings.py:30`, `backend/app/models/embeddings.py:31`, `backend/app/synthesis/pipeline.py:236`, `backend/app/synthesis/pipeline.py:241`, `backend/app/synthesis/pipeline.py:250`).

### Retrieval
- Chat requires `mini.system_prompt` and sends it wholesale to the agent (`backend/app/routes/chat.py:1111`, `backend/app/routes/chat.py:1293`).
- System prompt itself embeds the full `memory_content` under `# KNOWLEDGE` (`backend/app/synthesis/spirit.py:406`, `backend/app/synthesis/spirit.py:421`).
- Chat also supports on-demand search via `search_memories` tool (`backend/app/routes/chat.py:646`, `backend/app/routes/chat.py:930`).
- The runtime directive pushes search-first behavior for substantive questions (`backend/app/routes/chat.py:1160`, `backend/app/routes/chat.py:1161`, `backend/app/routes/chat.py:1175`).

### Search Algorithm
- `search_memories` is hybrid-with-fallback: vector first, keyword fallback (`backend/app/routes/chat.py:650`, `backend/app/routes/chat.py:657`).
- Vector search is conditional on embeddings module availability and session, with pgvector cosine-distance ordering (`backend/app/routes/chat.py:31`, `backend/app/routes/chat.py:611`, `backend/app/routes/chat.py:630`).
- Keyword search is overlap-count ranking over lines plus local context windows (`backend/app/routes/chat.py:569`, `backend/app/routes/chat.py:577`, `backend/app/routes/chat.py:585`, `backend/app/routes/chat.py:594`).
- `search_memories` exists in two runtime surfaces: chat agent and review predictor agent (`backend/app/routes/chat.py:646`, `backend/app/core/review_predictor_agent.py:306`).

### Freshness
- Regeneration overwrites `mini.memory_content` (`backend/app/synthesis/pipeline.py:1536`) and snapshots the prior version in `MiniRevision` (`backend/app/synthesis/pipeline.py:1519`, `backend/app/synthesis/pipeline.py:1523`).
- Evidence ingestion is upsert/hash-aware for evidence rows (`backend/app/synthesis/pipeline.py:305`, `backend/app/synthesis/pipeline.py:307`, `backend/app/synthesis/pipeline.py:309`).
- Memory findings are append-inserted (`backend/app/synthesis/explorers/tools.py:688`) and synthesis reads all `memory:%` findings for the mini without explicit run-window filtering (`backend/app/synthesis/pipeline.py:1251`, `backend/app/synthesis/pipeline.py:1253`). Stale-memory carryover risk is therefore present unless cleanup occurs elsewhere (inferred).

### Granularity
- Memory granularity at runtime is mostly per-snippet text lines, not strongly typed fact objects (`backend/app/synthesis/pipeline.py:1267`, `backend/app/synthesis/pipeline.py:1276`).
- Hierarchy is shallow in runtime memory (`[context] text`), not explicit project->fact->quote trees (`backend/app/synthesis/pipeline.py:1266`, `backend/app/synthesis/pipeline.py:1267`).

### Cross-References
- `save_memory` does not capture evidence IDs or KG node IDs (`backend/app/synthesis/explorers/tools.py:683`, `backend/app/synthesis/explorers/tools.py:692`).
- By contrast, principles and KG edges can carry evidence IDs/provenance (`backend/app/synthesis/explorers/tools.py:952`, `backend/app/synthesis/explorers/tools.py:958`, `backend/app/synthesis/explorers/tools.py:981`).
- Runtime memory blob therefore has weak explicit provenance links, while principles are provenance-aware (current-state split).

### What `memory_assembler.py` Outputs
`assemble_memory()` emits a markdown document with:
- title,
- `## The Core (Soul)` from merged principles,
- `## The Network (Brain)` grouped by node type and connected edges,
- `## The Archives (Episodic)` grouped by canonical memory sections,
- optional behavioral quotes,
- source summary,
- hidden embedded JSON between `GRAPH_DATA_START/END` containing merged `graph` and `principles` (`backend/app/synthesis/memory_assembler.py:278`, `backend/app/synthesis/memory_assembler.py:283`, `backend/app/synthesis/memory_assembler.py:296`, `backend/app/synthesis/memory_assembler.py:343`, `backend/app/synthesis/memory_assembler.py:366`, `backend/app/synthesis/memory_assembler.py:403`).

## 2) Knowledge Graph

### Schema
- Node types are explicit (`skill`, `project`, `concept`, etc.) (`backend/app/models/knowledge.py:11`).
- Relation enum includes reasoning edges requested in scope: `rejects_because`, `prefers_over`, `trades_off` (plus others) (`backend/app/models/knowledge.py:32`, `backend/app/models/knowledge.py:33`, `backend/app/models/knowledge.py:34`).

### Population
- Explorers populate KG through `save_knowledge_node` and `save_knowledge_edge` tools (`backend/app/synthesis/explorers/tools.py:805`, `backend/app/synthesis/explorers/tools.py:846`).
- Those are persisted as `ExplorerFinding` rows (`category="knowledge_node"|"knowledge_edge"`) (`backend/app/synthesis/explorers/tools.py:829`, `backend/app/synthesis/explorers/tools.py:871`).
- Pipeline reconstructs final KG JSON by reading those findings and coercing `RelationType(...)` (`backend/app/synthesis/pipeline.py:502`, `backend/app/synthesis/pipeline.py:527`, `backend/app/synthesis/pipeline.py:532`).

### Storage
- KG is stored as JSON blob in `Mini.knowledge_graph_json` (`backend/app/models/mini.py:66`).
- Also exposed via API `GET /minis/{id}/graph` alongside principles (`backend/app/routes/minis.py:1097`, `backend/app/routes/minis.py:1126`, `backend/app/routes/minis.py:1127`).

### Retrieval at Chat Time
- KG is queryable in chat via `search_knowledge_graph` and `explore_knowledge_graph` tools (`backend/app/routes/chat.py:674`, `backend/app/routes/chat.py:741`, `backend/app/routes/chat.py:960`, `backend/app/routes/chat.py:975`).
- `explore_knowledge_graph` supports `search|path|cluster|neighborhood` traversal (`backend/app/routes/chat.py:996`, `backend/app/core/graph.py:396`, `backend/app/core/graph.py:417`, `backend/app/core/graph.py:422`, `backend/app/core/graph.py:442`).

### Quality of Reasoning Edges
- The schema/tooling can store reasoning edges (`backend/app/models/knowledge.py:32`, `backend/app/synthesis/explorers/tools.py:855`).
- Explorer prompt examples still emphasize taxonomic edges like `USED_IN`/`EXPERT_IN` for connectivity (`backend/app/synthesis/explorers/github_explorer.py:385`, `backend/app/synthesis/explorers/github_explorer.py:386`).
- At HEAD, no repository-level metric enforces reasoning-edge coverage in saved KG (inferred/hypothesis).

### Integration
- KG and principles are used during soul synthesis through chief tools (`get_knowledge_graph`, `get_principles`) (`backend/app/synthesis/chief.py:292`, `backend/app/synthesis/chief.py:1170`, `backend/app/synthesis/chief.py:1183`).
- Chat-time prompt explicitly injects decision frameworks/principles into system prompt, but not a dedicated KG section (`backend/app/synthesis/spirit.py:480`, `backend/app/synthesis/spirit.py:500`).
- So KG is not dead, but it is less first-class than principles in final prompt shaping (inferred).

## 3) Gaps and Failure Modes

- Recency-fixation risk remains: code explicitly shuffles same-confidence findings to counter recency bias, signaling known bias pressure (`backend/app/synthesis/pipeline.py:1258`), but runtime memory is still a flat concatenation without temporal decay weighting (`backend/app/synthesis/pipeline.py:1267`, `backend/app/synthesis/pipeline.py:1276`).
- No-semantic-retrieval is only partially true: semantic retrieval exists but is optional and brittle to deployment/module availability (`backend/app/routes/chat.py:31`, `backend/app/routes/chat.py:611`); fallback is pure keyword overlap (`backend/app/routes/chat.py:577`, `backend/app/routes/chat.py:585`).
- Dead-KG claim is too strong at HEAD: KG has live chat tools and traversal handler (`backend/app/routes/chat.py:975`, `backend/app/core/graph.py:386`), but the default directive path prioritizes memories/evidence/principles and does not require KG usage (`backend/app/routes/chat.py:1161`, `backend/app/routes/chat.py:1175`).
- Memory != identity gap is real: personality/style and knowledge are co-located in one system prompt blob (`backend/app/synthesis/spirit.py:342`, `backend/app/synthesis/spirit.py:406`), and chat consumes that single blob (`backend/app/routes/chat.py:1293`).
- Chunk-and-embed gap is partial: chunking + embedding + pgvector retrieval already exist (`backend/app/synthesis/pipeline.py:189`, `backend/app/synthesis/pipeline.py:259`, `backend/app/routes/chat.py:630`), but retrieval/ranking is still simple (top cosine, no hybrid reranker/temporal weighting/provenance-aware scoring) (`backend/app/routes/chat.py:630`, inferred).

## 4) Improvement Plan (15 Tickets)

### Memory System Tickets

1. `MINI-MEM-01` Scope: Make memory retrieval explicitly hybrid (BM25-like keyword + embedding + provenance boosts) with deterministic ranking output. Effort: M. Files: `backend/app/routes/chat.py`, `backend/app/core/review_predictor_agent.py`, `backend/app/models/embeddings.py`.
2. `MINI-MEM-02` Scope: Introduce structured memory table (`project`, `fact`, `opinion`, `quote_ref`) and stop flattening to only `[ctx] text`. Effort: L. Files: `backend/app/models/evidence.py`, `backend/app/synthesis/pipeline.py`, `backend/alembic/*`.
3. `MINI-MEM-03` Scope: Add replace semantics for `memory:*` findings per pipeline run (soft versioning + active flag) to prevent stale accumulation. Effort: M. Files: `backend/app/synthesis/pipeline.py`, `backend/app/synthesis/explorers/tools.py`, `backend/app/models/evidence.py`.
4. `MINI-MEM-04` Scope: Extend `save_memory` to accept `evidence_ids` and optional `kg_node_ids`; propagate into memory assembly. Effort: M. Files: `backend/app/synthesis/explorers/tools.py`, `backend/app/synthesis/pipeline.py`, `backend/app/models/evidence.py`.
5. `MINI-MEM-05` Scope: Re-activate `assemble_memory` runtime path (or retire it) so there is one canonical memory representation contract. Effort: S. Files: `backend/app/synthesis/pipeline.py`, `backend/app/synthesis/memory_assembler.py`.
6. `MINI-MEM-06` Scope: Add temporal scoring/decay metadata to memory retrieval (recent boosts + long-horizon support bonuses). Effort: M. Files: `backend/app/routes/chat.py`, `backend/app/synthesis/explorers/tools.py`, `backend/app/models/evidence.py`.

### Knowledge Graph Tickets

7. `MINI-KG-01` Scope: Add a first-class `query_graph` tool with typed filters (`node_type`, `relation`, `min_weight`, `hops`) and machine-parseable results. Effort: M. Files: `backend/app/core/graph.py`, `backend/app/routes/chat.py`.
8. `MINI-KG-02` Scope: Add KG edge coverage QA (reasoning-edge ratio + per-source edge-type distribution). Effort: S. Files: `backend/app/synthesis/pipeline.py`, `backend/app/synthesis/explorers/*`, `backend/tests/test_graph.py`.
9. `MINI-KG-03` Scope: Strengthen explorer prompts/tool docs to require reasoning edges where evidence supports them (`rejects_because`, `prefers_over`, `trades_off`). Effort: S. Files: `backend/app/synthesis/explorers/github_explorer.py`, `backend/app/synthesis/explorers/repo_agent.py`, `backend/app/synthesis/explorers/tools.py`.
10. `MINI-KG-04` Scope: Inject compact KG-derived neighborhood summaries into system prompt (top connected concepts per topic). Effort: M. Files: `backend/app/synthesis/spirit.py`, `backend/app/synthesis/pipeline.py`, `backend/app/core/graph.py`.
11. `MINI-KG-05` Scope: Add debugging/visualization endpoint returning graph stats, centrality, disconnected components, orphan nodes. Effort: S. Files: `backend/app/routes/minis.py`, `backend/app/core/graph.py`.

### Integration Tickets

12. `MINI-INT-01` Scope: Build joined retrieval call for “what does subject think about X” that combines memory hits + principle hits + KG-neighborhood expansion before response. Effort: L. Files: `backend/app/routes/chat.py`, `backend/app/core/graph.py`, `backend/app/synthesis/framework_views.py`.
13. `MINI-INT-02` Scope: Make tool-use policy explicitly include KG tools for conceptual questions and architecture-tradeoff prompts. Effort: S. Files: `backend/app/routes/chat.py`, `backend/app/synthesis/spirit.py`.
14. `MINI-INT-03` Scope: Add provenance-aware answer scaffolding so outputs cite evidence IDs/source dates from memory/principles/KG traversals. Effort: M. Files: `backend/app/routes/chat.py`, `backend/app/synthesis/explorers/tools.py`, `backend/app/models/evidence.py`.
15. `MINI-INT-04` Scope: Add retrieval evaluation harness slices (memory-only vs memory+KG vs memory+KG+principles) to measure fidelity uplift. Effort: M. Files: `backend/eval/*`, `backend/scripts/run_fidelity_eval.py`, `backend/tests/test_chat.py`.

## Top 5 Highest-Leverage Tickets

1. `MINI-INT-01`: Highest direct fidelity gain because it replaces single-channel recall with joined reasoning context.
2. `MINI-MEM-03`: Prevents stale-memory pollution and improves prediction recency/trust.
3. `MINI-KG-03`: Converts KG from taxonomy-heavy to decision-reasoning-rich graph signal.
4. `MINI-MEM-04`: Adds hard provenance links from memory facts to evidence/KG, improving auditability.
5. `MINI-MEM-01`: Establishes robust retrieval ranking instead of opportunistic keyword fallback.
