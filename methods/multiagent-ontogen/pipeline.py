"""Multi-Agent Ontology Generation from unstructured text.

Method (Talukder, Mridul, Seneviratne, "Towards Automated Ontology Generation
from Unstructured Text: A Multi-Agent LLM Approach", arXiv 2604.23090, 2026):
an artifact-driven, planning-first pipeline where FOUR specialised LLM roles
collaborate to turn unstructured text into an OWL ontology:

    1. Domain Expert  - reads each sentence, surfaces candidate CONCEPTS
                        (capitalised nouns) and (subject, relation, object)
                        knowledge triples.
    2. Manager        - organises the raw findings into a single, deduplicated
                        PLAN (concepts + relations) before any code is written.
    3. Coder          - turns the plan into OWL FRAGMENTS (classes +
                        object properties with domain/range) in the model.
    4. Quality Assurer- VALIDATES / PRUNES the result: drops self-loops,
                        duplicate edges, and edges with missing endpoints.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - unstructured domain text (split into sentences).

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per ROLE-action, so the UI can show the
                      ontology being planned then built then pruned.
    manifest.json   - summary (backend, counts, role list, file list)

Only the Domain Expert role consults the LLM. With a real backend it uses the
shared `extract_triples` helper; with MOCK a deterministic heuristic does, so the
output is reproducible and golden-tested. Roles 2-4 (Manager/Coder/QA) are
deterministic for BOTH backends.
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
from backend.llm.extract import is_mock, extract_triples  # noqa: E402

EX = "http://example.org/product#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "I",
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
    "drive": "drives", "drives": "drives",
    "control": "controls", "controls": "controls",
    "manage": "manages", "manages": "manages",
    "support": "supports", "supports": "supports",
    "connect": "connectsTo", "connects": "connectsTo",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_classes(sentence: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def _mock_triples(sentence: str) -> list[dict]:
    """Deterministic Domain-Expert extraction for ONE sentence.

    Capitalised nouns are concepts; the first relational verb links the head
    concept to each following concept. Self-loops (same concept repeated) are
    INTENTIONALLY preserved here so the Quality Assurer role has something real
    to prune downstream.
    """
    raw_caps = [w for w in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence)
                if w not in _STOP]
    seq = [_singular(w) for w in raw_caps]  # keeps repeats (e.g. Part ... Part)
    classes = _extract_classes(sentence)    # dedup-ordered, for concept list
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)

    triples: list[dict] = []
    if rel and len(seq) >= 2:
        head = seq[0]
        for obj in seq[1:]:
            triples.append({"subject": head, "relation": rel, "object": obj})
    return triples


def mock_responder(prompt: str) -> str:
    """JSON stand-in for the Domain Expert LLM call (mock backend)."""
    sentence = prompt.split("Input:")[-1].strip()
    return json.dumps({"triples": _mock_triples(sentence)}, ensure_ascii=False)


def _read_sentences(input_dir: Path) -> list[str]:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    text = f.read_text(encoding="utf-8")
    # strip comment lines, then split into sentences on . ! ?
    body = "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")
    )
    parts = re.split(r"(?<=[.!?])\s+", body.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


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


def _domain_expert(llm, sentence: str, mock: bool) -> list[dict]:
    """Role 1: surface (subject, relation, object) triples from one sentence.

    REAL path uses the shared `extract_triples` helper (robust prompt + tolerant
    JSON + URI sanitisation). MOCK path uses the deterministic `_mock_triples`
    parse (which deliberately keeps self-loops/duplicates so QA prunes them).
    """
    if mock:
        # still goes through the mock backend so manifest.backend == "mock" and
        # the LLM abstraction is exercised, but we keep the raw (unfiltered)
        # triples so the Quality Assurer has work to do.
        llm.complete("Extract ontology triples.\nInput:" + sentence,
                     temperature=0.0, json_schema={"type": "object"})
        return _mock_triples(sentence)
    return extract_triples(llm, sentence)


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    sentences = _read_sentences(input_dir)
    mock = is_mock(llm)

    steps: list[dict] = []
    step_no = 0

    # ----- Role 1: Domain Expert (one step per sentence) -----------------
    # Raw findings: ordered lists of concepts and relation triples.
    raw_concepts: list[str] = []
    raw_relations: list[dict] = []  # {name, domain, range} - keeps dups/self-loops
    for sentence in sentences:
        step_no += 1
        triples = _domain_expert(llm, sentence, mock)
        found_c: list[str] = []
        found_r: list[dict] = []
        for t in triples:
            s, r, o = t["subject"], t["relation"], t["object"]
            for c in (s, o):
                if c not in raw_concepts:
                    raw_concepts.append(c)
                if c not in found_c:
                    found_c.append(c)
            rel = {"name": r, "domain": s, "range": o}
            # keep ALL findings (incl. duplicates / self-loops) so the Quality
            # Assurer has real cleanup to perform.
            raw_relations.append(rel)
            found_r.append(rel)
        steps.append({
            "step": step_no,
            "role": "DomainExpert",
            "cq": f"(DomainExpert) {sentence}",
            "added": {"classes": found_c, "object_properties": found_r,
                      "data_properties": []},
            "graph": {"nodes": [], "edges": []},  # nothing committed yet
        })

    # ----- Role 2: Manager (one step) ------------------------------------
    # Dedupe + organise the raw findings into a single ordered plan. (The raw
    # lists are already dedup-ordered; the Manager makes that explicit and is
    # the authoritative plan the Coder consumes.)
    # Concepts are deduplicated into a clean set; relation findings are carried
    # forward verbatim (the QA role does edge-level validation, not the Manager).
    plan_concepts = list(dict.fromkeys(raw_concepts))
    plan_relations = list(raw_relations)
    step_no += 1
    steps.append({
        "step": step_no,
        "role": "Manager",
        "cq": "(Manager) plan",
        "added": {"classes": plan_concepts, "object_properties": plan_relations,
                  "data_properties": []},
        "graph": {"nodes": [], "edges": []},  # plan only, still not committed
        "plan": {"concepts": plan_concepts, "relations": plan_relations},
    })

    # ----- Role 3: Coder (one step) --------------------------------------
    # Emit OWL fragments from the plan into the model.
    model = _Model()
    emitted_c: list[str] = []
    emitted_o: list[dict] = []
    for c in plan_concepts:
        if model.add_class(c):
            emitted_c.append(c)
    for p in plan_relations:
        for k in ("domain", "range"):
            if model.add_class(p[k]):
                emitted_c.append(p[k])
        # emit verbatim (allow raw duplicates/self-loops); QA will prune them.
        model.obj_props.append(p)
        emitted_o.append(p)
    step_no += 1
    steps.append({
        "step": step_no,
        "role": "Coder",
        "cq": "(Coder) emit",
        "added": {"classes": emitted_c, "object_properties": emitted_o,
                  "data_properties": []},
        "graph": model.to_graph(),
    })

    # ----- Role 4: Quality Assurer (one step) ----------------------------
    # Validate / prune: drop self-loops, duplicate edges, dangling endpoints.
    removed: list[dict] = []
    kept: list[dict] = []
    seen: set = set()
    valid_classes = set(model.classes)
    for p in model.obj_props:
        key = (p["domain"], p["name"], p["range"])
        reason = None
        if p["domain"] == p["range"]:
            reason = "self-loop"
        elif key in seen:
            reason = "duplicate"
        elif p["domain"] not in valid_classes or p["range"] not in valid_classes:
            reason = "missing-endpoint"
        if reason:
            removed.append({**p, "reason": reason})
        else:
            seen.add(key)
            kept.append(p)
    model.obj_props = kept
    step_no += 1
    steps.append({
        "step": step_no,
        "role": "QA",
        "cq": "(QA) validate",
        "added": {"classes": [], "object_properties": [], "data_properties": []},
        "removed": removed,
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
        "method": "multiagent-ontogen",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "roles": ["DomainExpert", "Manager", "Coder", "QA"],
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "data_properties": len(model.data_props),
            "qa_removed": len(removed),
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
