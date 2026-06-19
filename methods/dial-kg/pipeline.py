"""DIAL-KG - schema-free incremental KG construction with governance + schema evolution.

Method (Bao, Wang, Gao, Leng, Bao, Yu, "DIAL-KG: Schema-Free Incremental
Knowledge Graph Construction via Dynamic Schema Induction and Evolution-Intent
Assessment", arXiv 2603.20059, 2026): a CLOSED-LOOP incremental builder. Documents
arrive one at a time; for each, a dual-track extractor proposes entities/relations,
a GOVERNANCE adjudicator merges them into the accumulated graph (resolving
conflicts against a Meta-Knowledge Base of what already exists), and a SCHEMA
EVOLUTION step induces/extends entity TYPES so the schema grows as new kinds of
things appear. A Meta-Knowledge Base (Meta-KB) orchestrates the loop.

What makes DIAL-KG distinct from siblings in this library:
  - iText2KG    : incremental + semantic de-dup, but a FIXED (no) schema.
  - AutoSchemaKG: bottom-up schema induction, but ONE-SHOT over a corpus.
  - DIAL-KG     : incremental AND schema-evolving AND governed — induced types
                  EXTEND as documents arrive, and a governance adjudicator records
                  every merge/drop decision against the Meta-KB.

Closed loop per document:
    1. DUAL-TRACK EXTRACTION  - extract entities + relations from the document.
    2. GOVERNANCE ADJUDICATION- merge into the accumulated graph, deduping
                                singular/plural/case variants against the Meta-KB
                                (existing classes) and dropping duplicate/reverse
                                edges. Each decision (merged/dropped) is recorded.
    3. SCHEMA EVOLUTION       - map each new entity to an induced TYPE; when a type
                                first appears, record it as "evolved" for this step
                                and add an instanceOf edge entity -> type node.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt   - several documents separated by BLANK LINES (one doc = one
                 incremental unit). Required.

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per document (+ a final schema/Meta-KB step)
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend the model does dual-track
extraction (`extract_triples`); with MOCK a deterministic heuristic does, so the
output is reproducible and testable. The mock path needs no API key.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

# Make backend.llm importable whether run as a subprocess or imported directly.
_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402
from backend.llm.extract import is_mock, extract_triples  # noqa: E402

EX = "http://example.org/dialkg#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "Also", "Both", "Then", "Thus", "Here", "Every", "Many", "Some", "Any",
    "All", "No", "Most", "Few", "These", "Those",
}

# relational verbs -> canonical object-property name (shared vocabulary)
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
    "cool": "cools", "cools": "cools",
    "monitor": "monitors", "monitors": "monitors",
    "control": "controls", "controls": "controls",
    "power": "powers", "powers": "powers",
}

# --- SCHEMA EVOLUTION: keyword rule mapping an entity name -> induced TYPE -----
# Exact-name rules take priority; then suffix rules; else fall back to "Entity".
_TYPE_EXACT = {
    "Motor": "Device", "Pump": "Device", "Controller": "Device",
    "Sensor": "Device", "Valve": "Device", "Compressor": "Device",
    "Battery": "Device",
    "Steel": "Material", "Copper": "Material", "Coolant": "Material",
    "Aluminum": "Material", "Aluminium": "Material", "Polymer": "Material",
    "Lubricant": "Material",
    "Assembly": "System", "Product": "System", "Platform": "System",
    "Drivetrain": "System", "Chassis": "System",
    "Welding": "Process", "Assembling": "Process", "Cooling": "Process",
    "Inspection": "Process", "Calibration": "Process", "Machining": "Process",
}
_TYPE_SUFFIX = [
    ("ing", "Process"),   # Welding, Cooling, Machining
    ("ation", "Process"),  # Calibration, Inspection-like
    ("er", "Device"),     # Controller, Compressor (after exact already handled)
    ("or", "Device"),     # Sensor, Motor (after exact already handled)
]


def _induce_type(entity: str) -> str:
    """SCHEMA EVOLUTION rule: derive an induced TYPE from an entity name."""
    if entity in _TYPE_EXACT:
        return _TYPE_EXACT[entity]
    for suf, t in _TYPE_SUFFIX:
        if len(entity) > len(suf) and entity.endswith(suf):
            return t
    return "Entity"


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _norm(w: str) -> str:
    """Meta-KB match key: lowercase singular (case/number-insensitive)."""
    return _singular(w).lower()


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _extract_entities(sentence: str) -> list[str]:
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
# Deterministic MOCK: DUAL-TRACK extraction. The prompt carries a TRACK tag;
# branch on it so each track yields stable JSON with no API key.
# ---------------------------------------------------------------------------
def mock_responder(prompt: str) -> str:
    track = prompt.split("TRACK:")[-1].split("\n")[0].strip()
    payload = prompt.split("PAYLOAD:")[-1].strip()

    if track == "entities":
        ents: list[str] = []
        for s in _sentences(payload):
            for e in _extract_entities(s):
                if e not in ents:
                    ents.append(e)
        return json.dumps({"entities": ents}, ensure_ascii=False)

    if track == "relations":
        rels: list[dict] = []
        for s in _sentences(payload):
            ents = _extract_entities(s)
            rel = _extract_relation(s, ents)
            if rel:
                rels.append(rel)
        return json.dumps({"object_properties": rels}, ensure_ascii=False)

    return json.dumps({"ok": True}, ensure_ascii=False)


_ENTITY_PROMPT = (
    "You are the entity track of a dual-track extractor for incremental KG "
    "construction. Extract candidate ontology classes (named entities) from the "
    "document. Return ONLY JSON {{entities: [..]}}.\n"
    "TRACK: entities\n"
    "PAYLOAD: {doc}\n"
)

_RELATION_PROMPT = (
    "You are the relation track of a dual-track extractor. Extract object "
    "properties between entities in the document. Return ONLY JSON "
    "{{object_properties: [{{name, domain, range}}]}}.\n"
    "TRACK: relations\n"
    "PAYLOAD: {doc}\n"
)


def _read_documents(input_dir: Path) -> list[str]:
    """Split text.txt into documents by BLANK LINES (one doc = one increment)."""
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    raw = f.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", raw.strip())
    return [b.strip() for b in blocks if b.strip()]


def _doc_label(doc: str) -> str:
    """Short label for a step: the document's first line."""
    head = doc.strip().splitlines()[0].strip() if doc.strip() else doc
    return head if len(head) <= 80 else head[:77] + "..."


