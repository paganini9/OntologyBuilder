"""AutoSchemaKG - autonomous KG construction with bottom-up schema induction.

Method (Bai et al., arXiv 2505.23628, 2025; code: HKUST-KnowComp/AutoSchemaKG):
construct a knowledge graph from raw text WITHOUT any predefined schema. Two
things happen autonomously:

    Stage A  - triple extraction: pull (subject, relation, object) triples from
               each sentence. Subjects/objects become *instances*.
    Stage B  - schema induction: the schema is **induced bottom-up from the data**
               (not supplied by a human): every instance is assigned an entity
               TYPE, every relation label becomes a relation type. Classes emerge
               from the extracted instances rather than being given in advance.

That second point is the whole idea of AutoSchemaKG: the ontology/schema is a
*product* of extraction, induced from the text, with zero predefined schema.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free text; one sentence per line (or split on '.').

Outputs (out_dir):
    ontology.ttl    - induced schema + instances (Turtle / OWL)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per sentence + a final schema-induction step
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend the model does extraction; with
MOCK a deterministic heuristic does, so the output is reproducible and testable.
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

EX = "http://example.org/autoschemakg#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We",
}

# relational verbs -> canonical relation name (shared with cqbycq's vocabulary)
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
}

# --- Stage B: bottom-up type induction rules (deterministic) -----------------
# Exact instance names that map to a type.
_TYPE_EXACT = {
    "Motor": "Device", "Pump": "Device", "Controller": "Device",
    "Sensor": "Device",
    "Steel": "Material", "Copper": "Material", "Coolant": "Material",
    "Material": "Material", "Aluminum": "Material", "Aluminium": "Material",
    "Assembly": "System", "Product": "System", "System": "System",
}
# Suffix rules (applied if no exact match).
_TYPE_SUFFIX = {
    "er": "Device", "or": "Device",
}


def _induce_type(instance: str) -> str:
    """Bottom-up rule: derive an entity TYPE from an extracted instance name."""
    if instance in _TYPE_EXACT:
        return _TYPE_EXACT[instance]
    for suf, t in _TYPE_SUFFIX.items():
        if len(instance) > len(suf) and instance.endswith(suf):
            return t
    return "Entity"


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _capitalized_nouns(sentence: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM: parse a sentence -> triples JSON.

    Stage A only: extract (subject, relation, object) triples. Schema induction
    (Stage B) is a deterministic post-process in `run`, mirroring AutoSchemaKG's
    "extract first, induce schema from the data" flow.
    """
    sent = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    nouns = _capitalized_nouns(sent)
    words = re.findall(r"[a-zA-Z]+", sent.lower())
    noun_words = {n.lower() for n in nouns} | {n.lower() + "s" for n in nouns}
    rel = next((_REL[w] for w in words if w in _REL and w not in noun_words), None)

    triples = []
    if rel and len(nouns) >= 2:
        triples.append({"subject": nouns[0], "relation": rel, "object": nouns[1]})
        # chain extra objects to the same subject for richer graphs
        for obj in nouns[2:]:
            triples.append({"subject": nouns[0], "relation": rel, "object": obj})

    return json.dumps({"triples": triples}, ensure_ascii=False)


_PROMPT = (
    "You build a knowledge graph from text with NO predefined schema. Extract "
    "every factual relation in the sentence as triples. Return ONLY JSON with "
    "key 'triples' = list of {{subject, relation, object}}. Use short PascalCase "
    "entity names and camelCase relation names.\n"
    "Sentence: {sent}\n"
)


def _read_sentences(input_dir: Path) -> list[str]:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    raw = f.read_text(encoding="utf-8")
    sents: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # support both one-sentence-per-line and '.'-separated text
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip().rstrip(".!?").strip()
            if part:
                sents.append(part)
    return sents


