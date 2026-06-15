"""Zero-shot triple extraction from engineering standards.

Method (Yue, IEEE ICSC 2026 / SDI workshop, arXiv 2509.00140,
"LLM-based Zero-shot Triple Extraction for Automated Ontology Generation from
Software Engineering Standards"): instead of starting from competency questions,
this pipeline reads a STANDARD document directly and walks a five-stage,
zero-shot (no fine-tuning, no labelled data) pipeline:

    1. document segmentation     - split the standard into sections
    2. candidate term mining     - capitalized domain terms per section
    3. relation inference (LLM)   - (subject, relation, object) triples
    4. term normalization        - singular/case normalize, merge variants
    5. cross-section alignment    - unify identical terms across sections
                                    into a single ontology node

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    standard_text.txt  - an engineering-standard excerpt. Sections are delimited
                         by heading lines: "## <Section>" or numbered headings
                         like "1. Scope" / "2.1 Product Structure".

Outputs (out_dir):
    ontology.ttl    - the OWL ontology (Turtle): terms as owl:Class, relations
                      as owl:ObjectProperty with the inferred triples.
    ontology.json   - final graph as Cytoscape nodes/edges (== cqbycq schema).
    steps.json      - one snapshot per section (segmentation + mining +
                      relation inference), then a final "(normalize+align)"
                      snapshot for stages 4-5.
    manifest.json   - summary (backend, counts, file list).

The LLM step (stage 3) is abstracted via backend.llm. With a real backend the
model infers the triples; with MOCK a deterministic rule extracts them, so the
output is reproducible and testable.
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

EX = "http://example.org/standard#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "All", "Shall", "Should",
    "Must", "May", "Section", "Scope", "Note", "Clause",
}

# relational verbs -> canonical object-property name (shared vocabulary w/ cqbycq)
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
    "reference": "references", "references": "references",
    "specify": "specifies", "specifies": "specifies",
    "define": "defines", "defines": "defines",
    "describe": "describes", "describes": "describes",
}

_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s+|(?:\d+(?:\.\d+)*)[.)]?\s+)(?P<title>.+?)\s*$"
)


def _singular(w: str) -> str:
    """Crude singularization used by term normalization (stage 4)."""
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _normalize_term(t: str) -> str:
    """Stage-4 normalization: title-case + singularize so 'Materials',
    'material' and 'Material' collapse to one canonical term."""
    return _singular(t[:1].upper() + t[1:].lower())


# --------------------------------------------------------------------------
# Stage 1: document segmentation
# --------------------------------------------------------------------------

def _segment(text: str) -> list[dict]:
    """Split the standard into sections. A section = a heading line plus the
    body lines until the next heading. Text before any heading goes into a
    synthetic 'Preamble' section (only if non-empty)."""
    sections: list[dict] = []
    current = {"title": "Preamble", "lines": []}
    for raw in text.splitlines():
        m = _HEADING_RE.match(raw)
        if m and m.group("title"):
            if current["lines"]:
                sections.append(current)
            current = {"title": m.group("title").strip(), "lines": []}
        else:
            if raw.strip():
                current["lines"].append(raw.strip())
    if current["lines"]:
        sections.append(current)
    return sections


# --------------------------------------------------------------------------
# Stage 2: candidate term mining
# --------------------------------------------------------------------------

def _mine_terms(section_text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", section_text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


# --------------------------------------------------------------------------
# Stage 3: relation inference (LLM-backed; MOCK = deterministic rule)
# --------------------------------------------------------------------------

_PROMPT = (
    "You are an ontology engineer reading one section of an engineering "
    "standard. Perform ZERO-SHOT triple extraction: return ONLY JSON with keys "
    "terms (list of domain terms) and triples (list of {{subject, relation, "
    "object}}). Use relation names like consistsOf, requires, contains, "
    "produces, references.\n"
    "Section title: {title}\n"
    "Section text: {text}\n"
)


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM: parse one section -> terms + triples.

    Strategy: candidate terms are capitalized tokens; for each sentence, if it
    contains a relational verb and at least two candidate terms, emit a triple
    (first term, relation, second term)."""
    text = prompt.split("Section text:")[-1].strip()
    terms = _mine_terms(text)
    triples: list[dict] = []
    term_lower = {t.lower() for t in terms}

    for sent in re.split(r"[.;\n]", text):
        s_terms = _mine_terms(sent)
        if len(s_terms) < 2:
            continue
        words = re.findall(r"[a-zA-Z]+", sent.lower())
        s_term_lower = {t.lower() for t in s_terms}
        rel = next(
            (_REL[w] for w in words
             if w in _REL and w not in s_term_lower
             and w + "s" not in s_term_lower),
            None,
        )
        if rel:
            triples.append(
                {"subject": s_terms[0], "relation": rel, "object": s_terms[1]}
            )
    # de-dup terms referenced by triples but possibly filtered already are kept.
    _ = term_lower
    return json.dumps({"terms": terms, "triples": triples}, ensure_ascii=False)