class _Model:
    """Accumulated KG governed by a Meta-Knowledge Base.

    The Meta-KB is `_by_norm` (canonical class registry) + `types`/`entity_type`
    (induced schema). `to_graph()` emits the SAME Cytoscape schema as cqbycq's
    _Model so the front end renders it unchanged: entity nodes are type 'class',
    induced TYPE nodes are also type 'class', and instanceOf edges link an entity
    to its induced type.
    """

    def __init__(self) -> None:
        self.classes: list[str] = []            # accumulated entity classes
        self.obj_props: list[dict] = []         # {name, domain, range}
        self._by_norm: dict[str, str] = {}      # Meta-KB: norm key -> canonical
        self.types: list[str] = []              # induced schema types
        self.entity_type: dict[str, str] = {}   # entity -> induced type

    # -- entity classes (governance: de-dup against Meta-KB) ---------------
    def add_class(self, c: str) -> Optional[str]:
        """Add an entity class, matching case/number variants to an existing
        canonical class in the Meta-KB. Returns the canonical name if NEW, else
        None (governed/merged)."""
        if not c:
            return None
        key = _norm(c)
        if key in self._by_norm:
            return None
        self.classes.append(c)
        self._by_norm[key] = c
        return c

    def canonical(self, c: str) -> str:
        return self._by_norm.get(_norm(c), c)

    def has_class(self, c: str) -> bool:
        return _norm(c) in self._by_norm

    # -- object properties (governance: drop duplicate + reverse edges) ----
    def has_reverse(self, p: dict) -> bool:
        for q in self.obj_props:
            if q["domain"] == p["range"] and q["range"] == p["domain"] \
                    and q["name"] == p["name"]:
                return True
        return False

    def add_obj(self, p: dict) -> bool:
        if p not in self.obj_props:
            self.obj_props.append(p)
            return True
        return False

    # -- SCHEMA EVOLUTION: induce/extend the type of an entity -------------
    def evolve_type(self, entity: str) -> Optional[str]:
        """Map an entity to an induced TYPE. Returns the type name if it is NEW
        to the schema (i.e. the schema evolved this step), else None."""
        t = _induce_type(entity)
        self.entity_type[entity] = t
        if t not in self.types:
            self.types.append(t)
            return t
        return None

    def to_graph(self) -> dict:
        nodes = []
        # induced TYPE nodes (schema classes)
        for t in self.types:
            nodes.append({"data": {"id": t, "label": t, "type": "class",
                                   "attributes": []}})
        # entity classes
        for c in self.classes:
            nodes.append({"data": {"id": c, "label": c, "type": "class",
                                   "attributes": []}})
        edges = []
        for p in self.obj_props:
            edges.append({"data": {
                "id": f"{p['domain']}-{p['name']}-{p['range']}",
                "source": p["domain"], "target": p["range"],
                "label": p["name"]}})
        # instanceOf edges (entity -> induced type)
        for c in self.classes:
            t = self.entity_type.get(c)
            if t:
                edges.append({"data": {
                    "id": f"{c}-instanceOf-{t}",
                    "source": c, "target": t, "label": "instanceOf"}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))

    # induced schema types -> owl:Class
    for t in model.types:
        g.add((EXN[t], RDF.type, OWL.Class))
    # entity classes -> owl:Class, subClassOf its induced type
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
        t = model.entity_type.get(c)
        if t:
            g.add((EXN[c], RDFS.subClassOf, EXN[t]))
    # object properties -> owl:ObjectProperty + domain/range
    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    return g.serialize(format="turtle")


