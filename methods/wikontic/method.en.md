# Wikontic — Wikidata-aligned, ontology-aware knowledge graph construction

> Source: *Wikontic: Constructing Wikidata-Aligned, Ontology-Aware Knowledge Graphs with Large Language Models*, arXiv:2512.00590.

## 1. One-line summary
A multi-stage pipeline that builds a compact, ontology-consistent KG from open-domain text by **extracting candidate triplets with qualifiers**, **normalizing surface mentions to one canonical Wikidata item (QID)**, and **enforcing Wikidata type/relation constraints** so only ontology-valid statements survive.

## 2. Key ideas
- **Wikidata-aligned.** Every item is a canonical Wikidata entity (QID) and every relation a Wikidata property (PID), so the graph aligns with external knowledge out of the box.
- **Candidate triplets with qualifiers.** A relation lexicon pulls `(subject, property, object)` from each sentence; a trailing `in <year>` / `since <year>` clause becomes a **Wikidata qualifier** (point-in-time P585 / start-time P580).
- **Entity normalization (deduplication).** Surface mentions ("Apple", "Apple Inc.") map through an alias table to **one canonical item** (Q312, with its type), so duplicate mentions collapse into a single node.
- **Wikidata type/relation constraints.** Each property carries subject-type and value-type constraints (e.g. `foundedBy`/P112 requires an Organization subject and a Person value); a statement whose normalized endpoints violate the constraint is rejected — mirroring Wikidata property constraints.

## 3. Construction process (step by step)
1. **Read sentences** — `passages.txt` (one sentence per line; blank lines / `#` comments ignored).
2. **Candidate triplet extraction** — a relation lexicon yields `(subject, property, object)`; a trailing time clause is split off as a qualifier.
3. **Entity normalization** — map surface forms through the alias table to a canonical Wikidata item (QID + type); mentions resolving to the same item merge into one node.
4. **Constraint enforcement** — accept a statement only if `(subjType, property, valueType)` is allowed; violations are rejected (audit log).
5. **Emit** — `ontology.ttl` (typed items + object properties + Wikidata `rdfs:seeAlso` links), `ontology.json` (Cytoscape; item nodes carry QID + class, relation edges carry PID + qualifiers), `steps.json` (one snapshot per sentence).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `passages.txt` | one sentence per line |
| Output | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`, typed items (`rdfs:label` + Wikidata `rdfs:seeAlso`) |
| Output | `ontology.json` | graph; item nodes carry `qid` + `cls`, relation edges carry `pid` + `qualifiers` |
| Output | `steps.json` | per-sentence snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic sentence parsing → candidate triplets + qualifiers; normalization and constraints are rule-based — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM extracts triplets per sentence; normalization and constraint enforcement stay deterministic. With no key it auto-falls back to MOCK.

## 6. Try it
1. In `samples/passages.txt`, watch `Apple` and `Apple Inc.` collapse into a **single node (Q312)** (see the `merged` count).
2. Add a constraint-violating sentence (e.g. a city as the subject of `was founded by`) to see the statement **rejected** (`manifest.rejected`).
3. Append an `in <year>` / `since <year>` clause to see a **qualifier** (P585/P580) ride on the edge.
4. Run it: `python pipeline.py samples runs/out --backend mock` (or hit the site's **Run** button).
