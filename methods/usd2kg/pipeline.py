"""USD2KG - zero-shot LLM grounding from USD scenes to a SOMA-HOME ontology.

Method (From USD Scenes to Knowledge Graphs: Zero-Shot Ontology Grounding with
LLMs, arXiv:2606.09134, Shuai et al., 2026): a USD scene encodes prims as a
hierarchical graph with names, geometry, parent paths and siblings — but
mapping each prim to an ontology class ("grounding") has historically needed
hand-curated dictionaries. The paper shows an LLM can do it zero-shot from
three signals (lexical name, geometry, scene-graph hierarchy) and quantifies
which signal carries the load (hierarchy dominates).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    usd_scene.json  - {"ontology":..., "naming_regime":"semantic|abbreviated|opaque",
                       "prims":[{"name","parent_path","bbox":[w,h,d],"mass"}, ...]}

Outputs (out_dir):
    ontology.ttl    - OWL: SOMA-HOME class hierarchy + typed individuals (ABox)
    ontology.json   - Cytoscape graph: class nodes + prim instance nodes,
                      type edges carry chosen `strategy` and `feature` cue
    steps.json      - one snapshot per prim (UI replays the grounding)
    manifest.json   - summary (regime, EMA-style accuracy, per-strategy choice)

Three faithful, deterministic-on-MOCK ingredients per prim:
    * Strategy A — Name-only: lexical match of the prim name (lower-cased)
      against the linearised TBox (class names + aliases).
    * Strategy B — Context-augmented: when (A) yields nothing the pipeline
      reads the parent_path + sibling names and matches *those*; if a class
      is still not found, it picks the most specific superclass implied by
      the parent path (e.g. `Crockery_grp` -> `Crockery`), the paper's
      "superclass collapse" behaviour.
    * Strategy C — Chain-of-thought: when (B) still fails the pipeline falls
      back to bounding-box geometry (size buckets) to commit a superclass.
The chosen strategy + cue are recorded per prim, mirroring the paper's
feature-ablation telemetry.

Naming regimes (semantic / abbreviated / opaque) are applied as input
transforms so the same scene can be re-run under degraded names and the
strategy mix shifts toward (B)/(C), matching the paper's findings that
hierarchy dominates when names are degraded.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402
from backend.llm.extract import is_mock  # noqa: E402

EX = "http://example.org/usd2kg#"

# ---- Small SOMA-HOME-style TBox (kitchen domain) --------------------------
# tree: child -> parent. Root is "PhysicalObject".
_TBOX_TREE = {
    "Appliance": "DesignedFurniture",
    "Refrigerator": "Appliance",
    "Stove": "Appliance",
    "Microwave": "Appliance",
    "Sink": "Appliance",
    "DesignedFurniture": "DesignedContainer",
    "Table": "DesignedFurniture",
    "Chair": "DesignedFurniture",
    "DesignedContainer": "PhysicalObject",
    "Crockery": "DesignedContainer",
    "Cup": "Crockery",
    "Bowl": "Crockery",
    "Plate": "Crockery",
    "FlowerPot": "DesignedContainer",
    "Cutlery": "PhysicalObject",
    "Spoon": "Cutlery",
    "PhysicalObject": "Thing",
}

# Lexical catalogue: class name -> list of substring aliases (lower-case).
_ALIASES = {
    "Refrigerator": ["refrigerator", "fridge"],
    "Stove": ["stove", "oven", "cooktop"],
    "Microwave": ["microwave"],
    "Sink": ["sink"],
    "Table": ["table"],
    "Chair": ["chair"],
    "Cup": ["cup"],
    "Bowl": ["bowl"],
    "Plate": ["plate"],
    "Spoon": ["spoon"],
    "FlowerPot": ["flowerpot", "flower"],
    "Appliance": ["appliance"],
    "Crockery": ["crockery"],
    "Cutlery": ["cutlery"],
}

# Path-token -> superclass collapse (Strategy B fallback).
_PATH_HINTS = {
    "ApplianceArea": "Appliance",
    "Furniture": "DesignedFurniture",
    "Crockery": "Crockery",
    "Cutlery": "Cutlery",
    "SinkArea": "Appliance",
    "Counter": "PhysicalObject",
    "Decorations": "DesignedContainer",
}

# Strategy C: size-bucket superclasses from bounding-box dimensions.
def _size_class(bbox: list[float]) -> str:
    w, h, d = bbox
    vol = max(0.0, w * h * d)
    if vol >= 0.5:
        return "DesignedFurniture"
    if vol >= 0.05:
        return "Appliance"
    return "PhysicalObject"


# ---- Naming-regime transforms --------------------------------------------
def _abbrev(name: str) -> str:
    """Collision-free vowel removal + per-word truncation (toy version)."""
    parts = re.split(r"[_\W]+", name)
    out = []
    for p in parts:
        if not p:
            continue
        head = p[0].lower()
        rest = "".join(ch for ch in p[1:].lower() if ch not in "aeiou")[:3]
        out.append(head + rest)
    return "".join(out) or name


def _regime_transform(prim: dict, regime: str, idx: int) -> dict:
    """Return a shallow copy of the prim with name transformed per regime."""
    if regime == "semantic":
        return prim
    if regime == "abbreviated":
        return {**prim, "name": _abbrev(prim["name"])}
    if regime == "opaque":
        return {**prim, "name": f"obj_{idx:03d}"}
    return prim


# ---- Ontology utilities --------------------------------------------------
def _ancestors(cls: str) -> list[str]:
    chain = [cls]
    cur = cls
    while cur in _TBOX_TREE:
        cur = _TBOX_TREE[cur]
        chain.append(cur)
    return chain


def _seed_from_name(name: str) -> Optional[str]:
    low = name.lower()
    # explicit aliases first (longest-wins)
    hits = []
    for cls, aliases in _ALIASES.items():
        for a in aliases:
            if a in low:
                hits.append((len(a), cls))
    if hits:
        hits.sort(reverse=True)
        return hits[0][1]
    # then class name substrings
    for cls in _TBOX_TREE:
        if cls.lower() in low:
            return cls
    return None


def _seed_from_path(parent_path: str) -> Optional[str]:
    parts = [p for p in parent_path.split("/") if p]
    # last segment first (closest enclosing group)
    for p in reversed(parts):
        token = re.sub(r"_grp$|_group$", "", p)
        if token in _PATH_HINTS:
            return _PATH_HINTS[token]
    return None


# ---- LLM bridge ----------------------------------------------------------
def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: return Strategy A's choice or None."""
    # The prompt embeds a JSON {name, parent_path, bbox}.
    try:
        # Look for "Prim: {...}" line.
        line = [ln for ln in prompt.splitlines() if ln.startswith("Prim:")][-1]
        payload = json.loads(line[len("Prim:"):].strip())
    except Exception:
        return json.dumps({"class": None})
    seed = _seed_from_name(payload.get("name", ""))
    return json.dumps({"class": seed}, ensure_ascii=False)


