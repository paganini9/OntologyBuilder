# Ontology-Enhanced KG Completion (LLM) — Predict the Missing Links

> Source: Guo, Wang, Chen, Li, Chen, *Ontology-Enhanced Knowledge Graph Completion using Large Language Models*, arXiv:2507.20643 (2025).

## 1. One-line summary
Given a **partial knowledge graph** and its **ontology constraints**, predict the **missing links** (KG completion / link prediction). It **completes an existing KG** rather than building one from scratch.

## 2. How it differs from the other methods
Every other method here **constructs** an ontology/KG from free text or from competency questions. This one starts from a KG that **already exists but is incomplete**, and its only job is to **fill in the edges that should be there but are not**. No new classes are invented; the existing schema is the search space.

## 3. Key ideas
- **Completion, not construction**: the input is a graph, the output is the same graph **plus inferred edges**.
- **Ontology-enhanced**: class typing and property semantics (domain/range, transitivity, inverse, symmetry) constrain the prediction so inferred links stay **consistent** with the schema — exactly what keeps an LLM from hallucinating off-graph facts.
- **Grounded inference**: an inferred triple is kept only if its subject **and** object are **existing** classes and the edge is **not already present**.

## 4. Completion process (step by step)
1. **(load) seed KG** — parse `seed_kg.ttl` with rdflib: existing classes and existing object-property edges. Every loaded node/edge is tagged `origin = "seed"`.
2. **(complete) inferred edges** — predict the missing links:
   - **MOCK** (default, deterministic): ontology-rule completion —
     (a) **transitivity** on `partOf`/`consistsOf`/`contains` chains (A→B, B→C ⇒ A→C),
     (b) **inverse** for known pairs (`partOf`⇄`hasPart`),
     (c) **symmetry** for symmetric relations,
     (d) **domain/range**-aware suggestion. Only **new** edges are added.
   - **REAL** (`gemini`/`anthropic`): the seed KG is described as text and the model is asked to infer additional consistent triples; only triples between **existing** classes that are **not already present** are kept.
   Inferred edges are tagged `origin = "inferred"`.
3. **Emit** — final graph = seed + inferred. Writes `ontology.ttl` (OWL/Turtle), `ontology.json` (graph), `steps.json` (load → complete snapshots).

## 5. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `seed_kg.ttl` | the existing, partial KG (classes + object-property edges) |
| Output | `ontology.ttl` | seed + inferred edges, OWL (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges, `origin` = seed \| inferred |
| Output | `steps.json` | two snapshots: loaded seed, then completed graph |

## 6. LLM backend
- Default `mock`: deterministic rule-based completion, no key needed (stable golden files). On the sample KG it turns 4 seed edges into 10 (6 inferred).
- `gemini`/`anthropic`: with a key, a real LLM proposes completions, filtered to stay grounded in the seed classes. With no key it auto-falls back to MOCK.

## 7. Try it
1. Edit `samples/seed_kg.ttl` (add classes / leave some links out on purpose).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch the **inferred** (dashed/highlighted) edges appear on top of the seed graph.
