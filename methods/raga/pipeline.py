"""RAGA - Reading-And-Graph-building-Agent (Read-Search-Verify-Construct).

Method (Han & Cheng, "RAGA: Reading-And-Graph-building-Agent for Autonomous
Knowledge Graph Construction and Retrieval-Augmented Generation", arXiv 2605.17072,
2026): a single autonomous agent walks a source document one unit (sentence) at a
time and, for each unit, runs a ReAct-style cognitive loop constrained to four
explicit sub-stages:

    READ    -> propose candidate (subject, relation, object) triples from the unit.
    SEARCH  -> link the candidate entities against the graph built so far
               (context linking: which proposed entities already exist?).
    VERIFY  -> evidence-anchored verification: keep a candidate only if BOTH its
               subject and object are literally supported by the unit's text
               (their tokens appear in the sentence). Unsupported candidates
               (e.g. pronoun / implied objects) are dropped.
    CONSTRUCT -> commit the verified triples into the growing graph.

The defining trait vs. other pipelines: a *single-agent* ReAct cognitive loop is
run *per unit*, with the Read->Search->Verify->Construct constraint applied every
iteration, so the agent both grows and self-audits the graph as it reads. The
final graph contains ONLY evidence-anchored (verified) triples.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt   - free source text; one sentence = one agent unit.

Outputs (out_dir):
    ontology.ttl    - OWL of verified triples (Turtle, rdflib)
    ontology.json   - final graph as Cytoscape nodes/edges (verified only)
    steps.json      - one snapshot per sentence (the per-unit ReAct loop),
                      each with extra keys read / search / verify and cq=sentence.
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted via backend.llm.get_backend. With MOCK the READ stage
parses the sentence deterministically (golden-tested). With a REAL backend the
READ stage uses backend.llm.extract.extract_triples; either way SEARCH/VERIFY/
CONSTRUCT apply the SAME deterministic, evidence-anchored rules, so the final
graph is verified identically for both paths. With no key it auto-falls back to
MOCK.
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

EX = "http://example.org/raga#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "Them", "These",
    "Those", "He", "She", "Two", "Both",
}

# relational verbs -> canonical object-property name (shared idiom with cqbycq).
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
    "support": "supports", "supports": "supports",
    "drive": "drives", "drives": "drives",
    "mount": "mountedOn", "mounted": "mountedOn",
    "connect": "connectsTo", "connects": "connectsTo",
    "control": "controls", "controls": "controls",
    "protect": "protects", "protects": "protects",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _cap_nouns(text: str) -> list[str]:
    """Capitalized tokens (singularized), minus stopwords, in order."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# READ stage (LLM-abstracted). MOCK answers deterministically.
# ---------------------------------------------------------------------------

_READ_PROMPT = (
    "You are RAGA, a reading-and-graph-building agent. READ ONE sentence and "
    "propose candidate (subject, relation, object) triples as JSON "
    "{{\"candidates\": [{{\"subject\", \"relation\", \"object\"}}]}}.\n"
    "Sentence: {sentence}\n"
)


def _read_from_prompt(prompt: str) -> dict:
    """Deterministic READ: parse one sentence -> candidate triples.

    subject = first capitalized noun; objects = the other capitalized nouns;
    relation = first relational verb found. The agent is deliberately greedy
    here (the VERIFY stage is what enforces evidence anchoring), so an implied /
    pronoun object can leak a candidate that VERIFY later drops.
    """
    sentence = prompt.split("Sentence:")[-1].strip()
    nouns = _cap_nouns(sentence)
    words = re.findall(r"[a-zA-Z]+", sentence.lower())
    rel = next((_REL[w] for w in words if w in _REL), None)
    candidates: list[dict] = []
    if rel and nouns:
        subject = nouns[0]
        objects = nouns[1:]
        if objects:
            for obj in objects:
                cand = {"subject": subject, "relation": rel, "object": obj}
                if cand not in candidates:
                    candidates.append(cand)
        else:
            # A relation is asserted but the object is implied (e.g. a pronoun:
            # "It protects them."). The agent still PROPOSES a candidate using a
            # placeholder object lifted from the implied pronoun, which is NOT
            # evidence-anchored as a capitalized entity -> VERIFY will drop it.
            implied = _implied_object(sentence)
            if implied:
                candidates.append(
                    {"subject": subject, "relation": rel, "object": implied})
    return {"candidates": candidates}


_PRONOUNS = ["Them", "It", "They", "These", "Those", "Him", "Her"]


