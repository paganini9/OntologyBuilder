"""SAC-KG - structured, multi-level domain KG construction via a
Generator -> Verifier -> Pruner loop applied recursively (level by level).

Method (Chen et al., "SAC-KG: Exploiting Large Language Models as Skilled
Automatic Constructors for Domain Knowledge Graph", ACL 2024):
starting from seed entities, the KG is grown one *level* at a time. At each
level three components run in sequence:
    1. Generator - proposes candidate triples (relation, child entity) for every
       entity currently at the frontier.
    2. Verifier  - checks each candidate and keeps only the trustworthy ones,
       attaching a confidence.
    3. Pruner    - controls branching/structure so the KG does not explode and
       stays acyclic and free of duplicates.
The children that survive a level become the frontier for the next level, and
the loop repeats. The paper runs this for several levels over a real domain.

IMPORTANT - what this implementation is (and is NOT):
    The REAL SAC-KG Pruner is a generation-relation classifier built on a
    fine-tuned T5 + LoRA model that runs on a GPU; the Generator/Verifier use a
    large LLM with domain corpora. We do NOT reproduce that here. THIS file is a
    deterministic MOCK *simplification* that faithfully mirrors the
    Generator -> Verifier -> Pruner *multi-level loop* structure with no GPU, no
    fine-tuning and no API key, so the construction process is reproducible,
    testable and visualizable. A real hf-local/GPU run (T5-LoRA pruner) is a
    future option, not done here.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    seed_entities.txt  - one seed entity per line (blank / # comment lines ignored)

Outputs (out_dir):
    ontology.ttl    - the KG as OWL (Turtle): entities owl:Class, relations
                      owl:ObjectProperty, plus domain/range per relation
    ontology.json   - final graph as Cytoscape nodes/edges (== cqbycq schema)
    steps.json      - one snapshot per (level, stage) so the UI can replay the
                      Generator/Verifier/Pruner loop being executed
    manifest.json   - summary (backend, level/stage counts, file list)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Make backend.llm importable whether run as a subprocess or imported directly.
import sys

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402

EX = "http://example.org/sackg#"

LEVELS = 2          # number of expansion levels (recursion depth)
TOP_K = 2           # Pruner: max children kept per entity

# Relations the Verifier accepts (domain ontology relation vocabulary).
_ALLOWED_RELATIONS = {
    "hasPart", "consistsOf", "requires", "produces", "controls",
    "connectsTo", "madeOf", "subClassOf", "uses", "measures",
}

# Deterministic domain lexicon: entity -> ordered list of (relation, child).
# The Generator proposes from this; the Verifier/Pruner then filter it. Some
# entries are deliberately bad (unknown child, disallowed relation, cycle,
# duplicate) so the Verifier and Pruner each have something to drop.
_LEXICON: dict[str, list[tuple[str, str]]] = {
    "Engine": [
        ("hasPart", "Piston"),
        ("hasPart", "Crankshaft"),
        ("consistsOf", "Cylinder"),
        ("requires", "Fuel"),
        ("magicallyBecomes", "Unicorn"),   # disallowed relation -> Verifier drops
        ("hasPart", "Engine"),             # self-cycle -> Pruner drops
    ],
    "Piston": [
        ("madeOf", "Aluminum"),
        ("connectsTo", "Crankshaft"),
        ("hasPart", "PistonRing"),
        ("requires", "Lubricant"),
    ],
    "Crankshaft": [
        ("madeOf", "Steel"),
        ("connectsTo", "Bearing"),
        ("hasPart", "Engine"),             # back-edge cycle -> Pruner drops
        ("controls", "Vibration"),
    ],
    "Cylinder": [
        ("hasPart", "CombustionChamber"),
        ("madeOf", "CastIron"),
        ("teleportsTo", "Atlantis"),       # disallowed relation -> Verifier drops
        ("connectsTo", "ValveSet"),
    ],
    # Children below have lexicon entries too, but with only LEVELS=2 they form
    # the leaf frontier and are not expanded further; kept for plausibility.
    "Aluminum": [("uses", "Bauxite")],
    "Steel": [("madeOf", "Iron")],
}

# Entities the Verifier considers "known/plausible". A candidate whose child is
# not plausible is dropped (treated as a hallucination).
_KNOWN_ENTITIES = set(_LEXICON.keys()) | {
    "Fuel", "PistonRing", "Lubricant", "Aluminum", "Crankshaft", "Steel",
    "Bearing", "Vibration", "CombustionChamber", "CastIron", "ValveSet",
    "Bauxite", "Iron", "Piston", "Cylinder",
}
# NOTE: "Unicorn" and "Atlantis" are intentionally absent -> would be dropped by
# the Verifier even if their relations were allowed; here the relation check
# catches them first.


def _gen_prompt(entity: str) -> str:
    return (
        "You are SAC-KG's Generator. Propose candidate triples (relation, child "
        "entity) that expand the given domain entity. Return ONLY a JSON list of "
        '{"relation": str, "child": str}.\n'
        f"Entity: {entity}\n"
    )


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the Generator LLM.

    Reads the entity from the prompt and returns its lexicon candidates as JSON.
    Unknown entities yield an empty candidate list.
    """
    entity = prompt.split("Entity:")[-1].split("\n")[0].strip()
    cands = _LEXICON.get(entity, [])
    return json.dumps(
        [{"relation": r, "child": c} for (r, c) in cands], ensure_ascii=False
    )


