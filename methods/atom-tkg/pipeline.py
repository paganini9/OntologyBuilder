"""ATOM - AdapTive and OptiMized dynamic *temporal* knowledge graph construction.

Method (Lairgi et al., "ATOM: AdapTive and OptiMized dynamic temporal knowledge
graph construction using LLMs", arXiv:2510.22590):
static KG construction ignores that real-world facts are time-sensitive. ATOM
(1) splits each input document into minimal, self-contained **atomic facts**
(improving extraction exhaustivity and stability), (2) builds **atomic temporal
KGs** using a **dual-time** model that distinguishes *when information was
observed* from *when it is valid*, and (3) **merges** the atomic temporal KGs in
parallel into one continuously-updated Temporal Knowledge Graph (TKG).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    events.txt  - one dated note per line: "[YYYY-MM] free text".
                  The bracket date is the OBSERVED time (when the note was
                  recorded); "since YYYY" / "until|to YYYY" clauses give the
                  VALID interval. Blank / # comment lines are ignored.

Outputs (out_dir):
    ontology.ttl    - OWL: entities as owl:Class, relations as owl:ObjectProperty
                      (domain/range); each relation carries its validity interval
                      as an rdfs:comment (kept valid OWL).
    ontology.json   - final merged TKG as Cytoscape nodes/edges; every relation
                      edge carries observed / valid_from / valid_until + provenance.
    steps.json      - one snapshot per note (atomic TKG merged in), for replay.
    manifest.json   - summary (backend, counts, file list).

Dual-time, deterministic-on-MOCK:
    * observed   = the note's [YYYY-MM] bracket (when the fact was seen);
    * valid_from = "since YYYY" if present, else the observed date;
    * valid_until= "until YYYY" / "to YYYY" if present, else "" (open interval).
Merging is by (subject, relation, object): repeated facts keep the earliest
observed and widen the validity interval (min valid_from, max valid_until),
so re-observations reinforce rather than duplicate.

The LLM step is abstracted: with a real backend the model extracts the atomic
triples; with MOCK a deterministic heuristic does, so output is reproducible and
golden-testable. Dual-time tagging is rule-based in both paths.
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

EX = "http://example.org/temporal#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every", "If", "During", "Under",
    "Since", "Until", "From", "Becomes", "Become",
}

# relational verbs -> canonical object-property name
_REL = {
    "acquired": "acquired", "acquires": "acquired", "acquire": "acquired",
    "partners": "partnersWith", "partner": "partnersWith",
    "supplies": "supplies", "supply": "supplies", "supplied": "supplies",
    "uses": "uses", "use": "uses", "used": "uses",
    "owns": "owns", "own": "owns", "owned": "owns",
    "subsidiary": "subsidiaryOf",
    "merges": "mergesWith", "merge": "mergesWith", "merged": "mergesWith",
    "joins": "joins", "join": "joins", "joined": "joins",
    "leads": "leads", "lead": "leads", "led": "leads",
    "produces": "produces", "produce": "produces", "produced": "produces",
    "competes": "competesWith", "compete": "competesWith",
}


def _caps(text: str) -> list[str]:
    """Capitalised entity tokens (PascalCase already), stopwords removed."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def _year(text: str, *cues: str) -> str:
    """First 4-digit year following any of the cue words (e.g. 'since 2024')."""
    low = text.lower()
    for cue in cues:
        m = re.search(cue + r"\s+(\d{4})", low)
        if m:
            return m.group(1)
    return ""


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: a single atomic fact (subject, relation, object)."""
    fact = prompt.split("Atomic fact:")[-1].split("\n")[0].strip()
    low = fact.lower()
    caps = _caps(fact)
    words = re.findall(r"[a-zA-Z]+", low)
    class_words = {c.lower() for c in caps}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    if rel and len(caps) >= 2:
        return json.dumps(
            {"subject": caps[0], "relation": rel, "object": caps[1]},
            ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


_PROMPT = (
    "Extract ONE atomic (subject, relation, object) fact from the clause. Return "
    'ONLY JSON {{"subject":"...","relation":"...","object":"..."}} with PascalCase '
    "entities and a camelCase relation, or {{}} if none.\n"
    "Atomic fact: {fact}\n"
)


def _read_notes(input_dir: Path) -> list[str]:
    f = input_dir / "events.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    notes = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            notes.append(line)
    return notes


def _split_note(note: str) -> tuple[str, list[str]]:
    """Return (observed_date, [atomic clauses]). Atomic = sentence-level split."""
    observed = ""
    m = re.match(r"^\[([0-9]{4}(?:-[0-9]{2})?)\]\s*(.*)$", note)
    body = note
    if m:
        observed = m.group(1)
        body = m.group(2)
    clauses = [c.strip() for c in re.split(r"[.!?]+", body) if c.strip()]
    return observed, clauses


class _Model:
    """Merged temporal KG, insertion-ordered for deterministic output."""

    def __init__(self) -> None:
        self.entities: list[str] = []
        # key (subject,relation,object) -> fact dict (merged dual-time)
        self.facts: dict[tuple, dict] = {}
        self.order: list[tuple] = []

    def add_entity(self, e: str) -> bool:
        if e and e not in self.entities:
            self.entities.append(e)
            return True
        return False

    def add_fact(self, s: str, r: str, o: str, observed: str,
                 valid_from: str, valid_until: str, source: int) -> dict | None:
        key = (s, r, o)
        if key in self.facts:
            f = self.facts[key]
            # merge: earliest observed, widen validity interval
            if observed and (not f["observed"] or observed < f["observed"]):
                f["observed"] = observed
            if valid_from and (not f["valid_from"] or valid_from < f["valid_from"]):
                f["valid_from"] = valid_from
            if valid_until and valid_until > f.get("valid_until", ""):
                f["valid_until"] = valid_until
            f["observations"] += 1
            return None
        f = {"subject": s, "relation": r, "object": o, "observed": observed,
             "valid_from": valid_from, "valid_until": valid_until,
             "observations": 1, "source": source}
        self.facts[key] = f
        self.order.append(key)
        return f

    def _label(self, f: dict) -> str:
        vf, vu = f.get("valid_from", ""), f.get("valid_until", "")
        if vf and vu:
            span = f"{vf}..{vu}"
        elif vf:
            span = f"{vf}.."
        else:
            span = ""
        return f"{f['relation']} @[{span}]" if span else f["relation"]

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": e, "label": e, "type": "class", "attributes": []}}
            for e in self.entities
        ]
        edges = []
        for key in self.order:
            f = self.facts[key]
            edges.append({"data": {
                "id": f"{f['subject']}-{f['relation']}-{f['object']}",
                "source": f["subject"], "target": f["object"],
                "label": self._label(f),
                "observed": f["observed"], "valid_from": f["valid_from"],
                "valid_until": f["valid_until"], "provenance": f["source"],
            }})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for e in model.entities:
        g.add((EXN[e], RDF.type, OWL.Class))
    seen = set()
    for key in model.order:
        f = model.facts[key]
        pr = f["relation"]
        if pr not in seen:
            g.add((EXN[pr], RDF.type, OWL.ObjectProperty))
            seen.add(pr)
        g.add((EXN[pr], RDFS.domain, EXN[f["subject"]]))
        g.add((EXN[pr], RDFS.range, EXN[f["object"]]))
        vf, vu = f.get("valid_from", ""), f.get("valid_until", "")
        if vf or vu:
            span = f"valid {vf or '?'}..{vu or '?'} (observed {f['observed'] or '?'})"
            g.add((EXN[f"{f['subject']}_{pr}_{f['object']}"],
                   RDFS.comment, Literal(span)))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    notes = _read_notes(input_dir)

    mock = is_mock(llm)
    model = _Model()
    steps: list[dict] = []

    for i, note in enumerate(notes, 1):
        observed, clauses = _split_note(note)
        added_e: list[str] = []
        added_f: list[dict] = []
        atomic = 0
        for clause in clauses:
            valid_from = _year(clause, "since", "from") or observed
            valid_until = _year(clause, "until", "till", "to")
            if mock:
                raw = llm.complete(_PROMPT.format(fact=clause), temperature=0.0,
                                   json_schema={"type": "object"})
                try:
                    t = json.loads(raw)
                except json.JSONDecodeError:
                    t = {}
                triples = [t] if t.get("subject") else []
            else:
                triples = extract_triples(llm, clause)
            for t in triples:
                s, r, o = t.get("subject"), t.get("relation"), t.get("object")
                if not (s and r and o):
                    continue
                atomic += 1
                for ent in (s, o):
                    if model.add_entity(ent):
                        added_e.append(ent)
                f = model.add_fact(s, r, o, observed, valid_from, valid_until, i)
                if f is not None:
                    added_f.append(f)

        steps.append({
            "step": i,
            "stage": "atomic+merge",
            "cq": note,
            "observed": observed,
            "atomic_facts": atomic,
            "added": {"entities": added_e, "facts": added_f},
            "graph": model.to_graph(),
        })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    facts = [model.facts[k] for k in model.order]
    manifest = {
        "method": "atom-tkg",
        "backend": llm.name,
        "input_notes": len(notes),
        "counts": {
            "classes": len(model.entities),
            "object_properties": len({model.facts[k]["relation"] for k in model.order}),
            "data_properties": 0,
            "temporal_facts": len(facts),
            "dual_timed": sum(1 for f in facts if f["valid_from"] and f["valid_until"]),
            "bounded_intervals": sum(1 for f in facts if f["valid_until"]),
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