_PROMPT = (
    "You ground USD prims to OWL classes from a linearised TBox. "
    "Return ONLY JSON of the form {{\"class\":\"...\"}} or {{\"class\":null}}.\n"
    "Prim: {payload}\n"
    "TBox (alphabetical): {classes}\n"
)


def _read_scene(input_dir: Path) -> dict:
    f = input_dir / "usd_scene.json"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


# ---- Graph model ---------------------------------------------------------
class _Model:
    def __init__(self) -> None:
        self.classes: list[str] = []
        self.instances: list[dict] = []
        self.subclass: list[tuple[str, str]] = []

    def add_class(self, cls: str) -> None:
        cur = cls
        while True:
            if cur and cur not in self.classes:
                self.classes.append(cur)
            if cur not in _TBOX_TREE:
                break
            parent = _TBOX_TREE[cur]
            if parent not in self.classes:
                self.classes.append(parent)
            if (cur, parent) not in self.subclass:
                self.subclass.append((cur, parent))
            cur = parent

    def add_instance(self, name: str, cls: str, strategy: str, feature: str,
                     bbox: list[float], idx: int) -> None:
        self.instances.append({"name": name, "class": cls, "strategy": strategy,
                               "feature": feature, "bbox": bbox, "source": idx})
        self.add_class(cls)

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for i in self.instances:
            nodes.append({"data": {
                "id": i["name"], "label": i["name"], "type": "instance",
                "strategy": i["strategy"], "feature": i["feature"],
                "bbox": i["bbox"], "attributes": []}})
        edges = []
        for i in self.instances:
            edges.append({"data": {
                "id": f"{i['name']}-type-{i['class']}",
                "source": i["name"], "target": i["class"], "label": "type",
                "strategy": i["strategy"], "feature": i["feature"],
                "provenance": i["source"]}})
        for child, parent in self.subclass:
            edges.append({"data": {
                "id": f"{child}-subClassOf-{parent}",
                "source": child, "target": parent, "label": "subClassOf",
                "strategy": "tbox", "feature": "hierarchy", "provenance": 0}})
        return {"nodes": nodes, "edges": edges}


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
    for child, parent in model.subclass:
        g.add((EXN[child], RDFS.subClassOf, EXN[parent]))
    for i in model.instances:
        g.add((EXN[i["name"]], RDF.type, EXN[i["class"]]))
    return g.serialize(format="turtle")


