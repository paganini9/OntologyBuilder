# CQbyCQ — Ontology Construction One Competency Question at a Time

> Source: Lippolis et al., *Ontology Generation using Large Language Models*, ESWC 2024 (arXiv:2503.05388), the **CQbyCQ** variant.

## 1. One-line summary
Turn each **Competency Question (CQ)** independently (*memoryless*) into an OWL ontology fragment, then merge the fragments into one ontology.

## 2. Key ideas
- **Competency Question (CQ)**: a question the ontology must be able to answer, e.g. "Which parts does a product consist of?"
- **Memoryless**: each CQ is processed in isolation → short prompts, fewer tokens (~60% context saving in the paper). Cross-CQ consistency is recovered at the merge step.
- **Ontology fragment**: the (classes, object properties, data properties, restrictions) extracted from a single CQ.

## 3. Construction process (step by step)
1. **Collect CQs** — one per line in `competency_questions.txt`.
2. **CQ → fragment (loop)** — for each CQ, the LLM (or the MOCK heuristic) emits a JSON fragment `{classes, object_properties, data_properties, restrictions}`.
3. **Merge** — accumulate fragments into a growing graph. Classes referenced as a property domain/range are auto-created; duplicates are ignored.
4. **Emit** — after each CQ a snapshot is recorded so you can watch the ontology grow; finally `ontology.ttl` (OWL/Turtle), `ontology.json` (graph), and `steps.json` (per-step snapshots) are written.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `competency_questions.txt` | CQ list (one per line, `#` comments / blanks ignored) |
| Output | `ontology.ttl` | OWL ontology (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | per-CQ snapshots — for step replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable test golden files). Extracts capitalized nouns as classes and relational verbs (consist/made/produce/satisfy …) as object properties.
- `gemini`/`anthropic`: if a key is in the env, a real LLM produces richer fragments. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/competency_questions.txt` or add new CQs.
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch the graph grow with each CQ.
