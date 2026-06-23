"""LKD-KGC - domain-specific KG construction via knowledge-dependency parsing.

Method (LKD-KGC: Domain-Specific KG Construction via LLM-driven Knowledge
Dependency Parsing, arXiv:2505.24163, Sun et al., EDBT 2026): schema-guided KGC
usually assumes a hand-written schema and processes each document in isolation.
That fails on domain corpora where documents build on one another (a "concept"
note is a prerequisite for the "procedure" note that uses it). LKD-KGC instead

  1. parses *knowledge dependencies* between documents (who must be read first),
  2. derives an optimal read order from that dependency graph,
  3. autoregressively grows an *entity schema* by reading documents in order and
     accumulating hierarchical inter-document context, canonicalising the type
     labels by clustering, then
  4. uses that induced schema to guide unsupervised entity/relation extraction.

No predefined schema, no external reference KB.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    corpus.json - {"domain":..., "documents":[
                      {"id","title","text"}, ...]}
                  Dependencies are *inferred*, not given: document A depends on
                  document B when A's text mentions B's title (a foundational
                  note is therefore read before the notes that cite it).

Outputs (out_dir):
    ontology.ttl   - OWL: induced schema classes (+ DomainEntity root) +
                     object properties + typed individuals (ABox)
    ontology.json  - Cytoscape graph: schema-class nodes + entity nodes,
                     subClassOf / type / relation edges
    steps.json     - one snapshot per document processed in read order
                     (the UI replays schema growth + extraction)
    manifest.json  - summary (read order, raw vs canonical type counts, ...)

Deterministic-on-MOCK ingredients (faithful to the paper):
    * Dependency parsing - directed edge B->A when title(B) occurs in text(A);
      cycles broken deterministically (lowest id wins) so the graph is a DAG.
    * Read-order prioritisation - Kahn topological sort, ties broken by id, so
      foundational documents are processed before the documents that depend on
      them (the paper's "LLM-driven prioritisation", made deterministic).
    * Autoregressive schema generation - read in order; per document pull entity
      *type candidates*, then canonicalise/cluster them (singularise + alias
      map) so synonymous labels collapse to one schema class (the paper's
      embedding-based clustering, made deterministic).
    * Schema-guided extraction - typed entities + relations are emitted only for
      the canonical schema induced so far.
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

EX = "http://example.org/lkdkgc#"
ROOT_CLASS = "DomainEntity"

# ---- Entity-type lexicon (MOCK schema induction) --------------------------
# token (lower) -> raw type candidate label. Several tokens map to synonymous
# labels on purpose, so the clustering step has something to collapse.
_TYPE_LEXICON = {
    "controller": "Controller",
    "controllers": "Controllers",        # synonym -> Controller (plural)
    "sensor": "Sensor",
    "sensors": "Sensors",                 # synonym -> Sensor (plural)
    "actuator": "Actuator",
    "valve": "Valve",
    "pump": "Pump",
    "pumps": "Pumps",                     # synonym -> Pump (plural)
    "tank": "Tank",
    "pipeline": "Pipeline",
    "operator": "Operator",
    "procedure": "Procedure",
    "protocol": "Protocol",
    "alarm": "Alarm",
    "threshold": "Threshold",
}

# Canonicalisation alias map applied after singularisation: collapse remaining
# synonyms onto one canonical schema class.
_CANON_ALIAS = {
    "protocol": "procedure",   # Protocol -> Procedure
}

# Relation lexicon: (verb token -> relation name). Used by schema-guided
# extraction to connect two entities found in the same sentence.
_RELATIONS = [
    ("monitor", "monitors"),
    ("control", "controls"),
    ("regulate", "regulates"),
    ("open", "opens"),
    ("trigger", "triggers"),
    ("follow", "follows"),
    ("read", "reads"),
]


# ---- text helpers ---------------------------------------------------------
def _singular(word: str) -> str:
    w = word
    if w.endswith("ies") and len(w) > 3:
        return w[:-3] + "y"
    if w.endswith("ses") and len(w) > 3:
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _canon_type(raw_label: str) -> str:
    """Singularise + alias-collapse a raw type candidate to a schema class."""
    low = _singular(raw_label.lower())
    low = _CANON_ALIAS.get(low, low)
    return low[:1].upper() + low[1:]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.;\n]+", text) if s.strip()]


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", text.lower()) if t]


# ---- 1. dependency parsing -----------------------------------------------
def _parse_dependencies(docs: list[dict]) -> list[tuple[str, str]]:
    """Edge (B, A): B must be read before A because A mentions title(B)."""
    edges: list[tuple[str, str]] = []
    titles = {d["id"]: d.get("title", "").strip().lower() for d in docs}
    for a in docs:
        atext = a.get("text", "").lower()
        for b in docs:
            if a["id"] == b["id"]:
                continue
            tb = titles[b["id"]]
            if tb and tb in atext:
                edge = (b["id"], a["id"])
                if edge not in edges:
                    edges.append(edge)
    # break cycles deterministically: drop the edge whose source id is larger
    edge_set = set(edges)
    for (u, v) in list(edge_set):
        if (v, u) in edge_set and u > v:
            edge_set.discard((u, v))
    return sorted(edge_set)


# ---- 2. read-order prioritisation (Kahn topo sort, id tie-break) ----------
def _read_order(doc_ids: list[str], edges: list[tuple[str, str]]) -> list[str]:
    indeg = {d: 0 for d in doc_ids}
    succ: dict[str, list[str]] = {d: [] for d in doc_ids}
    for (u, v) in edges:
        indeg[v] += 1
        succ[u].append(v)
    ready = sorted([d for d in doc_ids if indeg[d] == 0])
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(succ[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    # any remaining (shouldn't happen — DAG) appended by id
    for d in sorted(doc_ids):
        if d not in order:
            order.append(d)
    return order


# ---- LLM bridge -----------------------------------------------------------
def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: extract type candidates from the doc text line."""
    try:
        line = [ln for ln in prompt.splitlines() if ln.startswith("Doc:")][-1]
        text = line[len("Doc:"):].strip()
    except Exception:
        return json.dumps({"types": []})
    cands = []
    for tok in _tokens(text):
        if tok in _TYPE_LEXICON:
            lbl = _TYPE_LEXICON[tok]
            if lbl not in cands:
                cands.append(lbl)
    return json.dumps({"types": cands}, ensure_ascii=False)


