"""ODKE+ - Ontology-guided 5-stage open-domain knowledge extraction.

Method (Khorshidi, Nikfarjam et al. / Apple, arXiv:2509.04696, 2025):
a production pipeline of five stages that turns a list of entities plus free
evidence text into a verified knowledge graph. The defining idea is the
**generation-verification separation**: an extraction step proposes candidate
facts, and an independent grounder (a 2nd verification pass) keeps only the
candidates that are actually supported by the evidence.

Five stages (each emits a `steps.json` snapshot for the UI slider):
    1. extraction-initiator : per entity, pick the property slots to fill
       (the dynamic "ontology snippet"). cq = "(initiate)".
    2. evidence-retriever   : per entity, gather evidence sentences that
       mention it. cq = "(retrieve)".
    3. hybrid-extractor     : from retrieved sentences, propose candidate
       triples (subject = entity, relation via the cqbycq verb map, object =
       another capitalized noun / slot filler). cq = "(extract)".
    4. grounder             : 2nd-pass verify - KEEP a candidate only if BOTH
       its subject and object co-occur in the evidence text, DROP otherwise.
       cq = "(ground/verify)".
    5. corroborator         : normalize + load the verified candidates into the
       final graph. cq = "(corroborate)".

The FINAL graph contains only verified triples.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    entities.txt   - one entity per line (blank lines / # comments ignored)
    evidence.txt   - free evidence text (optional; if absent every candidate is
                     unverifiable and the final graph is empty)

Outputs (out_dir):
    ontology.ttl    - OWL of verified facts (Turtle, rdflib)
    ontology.json   - final graph as Cytoscape nodes/edges (verified only)
    steps.json      - one snapshot per stage (5)
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted via backend.llm.get_backend; MOCK is deterministic so
the output is reproducible and testable. With a real backend the extraction LLM
(stage 3, via backend.llm.extract.extract_triples) proposes candidate triples
from the retrieved evidence, and the grounder (stage 4) applies the SAME
deterministic co-occurrence rule used by MOCK to keep only evidence-supported
candidates - so the final graph is real, non-empty when grounded, and verified
the same way for both paths. With no key it auto-falls back to MOCK.
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

EX = "http://example.org/odke#"

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
    "mount": "mountedOn", "mounted": "mountedOn",
}

# Default property slots the initiator proposes per entity (the ontology
# snippet). Mirrors ODKE+ "dynamic ontology snippet": which relations to fill.
_DEFAULT_SLOTS = ["madeOf", "hasPart", "manufacturer"]

# The open-domain extractor optimistically tries to fill the `manufacturer`
# slot with an expected filler even when evidence is silent (generation step).
# These guesses are deliberately NOT in the evidence, so the independent
# grounder (verification step) rejects them - this is the generation-
# verification separation at the heart of ODKE+.
_SLOT_GUESS = {
    "manufacturer": ("manufacturer", "Manufacturer"),
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
# LLM-abstracted stages. Each builds a prompt; MOCK answers deterministically.
# ---------------------------------------------------------------------------

_EXTRACT_PROMPT = (
    "You are an ontology-guided extractor. Given an entity, the property slots "
    "to fill, and supporting sentences, propose candidate triples as JSON "
    "{{\"candidates\": [{{\"subject\", \"relation\", \"object\"}}]}}.\n"
    "Entity: {entity}\nSlots: {slots}\nSentences:\n{sentences}\n"
)

_VERIFY_PROMPT = (
    "You are an independent verification LLM (grounder). For each candidate "
    "triple decide if it is supported by the evidence text. A triple is "
    "supported only if BOTH its subject and object appear in the evidence. "
    "Return JSON {{\"verdicts\": [{{\"keep\": bool, \"reason\": str}}]}}.\n"
    "Evidence:\n{evidence}\nCandidates: {candidates}\n"
)


def _extract_from_prompt(prompt: str) -> dict:
    """Deterministic extraction: parse entity + sentences -> candidate triples."""
    entity = prompt.split("Entity:")[-1].split("\n")[0].strip()
    slots = [s.strip() for s in
             prompt.split("Slots:")[-1].split("\n")[0].split(",") if s.strip()]
    sent_block = prompt.split("Sentences:\n")[-1]
    sentences = [s for s in sent_block.splitlines() if s.strip()]

    candidates: list[dict] = []
    for s in sentences:
        words = re.findall(r"[a-zA-Z]+", s.lower())
        rel = next((_REL[w] for w in words if w in _REL), None)
        if not rel:
            continue
        # objects = other capitalized nouns in the sentence (not the subject).
        for obj in _cap_nouns(s):
            if obj == entity:
                continue
            cand = {"subject": entity, "relation": rel, "object": obj}
            if cand not in candidates:
                candidates.append(cand)

    # Ontology-guided slot filling: optimistically propose an expected filler
    # for unsatisfied slots (open-domain generation). The grounder verifies.
    for slot in slots:
        if slot in _SLOT_GUESS:
            rel, obj = _SLOT_GUESS[slot]
            cand = {"subject": entity, "relation": rel, "object": obj}
            if cand not in candidates:
                candidates.append(cand)
    return {"candidates": candidates}


def _verify_from_prompt(prompt: str) -> dict:
    """Deterministic grounding: keep iff subject and object both in evidence."""
    evidence = prompt.split("Evidence:\n")[-1].split("\nCandidates:")[0]
    cands = json.loads(prompt.split("Candidates:")[-1].strip())
    present = set(_cap_nouns(evidence))
    verdicts = []
    for c in cands:
        keep = c["subject"] in present and c["object"] in present
        reason = ("subject+object co-occur in evidence" if keep
                  else "object not grounded in evidence")
        verdicts.append({"keep": keep, "reason": reason})
    return {"verdicts": verdicts}


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in routed by prompt header (extract vs verify)."""
    if prompt.startswith("You are an ontology-guided extractor"):
        return json.dumps(_extract_from_prompt(prompt), ensure_ascii=False)
    if prompt.startswith("You are an independent verification LLM"):
        return json.dumps(_verify_from_prompt(prompt), ensure_ascii=False)
    return json.dumps({}, ensure_ascii=False)


