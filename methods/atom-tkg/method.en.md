# ATOM — Dual-time temporal KG from atomic facts

> Source: *ATOM: AdapTive and OptiMized dynamic temporal knowledge graph construction using LLMs*, arXiv:2510.22590 (Lairgi et al., INSA Lyon / LIRIS).

## 1. One-line summary
Build a **Temporal Knowledge Graph** that keeps changing over time: split each note into minimal **atomic facts**, tag every fact with **dual time** (when it was *observed* vs when it is *valid*), then **merge** the atomic graphs so a re-observed fact widens its validity interval instead of duplicating.

## 2. Key ideas
- **Atomic facts**: long sentences hide several facts and make extraction unstable across runs. ATOM first decomposes each note into minimal, self-contained clauses, then extracts one `(subject, relation, object)` triple per clause — improving *exhaustivity* and *stability*.
- **Dual-time modeling**: a fact has two independent timelines — `observed` (when the note recorded it) and the `valid` interval (`valid_from` … `valid_until`, when the fact actually holds). "Beta is a subsidiary of Acme **since 2024**" recorded in a Jan-2024 note has `observed=2024-01` but `valid_from=2024`.
- **Parallel merge / continuous update**: atomic temporal KGs are merged by `(subject, relation, object)`. A repeated fact keeps the **earliest** observation and **widens** its validity interval (`min valid_from`, `max valid_until`), so new evidence updates the graph rather than bloating it.

## 3. Construction process (step by step)
1. **Read notes** — `events.txt`, one dated note per line `"[YYYY-MM] text"` (`#` comment lines ignored). The bracket is the **observed** date.
2. **Atomic decomposition** — split the note body into clauses (by `.` `!` `?`); each clause is one atomic fact.
3. **Extract + dual-time tag** — the LLM (or the MOCK heuristic) returns a triple per clause; rules set `valid_from` from a `since/from YYYY` cue (else the observed date) and `valid_until` from an `until/to YYYY` cue (else open).
4. **Merge** — fold each atomic fact into the running TKG by its triple key, widening the validity interval on re-observation. One snapshot is emitted per note so the UI can replay the graph growing and intervals widening.
5. **Emit** — `ontology.ttl` (entities as `owl:Class`, relations as `owl:ObjectProperty` with domain/range, each interval as an `rdfs:comment`), `ontology.json` (edges carry `observed` / `valid_from` / `valid_until` + `provenance`), `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `events.txt` | dated notes `"[YYYY-MM] text"`; `since/until YYYY` cues set validity |
| Output | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty` (domain/range), interval comments |
| Output | `ontology.json` | graph; each relation edge carries `observed` + `valid_from` + `valid_until` + `provenance` |
| Output | `steps.json` | per-note snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic, key-free (stable golden files). A small relational-verb map yields the atomic triple; dual-time tagging is pure rules.
- `gemini` / `anthropic` / `hf_local`: a real model extracts the atomic triples; dual-time tagging stays rule-based, so the temporal graph shape is stable. With no key it auto-falls back to MOCK.
- Note: the published ATOM targets large-scale streaming with parallelism and stability metrics; this implementation keeps the **atomic-fact + dual-time + interval-widening merge** core and runs key-free and reproducibly.

## 6. Try it
1. Edit `samples/events.txt` — date notes `[2024-01] ...`, add `since 2024` / `until 2025` cues, and re-state a fact in a later note to see its interval widen.
2. Hit **Run** (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch atomic facts merge in; hover an edge to read its observed vs valid times.
