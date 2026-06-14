# Hierarchical Extraction (Are LLMs Effective KG Constructors?)

> Source: *Are Large Language Models Effective Knowledge Graph Constructors?*, 2025 (arXiv:2510.11297).

## 1. One-line summary
Extract knowledge from text **hierarchically and in multiple levels** — first entities (concepts), then relations among them, finally the super/sub-class hierarchy — to build an ontology, while offering a systematic view of LLMs' KG-construction limits.

## 2. Key ideas
- **Hierarchical extraction**: rather than extracting triples in one shot, split by **level** — (L1) core entities/concepts, (L2) relations between entities, (L3) concept hierarchy (super/sub, is-a).
- **Multi-level refinement**: each level takes the previous level's output as input and progressively grows the structure.
- **Systematic evaluation view**: check coverage/consistency of the extraction per level (the paper quantifies LLM KGC limits).

## 3. Construction process (step by step)
1. **Collect text** — `text.txt` free body.
2. **L1 entity extraction** — extract core concepts (capitalized nouns, etc.) as class candidates.
3. **L2 relation extraction** — extract relations (object properties) between extracted entity pairs.
4. **L3 hierarchy** — infer is-a / super-sub relations to build a class hierarchy (subClassOf).
5. **Merge & emit** — a snapshot per level shows structure forming as "entities → relations → hierarchy"; write `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Free body text |
| Output | `ontology.ttl` | OWL with hierarchy (subClassOf) (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges |
| Output | `steps.json` | Per-level (L1/L2/L3) snapshots |

## 5. LLM backend
- Default `mock`: deterministic, no key. L1 extracts capitalized nouns, L2 uses relation-verb patterns, L3 infers is-a by rules (e.g. head-noun of a compound as super-class).
- `gemini`/`anthropic` (api): with a key a real LLM does per-level extraction. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/text.txt` with your own document.
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch the graph and hierarchy form in L1→L2→L3 order.
