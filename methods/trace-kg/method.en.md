# TRACE-KG — Text-driven schema, context-enriched KG

> Source: *Beyond Predefined Schemas: TRACE-KG for Context-Enriched Knowledge Graphs from Complex Documents* (**TRACE-KG**, Text-dRiven schemA), arXiv:2604.03496 (Arizona State University).

## 1. One-line summary
Build a knowledge graph **without a predefined ontology**: jointly induce a **data-driven schema** straight from the text, attach **conditional qualifiers** to relations, and keep **full traceability** of every edge back to its source sentence.

## 2. Key ideas
- **Beyond predefined schemas**: ontology-driven pipelines need a hand-built schema; schema-free extraction yields fragmented graphs. TRACE-KG sits in between — the schema scaffold is *induced from the text itself* (here, surfaced from explicit is-a cues), so it stays a reusable semantic backbone without up-front ontology design.
- **Context-enriched relations**: real documents state facts that only hold *under a condition*. TRACE-KG captures those conditions as **qualifiers** on the relation (e.g. `Pump consistsOf Impeller [Pressure]`), preserving context that flat triples drop.
- **Traceability**: every node and edge records the **source sentence index** (`provenance`), so the graph can always be traced back to the evidence.

## 3. Construction process (step by step)
1. **Read text** — free body text in `text.txt`, split into sentences (`#` comment lines ignored).
2. **Per-sentence classification** — the LLM (or the MOCK heuristic) tags each sentence as either:
   - an **is-a fact** → `subClassOf(child, parent)`, growing the induced schema scaffold; or
   - a **relation** `(subject, relation, object)` with an optional **qualifier** lifted from a `when / if / during / under / while` clause.
   A snapshot is emitted per sentence so the UI can replay the build.
3. **Accumulate** — classes, qualified relations, and subClassOf edges are merged in insertion order (deterministic). Every edge carries its `qualifier` (possibly empty) and `provenance` (source sentence).
4. **Emit** — `ontology.ttl` (classes as `owl:Class`, relations as `owl:ObjectProperty` with domain/range, hierarchy as `rdfs:subClassOf`), `ontology.json` (graph; edge labels show `relation [qualifier]`), `steps.json` (per-step snapshots).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | free text (split into sentences by `.` `!` `?`) |
| Output | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty` (domain/range), `rdfs:subClassOf` |
| Output | `ontology.json` | graph; relation edges carry `qualifier` + `provenance` in edge data |
| Output | `steps.json` | per-step snapshots — for step replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable golden files). is-a cues build the schema scaffold; `when/if/during/...` clauses become qualifiers.
- `gemini`/`anthropic`/`hf_local`: with a key/model a real LLM extracts the relations (qualifier left empty on the real path); the merge/emit logic is identical so the graph shape stays stable. With no key it auto-falls back to MOCK.
- Note: the published TRACE-KG is framed as multimodal; this implementation keeps the **text-driven schema + qualifiers + traceability** core and runs key-free and reproducibly.

## 6. Try it
1. Edit `samples/text.txt` — mix is-a sentences (`A Pump is a kind of Machine.`) with conditional relations (`The Pump consists of an Impeller when the Pressure is high.`).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch the schema scaffold and qualified relations appear; hover an edge to see its qualifier and source.
