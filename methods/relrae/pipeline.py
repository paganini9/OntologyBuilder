"""RELRaE - LLM-based Relationship Extraction, Labelling, Refinement, Evaluation.

Method (Hannah et al., "RELRaE: LLM-Based Relationship Extraction, Labelling,
Refinement, and Evaluation", arXiv:2507.03829, Univ. of Liverpool / Unilever):
robotic labs emit large volumes of XML. To make that data interoperable as a
knowledge graph, the XML *schema* must be enriched into an ontology schema. The
relationships between element types are only *implicitly* present in the XML
(parent/child nesting, reference attributes). RELRaE uses an LLM across four
stages to surface them:

    1. Extract  - find the relationships implicit in the XML structure.
    2. Label    - give each relationship a meaningful ontology label.
    3. Refine   - merge duplicates / canonicalise synonymous labels.
    4. Evaluate - LLM-as-a-judge scores each labelled relationship; low-scoring
                  ones are rejected (kept out of the final ontology schema).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    schema.xml  - one XML document/instance describing the lab data. Element
                  nesting = containment relationships; attributes ending in
                  "Ref"/"_ref"/"ref" = cross-references to another element type;
                  other attributes = data properties.

Outputs (out_dir):
    ontology.ttl    - OWL: element types as owl:Class, accepted relationships as
                      owl:ObjectProperty (domain/range), attributes as
                      owl:DatatypeProperty. Each relation's judge score is an
                      rdfs:comment (kept valid OWL).
    ontology.json   - final schema as Cytoscape nodes/edges; each relation edge
                      carries label, kind (nest|ref), score and accepted flag.
    steps.json      - one snapshot per extracted relationship as it is labelled,
                      refined and evaluated, so the UI can replay the build.
    manifest.json   - summary (backend, counts, file list).

The LLM step (label + judge score) is abstracted: with a real backend the model
labels and scores each relationship; with MOCK a deterministic heuristic does, so
output is reproducible and golden-testable. Structural extraction (walking the
XML) and refinement (dedup/canonicalise) are rule-based in both paths.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402
from backend.llm.extract import is_mock  # noqa: E402

EX = "http://example.org/lab#"
ACCEPT_THRESHOLD = 0.55

# nicer verbs for reference (usage) relationships, keyed by referenced type
_REF_VERBS = {
    "Instrument": "measuredWith",
    "Reagent": "consumes",
    "Operator": "operatedBy",
    "Protocol": "follows",
}
# synonymous labels collapsed during refinement
_CANON = {
    "hasMeasurements": "hasMeasurement",
    "hasSamples": "hasSample",
    "contains": "hasPart",
}


def _pascal(tag: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", tag)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _ref_type(attr: str) -> str:
    """instrumentRef / reagent_ref / sampleRef -> Instrument / Reagent / Sample."""
    base = re.sub(r"(_?[Rr]ef)$", "", attr)
    return _pascal(_singular(base))


def _is_ref(attr: str) -> bool:
    return bool(re.search(r"(_?[Rr]ef)$", attr)) and attr.lower() != "ref"


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM label+judge step.

    Input prompt carries one structural relationship line:
        "Relationship: <Domain> -[<kind>:<cue>]-> <Range>"
    Returns JSON {"label": <camelCase>, "score": <0..1>}.
    """
    m = re.search(r"Relationship:\s*(\w+)\s*-\[(\w+):([^\]]*)\]->\s*(\w+)", prompt)
    if not m:
        return json.dumps({"label": "", "score": 0.0})
    domain, kind, cue, rng = m.group(1), m.group(2), m.group(3).strip(), m.group(4)

    if kind == "ref":
        label = _REF_VERBS.get(rng, "uses" + rng)
    else:  # nest / containment
        label = "has" + _singular(rng)

    # LLM-as-a-judge heuristic: a clear verb-like label on distinct, resolvable
    # types scores high; generic containment scores lower; a relationship whose
    # range type is never defined as its own element is penalised.
    score = 0.5
    if kind == "ref":
        score += 0.25
    if rng in _REF_VERBS or label.startswith(("has", "uses")) is False:
        score += 0.1
    if domain != rng:
        score += 0.1
    if cue == "undefined":      # range type not defined elsewhere in the doc
        score -= 0.3
    score = round(max(0.0, min(1.0, score)), 2)
    return json.dumps({"label": label, "score": score}, ensure_ascii=False)


_PROMPT = (
    "You are an ontology engineer enriching an XML schema. Given ONE structural "
    "relationship implicit in the XML, return ONLY JSON {{\"label\":\"camelCase "
    "object property\",\"score\":0..1}} where score is your confidence that this "
    "is a good ontology relationship (LLM-as-a-judge).\n"
    "Relationship: {rel}\n"
)


def _read_xml(input_dir: Path) -> ET.Element:
    f = input_dir / "schema.xml"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return ET.fromstring(f.read_text(encoding="utf-8"))


