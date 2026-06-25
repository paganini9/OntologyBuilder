"""MedKGent - two-agent, confidence-aware, temporally evolving medical KG.

Method (Zhang et al., "MedKGent: A Large Language Model Agent Framework for
Constructing Temporally Evolving Medical Knowledge Graph", arXiv:2508.12393,
MBZUAI et al.): instead of naively unioning LLM extractions over a static corpus,
MedKGent builds a medical KG *day by day* with two cooperating agents:

    Extractor Agent  - reads each (dated) abstract, extracts (subject, relation,
                       object) triples, and assigns each a CONFIDENCE score via
                       sampling-based estimation; low-confidence triples are
                       filtered out.
    Constructor Agent- integrates the retained triples into a temporally evolving
                       graph in timestamp order. A re-observed fact is REINFORCED
                       (confidence combined, support incremented, last_seen
                       updated); contradictory facts are resolved by keeping the
                       higher-confidence one (the loser is marked superseded).

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    abstracts.txt  - one dated abstract per line: "[YYYY-MM-DD] free text".
                     The bracket date is when the finding was published (used to
                     order day-by-day construction). Blank / # comment lines are
                     ignored.

Outputs (out_dir):
    ontology.ttl    - OWL: entities as owl:Class, active relations as
                      owl:ObjectProperty (domain/range); each relation's
                      confidence/support/timespan as an rdfs:comment.
    ontology.json   - final KG as Cytoscape nodes/edges; each relation edge
                      carries confidence, support, first_seen, last_seen,
                      provenance, superseded.
    steps.json      - one snapshot per abstract (day), for temporal replay.
    manifest.json   - summary (backend, counts, file list).

Confidence + temporal logic is deterministic on MOCK so the output is
reproducible and golden-testable. With a real backend the Extractor's triples
come from the model; confidence aggregation and conflict resolution stay
rule-based, so the graph shape is stable.
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

EX = "http://example.org/med#"
EXTRACT_THRESHOLD = 0.30          # Extractor drops triples below this confidence

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "We", "Our",
    "These", "Those", "Their", "Both", "All", "Every", "If", "During", "Under",
    "Early", "Evidence", "Preliminary", "Large", "Recent", "New", "Trial",
    "Findings", "Reports", "Data", "Study", "Patients", "Adults",
}

# single-word relation triggers -> canonical relation
_REL = {
    "treats": "treats", "treat": "treats", "treated": "treats",
    "treatment": "treats", "treating": "treats",
    "causes": "causes", "cause": "causes", "caused": "causes",
    "inhibits": "inhibits", "inhibit": "inhibits", "inhibited": "inhibits",
    "induces": "induces", "induce": "induces", "induced": "induces",
    "prevents": "prevents", "prevent": "prevents", "prevented": "prevents",
    "worsens": "worsens", "worsen": "worsens", "worsened": "worsens",
    "exacerbates": "worsens",
    "regulates": "regulates", "regulate": "regulates", "regulated": "regulates",
    "expresses": "expresses", "express": "expresses", "expressed": "expresses",
    "associated": "associatedWith",
    "interacts": "interactsWith", "interact": "interactsWith",
    "reduces": "reduces", "reduce": "reduces", "reduced": "reduces",
    "lowers": "reduces", "lower": "reduces",
    "increases": "increases", "increase": "increases", "increased": "increases",
    "raises": "increases", "raise": "increases",
}

# polar-opposite relations on the same (subject, object) -> conflict
_OPPOSITE = {
    "treats": "worsens", "worsens": "treats",
    "prevents": "causes", "causes": "prevents",
    "reduces": "increases", "increases": "reduces",
}

_STRONG = {"significantly", "confirmed", "demonstrated", "established",
           "strongly", "randomized", "robust", "consistently"}
_HEDGE = {"may", "might", "suggest", "suggests", "possible", "possibly",
          "potential", "potentially", "could", "preliminary", "unclear",
          "reportedly"}


def _caps(text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def _confidence(clause: str) -> float:
    """Deterministic stand-in for sampling-based confidence estimation."""
    low = clause.lower()
    words = set(re.findall(r"[a-z]+", low))
    conf = 0.6
    conf += 0.2 * len(words & _STRONG)
    conf -= 0.15 * len(words & _HEDGE)
    return round(max(0.0, min(1.0, conf)), 2)


def mock_responder(prompt: str) -> str:
    """Deterministic Extractor stand-in: one (subject, relation, object) + conf."""
    clause = prompt.split("Clause:")[-1].split("\n")[0].strip()
    caps = _caps(clause)
    words = re.findall(r"[a-z]+", clause.lower())
    class_words = {c.lower() for c in caps}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    if rel and len(caps) >= 2:
        return json.dumps({"subject": caps[0], "relation": rel,
                           "object": caps[1], "confidence": _confidence(clause)},
                          ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


_PROMPT = (
    "You are the Extractor agent. From the clinical clause, return ONLY JSON "
    '{{"subject":"...","relation":"...","object":"...","confidence":0..1}} with '
    "PascalCase entities, a camelCase relation, and a sampling-based confidence, "
    "or {{}} if no factual triple.\n"
    "Clause: {clause}\n"
)


def _read_abstracts(input_dir: Path) -> list[str]:
    f = input_dir / "abstracts.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _split(abstract: str) -> tuple[str, list[str]]:
    """Return (date, [clauses]). Date is the leading [YYYY-MM-DD] bracket."""
    date = ""
    m = re.match(r"^\[([0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?)\]\s*(.*)$", abstract)
    body = abstract
    if m:
        date = m.group(1)
        body = m.group(2)
    clauses = [c.strip() for c in re.split(r"[.!?;]+", body) if c.strip()]
    return date, clauses


class _Model:
    """Temporally evolving KG; insertion-ordered for deterministic output."""

    def __init__(self) -> None:
        self.entities: list[str] = []
        self.facts: dict[tuple, dict] = {}     # (s,r,o) -> fact
        self.order: list[tuple] = []

    def add_entity(self, e: str) -> bool:
        if e and e not in self.entities:
            self.entities.append(e)
            return True
        return False

    def integrate(self, s: str, r: str, o: str, conf: float, date: str,
                  source: int) -> tuple[str, dict]:
        """Constructor step. Returns (action, fact) where action is
        'add' | 'reinforce' | 'duplicate-weaker'."""
        key = (s, r, o)
        if key in self.facts:
            f = self.facts[key]
            # reinforce: noisy-OR confidence, widen timespan, bump support
            new_conf = round(1 - (1 - f["confidence"]) * (1 - conf), 2)
            f["confidence"] = new_conf
            f["support"] += 1
            if date and date > f["last_seen"]:
                f["last_seen"] = date
            if date and (not f["first_seen"] or date < f["first_seen"]):
                f["first_seen"] = date
            self._resolve_conflict(f)
            return "reinforce", f
        f = {"subject": s, "relation": r, "object": o, "confidence": conf,
             "support": 1, "first_seen": date, "last_seen": date,
             "provenance": source, "superseded": False}
        self.facts[key] = f
        self.order.append(key)
        self._resolve_conflict(f)
        return "add", f

    def _resolve_conflict(self, f: dict) -> None:
        """If a polar-opposite relation exists on the same (subject, object),
        keep the higher-confidence fact; mark the loser superseded."""
        opp = _OPPOSITE.get(f["relation"])
        if not opp:
            return
        other_key = (f["subject"], opp, f["object"])
        other = self.facts.get(other_key)
        if not other:
            f["superseded"] = False
            return
        if f["confidence"] >= other["confidence"]:
            f["superseded"] = False
            other["superseded"] = True
        else:
            f["superseded"] = True
            other["superseded"] = False

    def to_graph(self) -> dict:
        nodes = [
            {"data": {"id": e, "label": e, "type": "class", "attributes": []}}
            for e in self.entities
        ]
        edges = []
        for key in self.order:
            f = self.facts[key]
            if f["superseded"]:
                continue
            edges.append({"data": {
                "id": f"{f['subject']}-{f['relation']}-{f['object']}",
                "source": f["subject"], "target": f["object"],
                "label": f"{f['relation']} ({f['confidence']})",
                "relation": f["relation"], "confidence": f["confidence"],
                "support": f["support"], "first_seen": f["first_seen"],
                "last_seen": f["last_seen"], "provenance": f["provenance"],
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
        if f["superseded"]:
            continue
        pr = f["relation"]
        if pr not in seen:
            g.add((EXN[pr], RDF.type, OWL.ObjectProperty))
            seen.add(pr)
        g.add((EXN[pr], RDFS.domain, EXN[f["subject"]]))
        g.add((EXN[pr], RDFS.range, EXN[f["object"]]))
        span = (f"confidence={f['confidence']} support={f['support']} "
                f"{f['first_seen'] or '?'}..{f['last_seen'] or '?'}")
        g.add((EXN[f"{f['subject']}_{pr}_{f['object']}"],
               RDFS.comment, Literal(span)))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    abstracts = _read_abstracts(input_dir)
    mock = is_mock(llm)

    # Constructor builds day-by-day: order abstracts by their date (stable).
    dated = sorted(enumerate(abstracts, 1),
                   key=lambda t: (_split(t[1])[0], t[0]))

    model = _Model()
    steps: list[dict] = []
    filtered_total = 0

    for step_i, (orig_i, abstract) in enumerate(dated, 1):
        date, clauses = _split(abstract)
        added_e: list[str] = []
        extracted: list[dict] = []
        actions: list[str] = []
        filtered = 0

        for clause in clauses:
            if mock:
                raw = llm.complete(_PROMPT.format(clause=clause), temperature=0.0,
                                   json_schema={"type": "object"})
                try:
                    t = json.loads(raw)
                except json.JSONDecodeError:
                    t = {}
                triples = [t] if t.get("subject") else []
            else:
                # real backend: extract triple(s); attach a default confidence
                from backend.llm.extract import extract_triples
                triples = []
                for tr in extract_triples(llm, clause):
                    tr = dict(tr)
                    tr.setdefault("confidence", _confidence(clause))
                    triples.append(tr)

            for t in triples:
                s, r, o = t.get("subject"), t.get("relation"), t.get("object")
                conf = float(t.get("confidence", _confidence(clause)))
                if not (s and r and o):
                    continue
                # Extractor agent: filter low-confidence extractions
                if conf < EXTRACT_THRESHOLD:
                    filtered += 1
                    continue
                extracted.append({"subject": s, "relation": r, "object": o,
                                  "confidence": conf})
                for ent in (s, o):
                    if model.add_entity(ent):
                        added_e.append(ent)
                # Constructor agent: integrate into temporal graph
                action, _f = model.integrate(s, r, o, conf, date, orig_i)
                actions.append(action)

        filtered_total += filtered
        steps.append({
            "step": step_i,
            "stage": "extract+construct",
            "date": date,
            "abstract": abstract,
            "extracted": extracted,
            "filtered_low_confidence": filtered,
            "actions": actions,
            "added_entities": added_e,
            "graph": model.to_graph(),
        })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    all_facts = [model.facts[k] for k in model.order]
    active = [f for f in all_facts if not f["superseded"]]
    manifest = {
        "method": "medkgent",
        "backend": llm.name,
        "input_abstracts": len(abstracts),
        "counts": {
            "classes": len(model.entities),
            "object_properties": len({f["relation"] for f in active}),
            "data_properties": 0,
            "facts_active": len(active),
            "facts_superseded": sum(1 for f in all_facts if f["superseded"]),
            "reinforced": sum(1 for f in all_facts if f["support"] > 1),
            "filtered_low_confidence": filtered_total,
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
