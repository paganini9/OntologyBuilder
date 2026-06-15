# Zero-shot Triple Extraction from Engineering Standards

> Source: Songhui Yue, *LLM-based Zero-shot Triple Extraction for Automated Ontology Generation from Software Engineering Standards*, IEEE ICSC 2026 (SDI workshop), arXiv:2509.00140.

## 1. One-line summary
Read an **engineering standard document directly** (section by section) and build an OWL ontology with a **zero-shot**, five-stage pipeline — no fine-tuning, no labelled data, no competency questions.

## 2. Key ideas
- **Standard-document input**: unlike CQ-driven methods, the source is the standard itself (e.g. a STEP/SPMM-style spec). Sections of the document are the unit of work.
- **Zero-shot**: the LLM infers (subject, relation, object) triples from each section with only an instruction prompt — no examples, no training.
- **Cross-section alignment**: the same term mentioned in different sections (e.g. *Component* in "Scope", "Product Structure" and "Material Requirements") is unified into a single ontology node, so the resulting ontology is consistent across the whole standard.

## 3. Construction process (the five stages)
1. **Document segmentation** — split the standard into sections using heading lines (`## Section`, or numbered headings like `2.1 Product Structure`).
2. **Candidate term mining** — collect capitalized domain terms inside each section (stop-words like *Shall/Section/Scope* removed).
3. **Relation inference (LLM, zero-shot)** — for each section the model (or the MOCK rule) emits `{terms, triples}` where each triple is `{subject, relation, object}` (e.g. *Product consistsOf Component*).
4. **Term normalization** — title-case + singularize terms so *Materials*, *material*, *Material* collapse to one canonical term, merging surface variants.
5. **Cross-section alignment** — identical normalized terms appearing in different sections are merged into one node; their relations are attached to that single node.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `standard_text.txt` | Engineering-standard excerpt. Sections delimited by `## Heading` or numbered headings |
| Output | `ontology.ttl` | OWL ontology (Turtle): terms as `owl:Class`, relations as `owl:ObjectProperty` + triples |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | one snapshot per section (stages 1-3), plus a final `(normalize+align)` snapshot (stages 4-5) |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable golden files). Mines capitalized terms and turns relational verbs (consist/contain/require/supply/satisfy …) into object-property triples.
- `api` (gemini/anthropic): if a key is in the env, a real LLM performs richer zero-shot triple extraction. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/standard_text.txt` with your own standard excerpt (keep `## Heading` style sections).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch each section contribute terms and triples, then see cross-section terms merge in the final alignment step.