_PROMPT = (
    "You induce an entity-type schema for a domain knowledge graph. "
    'Return ONLY JSON {{"types":["..."]}} listing entity-type candidates.\n'
    "Doc: {text}\n"
)


def _type_candidates(text: str, llm, mock: bool) -> list[str]:
    if mock:
        raw = llm.complete(_PROMPT.format(text=text), temperature=0.0,
                           json_schema={"type": "object"})
    else:
        raw = llm.complete(_PROMPT.format(text=text), temperature=0.0)
    try:
        return list(json.loads(raw).get("types", []))
    except json.JSONDecodeError:
        return []


# ---- graph model ----------------------------------------------------------
class _Model:
    def __init__(self) -> None:
        self.classes: list[str] = [ROOT_CLASS]
        self.subclass: list[tuple[str, str]] = []
        self.instances: list[dict] = []      # {name, cls, doc}
        self.relations: list[dict] = []       # {src, label, dst, doc}
        self._inst_names: set[str] = set()

    def add_class(self, cls: str) -> None:
        if cls not in self.classes:
            self.classes.append(cls)
        if cls != ROOT_CLASS and (cls, ROOT_CLASS) not in self.subclass:
            self.subclass.append((cls, ROOT_CLASS))

    def add_instance(self, name: str, cls: str, doc: str) -> None:
        self.add_class(cls)
        if name not in self._inst_names:
            self._inst_names.add(name)
            self.instances.append({"name": name, "class": cls, "doc": doc})

    def add_relation(self, src: str, label: str, dst: str, doc: str) -> None:
        rel = {"src": src, "label": label, "dst": dst, "doc": doc}
        if rel not in self.relations:
            self.relations.append(rel)

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for i in self.instances:
            nodes.append({"data": {"id": i["name"], "label": i["name"],
                                   "type": "instance", "cls": i["class"],
                                   "provenance": i["doc"], "attributes": []}})
        edges = []
        for child, parent in self.subclass:
            edges.append({"data": {"id": f"{child}-subClassOf-{parent}",
                                   "source": child, "target": parent,
                                   "label": "subClassOf"}})
        for i in self.instances:
            edges.append({"data": {"id": f"{i['name']}-type-{i['class']}",
                                   "source": i["name"], "target": i["class"],
                                   "label": "type", "provenance": i["doc"]}})
        for r in self.relations:
            edges.append({"data": {
                "id": f"{r['src']}-{r['label']}-{r['dst']}",
                "source": r["src"], "target": r["dst"], "label": r["label"],
                "provenance": r["doc"]}})
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
    for child, parent in model.subclass:
        g.add((EXN[child], RDFS.subClassOf, EXN[parent]))
    rel_names = {r["label"] for r in model.relations}
    for r in sorted(rel_names):
        g.add((EXN[r], RDF.type, OWL.ObjectProperty))
    for i in model.instances:
        g.add((EXN[i["name"]], RDF.type, EXN[i["class"]]))
    for r in model.relations:
        g.add((EXN[r["src"]], EXN[r["label"]], EXN[r["dst"]]))
    return g.serialize(format="turtle")