class _Model:
    """Accumulated KG: instances, induced types (classes), relations.

    `to_graph()` emits the SAME Cytoscape schema as cqbycq's _Model so the front
    end renders it unchanged. Instances are nodes of type 'instance'; induced
    types are nodes of type 'class'; an 'instanceOf' edge links each instance to
    its induced type.
    """

    def __init__(self) -> None:
        self.instances: list[str] = []          # extracted entities
        self.types: list[str] = []              # induced classes (Stage B)
        self.instance_type: dict[str, str] = {}
        self.triples: list[dict] = []           # {subject, relation, object}
        self.relations: list[str] = []          # induced relation types

    def add_instance(self, name: str) -> bool:
        if name and name not in self.instances:
            self.instances.append(name)
            return True
        return False

    def add_triple(self, t: dict) -> bool:
        if t not in self.triples:
            self.triples.append(t)
            if t["relation"] not in self.relations:
                self.relations.append(t["relation"])
            return True
        return False

    def induce_schema(self) -> dict:
        """Stage B: induce a type per instance, bottom-up from the data."""
        added_classes: list[str] = []
        for inst in self.instances:
            t = _induce_type(inst)
            self.instance_type[inst] = t
            if t not in self.types:
                self.types.append(t)
                added_classes.append(t)
        return {
            "classes": added_classes,
            "object_properties": list(self.relations),
            "data_properties": [],
        }

    def to_graph(self) -> dict:
        nodes = []
        # induced type nodes (classes)
        for t in self.types:
            nodes.append({"data": {"id": t, "label": t, "type": "class",
                                   "attributes": []}})
        # instance nodes
        for inst in self.instances:
            nodes.append({"data": {"id": inst, "label": inst, "type": "instance",
                                   "attributes": []}})
        edges = []
        # relation edges between instances
        for t in self.triples:
            edges.append({"data": {
                "id": f"{t['subject']}-{t['relation']}-{t['object']}",
                "source": t["subject"], "target": t["object"],
                "label": t["relation"]}})
        # instanceOf edges (only when schema has been induced)
        for inst in self.instances:
            typ = self.instance_type.get(inst)
            if typ:
                edges.append({"data": {
                    "id": f"{inst}-instanceOf-{typ}",
                    "source": inst, "target": typ, "label": "instanceOf"}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))

    # induced types -> owl:Class
    for t in model.types:
        g.add((EXN[t], RDF.type, OWL.Class))
    # induced relations -> owl:ObjectProperty
    for r in model.relations:
        g.add((EXN[r], RDF.type, OWL.ObjectProperty))
    # instances -> owl:NamedIndividual typed by induced class
    for inst in model.instances:
        g.add((EXN[inst], RDF.type, OWL.NamedIndividual))
        typ = model.instance_type.get(inst)
        if typ:
            g.add((EXN[inst], RDF.type, EXN[typ]))
    # relation triples between individuals
    for t in model.triples:
        g.add((EXN[t["subject"]], EXN[t["relation"]], EXN[t["object"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    sentences = _read_sentences(input_dir)

    model = _Model()
    steps = []

    # ---- Stage A: triple extraction (one step per sentence) ----------------
    for i, sent in enumerate(sentences, 1):
        raw = llm.complete(_PROMPT.format(sent=sent), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"triples": []}

        added_inst: list[str] = []
        added_rel: list[dict] = []
        for t in frag.get("triples", []):
            if not all(k in t for k in ("subject", "relation", "object")):
                continue
            for k in ("subject", "object"):
                if model.add_instance(t[k]):
                    added_inst.append(t[k])
            if model.add_triple(t):
                added_rel.append(t)

        steps.append({
            "step": i,
            "cq": sent,
            "stage": "extraction",
            "added": {"classes": [], "object_properties": added_rel,
                      "data_properties": [], "instances": added_inst},
            "graph": model.to_graph(),
        })

    # ---- Stage B: schema induction (one final step) ------------------------
    induced = model.induce_schema()
    steps.append({
        "step": len(sentences) + 1,
        "cq": "(schema induction)",
        "stage": "schema_induction",
        "added": {"classes": induced["classes"],
                  "object_properties": induced["object_properties"],
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
        "method": "autoschemakg",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "instances": len(model.instances),
            "induced_classes": len(model.types),
            "triples": len(model.triples),
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
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend), ensure_ascii=False))
