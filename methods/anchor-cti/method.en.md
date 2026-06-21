# ANCHOR — schema-agnostic CTI knowledge graph via hybrid ontology discovery

> Source: *Schema-Agnostic Knowledge Graph Construction via Hybrid Ontology Discovery for Cyber Threat Intelligence* (**ANCHOR**), arXiv:2606.01208, Kim et al., 2026.

## 1. One-line summary
Build a CTI knowledge graph that works **across schemas** (UCO, STIX, MALOnt) without rewriting prompts: each candidate entity is grounded by a **search-and-navigate** walk over the schema tree, and the assigned type is **SHACL-validated** before it is committed.

## 2. Key ideas
- **Schema-agnostic**: classical CTI extractors hardcode one prompt per schema. ANCHOR keeps the prompt the same; the schema is consulted as a *tree to be navigated*, so swapping UCO for STIX or MALOnt is a config change, not a rewrite.
- **Hybrid ontology discovery (search-and-navigate)**: a lexical-first search seeds a candidate class; if it fails validation the pipeline navigates *up* the `subClassOf` chain to the next ancestor that accepts the entity. Each instance records the full navigation `path` so the discovery is auditable.
- **SHACL-style validation**: every class can declare structural constraints (a value pattern, e.g. `CVE-\d{4}-\d{4,}` for `Vulnerability`, an IPv4 regex for `IPAddress`). An instance that fails its constraint is **demoted** to the validating ancestor (most-specific superclass) and flagged `shacl_demoted=true`, instead of being silently mis-typed.

## 3. Construction process (step by step)
1. **Read text** — free CTI body text in `text.txt`, split into sentences (comment lines starting with `#` ignored; dots inside IPs/CVE/hashes preserved).
2. **Candidate extraction** — the LLM (or the MOCK heuristic) returns the candidate tokens for each sentence: PascalCase entity names plus verbatim indicator values (IP, CVE id, hash, domain).
3. **Hybrid ontology discovery** — for each candidate the pipeline searches the schema's lexical catalogue (aliases + class names) for the most specific seed class, then navigates up the `subClassOf` chain until SHACL accepts the value. The entire chain (seed → … → accepted class) is recorded.
4. **Graph assembly** — committed instances are typed by `rdf:type`, the relevant slice of the class hierarchy is materialised, and CTI relations (`deploys`, `exfiltrates`, `affects`, `hosts`, `exploits`, …) are added when two entities co-occur.
5. **Emit** — `ontology.ttl` (OWL classes + subClassOf + typed individuals + object properties), `ontology.json` (Cytoscape graph; each edge tagged with the active `schema`), `steps.json` (one snapshot per sentence — the UI replays the discovery).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | free CTI text (split into sentences by `.` `!` `?`, dots inside IPs/CVE preserved) |
| Output | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, typed `rdf:type` individuals, `owl:ObjectProperty` relations |
| Output | `ontology.json` | graph; instance nodes carry `schema`, `value`, and `shacl_demoted` |
| Output | `steps.json` | per-step snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic candidate extraction + deterministic search-and-navigate + deterministic SHACL — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM only seeds candidate tokens; navigation and SHACL remain deterministic, so the graph shape stays stable. With no key it auto-falls back to MOCK.
- **Schema switch**: set `LLM_SCHEMA=uco|stix|malont`. The default is `uco`. The code path is identical, only the tree/aliases/SHACL change.

## 6. Try it
1. Edit `samples/text.txt` — mix typed assertions (`The IPAddress 198.51.100.7 hosts ...`) with malformed ones (`CVE-ABCDE` will be demoted).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Step through the slider — each step shows the discovery for one sentence, instances grow with their type chain, and SHACL demotions surface as instances whose `shacl_demoted=true`.
