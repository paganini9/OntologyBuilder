# LLM External Ontology Memory — heterogeneous ingestion + SHACL/OWL generation-verification-correction

> Source: *Automatic Ontology Construction Using LLMs as an External Layer of Memory, Verification, and Planning for Hybrid Intelligent Systems*, arXiv:2604.20795.

## 1. One-line summary
An automated pipeline that merges **heterogeneous sources (documents, APIs, dialogue logs)** into one RDF/OWL **ontological memory layer**. It runs entity recognition → relation extraction → normalization → triple generation, then **validates with SHACL/OWL constraints** in a *generation-verification-correction* loop (repairing what it can, e.g. normalizing a non-ISO date to `xsd:date`) and applies **continuous graph updates**.

## 2. Key ideas
- **Heterogeneous ingestion.** Dispatch on source type: `document`/`dialogue` run NER/RE over text, `api` maps record fields straight to triples. Every entity keeps source provenance.
- **External ontological memory.** Rather than relying only on parametric knowledge and vector retrieval (RAG), a separate, verifiable structured KG (RDF/OWL) is maintained as a memory layer.
- **Generation-verification-correction (three outcomes).** Unlike a reject-only validator, the SHACL/OWL check yields **three** outcomes — *accept*, *correct* (a fixable violation is repaired: a non-ISO date → `xsd:date`), or *reject* (an unfixable violation: a `worksIn` value that is not a Department (sh:class), an e-mail with no `@` (sh:pattern)).
- **Normalization + continuous updates.** Surface mentions normalize to canonical entities ("Eng" / "Engineering" → one Department node), and sources are processed in order, validating against the accumulated graph (because the api source recognized Bob as a Person, the later dialogue "Carol works in Bob" is rejected by sh:class).

## 3. Construction process (step by step)
1. **Read sources** — `sources.json` (list of `{id, type, content}`; content is text, a record, or a list of utterances).
2. **Heterogeneous ingestion + NER/RE** — type-aware dispatch extracts `(subject, property, value)` facts.
3. **Normalization** — surface → canonical entity (department aliases merged); a mention resolving to an existing entity inherits its type.
4. **Generation-verification-correction** — object properties checked with sh:class, data properties with datatype / sh:pattern; correct when fixable then accept, otherwise reject (audit log).
5. **Emit** — `ontology.ttl` (classes + object/datatype properties + validated ABox), `ontology.json` (Cytoscape; entity nodes carry provenance + accepted data attributes), `steps.json` (one snapshot per source).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `sources.json` | `{"sources":[{"id","type":"document|api|dialogue","content":...}]}` |
| Output | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`/`owl:DatatypeProperty`, typed individuals + literals |
| Output | `ontology.json` | graph; entity nodes carry `provenance` + data attributes, `worksIn` edges |
| Output | `steps.json` | per-source snapshots — for continuous-update replay |

## 5. LLM backend
- Default `mock`: rule-based NER/RE + deterministic normalization / validation / correction — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM can replace NER/RE on text sources, while normalization, validation, and correction stay deterministic. With no key it auto-falls back to MOCK.
- Scope note: the paper's inference-time planning use (e.g. Tower of Hanoi) is out of scope for this demo, which focuses on the **construction + validation layer**.

## 6. Try it
1. In `samples/sources.json`, watch the `document`, `api`, and `dialogue` sources merge into one graph.
2. Put a non-ISO date like `2019/12/01` in `joinedOn` to see it **corrected** (`manifest.corrected`), and an e-mail with no `@` to see it **rejected** (`manifest.rejected`).
3. Set a `worksIn` value to a person's name instead of a department to see the **sh:class** rejection.
4. Run it: `python pipeline.py samples runs/out --backend mock` (or hit the site's **Run** button).
