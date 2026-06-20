"""TRACE-KG - text-driven schema, context-enriched KG with qualifiers + traceability.

Method (Beyond Predefined Schemas: "TRACE-KG" — Text-dRiven schemA for
Context-Enriched Knowledge Graphs from Complex Documents, arXiv:2604.03496, ASU):
instead of assuming a predefined ontology (ontology-driven) or extracting flat
schema-free triples, TRACE-KG *jointly* builds (a) a context-enriched KG whose
relations carry conditional qualifiers and (b) an induced, data-driven schema
(the is-a scaffold surfaced from the text itself), while preserving full
traceability of every node/edge back to the source sentence.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free body text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL: classes, owl:ObjectProperty relations, rdfs:subClassOf
    ontology.json   - final graph as Cytoscape nodes/edges (edges carry qualifier
                      + source traceability in edge data)
    steps.json      - one snapshot per sentence, so the UI shows it being built
    manifest.json   - summary (backend, counts, file list)

Two faithful, deterministic-on-MOCK ingredients per sentence:
    * is-a cue ("X is a Y", "X are Y", "X is a kind/type of Y") -> induced schema
      edge subClassOf(X, Y)  (the text-driven scaffold);
    * otherwise a relation triple (subject, relation, object) with an optional
      conditional QUALIFIER captured from a "when/if/during/under/for ..." clause.
Every emitted edge records `source` = the sentence index (traceability).

The LLM step is abstracted: with a real backend the model extracts triples
(qualifier defaults empty), with MOCK a deterministic heuristic does, so the
output is reproducible and golden-testable.
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

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every", "If", "During", "Under",
    "When",
}

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
    "drive": "drives", "drives": "drives", "driven": "drives",
    "power": "powers", "powers": "powers", "powered": "powers",
    "connect": "connectsTo", "connects": "connectsTo",
}

_ISA_CUES = (" is a kind of ", " is a type of ", " is an ", " is a ", " are ")
_QUAL_CUES = ("when", "if", "during", "under", "while")


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _caps(text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def _qualifier(sentence: str) -> str:
    """Capture a conditional qualifier (PascalCase) from a when/if/... clause."""
    low = sentence.lower()
    for cue in _QUAL_CUES:
        idx = low.find(cue + " ")
        if idx >= 0:
            tail = sentence[idx + len(cue):]
            caps = _caps(tail)
            if caps:
                return caps[0]
    return ""


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: classify a sentence as is-a or qualified relation."""
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    low = sentence.lower()

    # is-a cue -> induced schema (subClassOf)
    for cue in _ISA_CUES:
        if cue in low:
            left = sentence[: low.find(cue)]
            right = sentence[low.find(cue) + len(cue):]
            lc, rc = _caps(left), _caps(right)
            if lc and rc:
                return json.dumps({"kind": "isa", "child": lc[0], "parent": rc[0]},
                                  ensure_ascii=False)

    # otherwise a relation triple with optional qualifier
    caps = _caps(sentence)
    words = re.findall(r"[a-zA-Z]+", low)
    class_words = {c.lower() for c in caps} | {c.lower() + "s" for c in caps}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    if rel and len(caps) >= 2:
        return json.dumps(
            {"kind": "rel", "subject": caps[0], "relation": rel,
             "object": caps[1], "qualifier": _qualifier(sentence)},
            ensure_ascii=False)
    return json.dumps({"kind": "none"}, ensure_ascii=False)


_PROMPT = (
    "You build a context-enriched knowledge graph with a text-driven schema. "
    "For the sentence, return ONLY JSON. If it states an is-a fact use "
    '{{"kind":"isa","child":"...","parent":"..."}}; otherwise use '
    '{{"kind":"rel","subject":"...","relation":"...","object":"...",'
    '"qualifier":"..."}} (qualifier = a condition, else empty). PascalCase names.\n'
    "Sentence: {sentence}\n"
)


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[.!?]+", text) if p.strip()]


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    # Drop comment lines (#...) so they do not become empty extraction steps.
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("#")]
    return "\n".join(lines)


class _Model:
    """Accumulated graph, insertion-ordered for deterministic output."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.rels: list[dict] = []      # {subject, relation, object, qualifier, source}
        self.subclass: list[dict] = []  # {child, parent, source}

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def add_rel(self, r: dict) -> bool:
        if r not in self.rels:
            self.rels.append(r)
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
        edges = []
        for r in self.rels:
            label = r["relation"]
            if r.get("qualifier"):
                label = f"{r['relation']} [{r['qualifier']}]"
            edges.append({"data": {
                "id": f"{r['subject']}-{r['relation']}-{r['object']}",
                "source": r["subject"], "target": r["object"], "label": label,
                "qualifier": r.get("qualifier", ""), "provenance": r.get("source"),
            }})
        for s in self.subclass:
            edges.append({"data": {
                "id": f"{s['child']}-subClassOf-{s['parent']}",
                "source": s["child"], "target": s["parent"], "label": "subClassOf",
                "qualifier": "", "provenance": s.get("source"),
            }})
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
    seen = set()
    for r in model.rels:
        pr = r["relation"]
        if pr not in seen:
            g.add((EXN[pr], RDF.type, OWL.ObjectProperty))
            seen.add(pr)
        g.add((EXN[pr], RDFS.domain, EXN[r["subject"]]))
        g.add((EXN[pr], RDFS.range, EXN[r["object"]]))
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

    for i, sent in enumerate(sentences, 1):
        added_c, added_r, added_s = [], [], []
        if mock:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {"kind": "none"}
            kind = frag.get("kind")
            if kind == "isa":
                child, parent = frag.get("child", ""), frag.get("parent", "")
                for c in (child, parent):
                    if model.add_class(c):
                        added_c.append(c)
                s = {"child": child, "parent": parent, "source": i}
                if child and parent and model.add_subclass(s):
                    added_s.append(s)
            elif kind == "rel":
                subj, obj = frag.get("subject", ""), frag.get("object", "")
                for c in (subj, obj):
                    if model.add_class(c):
                        added_c.append(c)
                r = {"subject": subj, "relation": frag.get("relation", ""),
                     "object": obj, "qualifier": frag.get("qualifier", ""),
                     "source": i}
                if subj and obj and model.add_rel(r):
                    added_r.append(r)
        else:
            # Real backend: triples -> relations (no qualifier inference).
            for t in extract_triples(llm, sent):
                for c in (t["subject"], t["object"]):
                    if model.add_class(c):
                        added_c.append(c)
                r = {"subject": t["subject"], "relation": t["relation"],
                     "object": t["object"], "qualifier": "", "source": i}
                if model.add_rel(r):
                    added_r.append(r)

        steps.append({
            "step": i,
            "stage": "extract",
            "cq": sent,
            "added": {"classes": added_c, "relations": added_r,
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
        "method": "trace-kg",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "classes": len(model.classes),
            "relations": len(model.rels),
            "subclass_of": len(model.subclass),
            "qualified_relations": sum(1 for r in model.rels if r.get("qualifier")),
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
