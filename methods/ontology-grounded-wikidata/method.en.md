# Ontology-Grounded KG (under Wikidata schema)

> Source: *Ontology-grounded Automatic Knowledge Graph Construction by LLM under Wikidata schema*, 2024 (arXiv:2412.20942).

## 1. One-line summary
Author an ontology from **Competency Questions (CQs)**, then **ground** its classes/relations to **Wikidata's standard schema (P-id properties)**, producing an externally-compatible ontology with minimal human intervention.

## 2. Key ideas
- **CQ-based authoring**: like CQbyCQ, draft classes/relations from CQs.
- **Wikidata grounding**: map locally-invented relation names (e.g. `consistsOf`) to standard Wikidata properties (e.g. `P527 has part`), making the KG compatible with the global public KG.
- **Minimal human intervention**: automate the mapping/alignment to reduce manual work.

## 3. Construction process (step by step)
1. **Collect CQs** — `competency_questions.txt`.
2. **Ontology authoring** — draft classes/object-properties from CQs (cqbycq style).
3. **Wikidata grounding** — map each class/relation to a Wikidata label/property (deterministic dictionary-based mapping; keep the local name if no match).
4. **Merge & emit** — annotate nodes/edges with Wikidata ids per grounding; write per-step snapshots and `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `competency_questions.txt` | CQ list |
| Output | `ontology.ttl` | OWL aligned to Wikidata properties (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (with Wikidata id annotations) |
| Output | `steps.json` | Authoring/grounding step snapshots |

## 5. LLM backend
- Default `mock`: deterministic, no key. Authoring uses the cqbycq heuristic; grounding uses a small built-in dictionary (e.g. has part→P527, made from material→P186, manufacturer→P176).
- `gemini`/`anthropic` (api): with a key a real LLM does authoring/grounding. With no key it auto-falls back to MOCK.
- Note: this implementation demonstrates grounding via a built-in dictionary instead of calling the live Wikidata API (offline, deterministic). Real Wikidata lookups can be added with network/key integration.

## 6. Try it
1. Edit `samples/competency_questions.txt`.
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to see authoring → Wikidata grounding and the mapped property ids.
