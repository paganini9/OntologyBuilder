"""OLLM - End-to-End Ontology Learning with LLMs (taxonomic backbone).

Method (Lo, Jiang, Li, Jamnik, "End-to-End Ontology Learning with Large Language
Models", arXiv:2410.23584, code https://github.com/andylolu2/ollm): rather than
extracting flat (subject, relation, object) triples, OLLM learns the *taxonomic
backbone* of an ontology end-to-end from text -- i.e. the rdfs:subClassOf / is-a
hierarchy of concepts. The original paper fine-tunes an LLM to generate the
hierarchy directly; here the LLM is used only to surface the concept set, and the
subClassOf backbone is induced deterministically so the MOCK path is fully
reproducible and golden-testable.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free body text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL ontology, concepts as owl:Class + rdfs:subClassOf
    ontology.json   - final TAXONOMY graph as Cytoscape nodes/edges
    steps.json      - one snapshot per sentence (concepts) + one taxonomy step
    manifest.json   - summary (backend, counts, file list)

Pipeline (two stages, both deterministic on the MOCK path):
    1. Concept extraction (per sentence) -> the concept set (classes).
    2. Taxonomy induction (deterministic) -> rdfs:subClassOf backbone:
       (a) compound-tail rule: "ElectricMotor" subClassOf "Motor" when "Motor"
           is a known concept; (b) every remaining top-level concept is attached
           to a synthetic root "Entity".

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
extracts triples and we keep only their concepts; with MOCK a deterministic
heuristic does, so the output is reproducible and testable.
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
from backend.llm.extract import is_mock, extract_triples  # noqa: E402

EX = "http://example.org/product#"
ROOT = "Entity"  # synthetic top-level class

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_concepts(text: str) -> list[str]:
    """Deterministic concept extraction: capitalized nouns (minus stop-words)."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM: per-sentence concept extraction."""
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    return json.dumps({"concepts": _extract_concepts(sentence)},
                      ensure_ascii=False)


_PROMPT = (
    "You are an ontology engineer building the taxonomic backbone of an "
    "ontology. From the sentence, extract the core concepts as PascalCase class "
    "names. Return ONLY JSON with key concepts (list).\n"
    "Sentence: {sentence}\n"
)


def _induce_taxonomy(concepts: list[str]) -> list[dict]:
    """Induce the rdfs:subClassOf backbone over the concept set (deterministic).

    (a) Compound-tail rule: a concept whose name ends with another known concept
        becomes its child (e.g. "ElectricMotor" subClassOf "Motor"). Each child
        is attached to its LONGEST matching tail parent (most specific).
    (b) Remaining concepts that gained no parent are attached to the synthetic
        root "Entity", giving a single connected taxonomy tree.

    Shared by both the MOCK and real backends so the hierarchy is identical
    regardless of how concepts were surfaced.
    """
    cset = list(concepts)
    subs: list[dict] = []
    has_parent: set[str] = set()

    for c in cset:
        best_parent = None
        for parent in cset:
            if parent == c:
                continue
            if len(c) > len(parent) and c.endswith(parent):
                if best_parent is None or len(parent) > len(best_parent):
                    best_parent = parent
        if best_parent is not None:
            subs.append({"child": c, "parent": best_parent})
            has_parent.add(c)

    # Attach every concept that did not get a compound-tail parent to the root.
    for c in cset:
        if c not in has_parent:
            subs.append({"child": c, "parent": ROOT})
    return subs


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return f.read_text(encoding="utf-8")


class _Model:
    """Accumulated taxonomy, in insertion order for deterministic output."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.subclass: list[dict] = []  # {child, parent}

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def add_subclass(self, s: dict) -> bool:
        if s not in self.subclass:
            self.subclass.append(s)
            return True
        return False

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": c, "label": c, "type": "class", "attributes": []}}
            for c in self.classes
        ]
        edges = [
            {"data": {"id": f"{s['child']}-subClassOf-{s['parent']}",
                      "source": s["child"], "target": s["parent"],
                      "label": "subClassOf"}}
            for s in self.subclass
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
    for s in model.subclass:
        g.add((EXN[s["child"]], RDFS.subClassOf, EXN[s["parent"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_text(input_dir)
    sentences = _split_sentences(text)

    mock = is_mock(llm)
    model = _Model()
    steps: list[dict] = []
    step_no = 0

    # ---- Stage 1: per-sentence concept extraction ---------------------------
    for sent in sentences:
        step_no += 1
        if mock:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"concepts": []}
            sent_concepts = list(frag.get("concepts", []))
        else:
            # Real backend: extract triples, keep only the concept set (we do
            # NOT use the relation kinds -- OLLM builds the taxonomy backbone).
            sent_concepts = []
            for t in extract_triples(llm, sent):
                for ent in (t["subject"], t["object"]):
                    if ent not in sent_concepts:
                        sent_concepts.append(ent)

        added_c = []
        for c in sent_concepts:
            if model.add_class(c):
                added_c.append(c)
        steps.append({
            "step": step_no,
            "stage": "concepts",
            "cq": f"(concepts) {sent}",
            "added": {"classes": added_c, "subclass_of": []},
            "graph": model.to_graph(),
        })

    # ---- Stage 2: taxonomy induction (deterministic, both paths) ------------
    step_no += 1
    added_s = []
    for s in _induce_taxonomy(list(model.classes)):
        model.add_class(s.get("parent", ""))  # ensure root "Entity" exists
        model.add_class(s.get("child", ""))
        if model.add_subclass(s):
            added_s.append(s)
    steps.append({
        "step": step_no,
        "stage": "taxonomy",
        "cq": "(taxonomy) induce hierarchy",
        "added": {"classes": [ROOT] if ROOT in model.classes else [],
                  "subclass_of": added_s},
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
        "method": "ollm",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "classes": len(model.classes),
            "subclass_of": len(model.subclass),
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
