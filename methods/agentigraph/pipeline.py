"""AGENTiGraph - interactive, multi-agent knowledge-graph construction.

Method (AGENTiGraph, CIKM 2025 Demo / arXiv 2508.02999):
a non-expert grows a knowledge graph through natural-language utterances. A set
of agents processes each user turn via three stages -- intent classification ->
task planning -> automatic knowledge integration -- and the KG grows turn by
turn (user in-the-loop). Unlike a single batch extraction, every turn changes
the graph a little (or, for a query, only records the intent).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    user_turns.txt  - one user utterance per line (blank lines / # comments ignored)
    seed_text.txt   - optional initial domain context (seeds initial classes)

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per turn (with intent), so the UI can replay
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
classifies intent and integrates knowledge; with MOCK a deterministic rule-based
agent does, so the output is reproducible and testable.
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
    "By", "With", "That", "This", "Each", "Its", "Let", "Add", "Connect", "Link",
    "Please", "Show", "List",
}

# relational verbs -> canonical object-property name (reused from cqbycq)
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
    "connect": "connectsTo", "connects": "connectsTo",
    "link": "linksTo", "links": "linksTo",
}

# words that signal an explicit add/connect intent
_ADD_WORDS = {"add", "connect", "link", "create", "introduce",
              "추가", "연결"}  # 추가 / 연결

_QUESTION_STARTS = {"what", "which", "who", "how", "where", "when", "why",
                    "is", "are", "does", "do", "can"}


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


def _classify_intent(turn: str) -> str:
    """Rule-based intent classification (mock agent)."""
    t = turn.strip()
    low = t.lower()
    first = re.findall(r"[a-zA-Z가-힣]+", low)
    first_word = first[0] if first else ""

    # query: ends with '?' or starts with an interrogative word
    if t.endswith("?") or first_word in _QUESTION_STARTS:
        return "query"

    words = set(re.findall(r"[a-zA-Z가-힣]+", low))
    classes = _extract_classes(t)
    has_rel = any(w in _REL for w in words)

    # add-relation: explicit add/connect verb, or >=2 entities + a relation verb
    if (words & _ADD_WORDS) or (len(classes) >= 2 and has_rel):
        if len(classes) >= 2:
            return "add-relation"
        return "add-entity"

    return "add-entity"


def _integrate(turn: str) -> dict:
    """Extract the ontology fragment for an add-* turn (cqbycq heuristic)."""
    classes = _extract_classes(turn)
    words = re.findall(r"[a-zA-Z]+", turn.lower())
    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)

    object_properties = []
    if rel and len(classes) >= 2:
        object_properties.append(
            {"name": rel, "domain": classes[0], "range": classes[1]}
        )
    return {"classes": classes, "object_properties": object_properties,
            "data_properties": []}


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the multi-agent LLM.

    Parses the user turn out of the prompt, classifies its intent, and (for
    add-* intents) returns the integration fragment. For a query it returns an
    empty fragment and the intent only.
    """
    turn = prompt.split("User turn:")[-1].split("\n")[0].strip()
    intent = _classify_intent(turn)
    if intent == "query":
        frag = {"classes": [], "object_properties": [], "data_properties": []}
    else:
        frag = _integrate(turn)
    return json.dumps({"intent": intent, **frag}, ensure_ascii=False)


_PROMPT = (
    "You are AGENTiGraph's multi-agent pipeline. For ONE user turn, (1) classify "
    "the intent as one of add-entity / add-relation / query, then (2) plan and "
    "return the knowledge to integrate. Return ONLY JSON with keys: intent, "
    "classes (PascalCase names), object_properties (list of {{name, domain, "
    "range}}), data_properties (list of {{name, domain, datatype}}).\n"
    "User turn: {turn}\n"
)


def _read_turns(input_dir: Path) -> list[str]:
    f = input_dir / "user_turns.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    turns = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            turns.append(line)
    return turns


def _read_seed(input_dir: Path) -> list[str]:
    f = input_dir / "seed_text.txt"
    if not f.exists():
        return []
    return _extract_classes(f.read_text(encoding="utf-8"))


class _Model:
    """Accumulated ontology, in insertion order for deterministic output."""

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
        edges = [
            {"data": {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": p["name"]}}
            for p in self.obj_props
        ]
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
    turns = _read_turns(input_dir)
    seed_classes = _read_seed(input_dir)

    model = _Model()
    steps = []

    # Seed the graph from the optional domain context (step 0-style integration,
    # folded into the model before the conversation begins).
    for c in seed_classes:
        model.add_class(c)

    intent_counts: dict[str, int] = {}
    for i, turn in enumerate(turns, 1):
        raw = llm.complete(_PROMPT.format(turn=turn), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"intent": "add-entity", "classes": [],
                    "object_properties": [], "data_properties": []}

        intent = frag.get("intent", "add-entity")
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

        added_c, added_o, added_d = [], [], []
        # query turns record intent only -> no graph change
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
            "cq": turn,
            "intent": intent,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": added_d},
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
        "method": "agentigraph",
        "backend": llm.name,
        "input_turns": len(turns),
        "seed_classes": len(seed_classes),
        "intents": intent_counts,
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
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
