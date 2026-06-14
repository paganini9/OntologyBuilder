# AI Agent-Driven Product Knowledge Graph (3 agents)

> Source: Peshevski, Stojanov, Trajanov, *An AI Agent-Driven Framework for Automated Product Knowledge Graph Construction in E-Commerce*, 1st GOBLIN Workshop 2025 (arXiv:2511.11017).

## 1. One-line summary
With no predefined schema and no hand-written rules, **three dedicated LLM agents** (① ontology creation/expansion → ② ontology refinement → ③ KG population) build a product knowledge graph from product-description text from scratch. The closest precedent for this project (product-development ontology).

## 2. Key ideas
- **Ontology-first**: unlike SAC-KG-style triple-first extraction, the **schema (classes/properties) is built first**, then individuals are populated into it.
- **Agent division of labor**:
  - **① Creation/expansion agent**: discover classes (product types, parts) and properties (specs, relations) from descriptions and grow the ontology.
  - **② Refinement agent**: merge duplicate classes, standardize names, tidy properties (the role of SAC-KG's verifier + pruner).
  - **③ Population agent**: instantiate each product as an individual according to the refined schema and fill in property values.
- **Metric**: property coverage rather than precision. The paper reports 97%+ coverage on air-conditioner descriptions.

## 3. Construction process (step by step)
1. **Collect product descriptions** — `product_descriptions.txt`, one product description per line (or paragraph).
2. **① Ontology creation/expansion (per product)** — extract classes / object properties / data properties from each description and add to the accumulated schema.
3. **② Ontology refinement** — merge similar/duplicate classes and standardize names (incl. singular/plural normalization).
4. **③ KG population** — instantiate each product as an individual of a refined-schema class, attaching extracted specs as data-property values and parts/relations as object properties.
5. **Emit** — snapshots per stage (① per-product schema expansion → ② refinement → ③ population) show "the schema being built and individuals filled in"; finally `ontology.ttl` (schema + individuals), `ontology.json` (graph), and `steps.json` are written.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `product_descriptions.txt` | Product descriptions (one product per line/paragraph) |
| Output | `ontology.ttl` | Schema (classes/properties) + individuals, OWL (Turtle) |
| Output | `ontology.json` | Cytoscape nodes (classes/individuals) / edges (relations) |
| Output | `steps.json` | Per-stage snapshots — replay creation/refinement/population |

## 5. LLM backend
- Default `mock`: deterministic, no key. Creation extracts capitalized nouns → classes, spec keywords → data properties, relational verbs → object properties; refinement merges by deterministic rules; population instantiates per product with IDs like `Product_1`.
- `gemini`/`anthropic` (api): with a key the three agents run on a real LLM for richer schema/individuals. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/product_descriptions.txt` with your own product catalog/spec descriptions.
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out`).
3. Use the step slider to follow ① schema expansion → ② refinement → ③ population.
