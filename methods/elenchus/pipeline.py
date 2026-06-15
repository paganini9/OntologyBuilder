"""Elenchus - building a knowledge base through prover-skeptic dialogue.

Method (Bradley P. Allen, "Elenchus: Generating Knowledge Bases from
Prover-Skeptic Dialogues", arXiv:2603.06974, 2026;
github.com/bradleypallen/elenchus):

A knowledge base is grown through an adversarial **two-role dialogue**. For each
candidate claim a PROVER asserts it (parses it into a candidate triple and puts
it forward); an independent SKEPTIC then challenges it. Only claims that survive
the dialectic - parseable, internally consistent with the KB so far, and
non-redundant - are ACCEPTED into the KB; claims that fail are REJECTED and
recorded but excluded.

Unlike Ontogenia's single self-critique loop (one model criticising its own
output), Elenchus is *bilateral / adversarial*: the asserting role and the
challenging role are distinct, so the verdict is contested rather than
self-confirmed, and some claims are genuinely thrown out.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    claims.txt   - one candidate claim per line, each a natural sentence
                   expressing a triple (e.g. "A Motor drives a Pump").
                   Blank lines / # comments ignored.

Outputs (out_dir):
    ontology.ttl    - OWL of the surviving KB (Turtle, rdflib) - accepted only
    ontology.json   - final graph as Cytoscape nodes/edges (accepted only)
    steps.json      - one snapshot per claim (the prover/skeptic exchange)
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted via backend.llm.get_backend; MOCK is deterministic so
the output is reproducible and testable. With a real api backend a prover LLM
asserts claims and a separate skeptic LLM challenges them; with no key it
auto-falls back to MOCK.
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

EX = "http://example.org/elenchus#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "Two", "Both",
}

# relational verbs -> canonical object-property name (shared with cqbycq).
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
    "drives": "drives",
    "mount": "mountedOn", "mounted": "mountedOn",
    "cool": "cools", "cools": "cools",
    "regulate": "regulates", "regulates": "regulates",
    "power": "powers", "powers": "powers",
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


# ---------------------------------------------------------------------------
# LLM-abstracted roles. Each builds a prompt; MOCK answers deterministically.
# ---------------------------------------------------------------------------

_PROVE_PROMPT = (
    "You are the PROVER in an adversarial dialogue. Parse ONE natural-language "
    "claim into a single candidate triple and assert it. Return ONLY JSON "
    "{{\"subject\", \"relation\", \"object\"}} (use empty strings if it cannot "
    "be parsed into a full triple).\n"
    "Claim: {claim}\n"
)

_SKEPTIC_PROMPT = (
    "You are the SKEPTIC in an adversarial dialogue. Challenge the PROVER's "
    "candidate triple against the knowledge base accepted so far. REJECT if it "
    "is unparseable, contradicts an accepted claim, or duplicates one; else "
    "ACCEPT. Return ONLY JSON {{\"verdict\": \"accepted\"|\"rejected\", "
    "\"reason\": str}}.\n"
    "Candidate: {candidate}\nKnowledge base: {kb}\n"
)


def _prove_from_prompt(prompt: str) -> dict:
    """Deterministic PROVER: parse the claim into a candidate triple."""
    claim = prompt.split("Claim:")[-1].strip()
    nouns = _cap_nouns(claim)
    words = re.findall(r"[a-zA-Z]+", claim.lower())
    # do not let a class noun be mistaken for a relational verb
    noun_words = {n.lower() for n in nouns} | {n.lower() + "s" for n in nouns}
    rel = next((_REL[w] for w in words if w in _REL and w not in noun_words),
               None)
    if rel and len(nouns) >= 2:
        return {"subject": nouns[0], "relation": rel, "object": nouns[1]}
    return {"subject": "", "relation": "", "object": ""}


def _skeptic_from_prompt(prompt: str) -> dict:
    """Deterministic SKEPTIC: challenge the candidate against the KB."""
    cand = json.loads(prompt.split("Candidate:")[-1].split("\nKnowledge base:")[0]
                      .strip())
    kb = json.loads(prompt.split("Knowledge base:")[-1].strip())

    s, r, o = cand.get("subject", ""), cand.get("relation", ""), cand.get("object", "")
    # (a) unparseable
    if not (s and r and o):
        return {"verdict": "rejected",
                "reason": "unparseable: not a full subject-relation-object triple"}
    # (c) duplicate of an accepted claim
    for t in kb:
        if t["subject"] == s and t["relation"] == r and t["object"] == o:
            return {"verdict": "rejected",
                    "reason": "redundant: duplicates an accepted claim"}
    # (b) contradiction: same subject+relation but different object,
    #     or the reverse edge already accepted
    for t in kb:
        if t["subject"] == s and t["relation"] == r and t["object"] != o:
            return {"verdict": "rejected",
                    "reason": (f"contradiction: {s} {r} already accepted "
                               f"with object {t['object']}")}
        if t["subject"] == o and t["object"] == s and t["relation"] == r:
            return {"verdict": "rejected",
                    "reason": (f"contradiction: reverse edge {o} {r} {s} "
                               "already accepted")}
    return {"verdict": "accepted",
            "reason": "survives the dialectic: parseable, consistent, novel"}


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in routed by prompt header (prover vs skeptic)."""
    if prompt.startswith("You are the PROVER"):
        return json.dumps(_prove_from_prompt(prompt), ensure_ascii=False)
    if prompt.startswith("You are the SKEPTIC"):
        return json.dumps(_skeptic_from_prompt(prompt), ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


def _read_claims(input_dir: Path) -> list[str]:
    f = input_dir / "claims.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    claims = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            claims.append(line)
    return claims


class _Model:
    """Accumulated KB of ACCEPTED facts (insertion order = deterministic)."""

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
    # asserted accepted triples (instance-level facts between the classes)
    for t in triples:
        g.add((EXN[t["subject"]], EXN[t["relation"]], EXN[t["object"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    claims = _read_claims(input_dir)

    model = _Model()
    kb: list[dict] = []        # accepted triples (the SKEPTIC's reference KB)
    accepted: list[dict] = []
    rejected: list[dict] = []
    steps: list[dict] = []

    for i, claim in enumerate(claims, 1):
        # --- PROVER asserts a candidate triple ---
        raw = llm.complete(_PROVE_PROMPT.format(claim=claim), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            cand = json.loads(raw)
        except json.JSONDecodeError:
            cand = {"subject": "", "relation": "", "object": ""}

        # --- SKEPTIC challenges it against the KB so far ---
        raw_v = llm.complete(
            _SKEPTIC_PROMPT.format(
                candidate=json.dumps(cand, ensure_ascii=False),
                kb=json.dumps(kb, ensure_ascii=False)),
            temperature=0.0, json_schema={"type": "object"})
        try:
            verdict = json.loads(raw_v)
        except json.JSONDecodeError:
            verdict = {"verdict": "rejected", "reason": "skeptic parse error"}

        v = verdict.get("verdict", "rejected")
        reason = verdict.get("reason", "")

        added_c: list[str] = []
        added_o: list[dict] = []
        if v == "accepted":
            s, r, o = cand["subject"], cand["relation"], cand["object"]
            if model.add_class(s):
                added_c.append(s)
            if model.add_class(o):
                added_c.append(o)
            op = {"name": r, "domain": s, "range": o}
            if model.add_obj(op):
                added_o.append(op)
            triple = {"subject": s, "relation": r, "object": o}
            kb.append(triple)
            accepted.append({**triple, "claim": claim})
        else:
            rejected.append({"claim": claim, "candidate": cand, "reason": reason})

        steps.append({
            "step": i,
            "cq": claim,
            "prover": cand,
            "skeptic": {"verdict": v, "reason": reason},
            "verdict": v,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": []},
            "graph": model.to_graph(),
        })

    graph = model.to_graph()
    accepted_triples = [{"subject": a["subject"], "relation": a["relation"],
                         "object": a["object"]} for a in accepted]
    ttl = _to_ttl(model, accepted_triples)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "elenchus",
        "backend": llm.name,
        "input_claims": len(claims),
        "counts": {
            "claims": len(claims),
            "accepted": len(accepted),
            "rejected": len(rejected),
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
