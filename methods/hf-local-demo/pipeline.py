"""hf-local-demo — triple extraction with a REAL local HuggingFace model.

This is the project's demonstration that a method can run a local open model on
this machine's GPU (no API key, no cloud). Each sentence is sent to the LLM with
an instruction to return JSON triples; triples become the ontology graph.

Dual backend, same code:
  - backend="mock"     -> deterministic stand-in (capitalized subject / relation
                          verb / capitalized object). Used by tests + keyless site,
                          so output is reproducible and golden-tested.
  - backend="hf_local" -> a real local model (HF_MODEL, default Qwen2.5-1.5B-Instruct)
                          runs on the GPU via transformers. Output is non-deterministic
                          and therefore NOT golden-tested; prove it via a real run.

Contract (shared by every method): run(input_dir, out_dir, backend=None) -> manifest.
Outputs: ontology.ttl, ontology.json (Cytoscape), steps.json, manifest.json.
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

EX = "http://example.org/product#"

_STOP = {"What", "Which", "Who", "Where", "When", "How", "Why", "The", "A", "An",
         "Is", "Are", "This", "That", "These", "It", "They", "Its"}
_REL = {
    "consist": "consistsOf", "consists": "consistsOf", "made": "madeOf",
    "has": "has", "have": "has", "contains": "contains", "contain": "contains",
    "uses": "uses", "use": "uses", "drives": "drives", "drive": "drives",
    "powers": "powers", "power": "powers", "requires": "requires",
    "require": "requires", "produces": "produces", "produce": "produces",
    "supplies": "supplies", "supply": "supplies", "controls": "controls",
    "control": "controls", "monitors": "monitors", "connects": "connectsTo",
    "performs": "performs", "perform": "performs", "includes": "includes",
}

_SYSTEM = ("You are an information-extraction system. From the sentence, extract "
           "(subject, relation, object) triples. Return ONLY JSON of the form "
           '{"triples":[{"subject":"...","relation":"...","object":"..."}]}. '
           "Use short PascalCase nouns for subject/object and a camelCase verb "
           "for relation. No prose.")


def _caps(s: str) -> list[str]:
    out = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", s):
        if t not in _STOP and t not in out:
            out.append(t)
    return out


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM (used when backend=mock)."""
    sent = prompt.split("Sentence:")[-1].strip()
    caps = _caps(sent)
    words = re.findall(r"[a-zA-Z]+", sent.lower())
    rel = next((_REL[w] for w in words if w in _REL), None)
    triples = []
    if rel and len(caps) >= 2:
        triples.append({"subject": caps[0], "relation": rel, "object": caps[1]})
    return json.dumps({"triples": triples}, ensure_ascii=False)


_ARTICLES = {"the", "a", "an", "this", "that", "these", "those"}


def _san_entity(s: str) -> str:
    """Make a URI-safe PascalCase class name (drop articles, spaces, punctuation)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]
    words = [w for w in words if w.lower() not in _ARTICLES] or words
    return "".join(w[:1].upper() + w[1:] for w in words)


def _san_relation(r: str) -> str:
    """URI-safe camelCase relation name."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", r) if w]
    if not words:
        return ""
    return words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])


def _parse_triples(raw: str) -> list[dict]:
    """Robustly pull a {"triples":[...]} object out of an LLM response."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for t in obj.get("triples", []):
        s = _san_entity(str(t.get("subject", "")))
        r = _san_relation(str(t.get("relation", "")))
        o = _san_entity(str(t.get("object", "")))
        if s and r and o and s != o:
            out.append({"subject": s, "relation": r, "object": o})
    return out


def _graph(nodes: list[str], edges: list[dict]) -> dict:
    return {
        "nodes": [{"data": {"id": n, "label": n, "type": "class", "attributes": []}}
                  for n in nodes],
        "edges": [{"data": {"id": f'{e["s"]}-{e["r"]}-{e["o"]}', "source": e["s"],
                            "target": e["o"], "label": e["r"]}} for e in edges],
    }


def _to_ttl(nodes, edges):
    from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef
    g = Graph(); EXN = Namespace(EX); g.bind("ex", EXN); g.bind("owl", OWL)
    g.add((URIRef(EX.rstrip("#")), RDF.type, OWL.Ontology))
    for n in nodes:
        g.add((EXN[n], RDF.type, OWL.Class))
    for e in edges:
        pr = EXN[e["r"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[e["s"]]))
        g.add((pr, RDFS.range, EXN[e["o"]]))
        g.add((EXN[e["s"]], pr, EXN[e["o"]]))
    return g.serialize(format="turtle")


def _read_sentences(input_dir: Path) -> list[str]:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    text = f.read_text(encoding="utf-8")
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir); out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    sentences = _read_sentences(input_dir)

    nodes: list[str] = []
    edges: list[dict] = []
    seen_e: set = set()
    steps = []
    for i, sent in enumerate(sentences, 1):
        raw = llm.complete(f"Sentence: {sent}", system=_SYSTEM,
                           json_schema={"type": "object"}, temperature=0.0)
        added_n, added_e = [], []
        for t in _parse_triples(raw):
            for x in (t["subject"], t["object"]):
                if x not in nodes:
                    nodes.append(x); added_n.append(x)
            key = (t["subject"], t["relation"], t["object"])
            if key not in seen_e:
                seen_e.add(key)
                e = {"s": t["subject"], "r": t["relation"], "o": t["object"]}
                edges.append(e); added_e.append(e)
        steps.append({
            "step": i, "cq": sent,
            "added": {"classes": added_n,
                      "object_properties": [{"name": e["r"], "domain": e["s"],
                                             "range": e["o"]} for e in added_e],
                      "data_properties": []},
            "graph": _graph(nodes, edges),
        })

    graph = _graph(nodes, edges)
    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(_to_ttl(nodes, edges), encoding="utf-8")
    manifest = {
        "method": "hf-local-demo", "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {"classes": len(nodes), "object_properties": len(edges),
                   "data_properties": 0},
        "files": ["ontology.ttl", "ontology.json", "steps.json"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir"); ap.add_argument("out_dir")
    ap.add_argument("--backend", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend), ensure_ascii=False))
