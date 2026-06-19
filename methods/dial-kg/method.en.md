# DIAL-KG — Schema-Free Incremental KG Construction with Governance & Schema Evolution

> Source: Bao, Wang, Gao, Leng, Bao, Yu, *DIAL-KG: Schema-Free Incremental Knowledge Graph Construction via Dynamic Schema Induction and Evolution-Intent Assessment*, arXiv:2603.20059 (2026). Code: not public.

## 1. One-line summary
A **closed-loop** incremental builder: for each arriving document, a **dual-track extractor** proposes entities/relations, a **governance adjudicator** merges them into the accumulated graph against a **Meta-Knowledge Base** (resolving duplicates/conflicts), and a **schema-evolution** step induces and **extends entity types** as new kinds of things appear — all with **no predefined schema**.

## 2. Key ideas
- **Schema-free & incremental**: documents are processed one at a time; nothing about the schema is fixed in advance.
- **Meta-Knowledge Base (Meta-KB)**: a registry of what already exists (canonical entity classes + induced types) that orchestrates the loop and is the reference for every governance decision.
- **Governance adjudication** (vs. plain de-dup): the merge step *records decisions* — singular/plural/case variants are merged to the existing canonical class, and duplicate/reverse edges are dropped. Each step reports what was merged and what was dropped (and why).
- **Dynamic schema evolution** (vs. one-shot induction): each new entity is mapped to an induced **type** (Device / Material / System / Process / Entity). When a type first appears, the step marks it as **evolved**, so the schema visibly **grows as documents arrive**.

### How it differs from siblings in this library
| Method | Incremental? | Schema induced? | Governance log? |
|--------|:---:|:---:|:---:|
| iText2KG | yes (with semantic de-dup) | no (schema-free, no types) | no |
| AutoSchemaKG | no (one-shot over a corpus) | yes (bottom-up) | no |
| **DIAL-KG** | **yes** | **yes, and it evolves per document** | **yes (merged/dropped recorded)** |

## 3. Construction process (closed loop per document)
1. **Collect documents** — `text.txt` with several documents (blank-line separated). One document = one incremental unit.
2. **Dual-track extraction** — extract entities (entity track) and relations (relation track). MOCK uses two deterministic tracks; a real backend uses the shared triple extractor.
3. **Governance adjudication** — merge into the accumulated graph against the Meta-KB: map variant entities to existing canonical classes, drop duplicate/reverse edges, and record every decision.
4. **Schema evolution** — induce a type for each new entity; first-time types are marked `evolved` and an `instanceOf` edge links the entity to its type node.
5. **Per-document snapshot** — one step per document (plus a final `(schema) Meta-KB` step) so the UI can replay the graph and schema growing.
6. **Emit** — `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Several documents (blank-line separated; one doc = one increment) |
| Output | `ontology.ttl` | OWL (Turtle): induced types `owl:Class`, entity classes `rdfs:subClassOf` their type, object properties with domain/range |
| Output | `ontology.json` | Cytoscape nodes/edges (type & entity nodes, relation + `instanceOf` edges) |
| Output | `steps.json` | Per-document snapshots with `governance` + `schema_types` — for step replay |

## 5. LLM backend
- Default `mock`: deterministic, no key. Entity track = capitalized nouns; relation track = relation-verb patterns; governance de-dups against the Meta-KB; schema evolution uses a keyword/suffix type rule.
- `gemini`/`anthropic` (api): with a key a real LLM performs dual-track extraction; the same governance + schema-evolution loop then runs. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/text.txt` with your own document set (blank-line separated). Reuse an entity across documents to see governance merge variants, and introduce different kinds of things to watch the schema evolve.
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch documents added one by one: variants merge, edges are governed, and induced types appear as the schema grows.
