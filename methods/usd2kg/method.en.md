# USD2KG — zero-shot LLM ontology grounding for USD scenes

> Source: *From USD Scenes to Knowledge Graphs: Zero-Shot Ontology Grounding with LLMs*, arXiv:2606.09134, Shuai et al., IEEE ICRA 2026 J-WOSMARS workshop. Code: <https://github.com/JTShuai/USD_2_KG>.

## 1. One-line summary
Replace the hand-curated dictionary that maps USD prims to OWL classes with a **zero-shot LLM grounding pipeline**: for each prim, try (A) name-only matching, then (B) context-augmented matching using the scene-graph hierarchy, then (C) chain-of-thought reasoning over bounding-box geometry — and pick the most specific class that lands.

## 2. Key ideas
- **USD prim → OWL class is the bottleneck**: building knowledge graphs from 3D scenes used to depend on per-asset dictionaries. The paper shows an LLM can do this zero-shot with 90–96% accuracy on descriptive names and a graceful 17–48% even when names are stripped to opaque identifiers.
- **Three prompting strategies, one pipeline**: each USD prim is tried under three strategies of increasing input richness — (A) name only, (B) name + parent path + sibling names, (C) (B) + step-by-step reasoning over geometry. Whichever fires first commits the class; the choice is recorded for ablation.
- **Naming regimes**: the same scene can be re-run under *semantic / abbreviated / opaque* names. The paper finds that hierarchy (parent paths, sibling names) carries most of the load when names degrade — exactly what this pipeline's strategy-shift telemetry surfaces.
- **TBox linearisation**: the ontology is presented to the LLM as a flat, alphabetical list of class names + descriptions, mirroring the paper's prompt format (positional bias acknowledged).

## 3. Construction process (step by step)
1. **Read scene** — `usd_scene.json` (`naming_regime`, list of prims with `name`, `parent_path`, `bbox=[w,h,d]`, optional `mass`).
2. **Apply naming regime** — `semantic` keeps names, `abbreviated` removes vowels and per-word truncates, `opaque` replaces names with `obj_NNN`.
3. **Strategy A — name-only** — the LLM (or MOCK heuristic) tries to match the prim name against the linearised TBox (alias table + class-name substrings, longest-wins).
4. **Strategy B — context-augmented** — if (A) returns nothing, the pipeline reads the `parent_path`, finds the closest enclosing group (e.g. `Crockery_grp` → `Crockery`), and commits that superclass (the paper's "superclass collapse" behaviour for ambiguous geometric similars).
5. **Strategy C — chain-of-thought over geometry** — if (B) still returns nothing, the bounding-box volume picks a size-bucket superclass (`DesignedFurniture` / `Appliance` / `PhysicalObject`).
6. **Emit** — `ontology.ttl` (OWL classes + `rdfs:subClassOf` hierarchy + typed individuals), `ontology.json` (Cytoscape: each instance node carries `strategy` and `feature`), `steps.json` (one snapshot per prim — the UI replays grounding).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `usd_scene.json` | `{"ontology":..., "naming_regime":"semantic\|abbreviated\|opaque", "prims":[...]}` |
| Output | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, typed `rdf:type` individuals |
| Output | `ontology.json` | graph; instance nodes carry `strategy` (A/B/C) and `feature` (name/hierarchy/geometry) |
| Output | `steps.json` | per-step snapshots — for step replay |

## 5. LLM backend
- Default `mock`: deterministic name-only seed + deterministic hierarchy/geometry fallbacks — stable golden files, key-free.
- `gemini`/`anthropic`/`hf_local`: the LLM proposes the Strategy-A class; B and C remain deterministic, so graph shape is stable. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/usd_scene.json` — add a few well-named prims (`Refrigerator_main`), a strangely-named one (`obj_042`), and a "junk" prim under `/Misc_grp` to trigger Strategy C.
2. Set `naming_regime` to `opaque` to watch the strategy mix shift toward (B): hierarchy dominates, matching the paper.
3. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
4. The step slider shows one grounding per step; the manifest's `strategies` block is the per-run ablation summary.
