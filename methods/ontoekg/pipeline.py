"""OntoEKG - LLM-driven ontology construction for enterprise knowledge graphs.

Method (Oyewale & Soru, "LLM-Driven Ontology Construction for Enterprise
Knowledge Graphs", arXiv:2602.01276, 2026): a two-phase pipeline that turns
enterprise free text into an OWL ontology.

  Phase A - EXTRACTION: per sentence, the LLM (or a deterministic MOCK heuristic)
            surfaces the core CLASSES (concepts) AND the OBJECT PROPERTIES
            (relations between them). Unlike OLLM -- which targets the taxonomy
            backbone only -- OntoEKG extracts BOTH the classes and the
            inter-class relations.
  Phase B - ENTAILMENT: over the accumulated classes, a subClassOf hierarchy is
            logically structured (entailed) deterministically, then everything is
            RDF-serialized. The hierarchy is layered ON TOP of the extracted
            object properties, so the final ontology has BOTH relational edges
            (object properties) AND an is-a backbone (rdfs:subClassOf).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - enterprise free text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL ontology: owl:Class, owl:ObjectProperty (+domain/range),
                      rdfs:subClassOf hierarchy
    ontology.json   - final graph as Cytoscape nodes/edges (object props + is-a)
    steps.json      - one snapshot per sentence (extraction) + one entailment step
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
extracts (subject, relation, object) triples via the shared extractor; with MOCK
a deterministic heuristic does, so the output is reproducible and testable.
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

EX = "http://example.org/enterprise#"
ROOT = "Entity"  # synthetic top-level class for the entailment hierarchy

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every",
}

# relational verbs -> canonical object-property name (Phase A extraction)
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
    "drive": "drives", "drives": "drives", "driven": "drives",
    "power": "powers", "powers": "powers", "powered": "powers",
    "supply": "supplies", "supplies": "supplies",
    "manage": "manages", "manages": "manages",
    "monitor": "monitors", "monitors": "monitors",
    "control": "controls", "controls": "controls",
    "assemble": "assembledFrom", "assembled": "assembledFrom",
    "report": "reportsTo", "reports": "reportsTo",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_classes(text: str) -> list[str]:
    """Deterministic class extraction: capitalized nouns (minus stop-words)."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM: parse a sentence into the EXTRACTION
    fragment (classes + object_properties), mirroring Phase A.
    """
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    classes = _extract_classes(sentence)
    words = re.findall(r"[a-zA-Z]+", sentence.lower())

    # Don't mistake a class noun ("Part" -> "part") for a relational verb.
    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    object_properties = []
    if rel and len(classes) >= 2:
        object_properties.append(
            {"name": rel, "domain": classes[0], "range": classes[1]}
        )

    return json.dumps(
        {"classes": classes, "object_properties": object_properties},
        ensure_ascii=False,
    )


_PROMPT = (
    "You are an enterprise ontology engineer. From the sentence, extract the core "
    "CLASSES (PascalCase concept names) and the OBJECT PROPERTIES (relations "
    "between two classes). Return ONLY JSON with keys: classes (list), "
    "object_properties (list of {{name, domain, range}}).\n"
    "Sentence: {sentence}\n"
)


def _triples_to_fragment(triples: list[dict]) -> dict:
    """Map real-LLM (subject, relation, object) triples to the SAME EXTRACTION
    fragment shape the mock path emits (classes + object_properties), so the
    downstream merge/step/emit code is shared.
    """
    classes: list[str] = []
    object_properties: list[dict] = []
    for t in triples:
        s, r, o = t.get("subject"), t.get("relation"), t.get("object")
        if not (s and r and o):
            continue
        for c in (s, o):
            if c not in classes:
                classes.append(c)
        op = {"name": r, "domain": s, "range": o}
        if op not in object_properties:
            object_properties.append(op)
    return {"classes": classes, "object_properties": object_properties}


def _entail_hierarchy(classes: list[str]) -> list[dict]:
    """Phase B ENTAILMENT: logically structure the classes into a subClassOf
    hierarchy (deterministic; identical for the MOCK and real backends).

    (a) Compound-tail rule: a class whose name ends with another known class is
        entailed to be its subclass (e.g. "ElectricMotor" subClassOf "Motor").
        Each child attaches to its LONGEST / most specific matching tail parent.
    (b) Root attachment: every remaining top-level class is attached to the
        synthetic root "Entity", giving a single connected hierarchy.
    """
    cset = list(classes)
    subs: list[dict] = []
    has_parent: set[str] = set()

    for c in cset:
        best_parent = None
        for parent in cset:
            if parent == c:
                continue
            if len(c) > len(parent) and c.endswith(parent):
                if best_parent is None or len(parent) > len(best_parent):
                    best_parent = parent
        if best_parent is not None:
            subs.append({"child": c, "parent": best_parent})
            has_parent.add(c)

    for c in cset:
        if c not in has_parent:
            subs.append({"child": c, "parent": ROOT})
    return subs


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return f.read_text(encoding="utf-8")


class _Model:
    """Accumulated ontology, in insertion order for deterministic output."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []     # {name, domain, range}
        self.subclass: list[dict] = []      # {child, parent}

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

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": c, "label": c, "type": "class", "attributes": []}}
            for c in self.classes
        ]
        edges = [
            {"data": {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": p["name"]}}
            for p in self.obj_props
        ]
        edges += [
            {"data": {"id": f"{s['child']}-subClassOf-{s['parent']}",
                      "source": s["child"], "target": s["parent"],
                      "label": "subClassOf"}}
            for s in self.subclass
        ]
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
    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    for s in model.subclass:
        g.add((EXN[s["child"]], RDFS.subClassOf, EXN[s["parent"]]))
    return g.serialize(format="turtle")


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

    # ---- Phase A: EXTRACTION (per sentence) ---------------------------------
    for sent in sentences:
        step_no += 1
        if mock:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"classes": [], "object_properties": []}
        else:
            # Real backend: use the shared triple extractor, then shape the
            # triples into the SAME extraction fragment the merge code consumes.
            frag = _triples_to_fragment(extract_triples(llm, sent))

        added_c, added_o = [], []
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
            "phase": "extraction",
            "cq": f"(extract) {sent}",
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": []},
            "graph": model.to_graph(),
        })

    # ---- Phase B: ENTAILMENT (deterministic hierarchy, both paths) ----------
    step_no += 1
    added_s = []
    for s in _entail_hierarchy(list(model.classes)):
        model.add_class(s.get("parent", ""))  # ensure root "Entity" exists
        model.add_class(s.get("child", ""))
        if model.add_subclass(s):
            added_s.append(s)
    steps.append({
        "step": step_no,
        "phase": "entailment",
        "cq": "(entail) hierarchy",
        "added": {"classes": [ROOT] if ROOT in model.classes else [],
                  "object_properties": [], "data_properties": [],
                  "subclass_of": added_s},
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
        "method": "ontoekg",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "subclass_of": len(model.subclass),
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
