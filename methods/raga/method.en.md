# RAGA — Read-Search-Verify-Construct Agent

> Source: Han & Cheng, *RAGA: Reading-And-Graph-building-Agent for Autonomous Knowledge Graph Construction and Retrieval-Augmented Generation*, 2026 (arXiv:2605.17072).

## 1. One-line summary
A **single autonomous agent** reads a document one unit (sentence) at a time and runs a **ReAct-style cognitive loop** constrained to four explicit stages — **Read → Search → Verify → Construct** — building and self-auditing a knowledge graph as it reads, with **evidence-anchored verification**.

## 2. Key ideas
- **Single-agent ReAct cognitive loop per unit**: rather than a fixed multi-component pipeline, *one* agent iterates over reading units and, for each unit, runs the same think→act loop.
- **Read–Search–Verify–Construct cognitive constraint**: the loop is forced through four sub-stages every iteration, so generation (Read) is always followed by context linking (Search) and self-audit (Verify) before anything is committed (Construct).
- **Evidence-anchored verification**: a candidate triple is committed only if BOTH its subject and object are literally supported by the unit's text. Implied / pronoun objects (no surface evidence) are dropped — this keeps precision high without a second model.
- **Incremental context linking**: the Search stage links proposed entities against the graph built so far, so the agent reuses existing nodes instead of duplicating them.

## 3. Construction process (step by step)
1. **Collect input** — `text.txt` (free source text). One sentence = one agent unit.
2. For each sentence the agent runs its ReAct loop:
   - **READ** — propose candidate (subject, relation, object) triples from the sentence.
   - **SEARCH** — link the proposed entities against the graph built so far (which already exist?).
   - **VERIFY** — evidence-anchored check: keep a candidate only if BOTH subject and object tokens appear in the sentence; drop implied/pronoun objects.
   - **CONSTRUCT** — commit the verified triples into the growing graph.
3. **Emit** — one `steps.json` snapshot per sentence (with the read/search/verify trace) plus `ontology.ttl` and `ontology.json`. The final graph contains only evidence-anchored triples.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Source text; one sentence per agent unit |
| Output | `ontology.ttl` | OWL of verified triples (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges (verified only) |
| Output | `steps.json` | One per-sentence ReAct snapshot (read / search / verify / constructed) |

## 5. LLM backend
- Default `mock`: deterministic, no key. The READ stage parses the sentence heuristically; SEARCH/VERIFY/CONSTRUCT apply deterministic rules. VERIFY keeps a candidate only if its subject and object are both anchored in the sentence text.
- `gemini`/`anthropic` (api): with a key the READ stage uses the real LLM (`backend.llm.extract.extract_triples`) to propose candidates; SEARCH/VERIFY/CONSTRUCT are unchanged, so the graph is verified the same way. With no key it auto-falls back to MOCK.

## 6. Try it
1. Replace `samples/text.txt` with your own sentences.
2. Run (or `python pipeline.py samples runs/out`).
3. Use the step slider to follow each sentence's Read→Search→Verify→Construct loop and see which candidates VERIFY drops (e.g. the implied-pronoun object in "The Housing protects them …").
