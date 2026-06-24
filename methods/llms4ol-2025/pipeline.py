"""LLMs4OL 2025 - heterogeneous, modular ontology learning (term -> type -> taxonomy).

Method (Beliaeva & Rahmatullaev, "Alexbek at LLMs4OL 2025 Tasks A, B, and C:
Heterogeneous LLM Methods for Ontology Learning", arXiv:2508.19428):
a single modular pipeline that spans the full ontology-learning process of the
LLMs4OL challenge:
  * Task A (Text2Onto): jointly extract domain *terms* and their ontological
    *types* from documents;
  * Task B (Term Typing): assign a type to an *unseen* term via retrieval-
    augmented matching against already-typed examples (a key-free, deterministic
    stand-in for the paper's embedding/cosine + ensemble retrieval);
  * Task C (Taxonomy Discovery): induce is-a (subClassOf) relations between the
    types, building the hierarchy scaffold.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    documents.txt - one line per document/clue (blank / # comment lines ignored):
        "<a/an term> is a/an <Type>"      -> Task A typed example (term -> Type)
        "<Type> is a kind of <Parent>"    -> Task C taxonomy edge (subClassOf)
        "? <term>"                        -> Task B query: unseen term to type

Outputs (out_dir):
    ontology.ttl   - OWL: types as owl:Class, hierarchy as rdfs:subClassOf, terms
                     as owl:NamedIndividual rdf:type'd to their Type.
    ontology.json  - graph; type nodes (class) + term nodes (term); edges are
                     instanceOf (term -> Type) and subClassOf (Type -> Parent).
    steps.json     - one snapshot per processed clue, in A -> C -> B order.
    manifest.json  - summary (backend, counts, file list).

The LLM step is abstracted: with a real backend the model extracts the (term,
type) pair; with MOCK a deterministic heuristic does, so output is reproducible
and golden-testable. Taxonomy (C) is cue-driven and term typing (B) is retrieval-
driven, identical in both paths, so the graph shape stays stable.
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

EX = "http://example.org/ol#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "Kind", "Type", "Subclass",
    "Subtype",
}
_ARTICLES = {"a", "an", "the"}

_TAXO_CUES = (" is a kind of ", " is a type of ", " is a subclass of ",
              " is a subtype of ")
_TYPING_CUES = (" is an ", " is a ", " are ")


def _caps(text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def _strip_article(s: str) -> str:
    toks = s.split()
    if toks and toks[0].lower() in _ARTICLES:
        toks = toks[1:]
    return " ".join(t.lower() for t in toks).strip()


def _tokset(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _trigrams(s: str) -> set:
    s = re.sub(r"\s+", "", s.lower())
    return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else {s}


def _route(line: str) -> Optional[str]:
    if line.startswith("?"):
        return "B"
    low = " " + line.lower() + " "
    if any(cue in low for cue in _TAXO_CUES):
        return "C"
    if any(cue in low for cue in _TYPING_CUES):
        return "A"
    return None


def _parse_typing(line: str) -> Optional[tuple]:
    low = line.lower()
    for cue in _TYPING_CUES:
        idx = low.find(cue)
        if idx >= 0:
            term = _strip_article(line[:idx])
            types = _caps(line[idx + len(cue):])
            if term and types:
                return term, types[0]
    return None


def _parse_taxonomy(line: str) -> Optional[tuple]:
    low = line.lower()
    for cue in _TAXO_CUES:
        idx = low.find(cue)
        if idx >= 0:
            lc = _caps(line[:idx])
            rc = _caps(line[idx + len(cue):])
            if lc and rc:
                return lc[0], rc[0]
    return None


def _retrieve(term: str, examples: list[dict]) -> tuple:
    """Nearest typed example: max shared tokens, then char-trigram overlap.

    Deterministic key-free stand-in for the paper's embedding-cosine + ensemble
    retrieval. Ties resolve to the earliest example (insertion order)."""
    qt = _tokset(term)
    best, best_score = None, 0
    for ex in examples:
        sc = len(qt & _tokset(ex["term"]))
        if sc > best_score:
            best, best_score = ex, sc
    if best is not None:
        return best, "token"
    qg = _trigrams(term)
    best, best_score = None, 0
    for ex in examples:
        sc = len(qg & _trigrams(ex["term"]))
        if sc > best_score:
            best, best_score = ex, sc
    if best is not None:
        return best, "trigram"
    return None, ""


def _decamel(s: str) -> str:
    return " ".join(re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", s)).lower()


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: extract one (term, type) pair from a document."""
    doc = prompt.split("Document:")[-1].strip()
    parsed = _parse_typing(doc)
    if parsed:
        term, typ = parsed
        return json.dumps({"term": term, "type": typ}, ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


_PROMPT_A = (
    "You perform Task A (Text2Onto) of ontology learning: from the document, "
    "extract ONE domain term and its ontological Type. Return ONLY JSON "
    '{{"term":"...","type":"..."}} with a lowercase term and a PascalCase Type.\n'
    "Document: {doc}\n"
)


def _real_typing(llm, doc: str) -> tuple:
    """Non-mock path: use the shared triple extractor; subject->term, object->Type."""
    triples = extract_triples(llm, doc)
    if triples:
        t = triples[0]
        return _decamel(t["subject"]), t["object"]
    parsed = _parse_typing(doc)
    return parsed if parsed else ("", "")


def _uri(term: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", term).strip("_")


def _read_docs(input_dir: Path) -> list[str]:
    f = input_dir / "documents.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


class _Model:
    """Accumulated ontology, insertion-ordered for deterministic output."""

    def __init__(self) -> None:
        self.types: list[str] = []
        self.terms: list[dict] = []       # {term, type, inferred, neighbor}
        self.subclass: list[dict] = []    # {child, parent}
        self._termset = set()

    def add_type(self, t: str) -> bool:
        if t and t not in self.types:
            self.types.append(t)
            return True
        return False

    def add_term(self, term: str, typ: str, inferred: bool = False,
                 neighbor: str = "") -> bool:
        if not term or term in self._termset:
            return False
        self._termset.add(term)
        self.terms.append({"term": term, "type": typ, "inferred": inferred,
                           "neighbor": neighbor})
        return True

    def add_subclass(self, child: str, parent: str) -> bool:
        s = {"child": child, "parent": parent}
        if child and parent and s not in self.subclass:
            self.subclass.append(s)
            return True
        return False

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": t, "label": t, "type": "class", "attributes": []}}
            for t in self.types
        ]
        nodes += [
            {"data": {"id": tm["term"], "label": tm["term"], "type": "term",
                      "attributes": []}}
            for tm in self.terms
        ]
        edges = []
        for s in self.subclass:
            edges.append({"data": {
                "id": f"{s['child']}-subClassOf-{s['parent']}",
                "source": s["child"], "target": s["parent"], "label": "subClassOf"}})
        for tm in self.terms:
            label = "instanceOf*" if tm["inferred"] else "instanceOf"
            edges.append({"data": {
                "id": f"{tm['term']}-instanceOf-{tm['type']}",
                "source": tm["term"], "target": tm["type"], "label": label,
                "inferred": tm["inferred"], "via": tm["neighbor"]}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for t in model.types:
        g.add((EXN[t], RDF.type, OWL.Class))
    for s in model.subclass:
        g.add((EXN[s["child"]], RDFS.subClassOf, EXN[s["parent"]]))
    for tm in model.terms:
        iri = EXN[_uri(tm["term"])]
        g.add((iri, RDF.type, OWL.NamedIndividual))
        g.add((iri, RDF.type, EXN[tm["type"]]))
        if tm["inferred"]:
            g.add((iri, RDFS.comment,
                   Literal(f"typed by retrieval from '{tm['neighbor']}'")))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    lines = _read_docs(input_dir)
    mock = is_mock(llm)

    a_docs, c_docs, b_terms = [], [], []
    for ln in lines:
        r = _route(ln)
        if r == "A":
            a_docs.append(ln)
        elif r == "C":
            c_docs.append(ln)
        elif r == "B":
            b_terms.append(ln[1:].strip())

    model = _Model()
    examples: list[dict] = []
    steps: list[dict] = []
    step = 0

    # Task A - Text2Onto: term + type extraction
    for doc in a_docs:
        step += 1
        if mock:
            raw = llm.complete(_PROMPT_A.format(doc=doc), temperature=0.0,
                               json_schema={"type": "object"})
            try:
                frag = json.loads(raw)
            except json.JSONDecodeError:
                frag = {}
            term, typ = frag.get("term", ""), frag.get("type", "")
        else:
            term, typ = _real_typing(llm, doc)
        added_t, added_term = [], []
        if term and typ:
            if model.add_type(typ):
                added_t.append(typ)
            if model.add_term(term, typ):
                added_term.append(term)
                examples.append({"term": term, "type": typ})
        steps.append({
            "step": step, "stage": "extract(A)", "cq": doc,
            "added": {"types": added_t, "terms": added_term, "subclass_of": []},
            "graph": model.to_graph(),
        })

    # Task C - Taxonomy Discovery: is-a between types
    for doc in c_docs:
        step += 1
        added_t, added_s = [], []
        parsed = _parse_taxonomy(doc)
        if parsed:
            child, parent = parsed
            for t in (child, parent):
                if model.add_type(t):
                    added_t.append(t)
            if model.add_subclass(child, parent):
                added_s.append({"child": child, "parent": parent})
        steps.append({
            "step": step, "stage": "taxonomy(C)", "cq": doc,
            "added": {"types": added_t, "terms": [], "subclass_of": added_s},
            "graph": model.to_graph(),
        })

    # Task B - Term Typing: type an unseen term via retrieval
    for term in b_terms:
        step += 1
        added_t, added_term = [], []
        typed = None
        ex, how = _retrieve(term, examples)
        if ex:
            typ = ex["type"]
            if model.add_type(typ):
                added_t.append(typ)
            if model.add_term(term, typ, inferred=True, neighbor=ex["term"]):
                added_term.append(term)
            typed = {"term": term, "type": typ, "via": ex["term"], "match": how}
        steps.append({
            "step": step, "stage": "typing(B)", "cq": f"? {term}",
            "added": {"types": added_t, "terms": added_term, "subclass_of": []},
            "typed_by_retrieval": typed,
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
        "method": "llms4ol-2025",
        "backend": llm.name,
        "input_documents": len(lines),
        "counts": {
            "classes": len(model.types),
            "object_properties": 0,
            "data_properties": 0,
            "types": len(model.types),
            "terms": len(model.terms),
            "typed_examples": len(examples),
            "taxonomy_edges": len(model.subclass),
            "inferred_typings": sum(1 for t in model.terms if t["inferred"]),
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
