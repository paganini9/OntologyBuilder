# KARMA — Multi-Agent LLM KG Enrichment

> Source: Lu, Wu, Zhao, Peng, Wang, *KARMA: Leveraging Multi-Agent LLMs for Automated Knowledge Graph Enrichment*, NeurIPS 2025 Spotlight.

## 1. One-line summary
**Multiple dedicated agents** (entity discovery, relation extraction, schema alignment, conflict resolution, …) divide the labor to iteratively parse, verify and integrate unstructured text and **automatically enrich an existing KG**.

## 2. Key ideas
- **Enrichment**: not built from scratch — **adds new knowledge to an existing KG**.
- **Agent division of labor**: core roles — (a) **entity discovery**, (b) **relation extraction**, (c) **schema alignment** (match to existing classes/properties), (d) **conflict resolution** (drop/merge contradictory edges). The paper uses 9 collaborative agents, yielding 38,230 new entities on PubMed, 83.1% verified accuracy, −18.6% conflicting edges.
- **Iterative verification**: each agent's output is verified/refined by the next.

## 3. Construction process (step by step)
1. **Collect inputs** — `seed_kg.ttl` (existing KG, optional) and `text.txt` (unstructured text to enrich from).
2. **Entity discovery** — find new entity candidates in the text.
3. **Relation extraction** — extract relations between entity pairs.
4. **Schema alignment** — map new entities/relations to existing KG classes/properties (create new if none).
5. **Conflict resolution** — clean up edges contradicting or duplicating the existing KG.
6. **Merge & emit** — per-stage (discover→extract→align→resolve) snapshots and `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Unstructured text to enrich from |
| Input | `seed_kg.ttl` | Existing KG (optional; start from empty if absent) |
| Output | `ontology.ttl` | Enriched OWL (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (seed vs new distinguished) |
| Output | `steps.json` | Per-agent-stage snapshots |

## 5. LLM backend
- Default `mock`: deterministic, no key. Discovery/extraction use the cqbycq heuristic; alignment matches names against existing KG nodes (singular/plural, case); conflict resolution drops duplicate/reverse edges by rule.
- `gemini`/`anthropic` (api): with a key a real LLM plays each agent role. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/text.txt` (and optionally `samples/seed_kg.ttl`) with your own.
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch the KG enriched via discover→extract→align→resolve.