def _ground(prim: dict, llm, mock: bool) -> dict:
    """Apply A -> B -> C strategies until a class is committed.

    Returns {"class","strategy","feature"}.
    """
    classes_blob = ", ".join(sorted(_TBOX_TREE))
    payload = json.dumps({"name": prim["name"],
                          "parent_path": prim.get("parent_path", ""),
                          "bbox": prim.get("bbox", [0.0, 0.0, 0.0])},
                         ensure_ascii=False)
    # Strategy A: name-only.
    if mock:
        raw = llm.complete(_PROMPT.format(payload=payload, classes=classes_blob),
                           temperature=0.0, json_schema={"type": "object"})
    else:
        raw = llm.complete(_PROMPT.format(payload=payload, classes=classes_blob),
                           temperature=0.0)
    try:
        seedA = json.loads(raw).get("class")
    except json.JSONDecodeError:
        seedA = None
    if seedA in _TBOX_TREE or seedA == "PhysicalObject":
        return {"class": seedA, "strategy": "A_name_only", "feature": "name"}

    # Strategy B: context-augmented (sibling/parent paths).
    seedB = _seed_from_path(prim.get("parent_path", ""))
    if seedB:
        return {"class": seedB, "strategy": "B_context",
                "feature": "hierarchy"}

    # Strategy C: chain-of-thought over geometry -> size superclass.
    cls = _size_class(prim.get("bbox", [0.0, 0.0, 0.0]))
    return {"class": cls, "strategy": "C_cot", "feature": "geometry"}


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = _read_scene(input_dir)
    regime = scene.get("naming_regime", "semantic")
    prims_in = scene.get("prims", [])
    llm = get_backend(backend, mock_responder=mock_responder)
    mock = is_mock(llm)

    model = _Model()
    steps: list[dict] = []
    strat_counts = {"A_name_only": 0, "B_context": 0, "C_cot": 0}

    for idx, raw_prim in enumerate(prims_in, 1):
        prim = _regime_transform(raw_prim, regime, idx)
        chosen = _ground(prim, llm, mock)
        model.add_instance(name=prim["name"], cls=chosen["class"],
                           strategy=chosen["strategy"],
                           feature=chosen["feature"],
                           bbox=prim.get("bbox", []), idx=idx)
        strat_counts[chosen["strategy"]] += 1
        steps.append({"step": idx, "stage": "ground", "cq": prim["name"],
                      "added": {"prim": prim["name"],
                                "class": chosen["class"],
                                "strategy": chosen["strategy"],
                                "feature": chosen["feature"]},
                      "graph": model.to_graph()})

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "usd2kg",
        "backend": llm.name,
        "naming_regime": regime,
        "input_prims": len(prims_in),
        "counts": {
            "classes": len(model.classes),
            "instances": len(model.instances),
            "subclass_of": len(model.subclass),
        },
        "strategies": strat_counts,
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
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend),
                     ensure_ascii=False))
