"""Ontogenia - iterative + metacognitive ontology construction from CQs.

Method (Lippolis, Ceriani et al., ESWC 2024 / arXiv 2503.05388, the *Ontogenia*
variant): like CQbyCQ, every competency question (CQ) is turned into a small
ontology fragment, but Ontogenia is **memoryful** (each CQ sees the ontology
built so far) and **metacognitive** (the LLM self-critiques and revises its own
draft before merging). After all CQs a final whole-ontology refinement pass
tidies the result.

Per CQ the loop is 3-phase:
    1. Draft        - heuristic fragment (same as CQbyCQ).            -> step
    2. Self-critique- deterministic rules refine the draft against     -> step
                      the accumulated model: merge near-duplicate
                      classes, normalize singular/plural, flag orphans.
    3. Merge        - the revised fragment is folded into the model.
Then once, after every CQ:
    4. Final pass   - connect orphan classes to a generic `Entity` root  -> step
                      via `subClassOf`, drop duplicate edges.

So steps.json holds ~2*N + 1 snapshots for N CQs (CQbyCQ holds N).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    competency_questions.txt  - one CQ per line (blank lines / # comments ignored)

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - draft / self-critique / final-refinement snapshots
    manifest.json   - summary (backend, counts, file list)

The MOCK backend keeps everything deterministic so the golden fixtures are stable.
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
ROOT = "Entity"  # generic super-class used by the refinement passes

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
    "group": "groupsInto", "groups": "groupsInto",
}

_DATA = {
    "name", "id", "identifier", "weight", "price", "cost", "color", "colour",
    "size", "dimension", "dimensions", "quantity", "length", "width", "height",
    "code", "version", "tolerance",
}

SUBCLASS = "subClassOf"


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
    """Deterministic stand-in for the LLM draft: parse a CQ -> fragment JSON.

    The accumulated-ontology context (if any) is ignored by the mock draft; the
    deterministic self-critique pass in `run()` is what reconciles the draft with
    the accumulated model, which is where the metacognition is emulated.
    """
    cq = prompt.split("Competency question:")[-1].split("\n")[0].strip()
    classes = _extract_classes(cq)
    words = re.findall(r"[a-zA-Z]+", cq.lower())

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
    "OWL ontology fragment, reusing terms from the ontology built so far. Return "
    "ONLY JSON with keys: classes (list of PascalCase class names), "
    "object_properties (list of {{name, domain, range}}), data_properties (list "
    "of {{name, domain, datatype}}), restrictions (list).\n"
    "Ontology so far (classes): {context}\n"
    "Competency question: {cq}\n"
)


def _frag_from_triples(triples: list[dict]) -> dict:
    """Convert shared-extractor triples into the same draft fragment shape the
    mock path produces (classes + object_properties{name,domain,range}).

    Subject/object become classes; relation becomes an object property whose
    domain/range are the subject/object classes. Insertion order is preserved so
    the downstream (identical) self-critique + refinement passes are stable.
    """
    classes: list[str] = []
    object_properties: list[dict] = []
    for t in triples:
        s, r, o = t["subject"], t["relation"], t["object"]
        for c in (s, o):
            if c not in classes:
                classes.append(c)
        prop = {"name": r, "domain": s, "range": o}
        if prop not in object_properties:
            object_properties.append(prop)
    return {
        "classes": classes,
        "object_properties": object_properties,
        "data_properties": [],
        "restrictions": [],
    }


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


# --- metacognitive self-critique helpers (deterministic) --------------------

# Irregular / hard plurals the naive `_singular` misses, mapping to canonical.
# Keys cover both the raw plural ("Subassemblies") and the form the draft
# heuristic produces after its naive `_singular` ("Subassemblie"), since the
# self-critique sees the already-drafted (mangled) class name.
_IRREGULAR = {
    "Subassemblies": "Subassembly", "Subassemblie": "Subassembly",
    "Properties": "Property", "Propertie": "Property",
    "Categories": "Category", "Categorie": "Category",
    "Facilities": "Facility", "Facilitie": "Facility",
    "Companies": "Company", "Companie": "Company",
}


def _norm_key(name: str) -> str:
    """Canonical comparison key: lower-cased, naive-singularized, irregular-aware."""
    fixed = _IRREGULAR.get(name, name)
    return _singular(fixed.lower())


def _canonical_name(name: str) -> str:
    """Preferred display form of a class (irregular-plural -> singular)."""
    return _IRREGULAR.get(name, name)


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

    # --- metacognition support ---------------------------------------------
    def find_match(self, name: str) -> Optional[str]:
        """Return an existing class that is a case/plural variant of `name`."""
        key = _norm_key(name)
        for c in self.classes:
            if _norm_key(c) == key:
                return c
        return None

    def has_edge(self, cls: str) -> bool:
        for p in self.obj_props:
            if p["domain"] == cls or p["range"] == cls:
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
    from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for p in model.obj_props:
        # subClassOf is rendered as rdfs:subClassOf, not as an object property.
        if p["name"] == SUBCLASS:
            g.add((EXN[p["domain"]], RDFS.subClassOf, EXN[p["range"]]))
            continue
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


def _rename_in_fragment(frag: dict, old: str, new: str) -> None:
    frag["classes"] = [new if c == old else c for c in frag.get("classes", [])]
    for p in frag.get("object_properties", []):
        if p.get("domain") == old:
            p["domain"] = new
        if p.get("range") == old:
            p["range"] = new
    for p in frag.get("data_properties", []):
        if p.get("domain") == old:
            p["domain"] = new


def _self_critique(frag: dict, model: _Model) -> tuple[dict, dict]:
    """Metacognitive pass: reconcile a draft fragment with the accumulated model.

    Deterministic rules:
      (a) MERGE: a drafted class that is a case/plural variant of an existing
          class is renamed to the existing class.
      (b) NORMALIZE: an irregular plural with no existing match is renamed to its
          canonical singular form.
    Returns (revised_fragment, change_log) where change_log records what changed
    so the UI can show the critique's effect.
    """
    revised = json.loads(json.dumps(frag))  # deep copy
    merged: list[dict] = []
    renamed: list[dict] = []

    # Work on a stable copy of the drafted class names.
    for name in list(revised.get("classes", [])):
        existing = model.find_match(name)
        if existing and existing != name:
            _rename_in_fragment(revised, name, existing)
            merged.append({"from": name, "into": existing})
            continue
        canon = _canonical_name(name)
        if canon != name and model.find_match(canon) is None:
            _rename_in_fragment(revised, name, canon)
            renamed.append({"from": name, "to": canon})

    # de-duplicate class list while preserving order (a merge can collide)
    seen: set[str] = set()
    deduped = []
    for c in revised.get("classes", []):
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    revised["classes"] = deduped

    return revised, {"merged": merged, "renamed": renamed}


def _merge_fragment(model: _Model, frag: dict) -> tuple[list, list, list]:
    """Fold a fragment into the model, returning what was newly added."""
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
    return added_c, added_o, added_d


def _final_refinement(model: _Model) -> tuple[list, list]:
    """Whole-ontology pass: attach orphan classes to `Entity` via subClassOf,
    and drop any duplicate edges. Returns (added_classes, added_edges)."""
    added_c, added_o = [], []

    orphans = [c for c in model.classes if not model.has_edge(c)]
    if orphans:
        if model.add_class(ROOT):
            added_c.append(ROOT)
        for c in orphans:
            if c == ROOT:
                continue
            edge = {"name": SUBCLASS, "domain": c, "range": ROOT}
            if model.add_obj(edge):
                added_o.append(edge)

    # drop duplicate edges (defensive; add_obj already guards, but be explicit)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for p in model.obj_props:
        key = (p["domain"], p["name"], p["range"])
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    model.obj_props = deduped

    return added_c, added_o


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    cqs = _read_cqs(input_dir)

    model = _Model()
    steps = []
    step_no = 0
    for cq in cqs:
        # --- DRAFT unit = one CQ -------------------------------------------
        if is_mock(llm):
            # Deterministic mock path: UNCHANGED (golden-tested).
            context = ", ".join(model.classes) or "(empty)"
            raw = llm.complete(
                _PROMPT.format(cq=cq, context=context),
                temperature=0.0, json_schema={"type": "object"},
            )
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"classes": [], "object_properties": [],
                        "data_properties": [], "restrictions": []}
        else:
            # Real-LLM path: robust triple extraction -> same fragment shape.
            triples = extract_triples(llm, cq)
            frag = _frag_from_triples(triples)

        # --- phase 1: draft (record before critique, do NOT merge yet) ------
        draft_model = _Model()
        # mirror the accumulated state so the draft snapshot shows it in context
        draft_model.classes = list(model.classes)
        draft_model.obj_props = list(model.obj_props)
        draft_model.data_props = list(model.data_props)
        d_c, d_o, d_d = _merge_fragment(draft_model, frag)
        step_no += 1
        steps.append({
            "step": step_no,
            "cq": cq,
            "added": {"classes": d_c, "object_properties": d_o,
                      "data_properties": d_d},
            "graph": draft_model.to_graph(),
        })

        # --- phase 2: self-critique (metacognition) ------------------------
        revised, changes = _self_critique(frag, model)
        # --- phase 3: merge revised fragment into the real model -----------
        r_c, r_o, r_d = _merge_fragment(model, revised)
        step_no += 1
        steps.append({
            "step": step_no,
            "cq": f"(self-critique) {cq}",
            "added": {
                "classes": r_c,
                "object_properties": r_o,
                "data_properties": r_d,
                "merged": changes["merged"],
                "renamed": changes["renamed"],
            },
            "graph": model.to_graph(),
        })

    # --- final whole-ontology refinement pass ------------------------------
    f_c, f_o = _final_refinement(model)
    step_no += 1
    steps.append({
        "step": step_no,
        "cq": "(final refinement)",
        "added": {"classes": f_c, "object_properties": f_o,
                  "data_properties": []},
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
        "method": "ontogenia",
        "backend": llm.name,
        "input_cqs": len(cqs),
        "steps": len(steps),
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
