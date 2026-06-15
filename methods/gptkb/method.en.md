# GPTKB — Materialize a Knowledge Base from an LLM's Parametric Knowledge

> Source: Hu, Nguyen, Ghosh, Razniewski, *GPTKB: Enabling LLM Knowledge Analysis via Extensive Materialization*, ACL 2025 (arXiv:2411.04920), [gptkb.org](https://gptkb.org).

## 1. One-line summary
Build a knowledge base **without any input corpus** by recursively querying an LLM about entities — starting from a few seeds, the model's own (parametric) knowledge is extracted into triples and the newly discovered entities are expanded recursively.

## 2. Key ideas
- **No input corpus**: there is no document collection to read. The knowledge comes entirely from the model itself ("the corpus is the model"). You only provide seed entities.
- **Recursive seed expansion**: for each entity the LLM is asked "what do you know about X?". Its answer is parsed into `(subject, relation, object)` triples; every object that is itself an entity becomes a new node to be expanded.
- **Depth limit**: the recursion is run breadth-first up to a fixed depth (here, depth 2) so the crawl terminates instead of expanding forever.
- **Consolidation / dedup**: an entity is queried at most once even if many triples point to it (a `visited` set), so the materialized KB has no duplicate nodes.

## 3. Construction process (step by step)
1. **Seeds** — one seed entity per line in `seed_entities.txt`. (No corpus.)
2. **Query the model (loop)** — pop the next entity from the BFS queue; the LLM (or the MOCK knowledge table) returns JSON `{entity, facts:[{relation, object}]}`.
3. **Materialize + recurse** — add each fact as a triple, register the object as a new entity, and enqueue it for expansion if we are still under the depth limit and it has not been visited.
4. **Consolidate** — skip any entity already visited so the KB is deduplicated.
5. **Emit** — after each expanded entity a snapshot is recorded so you can watch the KB grow outward from the seeds; finally `ontology.ttl` (OWL/Turtle, with materialized triples), `ontology.json` (graph) and `steps.json` (per-step snapshots) are written.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `seed_entities.txt` | seed entities (one per line, `#` comments / blanks ignored). **No corpus.** |
| Output | `ontology.ttl` | materialized KB (OWL/Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | per-entity snapshots — for step replay of the recursive crawl |

## 5. LLM backend
- Default `mock`: runs deterministically with no key. A small built-in knowledge table answers each "tell me about X" query, so the recursive expansion and golden files are stable.
- `api` (gemini/anthropic): with a key in the env, a real LLM materializes its actual parametric knowledge — far larger and richer. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/seed_entities.txt` (e.g. `Motor`, `Pump`).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out`).
3. Use the step slider to watch the KB expand seed → depth 1 → depth 2.
