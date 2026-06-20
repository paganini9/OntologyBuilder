"""ontokb-iterative - iterative LLM construction of an ontological knowledge base.

Method (Development of Ontological Knowledge Bases by Leveraging Large Language
Models, arXiv:2601.10436): an ontological KB is built through an *iterative*
knowledge-acquisition cycle -- a first pass drafts the skeleton (classes + the
relations between them), then a refinement pass enriches it (induces the
is-a hierarchy and attaches data attributes). The paper frames this as a
generate -> review -> refine loop; here the loop is two deterministic stages so
the MOCK path is reproducible and golden-testable.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free domain text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL: classes, object properties, subClassOf, datatype props
    ontology.json   - final graph as Cytoscape nodes/edges (data attrs on nodes)
    steps.json      - per-sentence DRAFT snapshots + one REFINE snapshot
    manifest.json   - summary (backend, counts, file list)

Two iterations (both deterministic on the MOCK path):
    1. DRAFT  - per sentence: classes + one object property (skeleton only).
    2. REFINE - over the whole draft: (a) compound-tail subClassOf hierarchy;
       (b) attach data attributes (name/price/weight/...) mentioned for a class.
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
from backend.llm.extract import is_mock, extract_triples  # noqa: E402

EX = "http://example.org/product#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every",
}

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
    "offer": "offers", "offers": "offers",
    "sell": "sells", "sells": "sells", "sold": "sells",
    "supply": "supplies", "supplies": "supplies",
}

_DATA = {
    "name", "id", "identifier", "weight", "price", "cost", "color", "colour",
    "size", "dimension", "dimensions", "quantity", "length", "width", "height",
    "code", "version", "tolerance", "year", "mileage", "model", "brand",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _classes(text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: DRAFT skeleton fragment from one sentence."""
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    classes = _classes(sentence)
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    object_properties = []
    if rel and len(classes) >= 2:
        object_properties.append({"name": rel, "domain": classes[0],
                                  "range": classes[1]})
    return json.dumps({"classes": classes, "object_properties": object_properties},
                      ensure_ascii=False)


_PROMPT = (
    "You are drafting the skeleton of an ontological knowledge base. From the "
    "sentence extract ONLY JSON with keys classes (PascalCase list) and "
    "object_properties (list of {{name, domain, range}}). No data attributes yet.\n"
    "Sentence: {sentence}\n"
)


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[.!?]+", text) if p.strip()]


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("#")]
    return "\n".join(lines)


class _Model:
    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []
        self.subclass: list[dict] = []        # {child, parent}
        self.data_props: list[dict] = []      # {name, domain}

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

    def add_subclass(self, s: dict) -> bool:
        if s not in self.subclass:
            self.subclass.append(s)
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
        edges = [
            {"data": {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": p["name"]}}
            for p in self.obj_props
        ]
        for s in self.subclass:
            edges.append({"data": {
                "id": f"{s['child']}-subClassOf-{s['parent']}",
                "source": s["child"], "target": s["parent"],
                "label": "subClassOf"}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, XSD, URIRef

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
    for s in model.subclass:
        g.add((EXN[s["child"]], RDFS.subClassOf, EXN[s["parent"]]))
    for p in model.data_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.DatatypeProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, XSD.string))
    return g.serialize(format="turtle")


def _refine(model: _Model, sentences: list[str]) -> dict:
    """Refinement pass: induce subClassOf hierarchy + attach data attributes."""
    added_s, added_d = [], []
    # (a) compound-tail subClassOf over the drafted classes
    cset = list(model.classes)
    for c in cset:
        best = None
        for parent in cset:
            if parent != c and len(c) > len(parent) and c.endswith(parent):
                if best is None or len(parent) > len(best):
                    best = parent
        if best is not None:
            s = {"child": c, "parent": best}
            if model.add_subclass(s):
                added_s.append(s)
    # (b) attach data attributes mentioned alongside a class
    for sent in sentences:
        caps = _classes(sent)
        if not caps:
            continue
        domain = caps[0]
        for w in re.findall(r"[a-zA-Z]+", sent.lower()):
            if w in _DATA:
                dp = {"name": w, "domain": domain}
                if model.add_data(dp):
                    added_d.append(dp)
    return {"subclass_of": added_s, "data_properties": added_d}


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_text(input_dir)
    sentences = _split_sentences(text)

    mock = is_mock(llm)
    model = _Model()
    steps: list[dict] = []
    step_no = 0

    # ---- Iteration 1: DRAFT (skeleton: classes + object properties) ---------
    for sent in sentences:
        step_no += 1
        added_c, added_o = [], []
        if mock:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"classes": [], "object_properties": []}
        else:
            frag = {"classes": [], "object_properties": []}
            for t in extract_triples(llm, sent):
                for c in (t["subject"], t["object"]):
                    if c not in frag["classes"]:
                        frag["classes"].append(c)
                frag["object_properties"].append(
                    {"name": t["relation"], "domain": t["subject"],
                     "range": t["object"]})

        for c in frag.get("classes", []):
            if model.add_class(c):
                added_c.append(c)
        for p in frag.get("object_properties", []):
            for k in ("domain", "range"):
                if model.add_class(p.get(k, "")):
                    added_c.append(p[k])
            if model.add_obj(p):
                added_o.append(p)
        steps.append({
            "step": step_no,
            "stage": "draft",
            "cq": f"(draft) {sent}",
            "added": {"classes": added_c, "object_properties": added_o,
                      "subclass_of": [], "data_properties": []},
            "graph": model.to_graph(),
        })

    # ---- Iteration 2: REFINE (hierarchy + data attributes) ------------------
    step_no += 1
    refined = _refine(model, sentences)
    steps.append({
        "step": step_no,
        "stage": "refine",
        "cq": "(refine) induce hierarchy + attach attributes",
        "added": {"classes": [], "object_properties": [],
                  "subclass_of": refined["subclass_of"],
                  "data_properties": refined["data_properties"]},
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
        "method": "ontokb-iterative",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "iterations": 2,
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "subclass_of": len(model.subclass),
            "data_properties": len(model.data_props),
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