def _read_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _read_inputs(input_dir: Path) -> tuple[list[str], str]:
    ef = input_dir / "entities.txt"
    if not ef.exists():
        raise FileNotFoundError(f"missing input: {ef}")
    entities = _read_lines(ef)
    evf = input_dir / "evidence.txt"
    evidence = evf.read_text(encoding="utf-8") if evf.exists() else ""
    return entities, evidence


class _Model:
    """Accumulated graph of VERIFIED facts (insertion order = deterministic)."""

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


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    entities, evidence = _read_inputs(input_dir)
    sentences = _split_sentences(evidence)

    model = _Model()
    steps: list[dict] = []

    # --- Stage 1: extraction-initiator -------------------------------------
    slots = {e: list(_DEFAULT_SLOTS) for e in entities}
    for e in entities:
        model.add_class(e)
    steps.append({
        "step": 1,
        "stage": "extraction-initiator",
        "cq": "(initiate)",
        "detail": {"slots": slots},
        "graph": model.to_graph(),
    })

    # --- Stage 2: evidence-retriever ---------------------------------------
    retrieved: dict[str, list[str]] = {}
    for e in entities:
        hits = [s for s in sentences if re.search(rf"\b{re.escape(e)}s?\b", s)]
        retrieved[e] = hits
    steps.append({
        "step": 2,
        "stage": "evidence-retriever",
        "cq": "(retrieve)",
        "detail": {"retrieved": retrieved},
        "graph": model.to_graph(),
    })

    # --- Stage 3: hybrid-extractor -----------------------------------------
    # MOCK: keep the exact deterministic candidate extraction (golden-tested).
    # REAL: let the shared real-LLM helper extract candidate triples from the
    #       retrieved evidence text. Either way the candidates then flow into
    #       the UNCHANGED grounder (Stage 4), whose rule keeps only triples
    #       whose subject AND object co-occur in the evidence.
    candidates: list[dict] = []
    if is_mock(llm):
        for e in entities:
            prompt = _EXTRACT_PROMPT.format(
                entity=e, slots=", ".join(slots[e]),
                sentences="\n".join(retrieved[e]) or "(none)")
            raw = llm.complete(prompt, temperature=0.0,
                               json_schema={"type": "object"})
            try:
                cands = json.loads(raw).get("candidates", [])
            except json.JSONDecodeError:
                cands = []
            for c in cands:
                if c not in candidates:
                    candidates.append(c)
    else:
        # Real backend: extract per entity from its retrieved evidence (fall
        # back to the full evidence text when retrieval found nothing for it),
        # so candidate subjects/objects are anchored to evidence the grounder
        # can later verify against.
        for e in entities:
            text = "\n".join(retrieved[e]) or evidence
            for t in extract_triples(llm, text):
                cand = {"subject": t["subject"],
                        "relation": t["relation"],
                        "object": t["object"]}
                if cand not in candidates:
                    candidates.append(cand)
    steps.append({
        "step": 3,
        "stage": "hybrid-extractor",
        "cq": "(extract)",
        "detail": {"candidates": candidates},
        "graph": model.to_graph(),
    })

    # --- Stage 4: grounder (2nd-pass verification) -------------------------
    # The grounder is the generation-verification separation: it runs the SAME
    # deterministic rule for BOTH paths - keep a candidate only if its subject
    # AND object co-occur in the evidence text, drop otherwise. On the MOCK
    # backend this is routed through llm.complete -> mock_responder (golden-
    # tested); on a REAL backend we apply the identical rule directly (the
    # verdict must not depend on a stochastic LLM), so the real-extracted
    # candidates are filtered exactly as the mock ones are.
    kept: list[dict] = []
    dropped: list[dict] = []
    if candidates:
        if is_mock(llm):
            prompt = _VERIFY_PROMPT.format(
                evidence=evidence,
                candidates=json.dumps(candidates, ensure_ascii=False))
            raw = llm.complete(prompt, temperature=0.0,
                               json_schema={"type": "object"})
            try:
                verdicts = json.loads(raw).get("verdicts", [])
            except json.JSONDecodeError:
                verdicts = []
        else:
            verdicts = _verify_from_prompt(_VERIFY_PROMPT.format(
                evidence=evidence,
                candidates=json.dumps(candidates, ensure_ascii=False))
            ).get("verdicts", [])
        for c, v in zip(candidates, verdicts):
            entry = {**c, "reason": v.get("reason", "")}
            (kept if v.get("keep") else dropped).append(entry)
    steps.append({
        "step": 4,
        "stage": "grounder",
        "cq": "(ground/verify)",
        "detail": {"kept": kept, "dropped": dropped},
        "graph": model.to_graph(),
    })

    # --- Stage 5: corroborator (load verified facts) -----------------------
    verified_triples: list[dict] = []
    for c in kept:
        s, r, o = c["subject"], c["relation"], c["object"]
        model.add_class(s)
        model.add_class(o)
        model.add_obj({"name": r, "domain": s, "range": o})
        triple = {"subject": s, "relation": r, "object": o}
        if triple not in verified_triples:
            verified_triples.append(triple)
    steps.append({
        "step": 5,
        "stage": "corroborator",
        "cq": "(corroborate)",
        "detail": {"loaded": verified_triples},
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
        "method": "odke-plus",
        "backend": llm.name,
        "input_entities": len(entities),
        "counts": {
            "entities": len(entities),
            "candidates": len(candidates),
            "verified": len(verified_triples),
            "dropped": len(dropped),
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
