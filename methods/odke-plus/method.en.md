# ODKE+ — Ontology-Guided 5-Stage Open-Domain Extraction

> Source: Khorshidi, Nikfarjam et al. (Apple), *ODKE+: Ontology-Guided Open-Domain Knowledge Extraction with LLMs*, 2025 (arXiv:2509.04696).

## 1. One-line summary
A **5-stage production pipeline** (extraction initiator → evidence retriever → hybrid extractor → grounder (2nd LLM verify) → corroborator) that **dynamically generates ontology snippets** per entity type to align with schema constraints while auto-extracting and loading facts.

## 2. Key ideas
- **Five components**: (1) **Extraction Initiator** (detect missing/stale facts), (2) **Evidence Retriever** (collect supporting docs), (3) **Hybrid Extractor** (rules + ontology-guided LLM prompts), (4) **Grounder** (a 2nd LLM verifies extracted facts), (5) **Corroborator** (rank/normalize candidates).
- **Dynamic ontology snippets**: generate the schema fragment each entity type needs, on the fly, to constrain extraction.
- **Generation–verification separation**: separate extraction LLM and verification LLM to raise precision (paper: 19M facts, 98.8% precision).

## 3. Construction process (step by step)
1. **Collect inputs** — `entities.txt` (entities to extract for) and evidence text (`samples/evidence.txt`, optional).
2. **Extraction initiation** — decide which property slots (ontology snippet) to fill for each entity.
3. **Evidence retrieval** — gather supporting sentences per entity.
4. **Hybrid extraction** — pull candidate facts (triples) with rules + (ontology-guided) LLM.
5. **Grounder verification** — a second pass checks each candidate against the evidence; failures are dropped.
6. **Corroborator** — rank/normalize verified candidates and load into the final graph.
7. **Emit** — per-stage snapshots and `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `entities.txt` | Entities to extract for (one per line) |
| Input | `evidence.txt` | Evidence text (optional) |
| Output | `ontology.ttl` | OWL of verified facts (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (verified only) |
| Output | `steps.json` | 5-stage snapshots (pass/fail of verification) |

## 5. LLM backend
- Default `mock`: deterministic, no key. Extraction uses the cqbycq heuristic; Grounder verification passes a candidate by the rule "do subject and object co-occur in the evidence text" (unmet candidates are dropped).
- `gemini`/`anthropic` (api): with a key an extraction LLM + a separate verification LLM are used. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/entities.txt` (and optionally `samples/evidence.txt`).
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to follow initiate→retrieve→extract→verify→corroborate and see dropped candidates.