def _extract(root: ET.Element):
    """Stage 1 - structural extraction.

    Returns (element_types, raw_rels, data_props) where:
      element_types : ordered list of PascalCase type names seen as elements
      raw_rels      : ordered list of {domain, range, kind, cue}
      data_props    : ordered list of {domain, name}
    """
    element_types: list[str] = []
    raw_rels: list[dict] = []
    data_props: list[dict] = []

    def note_type(t: str):
        if t and t not in element_types:
            element_types.append(t)

    def walk(elem: ET.Element):
        dt = _pascal(elem.tag)
        note_type(dt)
        for attr in elem.attrib:
            if _is_ref(attr):
                rt = _ref_type(attr)
                raw_rels.append({"domain": dt, "range": rt, "kind": "ref",
                                 "cue": attr})
            else:
                dp = {"domain": dt, "name": attr}
                if dp not in data_props:
                    data_props.append(dp)
        for child in list(elem):
            ct = _pascal(child.tag)
            raw_rels.append({"domain": dt, "range": ct, "kind": "nest",
                             "cue": child.tag})
            walk(child)

    walk(root)
    return element_types, raw_rels, data_props


class _Model:
    """Accumulated ontology schema, insertion-ordered for deterministic output."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.rels: list[dict] = []          # accepted object properties
        self.data_props: list[dict] = []
        self._rel_keys: set = set()

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def add_rel(self, r: dict) -> bool:
        key = (r["domain"], r["label"], r["range"])
        if key in self._rel_keys:
            return False
        self._rel_keys.add(key)
        self.rels.append(r)
        return True

    def add_data(self, dp: dict) -> bool:
        if dp not in self.data_props:
            self.data_props.append(dp)
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
            {"data": {"id": f"{r['domain']}-{r['label']}-{r['range']}",
                      "source": r["domain"], "target": r["range"],
                      "label": r["label"], "kind": r["kind"],
                      "score": r["score"], "accepted": True}}
            for r in self.rels
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
    seen = set()
    for r in model.rels:
        pr = r["label"]
        if pr not in seen:
            g.add((EXN[pr], RDF.type, OWL.ObjectProperty))
            seen.add(pr)
        g.add((EXN[pr], RDFS.domain, EXN[r["domain"]]))
        g.add((EXN[pr], RDFS.range, EXN[r["range"]]))
        g.add((EXN[f"{r['domain']}_{pr}_{r['range']}"], RDFS.comment,
               Literal(f"judge_score={r['score']} kind={r['kind']}")))
    for dp in model.data_props:
        pr = EXN[dp["name"]]
        g.add((pr, RDF.type, OWL.DatatypeProperty))
        g.add((pr, RDFS.domain, EXN[dp["domain"]]))
        g.add((pr, RDFS.range, XSD.string))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    root = _read_xml(input_dir)
    _ = is_mock(llm)  # both paths share the same prompt contract

    # Stage 1: structural extraction.
    element_types, raw_rels, data_props = _extract(root)
    defined = set(element_types)

    model = _Model()
    for c in element_types:
        model.add_class(c)
    for dp in data_props:
        model.add_data(dp)

    steps: list[dict] = []
    rejected: list[dict] = []
    seen_refine: set = set()
    for i, rr in enumerate(raw_rels, 1):
        # cue passed to the judge: mark a reference whose target type is never
        # defined as its own element ("undefined") so Evaluate can penalise it.
        cue = "undefined" if (rr["kind"] == "ref" and rr["range"] not in defined) \
            else rr["kind"]
        rel_str = f"{rr['domain']} -[{rr['kind']}:{cue}]-> {rr['range']}"

        # Stage 2 (Label) + Stage 4 (Evaluate) via the LLM (mock = deterministic).
        raw = llm.complete(_PROMPT.format(rel=rel_str), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            out = {}
        label = out.get("label", "")
        score = float(out.get("score", 0.0))

        # Stage 3 (Refine): canonicalise synonymous labels, then dedup by triple.
        label = _CANON.get(label, label)
        refine_key = (rr["domain"], label, rr["range"])
        duplicate = refine_key in seen_refine
        seen_refine.add(refine_key)

        accepted = bool(label) and not duplicate and score >= ACCEPT_THRESHOLD
        added = False
        if accepted:
            # a reference may introduce a not-yet-seen type as a class
            model.add_class(rr["range"])
            added = model.add_rel({"domain": rr["domain"], "range": rr["range"],
                                   "label": label, "kind": rr["kind"],
                                   "score": score})
        else:
            rejected.append({"domain": rr["domain"], "range": rr["range"],
                             "label": label, "kind": rr["kind"], "score": score,
                             "reason": "duplicate" if duplicate
                             else ("low_score" if label else "no_label")})

        steps.append({
            "step": i,
            "stage": "extract->label->refine->evaluate",
            "relationship": rel_str,
            "label": label,
            "kind": rr["kind"],
            "score": score,
            "accepted": added,
            "rejected_reason": None if added else (
                "duplicate" if duplicate else
                ("low_score" if label else "no_label")),
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
        "method": "relrae",
        "backend": llm.name,
        "input_elements": len(element_types),
        "raw_relationships": len(raw_rels),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.rels),
            "data_properties": len(model.data_props),
            "rejected": len(rejected),
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
