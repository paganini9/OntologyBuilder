# MedKGent — Two-agent, confidence-aware, temporally evolving medical KG

> Source: *MedKGent: A Large Language Model Agent Framework for Constructing Temporally Evolving Medical Knowledge Graph*, arXiv:2508.12393 (Zhang et al., MBZUAI et al.).

## 1. One-line summary
Instead of naively unioning LLM extractions over a static corpus, MedKGent builds a medical KG **day by day** with two cooperating agents: an **Extractor** that pulls confidence-scored triples from each dated abstract, and a **Constructor** that integrates them over time — **reinforcing** repeated findings and **resolving contradictions** by confidence.

## 2. Key ideas
- **Temporal dynamics.** Biomedical knowledge evolves: a 2022 claim can be overturned by a 2025 trial. MedKGent timestamps every fact and constructs the graph in publication-date order so the KG reflects *when* knowledge emerged.
- **Confidence, not just presence.** The Extractor assigns each triple a confidence via sampling-based estimation. Hedged claims ("may", "preliminary") score low and below a threshold are **filtered out**; strong claims ("confirmed", "significantly") score high.
- **Reinforcement.** When the same `(subject, relation, object)` is seen again, its confidence is combined (noisy-OR), its support count grows, and its time span widens — recurring knowledge is strengthened rather than duplicated.
- **Conflict resolution.** Polar-opposite relations on the same pair (e.g. `increases` vs `reduces` risk) are reconciled by keeping the higher-confidence fact; the loser is marked **superseded** and dropped from the active graph.

## 3. Construction process (step by step)
1. **Order by date** — abstracts are sorted by their `[YYYY-MM-DD]` stamp so the Constructor works forward in time.
2. **Extractor agent** — split each abstract into clauses; extract one `(subject, relation, object)` triple per clause and assign a confidence from linguistic cues. Drop triples below the confidence threshold.
3. **Constructor agent** — integrate each retained triple: *add* if new; *reinforce* (combine confidence, bump support, widen `first_seen…last_seen`) if seen before; on a polar conflict keep the stronger fact and supersede the weaker.
4. **Emit** — one snapshot per abstract (so the UI replays the graph evolving over time), then `ontology.ttl`, `ontology.json` (edges carry confidence / support / first_seen / last_seen / provenance), `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `abstracts.txt` | dated abstracts `"[YYYY-MM-DD] text"`; Capitalized entities, a relation verb links them; hedge/strong words set confidence |
| Output | `ontology.ttl` | OWL: entities as `owl:Class`, active relations as `owl:ObjectProperty` (domain/range); confidence/support/timespan as `rdfs:comment` |
| Output | `ontology.json` | graph; each relation edge carries `confidence`, `support`, `first_seen`, `last_seen`, `provenance` |
| Output | `steps.json` | per-abstract (per-day) snapshots — for temporal replay |

## 5. LLM backend
- Default `mock`: deterministic, key-free (stable golden files). A relation-verb map yields the triple and a transparent cue-based heuristic stands in for sampling-based confidence; reinforcement and conflict resolution are pure rules.
- `gemini` / `anthropic` / `hf_local`: a real model is the Extractor; confidence aggregation and conflict resolution stay rule-based, so the temporal graph shape is stable. With no key it auto-falls back to MOCK.
- Note: the published MedKGent processes ~10M PubMed abstracts with a 32B model to build the largest LLM-derived medical KG to date; this implementation keeps the **two-agent + confidence + temporal reinforcement/conflict** core and runs key-free and reproducibly on a small sample.

## 6. Try it
1. Edit `samples/abstracts.txt` — date each line `[YYYY-MM-DD]`, restate a fact in a later abstract to watch it reinforce, and add an opposite claim (`increases` vs `reduces`) with a stronger wording to watch conflict resolution.
2. Hit **Run** (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch the KG evolve day by day; hover an edge to read its confidence, support and time span.
