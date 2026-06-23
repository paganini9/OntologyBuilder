# OntoMetric — ontology-guided ESG metric KG construction with two-phase validation

> Source: *OntoMetric: An Ontology-Driven LLM-Assisted Framework for Automated ESG Metric Knowledge Graph Generation*, arXiv:2512.01289.

## 1. One-line summary
Turn ESG regulatory documents (SASB / TCFD / IFRS S2) into a governed metric knowledge graph by embedding the **ESGMKG ontology as a hard constraint** in extraction, minting **deterministic identifiers**, and running **two-phase validation** (semantic type verification + rule-based schema checking) while preserving page-level **provenance**.

## 2. Key ideas
- **ESG metric knowledge is structured but implicit.** Industries, reporting frameworks, metric categories, metrics, and calculation models connect through compositional dependencies that exist only implicitly in regulatory PDFs. Unconstrained LLM extraction hallucinates types and invalid relations.
- **Ontology as a first-class constraint.** The ESGMKG schema — `ReportingFramework`, `MetricCategory`, `Metric`, `CalculationModel`, `Industry`, with the allowed edges `hasCategory`, `hasMetric`, `computedBy`, `appliesToIndustry` — is operationalised directly inside extraction, not just consulted afterwards.
- **Structure-aware segmentation + provenance.** Documents are read segment-by-segment in order; a running `framework → category → metric` context captures compositional nesting, and every entity keeps page-level provenance back to the source text.
- **Deterministic identifiers.** Each entity gets a stable id (`RF:` / `CAT:` / `MET:` / `CM:` / `IND:`) derived from framework + category + name, so re-runs and cross-document merges are idempotent.
- **Two-phase validation.** *Phase 1 (semantic type verification)* drops any entity whose proposed type is not an ESGMKG class (a hallucinated "Tagline" is rejected). *Phase 2 (rule-based schema checking)* keeps a relation only if `(srcType, relation, dstType)` is an allowed ESGMKG edge — so a `CalculationModel` can never `appliesToIndustry`.

## 3. Construction process (step by step)
1. **Read document** — `esg_document.json` (`framework`, ordered `segments` with `page`, `heading`, `text`).
2. **Structure-aware segmentation** — process segments in order, tracking the `framework → category → metric` context and page provenance.
3. **Ontology-constrained extraction** — the heading prefix proposes an ESGMKG type; mint a deterministic id; pull in-text `computed by … model` → `CalculationModel` and `applies to … industry` → `Industry`.
4. **Phase 1 — semantic type verification** — reject entities whose proposed type is not in the ESGMKG schema.
5. **Phase 2 — rule-based schema checking** — accept a relation only if it is an allowed ESGMKG edge and both endpoints survived phase 1.
6. **Emit** — `ontology.ttl` (OWL classes + object properties + typed, labelled individuals), `ontology.json` (Cytoscape; instance nodes carry deterministic id + `provenance`), `steps.json` (one snapshot per segment — the UI replays population + validation).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `esg_document.json` | `{"framework":"SASB", "segments":[{"page","heading","text"}, ...]}` |
| Output | `ontology.ttl` | OWL: ESGMKG `owl:Class`, `owl:ObjectProperty`, typed individuals with `rdfs:label` |
| Output | `ontology.json` | graph; instance nodes carry `cls`, deterministic `id`, and page `provenance` |
| Output | `steps.json` | per-segment snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic heading-prefix → type proposal; deterministic id minting + rule-based validation — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM proposes the entity type per segment; id minting and the two validation phases stay deterministic, so the graph shape is stable. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/esg_document.json` — add a `Metric:` segment under a category and watch the `hasMetric` edge and a `MET:` id appear.
2. Add a segment with a non-ESGMKG heading prefix (e.g. `Tagline:`) to see **phase 1** reject the hallucinated entity.
3. Put `applies to the … industry` in a `Calculation Model:` segment to see **phase 2** reject the illegal `appliesToIndustry` edge while the same phrase in a `Metric:` segment is accepted.
4. Run it: `python pipeline.py samples runs/out --backend mock` (or hit the site's **Run** button). The manifest's `rejected_entities` / `rejected_relations` are the validation audit trail.
