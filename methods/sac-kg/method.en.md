# SAC-KG — Generator → Verifier → Pruner, applied multi-level

> Source: Chen et al., *SAC-KG: Exploiting Large Language Models as Skilled Automatic Constructors for Domain Knowledge Graph*, ACL 2024.

## 1. One-line summary
Grow a domain knowledge graph from **seed entities** by repeatedly running a three-stage **Generator → Verifier → Pruner** loop, one **level** at a time (recursively), until the desired depth is reached.

## 2. Key ideas
- **Generator**: an LLM proposes candidate triples `(relation, child entity)` that expand each entity on the current frontier, conditioned on domain corpora.
- **Verifier**: checks each candidate (relation/entity plausibility, support) and keeps only trustworthy ones, attaching a confidence; hallucinations are dropped.
- **Pruner**: controls the *structure* of the KG — caps branching and removes duplicate/cyclic edges so the graph stays compact and a DAG.
- **Multi-level (recursive)**: children that survive a level become the next level's frontier; the loop repeats for several levels.

## 3. Construction process (step by step)
1. **Read seeds** — one seed entity per line in `seed_entities.txt` (the level-0 frontier).
2. **For each level L = 1..N:**
   - **L generate** — Generator proposes candidate `(parent, relation, child)` triples for every frontier entity.
   - **L verify** — Verifier keeps candidates whose relation is in the allowed vocabulary and whose child is a plausible entity; the rest are dropped.
   - **L prune** — Pruner keeps at most **TOP_K** children per parent (stable order), and drops duplicates and cycle-forming edges. Survivors are written to the KG.
   - Surviving children form the next level's frontier.
3. **Emit** — one snapshot per `(level, stage)` is recorded (so the UI can replay the loop), then `ontology.ttl`, `ontology.json`, `steps.json` are written.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `seed_entities.txt` | seed entities (one per line, `#` comments / blanks ignored) |
| Output | `ontology.ttl` | KG as OWL/Turtle: entities `owl:Class`, relations `owl:ObjectProperty` (+ domain/range) |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) |
| Output | `steps.json` | per `(level, stage)` snapshots — for step replay |

## 5. LLM backend & the MOCK simplification
- **What the real method needs:** the original SAC-KG **Pruner** is a generation-relation classifier built on a **fine-tuned T5 + LoRA model running on a GPU**, and the Generator/Verifier use a large LLM over domain corpora. Reproducing it requires GPU + fine-tuning + an API/HF model.
- **What THIS implementation is:** a **deterministic MOCK simplification**. It runs with **no GPU, no fine-tuning and no API key**. The Generator is a fixed domain lexicon, the Verifier is a rule check (allowed relation + plausible entity), and the Pruner is a deterministic stand-in (top-K branching cap + duplicate/cycle removal). This faithfully mirrors the **Generator → Verifier → Pruner multi-level loop** and produces stable golden outputs for testing/visualization.
- **Future option:** a real `hf-local`/GPU run with a T5-LoRA pruner could replace the MOCK stand-in. It is **not** done here.

## 6. Try it
1. Edit `samples/seed_entities.txt` (e.g. add a seed present in the lexicon, like `Engine`).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch each level's **generate → verify → prune** stages add and drop candidates.
