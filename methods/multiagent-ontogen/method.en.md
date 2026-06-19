# Multi-Agent Ontology Generation — Domain Expert / Manager / Coder / QA

> Source: Talukder, Mridul, Seneviratne, *Towards Automated Ontology Generation from Unstructured Text: A Multi-Agent LLM Approach*, arXiv:2604.23090 (2026).

## 1. One-line summary
Four specialised LLM **roles collaborate** — a Domain Expert reads the text, a Manager plans, a Coder writes OWL, and a Quality Assurer prunes — turning **unstructured text** into an OWL ontology in a planning-first pipeline.

## 2. Key ideas
- **Artifact-driven roles**: each role consumes the previous role's artifact and produces the next, instead of one monolithic prompt. Responsibilities are clearly separated.
- **Planning-first**: nothing is "coded" into OWL until the Manager has organised the findings into an explicit plan, which keeps the ontology coherent.
- **Quality assurance pass**: a dedicated final role validates and prunes the result (self-loops, duplicate edges, dangling endpoints), so noise from extraction does not leak into the final ontology.

## 3. The four roles (step by step)
1. **Domain Expert** — reads the text **sentence by sentence** and surfaces candidate concepts (capitalised nouns) and (subject, relation, object) knowledge triples. One step per sentence: `(DomainExpert) <sentence>`.
2. **Manager** — deduplicates and organises all the findings into one **plan** (a clean concept set + the relation list). One step: `(Manager) plan`.
3. **Coder** — turns the plan into **OWL fragments** (classes + object properties with domain/range) and emits them into the model. One step: `(Coder) emit`.
4. **Quality Assurer** — **validates / prunes**: drops self-loops, duplicate edges, and edges whose endpoints are missing. One step: `(QA) validate`, listing what was removed.

Only the Domain Expert consults the LLM. The Manager, Coder, and QA are deterministic for both the mock and real backends.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | unstructured domain text (split into sentences; `#` comments / blanks ignored) |
| Output | `ontology.ttl` | OWL ontology (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | per-role snapshots — watch it get planned, built, then pruned |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable golden files). The Domain Expert extracts capitalised nouns as concepts and relational verbs (consist/made/supply/perform/satisfy/connect …) as object properties, **keeping** duplicates and self-loops so the QA role visibly prunes them.
- `gemini`/`anthropic` (`api`): if a key is in the env, the Domain Expert uses the real model via the shared `extract_triples` helper; the Manager/Coder/QA logic is unchanged. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/text.txt` (add sentences with capitalised entities and relation verbs).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch each role act: Domain Expert findings → Manager plan → Coder emit → QA prune.