def _implied_object(sentence: str) -> str:
    """Lift a Pascal-cased placeholder from an implied pronoun object, if any."""
    low = sentence.lower()
    for p in _PRONOUNS:
        if re.search(rf"\b{p.lower()}\b", low):
            return p
    return ""


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in routed by prompt header (only READ uses the LLM)."""
    if prompt.startswith("You are RAGA"):
        return json.dumps(_read_from_prompt(prompt), ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    return f.read_text(encoding="utf-8")


class _Model:
    """Accumulated graph of VERIFIED triples (insertion order = deterministic)."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []   # {name, domain, range}
        self.data_props: list[dict] = []  # (unused; kept for schema parity)

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


def _to_ttl(model: _Model, triples: list[dict]) -> str:
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    seen_props: set[str] = set()
    for p in model.obj_props:
        pr = EXN[p["name"]]
        if p["name"] not in seen_props:
            g.add((pr, RDF.type, OWL.ObjectProperty))
            seen_props.add(p["name"])
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    # asserted verified triples (instance-level facts between the classes)
    for t in triples:
        g.add((EXN[t["subject"]], EXN[t["relation"]], EXN[t["object"]]))
    return g.serialize(format="turtle")


def _verify(cand: dict, sentence: str) -> tuple[bool, str]:
    """Evidence-anchored VERIFY: keep iff BOTH subject and object tokens appear
    in the sentence (the unit's evidence). Pronoun / implied objects -> dropped.
    """
    s, o = cand["subject"], cand["object"]
    s_ok = re.search(rf"\b{re.escape(s)}s?\b", sentence) is not None
    o_ok = re.search(rf"\b{re.escape(o)}s?\b", sentence) is not None
    if s_ok and o_ok:
        return True, "subject+object both anchored in sentence evidence"
    if not o_ok:
        return False, "object not anchored in sentence evidence (implied/pronoun)"
    return False, "subject not anchored in sentence evidence"


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
    verified_triples: list[dict] = []
    total_candidates = 0
    total_dropped = 0

    # Per SENTENCE: run the agent's ReAct cognitive loop (Read->Search->Verify->
    # Construct). Emit ONE step per sentence with extra keys read/search/verify.
    for i, sentence in enumerate(sentences, 1):
        # --- READ -----------------------------------------------------------
        if mock:
            raw = llm.complete(_READ_PROMPT.format(sentence=sentence),
                               temperature=0.0, json_schema={"type": "object"})
            try:
                candidates = json.loads(raw).get("candidates", [])
            except json.JSONDecodeError:
                candidates = []
        else:
            # REAL path: the actual model proposes candidate triples for the
            # sentence; SEARCH/VERIFY/CONSTRUCT below are unchanged.
            candidates = [
                {"subject": t["subject"], "relation": t["relation"],
                 "object": t["object"]}
                for t in extract_triples(llm, sentence)
            ]
        total_candidates += len(candidates)

        # --- SEARCH (context linking) --------------------------------------
        # Which proposed entities already exist in the graph built so far?
        existing = set(model.classes)
        matched = []
        for c in candidates:
            for ent in (c["subject"], c["object"]):
                if ent in existing and ent not in matched:
                    matched.append(ent)
        search = {"existing_entities": list(model.classes), "matched": matched}

        # --- VERIFY (evidence-anchored) ------------------------------------
        kept: list[dict] = []
        dropped: list[dict] = []
        for c in candidates:
            keep, reason = _verify(c, sentence)
            entry = {**c, "reason": reason}
            (kept if keep else dropped).append(entry)
        total_dropped += len(dropped)

        # --- CONSTRUCT ------------------------------------------------------
        constructed: list[dict] = []
        for c in kept:
            s, r, o = c["subject"], c["relation"], c["object"]
            model.add_class(s)
            model.add_class(o)
            model.add_obj({"name": r, "domain": s, "range": o})
            triple = {"subject": s, "relation": r, "object": o}
            if triple not in verified_triples:
                verified_triples.append(triple)
            constructed.append(triple)

        steps.append({
            "step": i,
            "cq": sentence,
            "read": {"candidates": candidates},
            "search": search,
            "verify": {"kept": kept, "dropped": dropped},
            "constructed": constructed,
            "graph": model.to_graph(),
        })

    graph = model.to_graph()
    ttl = _to_ttl(model, verified_triples)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "raga",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "sentences": len(sentences),
            "candidates": total_candidates,
            "verified": len(verified_triples),
            "dropped": total_dropped,
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
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
