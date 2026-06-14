# AGENTiGraph — Interactive Multi-Agent KG Construction

> Source: *AGENTiGraph: A Multi-Agent Knowledge Graph Framework for Interactive, Domain-Specific LLM Chatbots*, CIKM 2025 Demo (arXiv:2508.02999).

## 1. One-line summary
So that non-experts can build and refine a knowledge graph through **natural-language utterances**, a set of agents handling **intent classification → task planning → automatic knowledge integration** processes each user turn and grows the KG (user in-the-loop).

## 2. Key ideas
- **Conversational incremental construction**: instead of one batch extraction, each user turn grows the KG a little.
- **Intent classification**: classify each utterance as add-entity / add-relation / query / refine (paper reports 95.12% intent accuracy on a 3,500-query benchmark).
- **Task planning**: decompose the classified intent into execution steps (which entities/relations to integrate, in what order).
- **Automatic knowledge integration**: merge the new knowledge into the existing KG without conflicts.

## 3. Construction process (step by step)
1. **Collect seed + turns** — `seed_text.txt` (initial domain context, optional) and `user_turns.txt` (one utterance per line).
2. **Per-turn intent classification (loop)** — classify each turn as add-entity / add-relation / query / refine.
3. **Task planning** — decompose the intent into integration steps (decide classes/relations to add).
4. **Knowledge integration** — merge into the KG per plan; unify/update when conflicting with existing nodes.
5. **Emit** — a snapshot per turn shows "the KG growing through conversation"; write `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `seed_text.txt` | Initial domain context (optional; may be empty) |
| Input | `user_turns.txt` | User utterances (one per line) |
| Output | `ontology.ttl` | OWL ontology (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges |
| Output | `steps.json` | Per-turn snapshots (with intent/plan) — for step replay |

## 5. LLM backend
- Default `mock`: deterministic, no key. Intent is classified by rules (question → query, "add/connect" verbs → add, two capitalized nouns + relation verb → add-relation); integration uses the cqbycq heuristic to extract classes/relations and merge.
- `gemini`/`anthropic` (api): with a key a real LLM does intent classification, planning and integration. With no key it auto-falls back to MOCK.

## 6. Try it
1. Add your own utterances to `samples/user_turns.txt` (e.g. "connect a part to the product").
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out`).
3. Use the step slider to see each turn's intent → integration result and the graph growing.
