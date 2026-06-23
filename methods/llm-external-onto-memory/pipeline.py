"""LLM External Ontology Memory - construct & validate an ontological memory layer.

Method (Automatic Ontology Construction Using LLMs as an External Layer of Memory,
Verification, and Planning for Hybrid Intelligent Systems, arXiv:2604.20795): an
automated pipeline builds and maintains an RDF/OWL knowledge graph from
**heterogeneous sources** (documents, APIs, dialogue logs). It runs entity
recognition -> relation extraction -> normalization -> triple generation, then
**validates with SHACL/OWL constraints** in a *generation-verification-correction*
loop and applies **continuous graph updates**.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    sources.json - {"sources":[{"id","type":"document|api|dialogue","content":...}]}
                   document/dialogue content is text; api content is a record.

Outputs (out_dir):
    ontology.ttl   - OWL classes + object/datatype properties + validated ABox
                     (typed individuals, worksIn relations, email/joinedOn literals)
    ontology.json  - Cytoscape graph: class nodes + entity nodes (carry source
                     provenance + accepted data attributes); worksIn edges
    steps.json     - one snapshot per source (UI replays continuous updates)
    manifest.json  - summary + corrected / rejected audit trails

Distinctive vs. a reject-only validator: the SHACL/OWL check has THREE outcomes -
accept, **correct** (a fixable violation is repaired, e.g. a non-ISO date is
normalized to xsd:date), or reject (an unfixable violation, e.g. a worksIn whose
value is not a Department, or an e-mail with no '@').
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

EX = "http://example.org/extmem#"

# ---- ontology (OWL) + SHACL shapes (first-class constraints) ----------------
CLASSES = ["Person", "Department"]
OBJ_PROPS = {"worksIn": {"domain": "Person", "range": "Department"}}
DATA_PROPS = {
    "email": {"domain": "Person", "datatype": "string", "pattern": r".+@.+"},
    "joinedOn": {"domain": "Person", "datatype": "date"},
}

# entity normalization: surface alias -> canonical Department label
DEPT_ALIASES = {"eng": "Engineering", "engineering": "Engineering",
                "engineering dept": "Engineering", "engineering department":
                "Engineering"}

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def _pascal(label: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", label) if w]
    return "".join(w[:1].upper() + w[1:] for w in words) or "Entity"


def _normalize_date(s: str) -> tuple[Optional[str], bool]:
    """Return (iso_date, corrected?) or (None, False) if uncorrectable."""
    s = s.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s, False                     # already xsd:date
    m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}", True
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$", s)
    if m and m.group(1).lower() in _MONTHS:
        return (f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-"
                f"{int(m.group(2)):02d}"), True
    return None, False


# ---- entity recognition + relation extraction (rule-based, backend-agnostic) -
_SENT_PATTERNS = [
    (re.compile(r"^(.+?) works in (.+)$", re.I), "worksIn", "obj"),
    (re.compile(r"^(.+?) joined on (.+)$", re.I), "joinedOn", "data"),
    (re.compile(r"^(.+?) can be reached at (.+)$", re.I), "email", "data"),
]


def _facts_from_text(text: str) -> list[dict]:
    facts: list[dict] = []
    for raw in re.split(r"(?<=[.])\s+", text.strip()):
        sent = raw.strip().rstrip(".").strip()
        if not sent:
            continue
        for rx, prop, kind in _SENT_PATTERNS:
            m = rx.match(sent)
            if m:
                facts.append({"subj": m.group(1).strip(), "prop": prop,
                              "value": m.group(2).strip(), "kind": kind})
                break
    return facts


def _facts_from_api(rec: dict) -> list[dict]:
    subj = rec.get("person", "").strip()
    facts: list[dict] = []
    if not subj:
        return facts
    if rec.get("worksIn"):
        facts.append({"subj": subj, "prop": "worksIn",
                      "value": str(rec["worksIn"]).strip(), "kind": "obj"})
    if rec.get("joinedOn"):
        facts.append({"subj": subj, "prop": "joinedOn",
                      "value": str(rec["joinedOn"]).strip(), "kind": "data"})
    if rec.get("email"):
        facts.append({"subj": subj, "prop": "email",
                      "value": str(rec["email"]).strip(), "kind": "data"})
    return facts


def _extract_facts(source: dict) -> list[dict]:
    """Heterogeneous ingestion: dispatch on source type."""
    typ = source.get("type")
    content = source.get("content")
    if typ == "api" and isinstance(content, dict):
        return _facts_from_api(content)
    if typ == "dialogue" and isinstance(content, list):
        facts: list[dict] = []
        for turn in content:
            facts.extend(_facts_from_text(turn.get("text", "")))
        return facts
    if typ == "document":
        return _facts_from_text(str(content))
    return []


# ---- graph model (continuous updates) --------------------------------------
class _Model:
    def __init__(self) -> None:
        self.classes: list[str] = list(CLASSES)
        self.items: list[dict] = []        # {id,label,cls,source,attrs:{}}
        self.relations: list[dict] = []    # {src,label,dst,source}
        self._by_label: dict[str, dict] = {}

    def resolve(self, surface: str, default_cls: str, source: str) -> dict:
        """Normalize a mention to a canonical item (creating it if new)."""
        key = surface.strip().lower()
        label = DEPT_ALIASES.get(key, surface.strip())
        lookup = label.lower()
        if lookup in self._by_label:
            return self._by_label[lookup]
        cls = "Department" if label in DEPT_ALIASES.values() else default_cls
        item = {"id": _pascal(label), "label": label, "cls": cls,
                "source": source, "attrs": {}}
        self.items.append(item)
        self._by_label[lookup] = item
        return item

    def add_relation(self, src: str, label: str, dst: str, source: str) -> bool:
        rel = {"src": src, "label": label, "dst": dst, "source": source}
        if rel in self.relations:
            return False
        self.relations.append(rel)
        return True

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for it in self.items:
            attrs = [f"{k}={v}" for k, v in it["attrs"].items()]
            nodes.append({"data": {"id": it["id"], "label": it["label"],
                                   "type": "instance", "cls": it["cls"],
                                   "provenance": it["source"],
                                   "attributes": attrs}})
        edges = []
        for it in self.items:
            edges.append({"data": {"id": f"{it['id']}-instanceOf-{it['cls']}",
                                   "source": it["id"], "target": it["cls"],
                                   "label": "instanceOf"}})
        for r in self.relations:
            edges.append({"data": {"id": f"{r['src']}-{r['label']}-{r['dst']}",
                                   "source": r["src"], "target": r["dst"],
                                   "label": r["label"],
                                   "provenance": r["source"]}})
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
    for p in OBJ_PROPS:
        g.add((EXN[p], RDF.type, OWL.ObjectProperty))
    for p in DATA_PROPS:
        g.add((EXN[p], RDF.type, OWL.DatatypeProperty))
    for it in model.items:
        u = EXN[it["id"]]
        g.add((u, RDF.type, EXN[it["cls"]]))
        g.add((u, RDFS.label, Literal(it["label"])))
        for k, v in it["attrs"].items():
            dt = XSD.date if DATA_PROPS.get(k, {}).get("datatype") == "date" \
                else XSD.string
            g.add((u, EXN[k], Literal(v, datatype=dt)))
    for r in model.relations:
        g.add((EXN[r["src"]], EXN[r["label"]], EXN[r["dst"]]))
    return g.serialize(format="turtle")


def _read_sources(input_dir: Path) -> list[dict]:
    f = input_dir / "sources.json"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return json.loads(f.read_text(encoding="utf-8")).get("sources", [])


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend)
    sources = _read_sources(input_dir)

    model = _Model()
    steps: list[dict] = []
    corrected: list[dict] = []
    rejected: list[dict] = []
    accepted = 0
    source_types: dict[str, int] = {}

    for src in sources:
        sid = src.get("id", "?")
        styp = src.get("type", "?")
        source_types[styp] = source_types.get(styp, 0) + 1
        added_items: list[str] = []
        added: list[list] = []
        step_corr: list[dict] = []
        step_rej: list[dict] = []

        for fact in _extract_facts(src):
            subj = model.resolve(fact["subj"], "Person", sid)
            if subj["id"] not in added_items:
                added_items.append(subj["id"])
            prop = fact["prop"]
            val = fact["value"]

            if fact["kind"] == "obj":  # worksIn -> SHACL sh:class verification
                obj = model.resolve(val, OBJ_PROPS[prop]["range"], sid)
                if obj["id"] not in added_items:
                    added_items.append(obj["id"])
                want = OBJ_PROPS[prop]["range"]
                if obj["cls"] != want:
                    rej = {"source": sid, "subj": subj["id"], "prop": prop,
                           "value": obj["id"], "found_type": obj["cls"],
                           "reason": f"sh:class {want} violated"}
                    rejected.append(rej)
                    step_rej.append(rej)
                    continue
                if model.add_relation(subj["id"], prop, obj["id"], sid):
                    accepted += 1
                    added.append([subj["id"], prop, obj["id"]])
            else:                       # data property -> verify/correct
                spec = DATA_PROPS[prop]
                if spec["datatype"] == "date":
                    iso, was_corr = _normalize_date(val)
                    if iso is None:
                        rej = {"source": sid, "subj": subj["id"], "prop": prop,
                               "value": val, "reason": "not a valid xsd:date"}
                        rejected.append(rej)
                        step_rej.append(rej)
                        continue
                    if was_corr:
                        c = {"source": sid, "subj": subj["id"], "prop": prop,
                             "raw": val, "fixed": iso}
                        corrected.append(c)
                        step_corr.append(c)
                    subj["attrs"][prop] = iso
                    accepted += 1
                    added.append([subj["id"], prop, iso])
                else:                   # string with sh:pattern (e.g. e-mail)
                    if not re.match(spec.get("pattern", ".*"), val):
                        rej = {"source": sid, "subj": subj["id"], "prop": prop,
                               "value": val, "reason": "sh:pattern violated"}
                        rejected.append(rej)
                        step_rej.append(rej)
                        continue
                    subj["attrs"][prop] = val
                    accepted += 1
                    added.append([subj["id"], prop, val])

        steps.append({"step": len(steps) + 1,
                      "stage": "ingest+extract+normalize+validate",
                      "cq": f"[{styp}] {sid}",
                      "added": {"items": added_items, "asserted": added,
                                "corrected": step_corr, "rejected": step_rej},
                      "graph": model.to_graph()})

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "llm-external-onto-memory",
        "backend": llm.name,
        "input_sources": len(sources),
        "source_types": source_types,
        "counts": {
            "recognized_entities": len(model.items),
            "accepted_assertions": accepted,
            "corrected_assertions": len(corrected),
            "rejected_assertions": len(rejected),
            "classes": len(model.classes),
        },
        "corrected": corrected,
        "rejected": rejected,
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
