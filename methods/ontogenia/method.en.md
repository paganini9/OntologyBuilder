# Ontogenia — Iterative + Metacognitive Prompting from CQ to OWL

> Source: Lippolis, Ceriani et al., *Ontology Generation using Large Language Models*, ESWC 2024 (arXiv:2503.05388, Springer DOI 10.1007/978-3-031-78952-6_38), the **Ontogenia** variant.

## 1. One-line summary
Process **Competency Questions (CQs)** but, unlike CQbyCQ, carry the ontology built so far as **context (memoryful)** and let the LLM **self-critique and revise its own output (metacognitive prompting)** in an iterative loop that progressively refines the ontology.

## 2. Key ideas
- **Competency Question (CQ)**: a question the ontology must be able to answer, e.g. "Which parts does a product consist of?"
- **Memoryful (context carried)**: when processing each CQ, the **accumulated ontology so far** is given as prompt context, so new fragments are aligned with existing classes/properties. (CQbyCQ treats CQs independently — *memoryless* — this is the core difference between the two.)
- **Metacognitive Prompting (MP)**: the LLM is asked to **self-reflect** — "Does the fragment I just produced really answer the CQ? Does it conflict with or duplicate existing definitions? Are there better names / hierarchies?" — and then emit a revised version.
- **Design-pattern guidance**: Ontology Design Patterns (ODPs) are referenced to shape the fragment structure (class hierarchy, property domain/range).
- **Iterative refinement loop**: draft → self-critique → revise → merge for each CQ, plus one final whole-ontology consistency refinement.

## 3. Construction process (step by step)
1. **Collect CQs** — one per line in `competency_questions.txt`.
2. **CQ → draft fragment (loop, with context)** — for each CQ the LLM (or the MOCK heuristic) is given the **accumulated ontology so far** and drafts a JSON fragment `{classes, object_properties, data_properties, restrictions}`.
3. **Self-critique pass (metacognition)** — the draft for the same CQ is fed back to the LLM to self-critique. This pass proposes (a) **merging duplicates** with existing classes, (b) more accurate **renaming**, and (c) adding missing **super/sub-classes / restrictions**, producing a **revised fragment**. This yields an extra step snapshot not present in CQbyCQ.
4. **Merge** — the revised fragment is accumulated into the growing graph. Classes referenced as a property domain/range are auto-created; duplicates are unified into the existing definition.
5. **Whole-ontology consistency refinement pass** — after all CQs, one final metacognitive refinement runs over the entire accumulated ontology: connect orphan classes, standardize names, remove obvious duplicates. This pass is recorded as its own step snapshot.
6. **Emit** — per-CQ draft/post-critique snapshots plus the final refinement snapshot are recorded so you can watch the ontology being refined through critique; finally `ontology.ttl` (OWL/Turtle), `ontology.json` (graph), and `steps.json` (per-step snapshots) are written.

> **Contrast with CQbyCQ**: CQbyCQ runs in 2 stages (fragment → merge) with no context, straight through. Ontogenia adds **one self-critique pass per CQ** plus **one final whole-ontology refinement pass**, so it has more steps and produces a more coherent output.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `competency_questions.txt` | CQ list (one per line, `#` comments / blanks ignored) |
| Output | `ontology.ttl` | OWL ontology (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | per-CQ draft / self-critique / final-refinement snapshots — for step replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable test golden files). The draft step uses the same heuristic as CQbyCQ (capitalized nouns → classes, relational verbs → object properties), and the **self-critique pass is also emulated with deterministic rules** — e.g. merge a similarly named class if one already exists in the accumulated graph, normalize singular/plural, assign a super-class to orphan classes.
- `gemini`/`anthropic`: with a key, a real LLM performs draft + metacognitive self-critique + final refinement for a more coherent ontology. With no key it auto-falls back to MOCK.
- Ontogenia inherently makes **2 LLM calls per CQ (draft + critique) plus 1 final refinement call**, so it costs more tokens than CQbyCQ but yields higher consistency.

## 6. Try it
1. Edit `samples/competency_questions.txt` or add new CQs.
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out`).
3. In the step slider, follow each CQ's **draft → post-critique** change and the final **whole-ontology refinement** step to see how critique tidies up the graph.
