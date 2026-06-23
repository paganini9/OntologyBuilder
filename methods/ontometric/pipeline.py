"""OntoMetric - ontology-guided ESG metric KG construction with validation.

Method (OntoMetric: An Ontology-Driven LLM-Assisted Framework for Automated ESG
Metric Knowledge Graph Generation, arXiv:2512.01289): ESG metric knowledge
(industries, reporting frameworks, metric categories, metrics, calculation
models) is structured but buried in regulatory PDFs (SASB, TCFD, IFRS S2).
Unconstrained LLM extraction hallucinates types and invalid relations. OntoMetric
embeds the **ESG Metric Knowledge Graph (ESGMKG) ontology as a first-class
constraint** in the extraction + population process and runs **two-phase
validation** (semantic type verification + rule-based schema checking) while
preserving page/segment **provenance**.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    esg_document.json - {"framework":"SASB",
                         "segments":[{"page","heading","text"}, ...]}

Outputs (out_dir):
    ontology.ttl   - OWL: ESGMKG schema classes + object properties +
                     typed individuals (validated ABox)
    ontology.json  - Cytoscape graph: schema-class nodes + validated entity
                     nodes (each carries deterministic id + page provenance)
    steps.json     - one snapshot per document segment (UI replays population)
    manifest.json  - summary (accepted/rejected entities & relations, ...)

Deterministic-on-MOCK ingredients (faithful to the paper):
    * Structure-aware segmentation - segments are read in order; each carries
      page-level provenance, and a running (framework -> category -> metric)
      context tracks the compositional nesting.
    * Ontology-constrained extraction - the heading prefix proposes an ESGMKG
      type and a *deterministic identifier* is minted (RF:/CAT:/MET:/CM:/IND:).
    * Two-phase validation -
        phase 1 (semantic type verification): drop entities whose proposed type
                 is not an ESGMKG class (e.g. a hallucinated "Tagline").
        phase 2 (rule-based schema check): keep a relation only if
                 (srcType, relation, dstType) is an allowed ESGMKG edge AND both
                 endpoints survived phase 1 (e.g. a CalculationModel cannot
                 `appliesToIndustry`).
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
from backend.llm.extract import is_mock  # noqa: E402

EX = "http://example.org/ontometric#"
ROOT_CLASS = "ESGEntity"

# ---- ESGMKG ontology (first-class constraint) -----------------------------
CLASSES = ["Industry", "ReportingFramework", "MetricCategory", "Metric",
           "CalculationModel"]

# Allowed compositional edges: (srcType, relation, dstType).
ALLOWED_EDGES = {
    ("ReportingFramework", "hasCategory", "MetricCategory"),
    ("MetricCategory", "hasMetric", "Metric"),
    ("Metric", "computedBy", "CalculationModel"),
    ("Metric", "appliesToIndustry", "Industry"),
}

# Heading-prefix -> proposed ESGMKG type (an unknown prefix yields a type that
# fails phase-1 semantic verification, mirroring a hallucinated entity).
_PREFIX_TYPE = {
    "framework": "ReportingFramework",
    "category": "MetricCategory",
    "metric": "Metric",
    "calculation model": "CalculationModel",
    "industry": "Industry",
}

# Type -> deterministic id prefix.
_ID_PREFIX = {
    "ReportingFramework": "RF",
    "MetricCategory": "CAT",
    "Metric": "MET",
    "CalculationModel": "CM",
    "Industry": "IND",
}


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


def _split_heading(heading: str) -> tuple[str, str]:
    """Return (prefix_lower, label). 'Metric: Scope 1' -> ('metric','Scope 1')."""
    if ":" in heading:
        pre, _, rest = heading.partition(":")
        return pre.strip().lower(), rest.strip()
    return heading.strip().lower(), heading.strip()


# ---- LLM bridge -----------------------------------------------------------
def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: echo the proposed type for the heading prefix."""
    try:
        line = [ln for ln in prompt.splitlines() if ln.startswith("Heading:")][-1]
        heading = line[len("Heading:"):].strip()
    except Exception:
        return json.dumps({"type": None})
    prefix, _ = _split_heading(heading)
    proposed = _PREFIX_TYPE.get(prefix, _title(prefix).replace(" ", ""))
    return json.dumps({"type": proposed}, ensure_ascii=False)


