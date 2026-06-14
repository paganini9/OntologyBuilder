"""Ontology-Grounded KG under Wikidata schema.

Method (arXiv:2412.20942, "Ontology-grounded Automatic Knowledge Graph
Construction by LLM under Wikidata schema"):

    1. Author an ontology from Competency Questions (CQs) - same memoryless,
       one-CQ-at-a-time heuristic as CQbyCQ.
    2. Ground the locally-invented object properties onto Wikidata's standard
       schema (P-id properties), so the KG is compatible with the global public
       KG. Grounding is demonstrated offline/deterministically via a small
       built-in dictionary (e.g. consistsOf -> P527 "has part").

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    competency_questions.txt  - one CQ per line (blank lines / # comments ignored)

Outputs (out_dir):
    ontology.ttl    - OWL ontology, grounded props link to Wikidata (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges (+ wikidata ids)
    steps.json      - per-CQ authoring snapshots + a final grounding snapshot
    manifest.json   - summary (backend, counts, file list)

The authoring LLM step is abstracted: with a real backend (gemini/anthropic) the
model extracts the fragment; with MOCK a deterministic heuristic does, so the
output is reproducible and testable. The grounding pass is always deterministic.
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
WD = "http://www.wikidata.org/entity/"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its",
}

# relational verbs -> canonical object-property name
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

_DATA = {
    "name", "id", "identifier", "weight", "price", "cost", "color", "colour",
    "size", "dimension", "dimensions", "quantity", "length", "width", "height",
    "code", "version", "tolerance",
}

# Built-in grounding: local object-property name -> (Wikidata P-id, label).
# Demonstrates the Wikidata-schema alignment offline & deterministically.
_WIKIDATA = {
    "consistsOf": ("P527", "has part"),
    "partOf": ("P361", "part of"),
    "madeOf": ("P186", "made from material"),
    "composedOf": ("P527", "has part"),
    "assembledFrom": ("P527", "has part"),
    "supplies": ("P176", "manufacturer"),
    "has": ("P527", "has part"),
    "contains": ("P527", "has part"),
    "includes": ("P527", "has part"),
    "performs": ("P366", "has use"),
    "satisfies": ("P366", "has use"),
    "uses": ("P366", "has use"),
    "produces": ("P1056", "product or material produced"),
    "requires": ("P1013", "criterion used"),
    "belongsTo": ("P361", "part of"),
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_classes(cq: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", cq):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM: parse the CQ -> ontology fragment JSON."""
    cq = prompt.split("Competency question:")[-1].split("\n")[0].strip()
    classes = _extract_classes(cq)
    words = re.findall(r"[a-zA-Z]+", cq.lower())

    # Exclude words that are actually class nouns (e.g. "Part" -> "part") so a
    # class noun doesn't get mistaken for a relational verb ("partOf").
    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    object_properties = []
    if rel and len(classes) >= 2:
        object_properties.append(
            {"name": rel, "domain": classes[0], "range": classes[1]}
        )

    data_properties = []
    if classes:
        for w in words:
            if w in _DATA:
                dp = {"name": w, "domain": classes[0], "datatype": "string"}
                if dp not in data_properties:
                    data_properties.append(dp)

    return json.dumps(
        {
            "classes": classes,
            "object_properties": object_properties,
            "data_properties": data_properties,
            "restrictions": [],
        },
        ensure_ascii=False,
    )


_PROMPT = (
    "You are an ontology engineer. Convert ONE competency question into a small "
    "OWL ontology fragment. Return ONLY JSON with keys: classes (list of "
    "PascalCase class names), object_properties (list of {{name, domain, range}}), "
    "data_properties (list of {{name, domain, datatype}}), restrictions (list).\n"
    "Competency question: {cq}\n"
)


def _read_cqs(input_dir: Path) -> list[str]:
    f = input_dir / "competency_questions.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    cqs = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            cqs.append(line)
    return cqs