class _Model:
    """Accumulated KG, insertion-ordered for deterministic output.

    Graph schema is identical to cqbycq's _Model.to_graph(): entities are
    classes (nodes), relations are object properties (edges).
    """

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []   # {name, domain, range}
        self.data_props: list[dict] = []  # unused here, kept for schema parity
        self._edge_keys: set[tuple] = set()

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def has_edge(self, domain: str, name: str, rng: str) -> bool:
        return (domain, name, rng) in self._edge_keys

    def add_obj(self, p: dict) -> bool:
        key = (p["domain"], p["name"], p["range"])
        if key in self._edge_keys:
            return False
        self.obj_props.append(p)
        self._edge_keys.add(key)
        return True

    def reaches(self, src: str, dst: str) -> bool:
        """True if dst is already reachable from src via existing edges
        (used to reject cycle-forming candidates, like the real Pruner keeps the
        KG a DAG)."""
        if src == dst:
            return True
        adj: dict[str, list[str]] = {}
        for p in self.obj_props:
            adj.setdefault(p["domain"], []).append(p["range"])
        seen = set()
        stack = [src]
        while stack:
            n = stack.pop()
            if n == dst:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adj.get(n, []))
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


def _read_seeds(input_dir: Path) -> list[str]:
    f = input_dir / "seed_entities.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    seeds = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            seeds.append(line)
    return seeds


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    seeds = _read_seeds(input_dir)

    model = _Model()
    steps: list[dict] = []

    # Seeds are the level-0 frontier; seed entities are added as classes.
    frontier: list[str] = []
    for s in seeds:
        if model.add_class(s):
            frontier.append(s)
        elif s not in frontier:
            frontier.append(s)

    totals = {"generated": 0, "verified": 0, "verifier_dropped": 0,
              "pruner_dropped": 0, "edges_added": 0}

    for level in range(1, LEVELS + 1):
        # ---- GENERATOR --------------------------------------------------
        # Propose candidates for every entity on the current frontier.
        candidates: list[dict] = []
        for entity in frontier:
            raw = llm.complete(_gen_prompt(entity), temperature=0.0,
                               json_schema={"type": "array"})
            try:
                proposed = json.loads(raw)
            except json.JSONDecodeError:
                proposed = []
            for item in proposed:
                rel = item.get("relation", "")
                child = item.get("child", "")
                if rel and child:
                    candidates.append({"parent": entity, "relation": rel,
                                       "child": child})
        totals["generated"] += len(candidates)
        steps.append({
            "step": len(steps) + 1,
            "level": level,
            "stage": "generate",
            "label": f"L{level} generate",
            "frontier": list(frontier),
            "added": {"candidates": [
                {"parent": c["parent"], "relation": c["relation"],
                 "child": c["child"]} for c in candidates]},
            "graph": model.to_graph(),
        })

        # ---- VERIFIER ---------------------------------------------------
        # Keep only candidates whose relation is allowed AND whose child is a
        # plausible/known entity; attach a deterministic confidence. Others are
        # treated as hallucinations and dropped.
        verified: list[dict] = []
        dropped_by_verifier: list[dict] = []
        for c in candidates:
            ok_rel = c["relation"] in _ALLOWED_RELATIONS
            ok_child = c["child"] in _KNOWN_ENTITIES
            if ok_rel and ok_child:
                # stable confidence: known + allowed -> high
                conf = 0.9 if c["child"] in _LEXICON else 0.75
                verified.append({**c, "confidence": conf})
            else:
                reason = ("relation-not-allowed" if not ok_rel
                          else "child-implausible")
                dropped_by_verifier.append({**c, "reason": reason})
        totals["verified"] += len(verified)
        totals["verifier_dropped"] += len(dropped_by_verifier)
        steps.append({
            "step": len(steps) + 1,
            "level": level,
            "stage": "verify",
            "label": f"L{level} verify",
            "frontier": list(frontier),
            "added": {"verified": verified, "dropped": dropped_by_verifier},
            "graph": model.to_graph(),
        })

        # ---- PRUNER -----------------------------------------------------
        # Deterministic stand-in for the T5-LoRA pruner: cap branching to TOP_K
        # children per parent (stable order = verification order), and drop
        # candidates that would create a duplicate or a cycle (keep the KG a
        # DAG). Survivors are written into the model.
        kept_per_parent: dict[str, int] = {}
        pruner_dropped: list[dict] = []
        added_edges: list[dict] = []
        next_frontier: list[str] = []
        for c in verified:
            parent, rel, child = c["parent"], c["relation"], c["child"]
            # duplicate edge?
            if model.has_edge(parent, rel, child):
                pruner_dropped.append({**c, "reason": "duplicate"})
                continue
            # cycle? (child already reaches parent, or self-loop)
            if model.reaches(child, parent):
                pruner_dropped.append({**c, "reason": "cycle"})
                continue
            # branching cap
            if kept_per_parent.get(parent, 0) >= TOP_K:
                pruner_dropped.append({**c, "reason": "branching-cap"})
                continue
            # accept
            model.add_class(child)
            edge = {"name": rel, "domain": parent, "range": child}
            model.add_obj(edge)
            kept_per_parent[parent] = kept_per_parent.get(parent, 0) + 1
            added_edges.append({**edge, "confidence": c["confidence"]})
            if child not in next_frontier:
                next_frontier.append(child)
        totals["pruner_dropped"] += len(pruner_dropped)
        totals["edges_added"] += len(added_edges)
        steps.append({
            "step": len(steps) + 1,
            "level": level,
            "stage": "prune",
            "label": f"L{level} prune",
            "frontier": list(frontier),
            "added": {"edges": added_edges, "dropped": pruner_dropped},
            "graph": model.to_graph(),
        })

        # children that survived become the next level's frontier
        frontier = next_frontier
        if not frontier:
            break

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "sac-kg",
        "backend": llm.name,
        "seeds": len(seeds),
        "levels": LEVELS,
        "top_k": TOP_K,
        "loop": totals,
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