# ---- entity / relation extraction (schema-guided) -------------------------
def _entity_name(token: str, cls: str) -> str:
    """A stable per-mention entity id: <Class>_<token>."""
    return f"{cls}_{token.lower()}"


def _extract(doc: dict, schema: dict, model: _Model) -> dict:
    """Schema-guided extraction for one document.

    schema: token(lower) -> canonical class (only canonical classes induced so
    far are eligible, the paper's schema-guided constraint).
    Returns {"entities": n, "relations": m}.
    """
    added_e, added_r = 0, 0
    for sent in _sentences(doc.get("text", "")):
        toks = _tokens(sent)
        present: list[tuple[int, str, str]] = []  # (pos, token, class)
        for pos, tok in enumerate(toks):
            base = _singular(tok)
            cls = schema.get(tok) or schema.get(base)
            if cls:
                name = _entity_name(base, cls)
                if name not in model._inst_names:
                    added_e += 1
                model.add_instance(name, cls, doc["id"])
                present.append((pos, base, cls))
        # relation: first verb in the sentence links the first two entities
        rel = None
        for vt, rname in _RELATIONS:
            if any(t == vt or t == vt + "s" or t == vt + "ed" for t in toks):
                rel = rname
                break
        if rel and len(present) >= 2:
            s = _entity_name(present[0][1], present[0][2])
            o = _entity_name(present[1][1], present[1][2])
            if s != o:
                before = len(model.relations)
                model.add_relation(s, rel, o, doc["id"])
                if len(model.relations) > before:
                    added_r += 1
    return {"entities": added_e, "relations": added_r}


def _read_corpus(input_dir: Path) -> dict:
    f = input_dir / "corpus.json"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return json.loads(f.read_text(encoding="utf-8"))


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    corpus = _read_corpus(input_dir)
    docs = corpus.get("documents", [])
    by_id = {d["id"]: d for d in docs}
    llm = get_backend(backend, mock_responder=mock_responder)
    mock = is_mock(llm)

    # 1. dependency parsing + 2. read order
    edges = _parse_dependencies(docs)
    order = _read_order([d["id"] for d in docs], edges)

    model = _Model()
    steps: list[dict] = []
    raw_candidate_count = 0
    schema: dict[str, str] = {}             # token(lower) -> canonical class
    canonical_classes: list[str] = []

    # 3. autoregressive schema generation + 4. schema-guided extraction
    for step_i, doc_id in enumerate(order, 1):
        doc = by_id[doc_id]
        cands = _type_candidates(doc.get("text", ""), llm, mock)
        raw_candidate_count += len(cands)
        new_classes = []
        for raw in cands:
            canon = _canon_type(raw)
            # map every surface token of this candidate to the canonical class
            schema[raw.lower()] = canon
            schema[_singular(raw.lower())] = canon
            if canon not in canonical_classes:
                canonical_classes.append(canon)
                new_classes.append(canon)
                model.add_class(canon)
        ext = _extract(doc, schema, model)
        steps.append({
            "step": step_i, "stage": "read+induce+extract",
            "cq": f"{doc_id}: {doc.get('title','')}",
            "added": {
                "doc": doc_id,
                "type_candidates": cands,
                "new_classes": new_classes,
                "entities": ext["entities"],
                "relations": ext["relations"],
            },
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
        "method": "lkd-kgc",
        "backend": llm.name,
        "domain": corpus.get("domain", ""),
        "input_documents": len(docs),
        "dependency_edges": [list(e) for e in edges],
        "read_order": order,
        "counts": {
            "raw_type_candidates": raw_candidate_count,
            "canonical_classes": len(canonical_classes),
            "instances": len(model.instances),
            "relations": len(model.relations),
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
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend),
                     ensure_ascii=False))
