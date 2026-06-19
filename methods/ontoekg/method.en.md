# OntoEKG — Two-phase ontology construction for enterprise knowledge graphs

> Source: Oyewale & Soru, *LLM-Driven Ontology Construction for Enterprise Knowledge Graphs* (**OntoEKG**), arXiv:2602.01276 (2026).

## 1. One-line summary
Build an enterprise OWL ontology in **two phases**: an **EXTRACTION** module that surfaces both the core **classes** and the **object properties** from text, then an **ENTAILMENT** module that logically structures those classes into a `rdfs:subClassOf` hierarchy before RDF serialization.

## 2. Key ideas
- **Two modules, one pipeline**: Phase A (extraction) reads enterprise text and produces a flat set of concepts plus the relations that connect them; Phase B (entailment) reasons over the concept set to derive an is-a hierarchy and serializes the whole thing to RDF/OWL.
- **Both classes AND object properties**: this is the key difference from OLLM, which targets the taxonomy backbone *only*. OntoEKG keeps the relational edges (object properties with domain/range) **and** adds an entailment hierarchy on top, so the final graph has two kinds of edges.
- **Enterprise focus**: the method is aimed at enterprise knowledge graphs — product lines, equipment, org structures — where both relations between entities and a clean class hierarchy matter for downstream querying and integration.
- **Entailment-as-structuring**: the hierarchy is not extracted sentence-by-sentence; it is *entailed* deterministically over the accumulated class set, giving a single connected, reproducible backbone.

## 3. Construction process (step by step)
1. **Read text** — enterprise free text in `text.txt`, split into sentences.
2. **Phase A — EXTRACTION (per sentence)** — the LLM (or the MOCK heuristic) surfaces the core **classes** (PascalCase concepts) and the **object properties** (relations `{name, domain, range}`) between them. A snapshot is emitted per sentence: `cq = "(extract) <sentence>"`. On a real backend the shared triple extractor maps each `(subject, relation, object)` triple to two classes + one object property.
3. **Phase B — ENTAILMENT** — over the accumulated classes the `subClassOf` hierarchy is structured deterministically:
   - **Compound-tail rule**: a class whose name ends with another known class is entailed as its subclass — `ElectricMotor` ⊑ `Motor`, `CoolantPump` ⊑ `Pump` (each child attaches to its longest / most specific matching parent).
   - **Root attachment**: every remaining top-level class is attached to a synthetic root `Entity`, giving one connected hierarchy.
   One snapshot is emitted: `cq = "(entail) hierarchy"`.
4. **Emit** — `ontology.ttl` (classes as `owl:Class`, relations as `owl:ObjectProperty` + domain/range, hierarchy as `rdfs:subClassOf`), `ontology.json` (the combined graph: object-property edges + is-a edges), `steps.json` (per-step snapshots).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | enterprise free text (split into sentences by `.` `!` `?`) |
| Output | `ontology.ttl` | OWL: `owl:Class` + `owl:ObjectProperty` (domain/range) + `rdfs:subClassOf` (Turtle) |
| Output | `ontology.json` | graph: nodes = classes; edges = object properties AND subClassOf (child→parent) |
| Output | `steps.json` | per-step snapshots — extraction steps then one entailment step |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable golden files). Capitalized nouns become classes; a relational verb becomes an object property; the subClassOf hierarchy is entailed by the compound-tail + root rules.
- `gemini`/`anthropic` (`llm_dependency: api`): with a key in the env, a real LLM extracts richer triples (Phase A uses the shared `extract_triples` helper); the entailment in Phase B is identical (deterministic) so the hierarchy stays stable. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/text.txt` (include relation verbs AND a base + compound concept, e.g. `Motor` + `ElectricMotor`, so you get both object properties and subClassOf links).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch classes and object properties appear (Phase A), then snap into the is-a hierarchy (Phase B).
