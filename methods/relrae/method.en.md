# RELRaE — XML schema → ontology relations (extract · label · refine · evaluate)

> Source: *RELRaE: LLM-Based Relationship Extraction, Labelling, Refinement, and Evaluation*, arXiv:2507.03829 (Hannah et al., University of Liverpool / Unilever Materials Innovation Factory).

## 1. One-line summary
Robotic labs emit large volumes of **XML**. To make that data interoperable as a knowledge graph, the XML *schema* must become an **ontology schema** — but the relationships between element types are only **implicit** in the XML. RELRaE uses an LLM in four stages to surface them: **Extract → Label → Refine → Evaluate**.

## 2. Key ideas
- **Relationships are implicit in structure.** Parent/child element nesting encodes *containment* relationships; an attribute ending in `Ref` cross-references another element type; the remaining attributes are *data properties*. None of these carry an ontology label on their own.
- **LLM labelling.** Each extracted structural relationship is handed to the model, which proposes a meaningful object-property label (e.g. `instrumentRef` between a `Measurement` and an `Instrument` → `measuredWith`, not a generic `ref`).
- **Refinement.** Repeated structure (the same `(domain, label, range)` appearing for every sample/measurement) is collapsed to one ontology relation, and synonymous labels are canonicalised.
- **LLM-as-a-judge.** Each labelled relationship is scored for quality; low-scoring ones are rejected so the final schema keeps only trustworthy relations. References whose target type is never defined in the document are penalised.

## 3. Construction process (step by step)
1. **Extract** — parse `schema.xml`; walk the tree. Emit a *nest* relationship for every parent→child element pair, a *ref* relationship for every `…Ref` attribute (target type derived from the attribute name, e.g. `instrumentRef` → `Instrument`), and a data property for every other attribute.
2. **Label** — the LLM (or MOCK heuristic) names each relationship: containment → `has<Child>`; reference → a usage verb (`measuredWith`, `consumes`, …).
3. **Refine** — canonicalise synonymous labels, then deduplicate by `(domain, label, range)` so repeated structure becomes a single relation.
4. **Evaluate** — the LLM-as-a-judge assigns each relation a score in `[0,1]`; relations below the acceptance threshold (or duplicates) are rejected and excluded from the ontology.

A snapshot is emitted per raw relationship so the UI can replay extraction, labelling, refinement and judging, with the schema growing as relations are accepted.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `schema.xml` | one lab XML record; nesting = containment, `…Ref` attrs = cross-references, other attrs = data properties |
| Output | `ontology.ttl` | OWL: element types as `owl:Class`, accepted relations as `owl:ObjectProperty` (domain/range), attributes as `owl:DatatypeProperty`; judge score per relation as `rdfs:comment` |
| Output | `ontology.json` | graph; each relation edge carries `label`, `kind` (nest/ref), `score`, `accepted` |
| Output | `steps.json` | per-relationship snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic, key-free (stable golden files). A label map yields the object-property name and a transparent heuristic produces the judge score, so labelling and evaluation are reproducible.
- `gemini` / `anthropic` / `hf_local`: a real model labels and scores each relationship; structural extraction and refinement stay rule-based, so the schema shape is stable. With no key it auto-falls back to MOCK.
- Note: the published RELRaE targets semi-automatic ontology generation for lab-automation XML with human-in-the-loop review; this implementation keeps the **extract → label → refine → evaluate** core and runs key-free and reproducibly.

## 6. Try it
1. Edit `samples/schema.xml` — nest elements, add `…Ref` attributes pointing at other element types, add plain attributes as data properties.
2. Hit **Run** (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch relationships be labelled, merged and judged; hover an edge to read its label, kind and judge score.
