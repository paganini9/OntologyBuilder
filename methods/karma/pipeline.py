"""KARMA - multi-agent LLM knowledge-graph ENRICHMENT.

Method (Lu et al., NeurIPS 2025 Spotlight, "KARMA"): several dedicated agents
divide the labor of turning unstructured text into KG additions and merging them
into an EXISTING knowledge graph (enrichment, not from-scratch construction).
This implementation models four core agents, each emitting a step snapshot:

    1. entity-discovery   - capitalized-noun entities from text -> candidate classes
    2. relation-extraction- relational verbs -> object properties between entities
    3. schema-alignment   - merge new classes that are singular/plural/case
                            variants of existing (seed or earlier-added) classes
    4. conflict-resolution- drop duplicate edges and reverse-direction duplicates

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt      - free unstructured text to enrich from (required)
    seed_kg.ttl   - existing KG to enrich (optional; empty start if absent)

Outputs (out_dir):
    ontology.ttl    - the enriched OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges (seed vs new tagged)
    steps.json      - one snapshot per agent stage (UI shows the enrichment)
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
plays each agent role; with MOCK a deterministic heuristic does, so the output is
reproducible and testable. The mock path needs no API key.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Make backend.llm importable whether run as a subprocess or imported directly.
import sys

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402

EX = "http://example.org/product#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "Also", "Both", "Then", "Thus", "Here", "Every", "Many", "Some", "Any",
    "All", "No", "Most", "Few",
}

# relational verbs -> canonical object-property name (shared with cqbycq)
_REL = {
    "consist": "consistsOf", "consists": "consistsOf",
    "made": "madeOf", "compose": "composedOf", "composed": "composedOf",
    "has": "has", "have": "has", "having": "has",
    "produce": "produces", "produces": "produces", "produced": "produces",
    "require": "requires", "requires": "requires", "required": "requires",
    "contain": "contains", "contains": "contains",
    "use": "uses", "uses": "uses", "used": "uses",
    "belong": "belongsTo", "belongs": "belongsTo",
    "part": "partOf",
    "include": "includes", "includes": "includes",
    "perform": "performs", "performs": "performs",
    "satisfy": "satisfies", "satisfies": "satisfies",
    "supply": "supplies", "supplies": "supplies",
    "assemble": "assembledFrom", "assembled": "assembledFrom",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _norm(w: str) -> str:
    """Alignment key: lowercase singular -> case/number-insensitive identity."""
    return _singular(w).lower()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _discover_entities(sentence: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def _extract_relation(sentence: str, entities: list[str]) -> Optional[dict]:
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    ent_words = {e.lower() for e in entities} | {e.lower() + "s" for e in entities}
    rel = next(
        (_REL[w] for w in words if w in _REL and w not in ent_words), None)
    if rel and len(entities) >= 2:
        return {"name": rel, "domain": entities[0], "range": entities[1]}
    return None


# ---------------------------------------------------------------------------
# Deterministic MOCK agent: the prompt carries a STAGE tag; we branch on it so
# each agent role yields a stable, structured JSON answer with no API key.
# ---------------------------------------------------------------------------
def mock_responder(prompt: str) -> str:
    stage = prompt.split("STAGE:")[-1].split("\n")[0].strip()
    payload_raw = prompt.split("PAYLOAD:")[-1].strip()

    if stage == "entity-discovery":
        sentence = payload_raw.split("\n")[0]
        return json.dumps({"entities": _discover_entities(sentence)},
                          ensure_ascii=False)

    if stage == "relation-extraction":
        data = json.loads(payload_raw)
        rel = _extract_relation(data["sentence"], data["entities"])
        return json.dumps({"object_property": rel}, ensure_ascii=False)

    # alignment / conflict-resolution are graph-level rules done in run();
    # the mock simply acknowledges (kept for symmetry with a real backend).
    return json.dumps({"ok": True}, ensure_ascii=False)


_ENTITY_PROMPT = (
    "You are the entity-discovery agent. Find candidate ontology classes "
    "(named entities) in the sentence. Return ONLY JSON {{entities: [..]}}.\n"
    "STAGE: entity-discovery\n"
    "PAYLOAD: {sentence}\n"
)

_RELATION_PROMPT = (
    "You are the relation-extraction agent. Given a sentence and its entities, "
    "extract ONE object property. Return ONLY JSON {{object_property: "
    "{{name, domain, range}} | null}}.\n"
    "STAGE: relation-extraction\n"
    "PAYLOAD: {payload}\n"
)


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return f.read_text(encoding="utf-8")


class _Model:
    """Accumulated ontology, insertion-ordered. Nodes/edges tagged seed|new."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.origin: dict[str, str] = {}        # class -> "seed"|"new"
        self.obj_props: list[dict] = []         # each: {name,domain,range,origin}
        # alignment map: normalized key -> canonical class name actually kept
        self._by_norm: dict[str, str] = {}

    # -- classes -----------------------------------------------------------
    def add_class(self, c: str, origin: str) -> Optional[str]:
        """Add a class with schema alignment. Returns the canonical name used,
        or None if nothing new was added (already present under same name)."""
        if not c:
            return None
        key = _norm(c)
        if key in self._by_norm:
            return None  # aligned to an existing class -> no new node
        if c in self.classes:
            return None
        self.classes.append(c)
        self.origin[c] = origin
        self._by_norm[key] = c
        return c

    def canonical(self, c: str) -> str:
        return self._by_norm.get(_norm(c), c)

    # -- object properties -------------------------------------------------
    def add_obj(self, p: dict) -> bool:
        if p not in self.obj_props:
            self.obj_props.append(p)
            return True
        return False

    def to_graph(self) -> dict:
        attrs: dict[str, list[str]] = {c: [] for c in self.classes}
        nodes = [
            {"data": {"id": c, "label": c, "type": "class",
                      "attributes": attrs.get(c, []),
                      "origin": self.origin.get(c, "new")}}
            for c in self.classes
        ]
        edges = [
            {"data": {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": p["name"], "origin": p.get("origin", "new")}}
            for p in self.obj_props
        ]
        return {"nodes": nodes, "edges": edges}


def _load_seed(input_dir: Path, model: _Model) -> int:
    """Pre-load classes + object-property edges from seed_kg.ttl if present."""
    f = input_dir / "seed_kg.ttl"
    if not f.exists():
        return 0
    from rdflib import Graph, RDF, RDFS, OWL

    g = Graph()
    g.parse(f, format="turtle")

    def _local(uri) -> str:
        s = str(uri)
        return re.split(r"[#/]", s)[-1]

    n = 0
    for c in g.subjects(RDF.type, OWL.Class):
        if model.add_class(_local(c), "seed"):
            n += 1
    for p in g.subjects(RDF.type, OWL.ObjectProperty):
        dom = next(g.objects(p, RDFS.domain), None)
        rng = next(g.objects(p, RDFS.range), None)
        if dom is None or rng is None:
            continue
        d, r = _local(dom), _local(rng)
        model.add_class(d, "seed")
        model.add_class(r, "seed")
        model.add_obj({"name": _local(p),
                       "domain": model.canonical(d),
                       "range": model.canonical(r),
                       "origin": "seed"})
    return n


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_text(input_dir)
    sentences = _sentences(text)

    model = _Model()
    seed_classes = _load_seed(input_dir, model)
    steps: list[dict] = []

    # ---- Stage 1: entity-discovery --------------------------------------
    discovered: list[list[str]] = []   # per-sentence raw entity names
    added_entities: list[str] = []
    for s in sentences:
        raw = llm.complete(_ENTITY_PROMPT.format(sentence=s),
                           temperature=0.0, json_schema={"type": "object"})
        try:
            ents = json.loads(raw).get("entities", [])
        except json.JSONDecodeError:
            ents = []
        discovered.append(ents)
        for e in ents:
            # provisionally add as new class (alignment refines later, but
            # add_class already aligns case/number against existing classes)
            if model.add_class(e, "new"):
                added_entities.append(e)
    steps.append({
        "step": 1, "stage": "entity-discovery", "cq": "(discover)",
        "agent": "entity-discovery",
        "added": {"classes": added_entities, "object_properties": []},
        "note": f"discovered {len(added_entities)} new entit"
                f"{'y' if len(added_entities) == 1 else 'ies'} from "
                f"{len(sentences)} sentence(s)",
        "graph": model.to_graph(),
    })

    # ---- Stage 2: relation-extraction -----------------------------------
    raw_edges: list[dict] = []
    added_rel: list[dict] = []
    for s, ents in zip(sentences, discovered):
        payload = json.dumps({"sentence": s, "entities": ents},
                             ensure_ascii=False)
        raw = llm.complete(_RELATION_PROMPT.format(payload=payload),
                           temperature=0.0, json_schema={"type": "object"})
        try:
            rel = json.loads(raw).get("object_property")
        except json.JSONDecodeError:
            rel = None
        if not rel:
            continue
        edge = {"name": rel["name"],
                "domain": model.canonical(rel["domain"]),
                "range": model.canonical(rel["range"]),
                "origin": "new"}
        raw_edges.append(edge)
        if model.add_obj(edge):
            added_rel.append(edge)
    steps.append({
        "step": 2, "stage": "relation-extraction", "cq": "(extract)",
        "agent": "relation-extraction",
        "added": {"classes": [], "object_properties": added_rel},
        "note": f"extracted {len(added_rel)} object propert"
                f"{'y' if len(added_rel) == 1 else 'ies'}",
        "graph": model.to_graph(),
    })

    # ---- Stage 3: schema-alignment --------------------------------------
    # Report variants merged during discovery (case/number) against any class
    # already present (seed or earlier sentence) under the same normalized key.
    merged: list[dict] = []
    for ents in discovered:
        for e in ents:
            canon = model.canonical(e)
            if canon != e:  # surface form differs from the kept canonical class
                rec = {"variant": e, "merged_into": canon}
                if rec not in merged:
                    merged.append(rec)
    steps.append({
        "step": 3, "stage": "schema-alignment", "cq": "(align)",
        "agent": "schema-alignment",
        "added": {"classes": [], "object_properties": []},
        "merged": merged,
        "note": f"aligned {len(merged)} class variant(s) to existing classes",
        "graph": model.to_graph(),
    })

    # ---- Stage 4: conflict-resolution -----------------------------------
    # Drop exact-duplicate edges and reverse-direction duplicates (keep first).
    kept: list[dict] = []
    removed: list[dict] = []
    seen: set[tuple] = set()           # (name, domain, range)
    seen_pairs: set[tuple] = set()     # (name, frozenset{domain,range})
    for e in model.obj_props:
        key = (e["name"], e["domain"], e["range"])
        rkey = (e["name"], frozenset((e["domain"], e["range"])))
        if key in seen:
            removed.append({**e, "reason": "duplicate"})
            continue
        if rkey in seen_pairs:
            removed.append({**e, "reason": "reverse-duplicate"})
            continue
        seen.add(key)
        seen_pairs.add(rkey)
        kept.append(e)
    model.obj_props = kept
    steps.append({
        "step": 4, "stage": "conflict-resolution", "cq": "(resolve)",
        "agent": "conflict-resolution",
        "added": {"classes": [], "object_properties": []},
        "removed": removed,
        "note": f"removed {len(removed)} conflicting/duplicate edge(s)",
        "graph": model.to_graph(),
    })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    new_classes = sum(1 for c in model.classes if model.origin.get(c) == "new")
    manifest = {
        "method": "karma",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "seed_classes": seed_classes,
        "counts": {
            "classes": len(model.classes),
            "new_classes": new_classes,
            "object_properties": len(model.obj_props),
            "aligned": len(merged),
            "conflicts_removed": len(removed),
        },
        "files": ["ontology.ttl", "ontology.json", "steps.json"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--backend", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend), ensure_ascii=False))