class _Model:
    """Accumulated ontology, in insertion order for deterministic output.

    Each object property may carry an extra `wikidata` key once grounded, e.g.
    {"name": "consistsOf", "domain": "Product", "range": "Part",
     "wikidata": "P527", "wikidata_label": "has part"}.
    """

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []
        self.data_props: list[dict] = []

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def add_obj(self, p: dict) -> bool:
        if p not in self.obj_props:
            self.obj_props.append(p)
            return True
        return False

    def add_data(self, p: dict) -> bool:
        if p not in self.data_props:
            self.data_props.append(p)
            return True
        return False

    def to_graph(self) -> dict:
        attrs: dict[str, list[str]] = {c: [] for c in self.classes}
        for dp in self.data_props:
            attrs.setdefault(dp["domain"], [])
            if dp["name"] not in attrs[dp["domain"]]:
                attrs[dp["domain"]].append(dp["name"])
        nodes = [
            {"data": {"id": c, "label": c, "type": "class",
                      "attributes": attrs.get(c, [])}}
            for c in self.classes
        ]
        edges = []
        for p in self.obj_props:
            data = {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                    "source": p["domain"], "target": p["range"],
                    "label": p["name"]}
            wd = p.get("wikidata")
            if wd:
                data["wikidata"] = wd
                data["wikidata_label"] = p.get("wikidata_label", "")
                data["label"] = f"{p['name']} ({wd})"
            edges.append({"data": data})
        return {"nodes": nodes, "edges": edges}


def _ground(model: _Model) -> list[dict]:
    """Map each object property to a Wikidata property via the built-in dict.

    Mutates the props in place (adds wikidata / wikidata_label) and returns the
    list of grounded property dicts (for the step summary)."""
    grounded = []
    for p in model.obj_props:
        hit = _WIKIDATA.get(p["name"])
        if hit:
            pid, label = hit
            p["wikidata"] = pid
            p["wikidata_label"] = label
            grounded.append(dict(p))
    return grounded


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, XSD, URIRef
    from rdflib.namespace import SKOS

    g = Graph()
    EXN = Namespace(EX)
    WDN = Namespace(WD)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    g.bind("skos", SKOS)
    g.bind("wd", WDN)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
        wd = p.get("wikidata")
        if wd:
            wd_uri = URIRef(WD + wd)
            g.add((pr, SKOS.exactMatch, wd_uri))
            g.add((pr, RDFS.seeAlso, wd_uri))
    for p in model.data_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.DatatypeProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, XSD.string))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    cqs = _read_cqs(input_dir)

    model = _Model()
    steps = []
    # --- Phase 1: authoring (one step per CQ) ---
    for i, cq in enumerate(cqs, 1):
        raw = llm.complete(_PROMPT.format(cq=cq), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"classes": [], "object_properties": [],
                    "data_properties": [], "restrictions": []}

        added_c, added_o, added_d = [], [], []
        for c in frag.get("classes", []):
            if model.add_class(c):
                added_c.append(c)
        for p in frag.get("object_properties", []):
            for k in ("domain", "range"):
                if model.add_class(p.get(k, "")):
                    added_c.append(p[k])
            if model.add_obj(p):
                added_o.append(p)
        for p in frag.get("data_properties", []):
            if model.add_class(p.get("domain", "")):
                added_c.append(p["domain"])
            if model.add_data(p):
                added_d.append(p)

        steps.append({
            "step": i,
            "cq": cq,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": added_d},
            "graph": model.to_graph(),
        })

    # --- Phase 2: Wikidata grounding (one final step) ---
    grounded = _ground(model)
    steps.append({
        "step": len(cqs) + 1,
        "cq": "(wikidata grounding)",
        "added": {
            "classes": [],
            "object_properties": grounded,
            "data_properties": [],
            "grounded": [
                {"name": p["name"], "wikidata": p["wikidata"],
                 "wikidata_label": p["wikidata_label"]}
                for p in grounded
            ],
        },
        "graph": model.to_graph(),
    })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "ontology-grounded-wikidata",
        "backend": llm.name,
        "input_cqs": len(cqs),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "data_properties": len(model.data_props),
            "grounded_properties": len(grounded),
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
