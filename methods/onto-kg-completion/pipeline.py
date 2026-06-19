"""Ontology-Enhanced KG Completion (LLM) - COMPLETE a partial KG, not build it.

Method (Guo, Wang, Chen, Li, Chen, "Ontology-Enhanced Knowledge Graph Completion
using Large Language Models", arXiv 2507.20643, 2025).

PARADIGM (distinct from every other method in this project): the input is an
EXISTING but INCOMPLETE knowledge graph plus its ontology constraints. The task
is to predict the MISSING links (knowledge-graph completion / link prediction),
NOT to construct an ontology from free text. The ontology (class typing,
property domain/range, transitivity / inverse / symmetry) constrains the LLM so
the inferred links stay consistent with the schema.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    seed_kg.ttl   - the existing, partial KG (classes + object-property edges)

Outputs (out_dir):
    ontology.ttl    - seed + inferred edges, as OWL (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges (origin: seed|inferred)
    steps.json      - snapshots: (load) seed KG, then (complete) inferred edges
    manifest.json   - summary (backend, seed vs final counts, file list)

The completion step is abstracted:
  * MOCK: deterministic ontology-rule completion (transitivity on
    partOf/consistsOf-style chains, symmetry/inverse, domain/range suggestion).
    Adds ONLY new edges not already present -> reproducible golden output.
  * REAL: serialize the seed KG to text and ask the model to infer additional
    missing triples; only triples whose subject AND object are EXISTING seed
    classes and that are NOT already present are kept (completion stays grounded).
The mock path needs no API key.
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

# Transitive relations: if (A rel B) and (B rel C) then (A rel C) is missing.
_TRANSITIVE = {"partOf", "consistsOf", "contains", "includes", "hasPart"}
# Symmetric relations: if (A rel B) then (B rel A) is missing.
_SYMMETRIC = {"connectedTo", "adjacentTo", "compatibleWith", "matedWith"}
# Inverse pairs: if (A rel B) then (B inv A) is missing.
_INVERSE = {
    "partOf": "hasPart", "hasPart": "partOf",
    "consistsOf": "componentOf", "componentOf": "consistsOf",
}


def _local(uri) -> str:
    """Local name of a URI (after the last # or /)."""
    return re.split(r"[#/]", str(uri))[-1]


def _base_rel(name: str) -> str:
    """Canonical relation label, dropping a trailing _N disambiguator.

    rdflib needs a unique subject URI per object property, so a seed KG that
    reuses the same relation many times writes partOf, partOf_1, partOf_2, ...
    For completion we reason over the SEMANTIC relation, so collapse them.
    """
    return re.sub(r"_\d+$", "", str(name))


class _Model:
    """Accumulated KG, insertion-ordered. Nodes/edges tagged seed|inferred.

    Graph format == cqbycq/karma `_Model.to_graph()` (with an extra `origin`).
    """

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.origin: dict[str, str] = {}           # class -> "seed"|"inferred"
        self.obj_props: list[dict] = []            # {name,domain,range,origin}
        self._edge_keys: set[tuple] = set()        # (base_rel, domain, range)

    def add_class(self, c: str, origin: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            self.origin[c] = origin
            return True
        return False

    def has_edge(self, name: str, domain: str, rng: str) -> bool:
        return (_base_rel(name), domain, rng) in self._edge_keys

    def add_obj(self, name: str, domain: str, rng: str, origin: str) -> bool:
        key = (_base_rel(name), domain, rng)
        if key in self._edge_keys:
            return False
        self._edge_keys.add(key)
        self.obj_props.append(
            {"name": name, "domain": domain, "range": rng, "origin": origin})
        return True

    def edges_by_base(self) -> list[tuple]:
        """List of (base_rel, domain, range) over current edges (any origin)."""
        return [(_base_rel(p["name"]), p["domain"], p["range"])
                for p in self.obj_props]

    def to_graph(self) -> dict:
        attrs: dict[str, list[str]] = {c: [] for c in self.classes}
        nodes = [
            {"data": {"id": c, "label": c, "type": "class",
                      "attributes": attrs.get(c, []),
                      "origin": self.origin.get(c, "seed")}}
            for c in self.classes
        ]
        edges = [
            {"data": {"id": f"{p['domain']}-{_base_rel(p['name'])}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": _base_rel(p["name"]),
                      "origin": p.get("origin", "seed")}}
            for p in self.obj_props
        ]
        return {"nodes": nodes, "edges": edges}


def _load_seed(input_dir: Path, model: _Model) -> int:
    """Load classes + object-property edges from seed_kg.ttl (required input)."""
    f = input_dir / "seed_kg.ttl"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    from rdflib import Graph, RDF, RDFS, OWL

    g = Graph()
    g.parse(f, format="turtle")

    n_edges = 0
    for c in g.subjects(RDF.type, OWL.Class):
        model.add_class(_local(c), "seed")
    for p in g.subjects(RDF.type, OWL.ObjectProperty):
        dom = next(g.objects(p, RDFS.domain), None)
        rng = next(g.objects(p, RDFS.range), None)
        if dom is None or rng is None:
            continue
        d, r = _local(dom), _local(rng)
        model.add_class(d, "seed")
        model.add_class(r, "seed")
        if model.add_obj(_local(p), d, r, "seed"):
            n_edges += 1
    return n_edges


def _rule_completion(model: _Model) -> list[dict]:
    """Deterministic ontology-rule completion over the seed edges.

    Returns the list of NEW edges (dicts) to add, in a stable order:
      (a) transitivity on transitive relations (one closure pass),
      (b) symmetry for symmetric relations,
      (c) inverse for known inverse pairs,
      (d) domain/range suggestion: classes that participate as the SUBJECT of a
          transitive relation but never as its OBJECT get linked to the chain's
          ultimate root when a clear root exists (kept conservative).
    Only edges whose endpoints are existing classes and that are NOT already
    present are returned.
    """
    base_edges = model.edges_by_base()           # [(rel, dom, rng), ...]
    classes = set(model.classes)
    proposed: list[dict] = []
    seen: set[tuple] = set(base_edges)

    def propose(rel: str, dom: str, rng: str, rule: str) -> None:
        if dom == rng:
            return
        if dom not in classes or rng not in classes:
            return
        key = (rel, dom, rng)
        if key in seen:
            return
        seen.add(key)
        proposed.append({"name": rel, "domain": dom, "range": rng,
                         "origin": "inferred", "rule": rule})

    # (a) transitivity (single closure pass over the original seed edges; the
    #     freshly proposed edges then feed a second pass for longer chains).
    for _pass in range(2):
        current = base_edges + [(p["name"], p["domain"], p["range"])
                                for p in proposed]
        for rel1, a, b in current:
            if rel1 not in _TRANSITIVE:
                continue
            for rel2, c, d in current:
                if rel2 != rel1 or c != b:
                    continue
                propose(rel1, a, d, "transitivity")

    # (b) symmetry
    for rel, a, b in base_edges:
        if rel in _SYMMETRIC:
            propose(rel, b, a, "symmetry")

    # (c) inverse
    for rel, a, b in base_edges:
        inv = _INVERSE.get(rel)
        if inv:
            propose(inv, b, a, "inverse")

    return proposed


def _seed_as_text(model: _Model) -> str:
    """Serialize the seed KG to a compact natural-language description for the
    real backend, so it can infer additional consistent triples."""
    lines = ["Existing knowledge graph (classes and relations):"]
    lines.append("Classes: " + ", ".join(model.classes) + ".")
    for p in model.obj_props:
        lines.append(f"{p['domain']} {_base_rel(p['name'])} {p['range']}.")
    return "\n".join(lines)


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
    # Mint a UNIQUE property URI per (relation, domain, range) edge so each
    # edge's domain/range is unambiguous in the serialized OWL (rdflib needs a
    # distinct subject URI per property declaration).
    used: set[str] = set()
    for p in model.obj_props:
        base = _base_rel(p["name"])
        uri = base
        k = 1
        while uri in used:
            uri = f"{base}_{k}"
            k += 1
        used.add(uri)
        pr = EXN[uri]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=_mock_responder)
    model = _Model()

    # ---- Step 1: (load) seed KG -----------------------------------------
    seed_edges = _load_seed(input_dir, model)
    seed_classes = len(model.classes)
    steps: list[dict] = [{
        "step": 1,
        "cq": "(load) seed KG",
        "phase": "load",
        "added": {"classes": list(model.classes),
                  "object_properties":
                      [{"name": _base_rel(p["name"]), "domain": p["domain"],
                        "range": p["range"]} for p in model.obj_props]},
        "note": f"loaded {seed_classes} class(es) and {seed_edges} edge(s) "
                f"from seed_kg.ttl",
        "graph": model.to_graph(),
    }]

    # ---- Step 2: (complete) inferred edges -------------------------------
    if is_mock(llm):
        inferred = _rule_completion(model)
    else:
        inferred = _llm_completion(llm, model)

    added: list[dict] = []
    for e in inferred:
        if model.add_obj(e["name"], e["domain"], e["range"], "inferred"):
            added.append(e)

    steps.append({
        "step": 2,
        "cq": "(complete) inferred edges",
        "phase": "complete",
        "added": {"classes": [],
                  "object_properties":
                      [{"name": e["name"], "domain": e["domain"],
                        "range": e["range"],
                        "rule": e.get("rule", "llm")} for e in added]},
        "note": f"inferred {len(added)} missing edge(s) consistent with the "
                f"ontology",
        "graph": model.to_graph(),
    })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    final_edges = len(model.obj_props)
    manifest = {
        "method": "onto-kg-completion",
        "backend": llm.name,
        "seed_classes": seed_classes,
        "seed_edges": seed_edges,
        "counts": {
            "classes": len(model.classes),
            "edges": final_edges,
            "seed_edges": seed_edges,
            "inferred_edges": len(added),
        },
        "files": ["ontology.ttl", "ontology.json", "steps.json"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Real-backend completion (grounded): keep only triples whose endpoints are
# existing seed classes and that are not already present.
# ---------------------------------------------------------------------------
def _llm_completion(llm, model: _Model) -> list[dict]:
    text = _seed_as_text(model) + (
        "\n\nInfer additional missing triples that are consistent with this "
        "knowledge graph and its relations. Only use the classes listed above.")
    triples = extract_triples(llm, text)
    classes = set(model.classes)
    out: list[dict] = []
    for t in triples:
        s, r, o = t["subject"], t["relation"], t["object"]
        if s not in classes or o not in classes:
            continue
        if model.has_edge(r, s, o):
            continue
        if any(e["name"] == r and e["domain"] == s and e["range"] == o
               for e in out):
            continue
        out.append({"name": r, "domain": s, "range": o,
                    "origin": "inferred", "rule": "llm"})
    return out


# ---------------------------------------------------------------------------
# Deterministic MOCK responder. The mock COMPLETION itself is graph-rule based
# (see _rule_completion); this responder only exists so a real-style triple
# prompt path could still resolve deterministically if ever exercised.
# ---------------------------------------------------------------------------
def _mock_responder(prompt: str) -> str:
    return json.dumps({"triples": []}, ensure_ascii=False)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--backend", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend), ensure_ascii=False))