_PROMPT = (
    "You extract an ESG entity constrained to the ESGMKG ontology. "
    'Return ONLY JSON {{"type":"..."}} naming the ESGMKG class.\n'
    "Heading: {heading}\n"
    "Allowed classes: {classes}\n"
)


def _proposed_type(heading: str, llm, mock: bool) -> str:
    if mock:
        raw = llm.complete(_PROMPT.format(heading=heading,
                                          classes=", ".join(CLASSES)),
                           temperature=0.0, json_schema={"type": "object"})
    else:
        raw = llm.complete(_PROMPT.format(heading=heading,
                                          classes=", ".join(CLASSES)),
                           temperature=0.0)
    try:
        return json.loads(raw).get("type") or ""
    except json.JSONDecodeError:
        return ""


# ---- graph model ----------------------------------------------------------
class _Model:
    def __init__(self) -> None:
        # ESGMKG schema is predefined (ontology-driven): seed all classes.
        self.classes: list[str] = [ROOT_CLASS] + CLASSES
        self.subclass: list[tuple[str, str]] = [(c, ROOT_CLASS) for c in CLASSES]
        self.instances: list[dict] = []   # {id, label, cls, page}
        self.relations: list[dict] = []   # {src, label, dst, page}
        self._ids: set[str] = set()

    def add_instance(self, eid: str, label: str, cls: str, page: int) -> bool:
        if eid in self._ids:
            return False
        self._ids.add(eid)
        self.instances.append({"id": eid, "label": label, "cls": cls,
                               "page": page})
        return True

    def add_relation(self, src: str, label: str, dst: str, page: int) -> bool:
        rel = {"src": src, "label": label, "dst": dst, "page": page}
        if rel in self.relations:
            return False
        self.relations.append(rel)
        return True

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for i in self.instances:
            nodes.append({"data": {"id": i["id"], "label": i["label"],
                                   "type": "instance", "cls": i["cls"],
                                   "provenance": f"p{i['page']}",
                                   "attributes": []}})
        edges = []
        for child, parent in self.subclass:
            edges.append({"data": {"id": f"{child}-subClassOf-{parent}",
                                   "source": child, "target": parent,
                                   "label": "subClassOf"}})
        for i in self.instances:
            edges.append({"data": {"id": f"{i['id']}-type-{i['cls']}",
                                   "source": i["id"], "target": i["cls"],
                                   "label": "type",
                                   "provenance": f"p{i['page']}"}})
        for r in self.relations:
            edges.append({"data": {
                "id": f"{r['src']}-{r['label']}-{r['dst']}",
                "source": r["src"], "target": r["dst"], "label": r["label"],
                "provenance": f"p{r['page']}"}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef, Literal

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for child, parent in model.subclass:
        g.add((EXN[child], RDFS.subClassOf, EXN[parent]))
    for rel in sorted({r["label"] for r in model.relations}):
        g.add((EXN[rel], RDF.type, OWL.ObjectProperty))

    def uri(eid: str) -> URIRef:
        return EXN[_slug(eid).replace("-", "_")]

    for i in model.instances:
        u = uri(i["id"])
        g.add((u, RDF.type, EXN[i["cls"]]))
        g.add((u, RDFS.label, Literal(i["label"])))
    for r in model.relations:
        g.add((uri(r["src"]), EXN[r["label"]], uri(r["dst"])))
    return g.serialize(format="turtle")


# ---- in-text extraction patterns ------------------------------------------
_RE_COMPUTED = re.compile(r"computed by (?:the )?(.+?) model", re.I)
_RE_INDUSTRY = re.compile(r"applies to (?:the )?(.+?) industry", re.I)


def _read_doc(input_dir: Path) -> dict:
    f = input_dir / "esg_document.json"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = _read_doc(input_dir)
    framework = doc.get("framework", "FRAMEWORK")
    fw_slug = _slug(framework)
    segments = doc.get("segments", [])
    llm = get_backend(backend, mock_responder=mock_responder)
    mock = is_mock(llm)

    model = _Model()
    steps: list[dict] = []
    rejected_entities: list[dict] = []
    rejected_relations: list[dict] = []
    accepted_e = accepted_r = 0

    ctx_framework = ctx_category = ""   # deterministic compositional context
    cur_cat_slug = ""

    for seg_i, seg in enumerate(segments, 1):
        page = seg.get("page", 0)
        heading = seg.get("heading", "")
        text = seg.get("text", "")
        prefix, label = _split_heading(heading)
        proposed = _proposed_type(heading, llm, mock)

        added_e, added_r = [], []

        # --- phase 1: semantic type verification ---
        if proposed not in CLASSES:
            rejected_entities.append({"segment": seg_i, "page": page,
                                      "label": label, "proposed_type": proposed,
                                      "reason": "type not in ESGMKG schema"})
            steps.append({"step": seg_i, "stage": "extract+validate",
                          "cq": f"p{page}: {heading}",
                          "added": {"entity": None, "rejected_type": proposed,
                                    "relations": []},
                          "graph": model.to_graph()})
            continue

        # mint deterministic id for the heading entity
        cls = proposed
        if cls == "ReportingFramework":
            eid = f"RF:{fw_slug}"
            ctx_framework = eid
        elif cls == "MetricCategory":
            cur_cat_slug = _slug(label)
            eid = f"CAT:{fw_slug}:{cur_cat_slug}"
            ctx_category = eid
        elif cls == "Metric":
            eid = f"MET:{fw_slug}:{cur_cat_slug or 'uncat'}:{_slug(label)}"
        elif cls == "CalculationModel":
            eid = f"CM:{fw_slug}:{_slug(label)}"
        else:  # Industry
            eid = f"IND:{_slug(label)}"

        if model.add_instance(eid, label, cls, page):
            accepted_e += 1
            added_e.append(eid)

        # structural (compositional) relations from nesting context
        proposed_rels: list[tuple[str, str, str, str, str]] = []
        # (src_id, src_type, relation, dst_id, dst_type)
        if cls == "MetricCategory" and ctx_framework:
            proposed_rels.append((ctx_framework, "ReportingFramework",
                                  "hasCategory", eid, "MetricCategory"))
        if cls == "Metric" and ctx_category:
            proposed_rels.append((ctx_category, "MetricCategory",
                                  "hasMetric", eid, "Metric"))

        # in-text relations: src = the current segment's entity (cls)
        m = _RE_COMPUTED.search(text)
        if m:
            cm_label = _title(m.group(1).strip())
            cm_id = f"CM:{fw_slug}:{_slug(cm_label)}"
            if model.add_instance(cm_id, cm_label, "CalculationModel", page):
                accepted_e += 1
                added_e.append(cm_id)
            proposed_rels.append((eid, cls, "computedBy", cm_id,
                                  "CalculationModel"))
        m = _RE_INDUSTRY.search(text)
        if m:
            ind_label = _title(m.group(1).strip())
            ind_id = f"IND:{_slug(ind_label)}"
            if model.add_instance(ind_id, ind_label, "Industry", page):
                accepted_e += 1
                added_e.append(ind_id)
            # src type is the *current* entity type -> a non-Metric src makes
            # this an illegal edge that phase-2 will reject.
            proposed_rels.append((eid, cls, "appliesToIndustry", ind_id,
                                  "Industry"))

        # --- phase 2: rule-based schema check ---
        for (s_id, s_t, rel, d_id, d_t) in proposed_rels:
            if (s_t, rel, d_t) in ALLOWED_EDGES:
                if model.add_relation(s_id, rel, d_id, page):
                    accepted_r += 1
                    added_r.append([s_id, rel, d_id])
            else:
                rejected_relations.append({"segment": seg_i, "page": page,
                                           "edge": [s_id, rel, d_id],
                                           "src_type": s_t, "dst_type": d_t,
                                           "reason": "edge not in ESGMKG schema"})

        steps.append({"step": seg_i, "stage": "extract+validate",
                      "cq": f"p{page}: {heading}",
                      "added": {"entity": eid, "type": cls,
                                "relations": added_r},
                      "graph": model.to_graph()})

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "ontometric",
        "backend": llm.name,
        "framework": framework,
        "input_segments": len(segments),
        "counts": {
            "accepted_entities": accepted_e,
            "rejected_entities": len(rejected_entities),
            "accepted_relations": accepted_r,
            "rejected_relations": len(rejected_relations),
            "classes": len(model.classes),
        },
        "rejected_entities": rejected_entities,
        "rejected_relations": rejected_relations,
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
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend),
                     ensure_ascii=False))