def _read_standard(input_dir: Path) -> str:
    f = input_dir / "standard_text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return f.read_text(encoding="utf-8")


class _Model:
    """Accumulated ontology, in insertion order for deterministic output.

    Same public surface + identical to_graph() schema as cqbycq._Model so the
    front-end renders it unchanged."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []
        self.data_props: list[dict] = []  # unused here; kept for schema parity

    def add_class(self, c: str) -> bool:
        if c and c not in self.classes:
            self.classes.append(c)
            return True
        return False

    def add_obj(self, p: dict) -> bool:
        if p not in self.obj_props:
            self.obj_props.append(p)
            return True
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


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_standard(input_dir)

    # Stage 1: segmentation.
    sections = _segment(text)

    model = _Model()
    steps: list[dict] = []

    # raw_terms records the un-normalized term seen per section, so cross-section
    # alignment (stage 5) can be reported.
    raw_term_occurrences: dict[str, list[str]] = {}  # normalized -> [sections]

    # Stages 2-3 per section, building a RAW model first (terms mined verbatim).
    for i, sec in enumerate(sections, 1):
        section_text = "\n".join(sec["lines"])

        # Stage 2: candidate term mining (reported in the step).
        mined = _mine_terms(section_text)

        # Stage 3: relation inference via the (mock) LLM.
        raw = llm.complete(
            _PROMPT.format(title=sec["title"], text=section_text),
            temperature=0.0, json_schema={"type": "object"},
        )
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"terms": [], "triples": []}

        added_c: list[str] = []
        added_o: list[dict] = []

        # Stage 4 is applied here as terms enter the model (normalize on add)
        # and stage 5 (alignment) happens implicitly because the model dedups by
        # normalized class name across sections.
        def _enter(term: str) -> str:
            norm = _normalize_term(term)
            if model.add_class(norm):
                added_c.append(norm)
            raw_term_occurrences.setdefault(norm, [])
            if sec["title"] not in raw_term_occurrences[norm]:
                raw_term_occurrences[norm].append(sec["title"])
            return norm

        for t in frag.get("terms", []) or mined:
            _enter(t)
        for tr in frag.get("triples", []):
            subj = _enter(tr["subject"])
            obj = _enter(tr["object"])
            p = {"name": tr["relation"], "domain": subj, "range": obj}
            if model.add_obj(p):
                added_o.append(p)

        steps.append({
            "step": i,
            "cq": f"section: {sec['title']}",
            "mined_terms": mined,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": []},
            "graph": model.to_graph(),
        })

    # Stages 4-5 explicit snapshot: report which terms were aligned across >1
    # section (already merged into single nodes during accumulation).
    aligned = {k: v for k, v in raw_term_occurrences.items() if len(v) > 1}
    steps.append({
        "step": len(sections) + 1,
        "cq": "(normalize+align)",
        "aligned_terms": aligned,
        "added": {"classes": [], "object_properties": [], "data_properties": []},
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
        "method": "se-standards-zeroshot",
        "backend": llm.name,
        "input_sections": len(sections),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "aligned_terms": len(aligned),
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
