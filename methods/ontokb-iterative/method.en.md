# Iterative LLM Ontological KB — draft → refine

> Source: *Development of Ontological Knowledge Bases by Leveraging Large Language Models*, arXiv:2601.10436 (vehicle-sales case study).

## 1. One-line summary
Build an ontological knowledge base through an **iterative** cycle: a first pass **drafts** the skeleton (classes + relations), then a **refinement** pass enriches it (induces the is-a hierarchy and attaches data attributes).

## 2. Key ideas
- **Iterative knowledge acquisition**: rather than one-shot extraction, the KB is developed in passes — generate, then review-and-refine. This makes the construction *auditable*: you can see what the draft captured and what refinement added.
- **Skeleton first, enrichment later**: the draft deliberately keeps only classes and the object properties between them. Hierarchy and attributes are *not* invented in the first pass; they are derived in refinement, where the whole draft is in view.
- **Artifact generation**: each pass produces a concrete artifact (the growing ontology graph + TTL), and the step snapshots are the audit trail of the cycle.

## 3. Construction process (step by step)
1. **Read text** — free domain text in `text.txt`, split into sentences (`#` comment lines ignored).
2. **Iteration 1 — DRAFT (per sentence)**: the LLM (or MOCK heuristic) extracts classes and one object property `{name, domain, range}`. One snapshot per sentence (`stage = "draft"`).
3. **Iteration 2 — REFINE (over the whole draft)**:
   - **Hierarchy**: compound-tail rule induces `rdfs:subClassOf` (e.g. `ElectricVehicle ⊑ Vehicle`, `SportsCar ⊑ Car`).
   - **Attributes**: data words (`price`, `model`, `brand`, `year`, `color`, …) mentioned for a class are attached as datatype properties.
   One snapshot (`stage = "refine"`).
4. **Emit** — `ontology.ttl` (classes, object properties, `rdfs:subClassOf`, datatype properties), `ontology.json` (graph; data attributes shown on nodes), `steps.json` (draft snapshots + the refine snapshot).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | free domain text (split into sentences by `.` `!` `?`) |
| Output | `ontology.ttl` | OWL: classes, object/datatype properties, `rdfs:subClassOf` |
| Output | `ontology.json` | graph; nodes carry their data attributes |
| Output | `steps.json` | per-sentence draft snapshots + one refine snapshot |

## 5. LLM backend
- Default `mock`: deterministic, no key (stable golden files). Draft = capitalized nouns + a relational verb; refine = compound-tail subClassOf + data-word attributes.
- `gemini`/`anthropic`/`hf_local`: with a key/model the draft uses a real extractor; refinement is identical (deterministic) so the hierarchy/attributes stay stable. No key → auto MOCK fallback.

## 6. Try it
1. Edit `samples/text.txt` — include a base class and a compound (e.g. `Vehicle` + `ElectricVehicle`) and some attribute words (`price`, `year`).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch the draft skeleton form, then the refine step snap in the hierarchy and attributes.
