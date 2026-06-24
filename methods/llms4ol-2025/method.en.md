# LLMs4OL 2025 — Modular ontology learning (term → type → taxonomy)

> Source: *Alexbek at LLMs4OL 2025 Tasks A, B, and C: Heterogeneous LLM Methods for Ontology Learning* (Few-Shot Prompting, Ensemble Typing, Attention-Based Taxonomies), arXiv:2508.19428. Code: github.com/BelyaevaAlex/LLMs4OL-Challenge-Alexbek.

## 1. One-line summary
A single, **modular** pipeline that covers the whole ontology-learning loop of the LLMs4OL challenge: **extract** terms and their types from text (Task A), **type** previously unseen terms by **retrieval** (Task B), and **induce the is-a taxonomy** over the types (Task C) — lightweight, with no full fine-tuning.

## 2. Key ideas
- **Three subtasks, one pipeline**: rather than a monolith, ontology learning is decomposed into Text2Onto (A), term typing (B), and taxonomy discovery (C) — each a small, swappable module that shares the same growing ontology.
- **Retrieval-augmented term typing (the standout)**: an unseen term is typed by finding its **nearest already-typed example** and copying that type — the paper uses embedding cosine + a confidence-weighted ensemble; here a deterministic **shared-token / char-trigram** match is a faithful, key-free stand-in. So `axial pump` is typed `Pump` because its nearest typed neighbour is `centrifugal pump`.
- **Taxonomy as is-a induction**: the type hierarchy (`Pump ⊑ Machine`) is induced from is-a cues, giving the reusable backbone the typed terms hang from.

## 3. Construction process (step by step)
1. **Read & route** — `documents.txt`; each clue is routed by its surface form: `"<a/an term> is a/an <Type>"` → Task A; `"<Type> is a kind of <Parent>"` → Task C; `"? <term>"` → Task B.
2. **Task A — Text2Onto** — for each A clue the LLM (or the MOCK heuristic) returns a `(term, Type)` pair; the Type becomes a class, the term an individual `instanceOf` that class. These pairs become the **retrieval bank**.
3. **Task C — Taxonomy Discovery** — each C clue adds a `subClassOf(Type, Parent)` edge, growing the hierarchy (parents are created on demand).
4. **Task B — Term Typing** — each unseen `? term` is matched against the retrieval bank (max shared tokens, then trigram overlap; ties → earliest example) and typed accordingly; the edge is marked inferred and records the neighbour it was matched against.
5. **Emit** — `ontology.ttl` (types as `owl:Class`, hierarchy as `rdfs:subClassOf`, terms as `owl:NamedIndividual` `rdf:type`'d to their class), `ontology.json` (type + term nodes; `subClassOf` and `instanceOf` edges; inferred typings labelled `instanceOf*`), `steps.json` (one snapshot per clue, in A → C → B order).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `documents.txt` | A/`is a`, C/`is a kind of`, B/`? term` clues |
| Output | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, typed `owl:NamedIndividual` |
| Output | `ontology.json` | type + term nodes; `subClassOf` + `instanceOf` edges (inferred → `instanceOf*`, with `via`) |
| Output | `steps.json` | per-clue snapshots in Task A → C → B order |

## 5. LLM backend
- Default `mock`: deterministic, key-free (stable golden files). Task A extraction is a heuristic parse; Task B retrieval and Task C taxonomy are rule-based — so the graph is reproducible.
- `gemini` / `anthropic` / `hf_local`: a real model performs the Task A `(term, type)` extraction; retrieval (B) and taxonomy (C) stay deterministic, so the shape stays stable. With no key it auto-falls back to MOCK.
- Note: the published system also trains a small cross-attention layer (with LoRA) for taxonomy and an embedding ensemble for typing; this implementation keeps the **three-subtask structure + retrieval typing + is-a induction** core and runs key-free and reproducibly, with no GPU or fine-tuning.

## 6. Try it
1. Edit `samples/documents.txt` — add typed examples (`A gear pump is a Pump.`), is-a edges (`Pump is a kind of Machine.`), and unseen queries (`? rotary pump`).
2. Hit **Run** (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch Task A extraction, then Task C taxonomy, then Task B retrieval-typing; hover an `instanceOf*` edge to see which neighbour it was typed from.