# ---------------------------------------------------------------------------
# DUAL-TRACK EXTRACTION: produce (entities, relations) for a document. MOCK uses
# the deterministic two-track responder; REAL uses the shared triple extractor.
# Both feed the SAME governance + schema-evolution loop below.
# ---------------------------------------------------------------------------
def _extract_mock(llm, doc: str) -> tuple[list[str], list[dict]]:
    raw = llm.complete(_ENTITY_PROMPT.format(doc=doc), temperature=0.0,
                       json_schema={"type": "object"})
    try:
        ents = json.loads(raw).get("entities", [])
    except json.JSONDecodeError:
        ents = []
    raw = llm.complete(_RELATION_PROMPT.format(doc=doc), temperature=0.0,
                       json_schema={"type": "object"})
    try:
        rels = json.loads(raw).get("object_properties", [])
    except json.JSONDecodeError:
        rels = []
    return ents, rels


def _extract_real(llm, doc: str) -> tuple[list[str], list[dict]]:
    trips = extract_triples(llm, doc)
    ents: list[str] = []
    rels: list[dict] = []
    for t in trips:
        s, o = t["subject"], t["object"]
        for e in (s, o):
            if e not in ents:
                ents.append(e)
        rels.append({"name": t["relation"], "domain": s, "range": o})
    return ents, rels


def _govern_and_evolve(model: "_Model", ents: list[str],
                       rels: list[dict]) -> tuple[dict, dict, list[str]]:
    """GOVERNANCE ADJUDICATION + SCHEMA EVOLUTION for one document.

    Returns (added, governance, evolved_types):
      added       - {classes, object_properties, data_properties} actually added.
      governance  - {merged_entities, dropped_edges} = adjudication decisions.
      evolved_types - induced types that are NEW to the schema this step.
    """
    added_c: list[str] = []
    merged_entities: list[dict] = []   # variant -> existing canonical
    dropped_edges: list[dict] = []     # edge + reason

    # gather all entity mentions (relation endpoints included)
    mentions: list[str] = list(ents)
    for r in rels:
        for k in ("domain", "range"):
            if r.get(k):
                mentions.append(r[k])

    for e in mentions:
        if model.has_class(e):
            canon = model.canonical(e)
            if canon != e:  # a true variant got merged to the Meta-KB canonical
                rec = {"variant": e, "canonical": canon}
                if rec not in merged_entities:
                    merged_entities.append(rec)
            continue
        new = model.add_class(e)
        if new:
            added_c.append(new)

    added_o: list[dict] = []
    for r in rels:
        edge = {"name": r["name"],
                "domain": model.canonical(r["domain"]),
                "range": model.canonical(r["range"])}
        if edge in model.obj_props:
            dropped_edges.append({**edge, "reason": "duplicate"})
            continue
        if model.has_reverse(edge):
            dropped_edges.append({**edge, "reason": "reverse"})
            continue
        if model.add_obj(edge):
            added_o.append(edge)

    # SCHEMA EVOLUTION: induce/extend type for every newly added entity class.
    evolved_types: list[str] = []
    for c in added_c:
        t = model.evolve_type(c)
        if t:
            evolved_types.append(t)

    added = {"classes": added_c, "object_properties": added_o,
             "data_properties": []}
    governance = {"merged_entities": merged_entities,
                  "dropped_edges": dropped_edges}
    return added, governance, evolved_types


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
        # --- DUAL-TRACK EXTRACTION (backend-specific) --------------------
        if mock:
            ents, rels = _extract_mock(llm, doc)
        else:
            ents, rels = _extract_real(llm, doc)

        # --- GOVERNANCE ADJUDICATION + SCHEMA EVOLUTION (shared) ----------
        added, governance, evolved = _govern_and_evolve(model, ents, rels)

        steps.append({
            "step": i,
            "cq": _doc_label(doc),
            "document": i,
            "added": added,
            "governance": governance,
            "schema_types": list(model.types),
            "evolved_types": evolved,
            "graph": model.to_graph(),
        })

    # --- final step: Meta-KB schema summary -----------------------------
    steps.append({
        "step": len(documents) + 1,
        "cq": "(schema) Meta-KB",
        "stage": "schema_evolution",
        "added": {"classes": [], "object_properties": [], "data_properties": []},
        "governance": {"merged_entities": [], "dropped_edges": []},
        "schema_types": list(model.types),
        "evolved_types": [],
        "graph": model.to_graph(),
    })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    total_merged = sum(len(s["governance"]["merged_entities"]) for s in steps)
    total_dropped = sum(len(s["governance"]["dropped_edges"]) for s in steps)

    manifest = {
        "method": "dial-kg",
        "backend": llm.name,
        "input_documents": len(documents),
        "counts": {
            "entity_classes": len(model.classes),
            "induced_types": len(model.types),
            "object_properties": len(model.obj_props),
            "governance_merged": total_merged,
            "governance_dropped_edges": total_dropped,
        },
        "induced_types": list(model.types),
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
