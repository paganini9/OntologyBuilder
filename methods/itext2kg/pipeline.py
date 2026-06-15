"""iText2KG - incremental, zero-shot knowledge-graph construction.

Method (Lairgi et al., WISE 2024, arXiv:2409.03284, "iText2KG"): multiple
documents are processed INCREMENTALLY, one at a time, through four modules:

    1. Document Distiller          - normalize/clean a document into semantic
                                     blocks suited for extraction.
    2. Incremental Entity Extractor- extract entities (capitalized nouns) and
                                     SEMANTICALLY DE-DUP them against the global
                                     accumulated entity set (singular/plural +
                                     case variants collapse to one class).
    3. Incremental Relation Extractor - extract object properties (relation
                                     verbs) between entities, referencing the
                                     accumulated entity set.
    4. Graph Integrator            - merge new nodes/edges into the accumulated
                                     graph; drop duplicate edges.

Each document yields ONE step snapshot, so the UI can replay the graph growing
"as documents are added" - later documents REUSE entities introduced by earlier
ones rather than creating duplicate nodes.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt   - several documents separated by BLANK LINES (one doc = one
                 incremental unit). Required.

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per document (the incremental build)
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
plays each module; with MOCK a deterministic heuristic does, so the output is
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
from backend.llm.extract import is_mock, extract_triples  # noqa: E402

EX = "http://example.org/product#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "Also", "Both", "Then", "Thus", "Here", "Every", "Many", "Some", "Any",
    "All", "No", "Most", "Few",
}

# relational verbs -> canonical object-property name (shared with cqbycq/karma)
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
    "transmit": "transmits", "transmits": "transmits",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _norm(w: str) -> str:
    """Semantic-match key: lowercase singular (case/number-insensitive)."""
    return _singular(w).lower()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


# ---------------------------------------------------------------------------
# Module 1: Document Distiller (mock = whitespace normalization, sentence keep)
# ---------------------------------------------------------------------------
def _distill(doc: str) -> str:
    return re.sub(r"\s+", " ", doc).strip()


# ---------------------------------------------------------------------------
# Module 2 helpers: entity extraction (capitalized nouns, surface forms)
# ---------------------------------------------------------------------------
def _extract_entities(sentence: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# Module 3 helpers: relation extraction (relation verb between two entities)
# ---------------------------------------------------------------------------
def _extract_relation(sentence: str, entities: list[str]) -> Optional[dict]:
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    ent_words = {e.lower() for e in entities} | {e.lower() + "s" for e in entities}
    rel = next(
        (_REL[w] for w in words if w in _REL and w not in ent_words), None)
    if rel and len(entities) >= 2:
        return {"name": rel, "domain": entities[0], "range": entities[1]}
    return None


# ---------------------------------------------------------------------------
# Deterministic MOCK module: prompt carries a MODULE tag; branch on it so each
# module yields a stable, structured JSON answer with no API key.
# ---------------------------------------------------------------------------
def mock_responder(prompt: str) -> str:
    module = prompt.split("MODULE:")[-1].split("\n")[0].strip()
    payload_raw = prompt.split("PAYLOAD:")[-1].strip()

    if module == "distill":
        return json.dumps({"distilled": _distill(payload_raw)},
                          ensure_ascii=False)

    if module == "entities":
        ents: list[str] = []
        for s in _sentences(payload_raw):
            for e in _extract_entities(s):
                if e not in ents:
                    ents.append(e)
        return json.dumps({"entities": ents}, ensure_ascii=False)

    if module == "relations":
        data = json.loads(payload_raw)
        rels: list[dict] = []
        for s in _sentences(data["distilled"]):
            ents = _extract_entities(s)
            rel = _extract_relation(s, ents)
            if rel:
                rels.append(rel)
        return json.dumps({"object_properties": rels}, ensure_ascii=False)

    return json.dumps({"ok": True}, ensure_ascii=False)


_DISTILL_PROMPT = (
    "You are the Document Distiller. Normalize this document into clean "
    "semantic blocks. Return ONLY JSON {{distilled: <text>}}.\n"
    "MODULE: distill\n"
    "PAYLOAD: {doc}\n"
)

_ENTITY_PROMPT = (
    "You are the Incremental Entity Extractor. Extract candidate ontology "
    "classes (named entities) from the distilled document. Return ONLY JSON "
    "{{entities: [..]}}.\n"
    "MODULE: entities\n"
    "PAYLOAD: {doc}\n"
)

_RELATION_PROMPT = (
    "You are the Incremental Relation Extractor. Given the distilled document, "
    "extract object properties between entities. Return ONLY JSON "
    "{{object_properties: [{{name, domain, range}}]}}.\n"
    "MODULE: relations\n"
    "PAYLOAD: {payload}\n"
)


def _read_documents(input_dir: Path) -> list[str]:
    """Split text.txt into documents by BLANK LINES (one doc = one increment)."""
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    raw = f.read_text(encoding="utf-8")
    # blocks separated by one-or-more blank lines
    blocks = re.split(r"\n\s*\n", raw.strip())
    return [b.strip() for b in blocks if b.strip()]


class _Model:
    """Accumulated ontology, insertion-ordered for deterministic output.

    Entities are semantically de-duped via a normalized (lowercase-singular)
    key, so a later document's "Pumps" maps to the existing canonical "Pump".
    """

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []
        # semantic-match map: normalized key -> canonical class name kept
        self._by_norm: dict[str, str] = {}

    # -- classes (with incremental semantic de-dup) ------------------------
    def add_class(self, c: str) -> Optional[str]:
        """Add a class, matching case/number variants to an existing canonical
        class. Returns the canonical name if NEW, else None (deduped)."""
        if not c:
            return None
        key = _norm(c)
        if key in self._by_norm:
            return None  # semantically matched to existing class -> no new node
        self.classes.append(c)
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


def _doc_label(distilled: str) -> str:
    """Short label for the step: first sentence of the distilled document."""
    sents = _sentences(distilled)
    head = sents[0] if sents else distilled
    return head if len(head) <= 80 else head[:77] + "..."


# ---------------------------------------------------------------------------
# Shared Module 4: Graph Integrator. Both the MOCK heuristic and the REAL-LLM
# path produce (entities, relations) for a document and funnel them through
# THIS single integrator, so cross-document semantic de-dup is identical for
# both backends. `relations` are dicts {name, domain, range}.
# ---------------------------------------------------------------------------
def _integrate(model: "_Model", ents: list[str], rels: list[dict]) -> dict:
    added_c: list[str] = []
    for e in ents:
        # semantic de-dup against the GLOBAL accumulated entity set
        if model.add_class(e):
            added_c.append(e)

    added_o: list[dict] = []
    for r in rels:
        for k in ("domain", "range"):
            # endpoint may be a brand-new entity only seen in a relation
            if model.add_class(r.get(k, "")):
                added_c.append(model.canonical(r[k]))
        edge = {"name": r["name"],
                "domain": model.canonical(r["domain"]),
                "range": model.canonical(r["range"])}
        if model.add_obj(edge):
            added_o.append(edge)

    return {"classes": added_c, "object_properties": added_o,
            "data_properties": []}


def _extract_mock(llm, doc: str) -> tuple[str, list[str], list[dict]]:
    """MOCK path: distill -> entities -> relations via the deterministic
    mock_responder modules (EXACTLY the original logic)."""
    # --- Module 1: Document Distiller ------------------------------------
    raw = llm.complete(_DISTILL_PROMPT.format(doc=doc), temperature=0.0,
                       json_schema={"type": "object"})
    try:
        distilled = json.loads(raw).get("distilled", _distill(doc))
    except json.JSONDecodeError:
        distilled = _distill(doc)

    # --- Module 2: Incremental Entity Extractor --------------------------
    raw = llm.complete(_ENTITY_PROMPT.format(doc=distilled),
                       temperature=0.0, json_schema={"type": "object"})
    try:
        ents = json.loads(raw).get("entities", [])
    except json.JSONDecodeError:
        ents = []

    # --- Module 3: Incremental Relation Extractor ------------------------
    payload = json.dumps({"distilled": distilled}, ensure_ascii=False)
    raw = llm.complete(_RELATION_PROMPT.format(payload=payload),
                       temperature=0.0, json_schema={"type": "object"})
    try:
        rels = json.loads(raw).get("object_properties", [])
    except json.JSONDecodeError:
        rels = []
    return distilled, ents, rels


def _extract_real(llm, doc: str) -> tuple[str, list[str], list[dict]]:
    """REAL-LLM path: the model extracts (subject, relation, object) triples for
    the document; we derive entities + {name,domain,range} relations from them,
    then feed the SAME incremental integrator the mock path uses."""
    distilled = _distill(doc)
    trips = extract_triples(llm, distilled)
    ents: list[str] = []
    rels: list[dict] = []
    for t in trips:
        s, o = t["subject"], t["object"]
        for e in (s, o):
            if e not in ents:
                ents.append(e)
        rels.append({"name": t["relation"], "domain": s, "range": o})
    return distilled, ents, rels


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    documents = _read_documents(input_dir)

    model = _Model()
    steps: list[dict] = []

    mock = is_mock(llm)
    for i, doc in enumerate(documents, 1):
        # Modules 1-3 differ by backend; the MOCK heuristic and the REAL model
        # each produce (distilled, entities, relations) for this document.
        if mock:
            distilled, ents, rels = _extract_mock(llm, doc)
        else:
            distilled, ents, rels = _extract_real(llm, doc)

        # --- Module 4: Graph Integrator (SHARED) -------------------------
        # Cross-document semantic de-dup + edge merge, identical for both paths.
        added = _integrate(model, ents, rels)

        # --- Shared step emit (cqbycq-compatible schema) -----------------
        steps.append({
            "step": i,
            "cq": _doc_label(distilled),
            "document": i,
            "distilled": distilled,
            "added": added,
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
        "method": "itext2kg",
        "backend": llm.name,
        "input_documents": len(documents),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "data_properties": 0,
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
