# OLLM — End-to-End Ontology Learning (the taxonomic backbone)

> Source: Lo, Jiang, Li, Jamnik, *End-to-End Ontology Learning with Large Language Models* (**OLLM**), arXiv:2410.23584. Code: https://github.com/andylolu2/ollm

## 1. One-line summary
Learn the **taxonomic backbone** of an ontology — the `rdfs:subClassOf` (is-a) hierarchy of concepts — **end-to-end** from raw text, instead of mining flat (subject, relation, object) triples.

## 2. Key ideas
- **Taxonomy / backbone**: the skeleton of an ontology is its is-a tree (e.g. `ElectricMotor ⊑ Motor ⊑ Component`). OLLM targets this backbone directly rather than as a by-product of relation extraction.
- **End-to-end**: the original paper *fine-tunes* an LLM to emit the hierarchy in one pass (with custom regularisation against over-fitting to leaf nodes), so the model learns the structure, not just local edges. This makes OLLM distinct from triple/relation-extraction methods (CQbyCQ, "Are LLMs Effective KGC").
- **subClassOf-first**: every concept ends up as an `owl:Class`, connected to a single rooted tree via `rdfs:subClassOf`.

## 3. Construction process (step by step)
1. **Read text** — free body text in `text.txt`, split into sentences.
2. **Concept extraction (per sentence)** — the LLM (or the MOCK heuristic) surfaces the core concepts as PascalCase class names. We keep the *concept set* only; relation kinds are not needed for the backbone. A snapshot is emitted per sentence: `cq = "(concepts) <sentence>"`.
3. **Taxonomy induction** — the `subClassOf` backbone is built deterministically over the accumulated concepts:
   - **Compound-tail rule**: a concept whose name ends with another known concept becomes its child — `ElectricMotor` ⊑ `Motor`, `CoolantPump` ⊑ `Pump`, `TemperatureSensor` ⊑ `Sensor` (each child attaches to its longest / most specific matching parent).
   - **Root attachment**: every remaining top-level concept is attached to a synthetic root `Entity`, yielding one connected taxonomy tree.
   One snapshot is emitted: `cq = "(taxonomy) induce hierarchy"`.
4. **Emit** — `ontology.ttl` (concepts as `owl:Class`, hierarchy as `rdfs:subClassOf`), `ontology.json` (the taxonomy graph), `steps.json` (per-step snapshots).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | free text (split into sentences by `.` `!` `?`) |
| Output | `ontology.ttl` | OWL: `owl:Class` + `rdfs:subClassOf` (Turtle) |
| Output | `ontology.json` | taxonomy graph (nodes = classes, edges = subClassOf child→parent) |
| Output | `steps.json` | per-step snapshots — for step replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable test golden files). Capitalized nouns become concepts; the subClassOf backbone is induced by the compound-tail + root rules.
- `gemini`/`anthropic`: with a key in the env, a real LLM surfaces richer concepts; the taxonomy induction is identical (deterministic) so the backbone stays stable. With no key it auto-falls back to MOCK.
- Note: the published OLLM additionally *fine-tunes* a model to generate the hierarchy. This implementation keeps the **end-to-end taxonomy objective** but uses deterministic induction so it runs key-free and reproducibly.

## 6. Try it
1. Edit `samples/text.txt` (include both a base concept and a compound, e.g. `Motor` + `ElectricMotor`, to get real subClassOf links).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch concepts appear, then snap into the is-a hierarchy.
