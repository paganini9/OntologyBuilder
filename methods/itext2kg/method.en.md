# iText2KG — Incremental Zero-Shot Knowledge Graph Construction

> Source: Lairgi, Moncla, Cazabet, Benabdeslem, Cléau, *iText2KG: Incremental Knowledge Graphs Construction Using Large Language Models*, WISE 2024 (arXiv:2409.03284). Code: github.com/AuvaLab/itext2kg.

## 1. One-line summary
Process multiple documents **incrementally, one at a time** through four modules — **Document Distiller → Incremental Entity Extractor → Incremental Relation Extractor → Graph Integrator** — growing a knowledge graph with semantic de-duplication and no predefined schema or post-processing.

## 2. Key ideas
- **Incremental construction**: documents are processed **sequentially**, each added to the accumulated graph; a new document's entities/relations are **semantically matched against existing ones** to avoid duplicates.
- **Document Distiller**: refine raw text into **semantic blocks** suited for extraction (summarize/normalize).
- **Incremental entity/relation extractors**: extract entities, then relations, while **referencing the global entity set** so the same thing collapses to one node (zero-shot).
- **Graph Integrator**: integrate results into the accumulated graph and visualize.

## 3. Construction process (step by step)
1. **Collect documents** — `text.txt` with several documents (blank-line separated). One document = one incremental unit.
2. **Distill** — refine each document into semantic blocks (MOCK: whitespace/sentence normalization).
3. **Incremental entity extraction** — extract entities (capitalized nouns) and **semantically match** against accumulated entities (singular/plural, case) to merge duplicates.
4. **Incremental relation extraction** — extract relations (object properties) between entity pairs and accumulate.
5. **Graph integration** — merge new nodes/edges; drop duplicate edges. A **snapshot per document** shows the incremental growth "as documents are added".
6. **Emit** — `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Several documents (blank-line separated; one doc = one increment) |
| Output | `ontology.ttl` | OWL (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges |
| Output | `steps.json` | Per-document incremental snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic, no key. Distill normalizes text; entities are capitalized nouns with accumulated semantic de-dup; relations use relation-verb patterns.
- `gemini`/`anthropic` (api): with a key a real LLM runs the four modules for richer distillation/extraction/dedup. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/text.txt` with your own document set (blank-line separated).
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch documents added one by one and the graph grow without duplicates.
