# LKD-KGC — domain-specific KG construction via knowledge-dependency parsing

> Source: *LKD-KGC: Domain-Specific KG Construction via LLM-driven Knowledge Dependency Parsing*, arXiv:2505.24163, Sun et al., submitted to EDBT 2026.

## 1. One-line summary
Build a domain knowledge graph **without a predefined schema and without an external reference KB**: infer the *knowledge dependencies* between documents, read them in dependency order, autoregressively grow an entity-type schema (clustering synonymous labels), and let that induced schema guide entity/relation extraction.

## 2. Key ideas
- **Documents are not independent.** Schema-guided KGC usually processes each document in isolation, but a domain corpus has structure: a "Sensors" note is a prerequisite for the "Operating Procedure" note that cites it. LKD-KGC makes that ordering explicit.
- **Knowledge-dependency parsing.** A directed dependency graph is inferred over the corpus — document *A depends on B* when A's text references B (here: mentions B's title). Cycles are broken deterministically so the result is a DAG.
- **Read-order prioritisation.** A topological sort of the dependency DAG yields the processing order, so foundational documents are read before the documents that build on them (the paper's "LLM-driven prioritisation").
- **Autoregressive schema induction.** Reading in order, each document contributes entity-type *candidates*; these are canonicalised and **clustered** (singularisation + synonym collapse) so `Sensors`/`Sensor` and `Protocol`/`Procedure` land on one schema class. Inter-document context accumulates — later documents extend, not reset, the schema.
- **Schema-guided, unsupervised extraction.** Entities and relations are emitted only for the canonical schema induced so far — no hand-written schema, no public-domain reference KB.

## 3. Construction process (step by step)
1. **Read corpus** — `corpus.json` (`domain`, list of `documents` with `id`, `title`, `text`).
2. **Parse dependencies** — add edge `B → A` whenever `title(B)` occurs in `text(A)`; break cycles (lower id wins) to guarantee a DAG.
3. **Prioritise read order** — Kahn topological sort with id tie-break.
4. **Induce schema autoregressively** — for each document in read order, pull type candidates, canonicalise + cluster them into schema classes (subclasses of `DomainEntity`), accumulating across documents.
5. **Schema-guided extraction** — within each document, type the mentions that match the induced schema and connect entity pairs sharing a sentence + relation verb.
6. **Emit** — `ontology.ttl` (OWL classes + `owl:ObjectProperty` + typed individuals), `ontology.json` (Cytoscape; instance nodes carry `provenance` = source doc), `steps.json` (one snapshot per document — the UI replays schema growth).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `corpus.json` | `{"domain":..., "documents":[{"id","title","text"}, ...]}` |
| Output | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf DomainEntity`, `owl:ObjectProperty`, typed individuals |
| Output | `ontology.json` | graph; instance nodes carry `cls` + `provenance` (source doc) |
| Output | `steps.json` | per-document snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic type-candidate extraction from a lexicon + deterministic clustering — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM proposes type candidates per document; dependency parsing, read order, clustering and extraction stay deterministic, so the graph shape is stable. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/corpus.json` — add a document whose text mentions an existing document's **title** to create a new dependency edge, and watch the read order change.
2. Introduce a synonym (e.g. another plural, or a label that aliases onto an existing class) to see clustering collapse it into one schema class.
3. Run it: `python pipeline.py samples runs/out --backend mock` (or hit the site's **Run** button).
4. The manifest's `read_order`, `dependency_edges`, and `raw_type_candidates` vs `canonical_classes` are the per-run telemetry for the method's two distinctive moves.
