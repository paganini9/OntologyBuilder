"""GPTKB - materialize an LLM's PARAMETRIC knowledge by recursive querying.

Method (Hu, Nguyen, Ghosh, Razniewski, ACL 2025 / arXiv 2411.04920, gptkb.org):
there is NO input corpus. Starting from a few SEED entities, the LLM is asked
"what do you know about <entity>?"; its answer is parsed into (subject, relation,
object) triples. Every object that is itself an entity becomes a new node to be
expanded. This recursive seed expansion is run breadth-first up to a depth limit,
and the discovered entities/triples are consolidated (deduplicated) into a single
knowledge base. The knowledge is the model's own - the corpus is the model.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    seed_entities.txt  - one seed entity per line (blank lines / # comments ignored)

Outputs (out_dir):
    ontology.ttl    - the materialized KB (Turtle / OWL)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per expanded entity, so the UI can show the
                      recursive crawl growing the KB
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend the model answers the
"tell me about X" query; with MOCK a deterministic built-in knowledge table
answers, so the recursive expansion is reproducible and testable.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Optional

# Make backend.llm importable whether run as a subprocess or imported directly.
import sys

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402

EX = "http://example.org/gptkb#"

DEPTH_LIMIT = 2

# The mock "LLM": a small deterministic slice of parametric knowledge. Each entry
# is entity -> list of (relation, object). Objects that are themselves keys here
# get expanded recursively, which is what gives the crawl material to work with.
_KNOWLEDGE: dict[str, list[tuple[str, str]]] = {
    "Motor": [("hasPart", "Rotor"), ("hasPart", "Stator"), ("requires", "Power")],
    "Pump": [("hasPart", "Impeller"), ("movesFluid", "Coolant"), ("requires", "Power")],
    "Rotor": [("madeOf", "Steel"), ("rotatesIn", "Stator")],
    "Stator": [("madeOf", "Copper"), ("hasPart", "Winding")],
    "Impeller": [("madeOf", "Steel"), ("movesFluid", "Coolant")],
    "Power": [("suppliedBy", "Battery"), ("measuredIn", "Watt")],
    "Coolant": [("flowsThrough", "Pump"), ("madeOf", "Water")],
    "Battery": [("storesEnergy", "Power"), ("madeOf", "Lithium")],
    "Steel": [("isA", "Metal")],
    "Copper": [("isA", "Metal")],
    "Winding": [("madeOf", "Copper")],
}


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM.

    Parses the queried entity out of the prompt and returns the model's
    "parametric knowledge" about it as a JSON list of {relation, object}.
    Unknown entities return an empty fact list (a leaf).
    """
    entity = prompt.split("Entity:")[-1].split("\n")[0].strip()
    facts = _KNOWLEDGE.get(entity, [])
    return json.dumps(
        {"entity": entity,
         "facts": [{"relation": r, "object": o} for r, o in facts]},
        ensure_ascii=False,
    )


_PROMPT = (
    "You are a knowledge base. State, from your own parametric knowledge, the "
    "salient facts about the given entity. Return ONLY JSON with keys: entity "
    "(string), facts (list of {{relation, object}} where relation is a "
    "camelCase predicate and object is an entity or value).\n"
    "Entity: {entity}\n"
)


def _read_seeds(input_dir: Path) -> list[str]:
    f = input_dir / "seed_entities.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    seeds = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in seeds:
            seeds.append(line)
    return seeds


class _Model:
    """Accumulated KB graph, in insertion order for deterministic output.

    Mirrors cqbycq's _Model.to_graph() schema exactly so the frontend renders it
    unchanged: nodes carry {id,label,type,attributes}, edges {id,source,target,
    label}.
    """

    def __init__(self) -> None:
        self.entities: list[str] = []
        self.rels: list[dict] = []  # {name, domain, range}

    def add_entity(self, e: str) -> bool:
        if e and e not in self.entities:
            self.entities.append(e)
            return True
        return False

    def add_rel(self, p: dict) -> bool:
        if p not in self.rels:
            self.rels.append(p)
            return True
        return False

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": e, "label": e, "type": "class", "attributes": []}}
            for e in self.entities
        ]
        edges = [
            {"data": {"id": f"{p['domain']}-{p['name']}-{p['range']}",
                      "source": p["domain"], "target": p["range"],
                      "label": p["name"]}}
            for p in self.rels
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
    for e in model.entities:
        g.add((EXN[e], RDF.type, OWL.Class))
    seen_props = set()
    for p in model.rels:
        pr = EXN[p["name"]]
        if p["name"] not in seen_props:
            g.add((pr, RDF.type, OWL.ObjectProperty))
            seen_props.add(p["name"])
        # materialize the actual triple subject -> object as well
        g.add((EXN[p["domain"]], pr, EXN[p["range"]]))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    seeds = _read_seeds(input_dir)

    model = _Model()
    steps = []

    # Breadth-first recursive expansion with a depth limit. `visited` is the
    # consolidation/dedup set: an entity is queried at most once even if it is
    # reached again as the object of several triples.
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    for s in seeds:
        model.add_entity(s)
        queue.append((s, 0))

    step_no = 0
    while queue:
        entity, depth = queue.popleft()
        if entity in visited:
            continue
        visited.add(entity)

        raw = llm.complete(_PROMPT.format(entity=entity), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            ans = json.loads(raw)
        except json.JSONDecodeError:
            ans = {"entity": entity, "facts": []}

        added_e, added_r = [], []
        for fact in ans.get("facts", []):
            obj = fact.get("object", "")
            rel = fact.get("relation", "")
            if not obj or not rel:
                continue
            if model.add_entity(obj):
                added_e.append(obj)
            p = {"name": rel, "domain": entity, "range": obj}
            if model.add_rel(p):
                added_r.append(p)
            # recurse: enqueue newly discovered entities for expansion, but only
            # while we are under the depth limit.
            if depth < DEPTH_LIMIT and obj not in visited:
                queue.append((obj, depth + 1))

        step_no += 1
        steps.append({
            "step": step_no,
            "cq": f"expand: {entity} (depth {depth})",
            "entity": entity,
            "depth": depth,
            "added": {"entities": added_e, "relations": added_r},
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
        "method": "gptkb",
        "backend": llm.name,
        "input_seeds": len(seeds),
        "depth_limit": DEPTH_LIMIT,
        "counts": {
            "entities": len(model.entities),
            "relations": len(model.rels),
            "expanded": len(visited),
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
