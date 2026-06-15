"""Hierarchical multi-level extraction (Are LLMs Effective KG Constructors?).

Method (arXiv:2510.11297, "Are Large Language Models Effective Knowledge Graph
Constructors?"): instead of extracting triples in one shot, knowledge is mined
from text in three levels that refine one another:

    L1  entities/concepts      -> classes
    L2  relations              -> object properties between entity pairs
    L3  super/sub hierarchy    -> rdfs:subClassOf (is-a)

Each level consumes the previous level's output and grows the structure, so the
UI can replay "entities -> relations -> hierarchy".

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free body text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL ontology with hierarchy (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per L1 sentence + one each for L2 and L3
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
does per-level extraction; with MOCK a deterministic heuristic does, so the
output is reproducible and testable.
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
    "drive": "drives", "drives": "drives", "driven": "drives",
    "power": "powers", "powers": "powers", "powered": "powers",
    "cool": "cools", "cools": "cools",
    "control": "controls", "controls": "controls",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_classes(text: str) -> list[str]:
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


# ---- mock LLM responders (one per level) ------------------------------------

def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM, dispatched by level marker in prompt."""
    if "LEVEL: L1" in prompt:
        sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
        return json.dumps({"classes": _extract_classes(sentence)},
                          ensure_ascii=False)

    if "LEVEL: L2" in prompt:
        # Input: a list of sentences and the known classes; emit object props.
        body = prompt.split("Sentences:")[-1]
        sentences = [s for s in body.split("\n") if s.strip()
                     and not s.startswith("Known")]
        known = []
        m = re.search(r"Known classes:\s*(.*)", prompt)
        if m:
            known = [c.strip() for c in m.group(1).split(",") if c.strip()]
        known_set = set(known)
        class_words = {c.lower() for c in known} | {c.lower() + "s" for c in known}
        props: list[dict] = []
        for sent in sentences:
            present = [c for c in known if re.search(rf"\b{re.escape(c)}s?\b", sent)]
            if len(present) < 2:
                continue
            words = re.findall(r"[a-zA-Z]+", sent.lower())
            rel = next((_REL[w] for w in words
                        if w in _REL and w not in class_words), None)
            if rel:
                p = {"name": rel, "domain": present[0], "range": present[1]}
                if p not in props:
                    props.append(p)
        return json.dumps({"object_properties": props}, ensure_ascii=False)

    if "LEVEL: L3" in prompt:
        m = re.search(r"Known classes:\s*(.*)", prompt)
        classes = []
        if m:
            classes = [c.strip() for c in m.group(1).split(",") if c.strip()]
        subs: list[dict] = []
        cset = set(classes)
        # Compound name whose tail matches an existing class -> child subClassOf parent.
        for c in classes:
            for parent in classes:
                if parent == c:
                    continue
                if len(c) > len(parent) and c.endswith(parent):
                    pair = {"child": c, "parent": parent}
                    if pair not in subs:
                        subs.append(pair)
        return json.dumps({"subclass_of": subs}, ensure_ascii=False)

    return json.dumps({}, ensure_ascii=False)


_L1_PROMPT = (
    "You are an ontology engineer. LEVEL: L1 (entity extraction).\n"
    "Extract core concepts as PascalCase class names. Return ONLY JSON with key "
    "classes (list).\n"
    "Sentence: {sentence}\n"
)

_L2_PROMPT = (
    "You are an ontology engineer. LEVEL: L2 (relation extraction).\n"
    "Given the known classes and the sentences, extract relations as object "
    "properties. Return ONLY JSON with key object_properties (list of "
    "{{name, domain, range}}).\n"
    "Known classes: {classes}\n"
    "Sentences:\n{sentences}\n"
)

_L3_PROMPT = (
    "You are an ontology engineer. LEVEL: L3 (hierarchy extraction).\n"
    "Given the known classes, infer is-a / super-sub relations. Return ONLY JSON "
    "with key subclass_of (list of {{child, parent}}).\n"
    "Known classes: {classes}\n"
)


def _infer_subclasses(classes: list[str]) -> list[dict]:
    """Deterministic L3 rule (shared by mock and real paths).

    A compound class name whose tail matches another known class becomes a
    child (rdfs:subClassOf) of that class. This is the same rule encoded in
    mock_responder's L3 branch, lifted out so the real backend gets identical
    hierarchy behaviour without consulting the model.
    """
    subs: list[dict] = []
    for c in classes:
        for parent in classes:
            if parent == c:
                continue
            if len(c) > len(parent) and c.endswith(parent):
                pair = {"child": c, "parent": parent}
                if pair not in subs:
                    subs.append(pair)
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
        self.obj_props: list[dict] = []
        self.data_props: list[dict] = []
        self.subclass: list[dict] = []  # {child, parent}

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

    model = _Model()
    steps: list[dict] = []
    step_no = 0
    mock = is_mock(llm)
    real_props: list[dict] = []  # L2 relations accumulated on the real path

    # ---- L1: per-sentence entity extraction ---------------------------------
    for sent in sentences:
        step_no += 1
        if mock:
            raw = llm.complete(_L1_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"classes": []}
            sent_classes = list(frag.get("classes", []))
        else:
            # Real backend: one extraction per sentence. Subjects/objects become
            # L1 classes; the same triples' relations feed L2 below.
            triples = extract_triples(llm, sent)
            sent_classes = []
            for t in triples:
                for ent in (t["subject"], t["object"]):
                    if ent not in sent_classes:
                        sent_classes.append(ent)
                prop = {"name": t["relation"], "domain": t["subject"],
                        "range": t["object"]}
                if prop not in real_props:
                    real_props.append(prop)
        added_c = []
        for c in sent_classes:
            if model.add_class(c):
                added_c.append(c)
        steps.append({
            "step": step_no,
            "level": "L1",
            "cq": sent,
            "added": {"classes": added_c, "object_properties": [],
                      "data_properties": [], "subclass_of": []},
            "graph": model.to_graph(),
        })

    # ---- L2: relation extraction across sentences ---------------------------
    step_no += 1
    if mock:
        raw = llm.complete(
            _L2_PROMPT.format(classes=", ".join(model.classes),
                              sentences="\n".join(sentences)),
            temperature=0.0, json_schema={"type": "object"})
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"object_properties": []}
        l2_props = list(frag.get("object_properties", []))
    else:
        l2_props = real_props
    added_o = []
    for p in l2_props:
        for k in ("domain", "range"):
            model.add_class(p.get(k, ""))
        if model.add_obj(p):
            added_o.append(p)
    steps.append({
        "step": step_no,
        "level": "L2",
        "cq": "(L2 relations)",
        "added": {"classes": [], "object_properties": added_o,
                  "data_properties": [], "subclass_of": []},
        "graph": model.to_graph(),
    })

    # ---- L3: hierarchy (is-a) inference -------------------------------------
    # Deterministic compound-tail subClassOf rule, identical for both paths.
    step_no += 1
    added_s = []
    for s in _infer_subclasses(list(model.classes)):
        model.add_class(s.get("child", ""))
        model.add_class(s.get("parent", ""))
        if model.add_subclass(s):
            added_s.append(s)
    steps.append({
        "step": step_no,
        "level": "L3",
        "cq": "(L3 hierarchy)",
        "added": {"classes": [], "object_properties": [],
                  "data_properties": [], "subclass_of": added_s},
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
        "method": "are-llms-effective-kgc",
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
