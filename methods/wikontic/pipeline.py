"""Wikontic - Wikidata-aligned, ontology-aware KG construction from open text.

Method (Wikontic: Constructing Wikidata-Aligned, Ontology-Aware Knowledge Graphs
with Large Language Models, arXiv:2512.00590): a multi-stage pipeline that builds
a compact, ontology-consistent KG from open-domain text by (1) extracting
candidate triplets **with qualifiers**, (2) **normalizing entity mentions** to a
canonical item to cut duplication, and (3) enforcing **Wikidata-based type and
relation constraints** so only ontology-valid statements survive.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    passages.txt - one sentence per line (blank lines / # comments ignored)

Outputs (out_dir):
    ontology.ttl   - OWL/Wikidata-aligned: items typed (P31/instanceOf), object
                     properties (Pxxx) with statements; qualifiers as comments
    ontology.json  - Cytoscape graph: item nodes (carry QID + class) + class
                     nodes; relation edges carry the Wikidata PID + qualifiers
    steps.json     - one snapshot per sentence (UI replays construction)
    manifest.json  - summary (raw surfaces, canonical items, merged, accepted /
                     rejected statements, qualified statements)

Deterministic-on-MOCK ingredients (faithful to the paper):
    * Candidate triplet extraction with qualifiers - a relation lexicon pulls
      (subject, property, object) from each sentence; a trailing `in <year>` /
      `since <year>` clause becomes a Wikidata qualifier (point-in-time P585 /
      start-time P580).
    * Entity normalization - surface mentions ("Apple", "Apple Inc.") map through
      an alias table to ONE canonical Wikidata item (QID + type), so duplicate
      mentions collapse into a single node.
    * Wikidata type/relation constraints - every property carries subject-type
      and value-type constraints (e.g. foundedBy/P112 requires an Organization
      subject and a Person value); a statement whose normalized endpoints violate
      the constraint is rejected, mirroring Wikidata property constraints.
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
from backend.llm.extract import is_mock, extract_triples, san_relation  # noqa: E402

EX = "http://example.org/wikontic#"
WD = "http://www.wikidata.org/entity/"

# ---- mini Wikidata ontology (first-class constraint) ----------------------
# alias key (lowercase, article/period-stripped) -> (label, qid, type)
ALIASES = {
    "apple inc": ("Apple Inc.", "Q312", "Organization"),
    "apple": ("Apple Inc.", "Q312", "Organization"),
    "steve jobs": ("Steve Jobs", "Q19837", "Person"),
    "steve wozniak": ("Steve Wozniak", "Q483382", "Person"),
    "tim cook": ("Tim Cook", "Q265852", "Person"),
    "cupertino": ("Cupertino", "Q110739", "City"),
    "california": ("California", "Q99", "Region"),
    "united states": ("United States", "Q30", "Country"),
    "usa": ("United States", "Q30", "Country"),
    "u.s.": ("United States", "Q30", "Country"),
    "us": ("United States", "Q30", "Country"),
}

# relation phrase (matched case-insensitively, longest first) -> property key
_REL_PHRASES = [
    ("was founded by", "foundedBy"),
    ("is headquartered in", "headquarters"),
    ("is located in", "locatedIn"),
    ("is led by", "chiefExecutiveOfficer"),
]

# property key -> Wikidata PID + subject/value type constraints
PROPS = {
    "foundedBy": {"pid": "P112", "subj": {"Organization"}, "obj": {"Person"}},
    "headquarters": {"pid": "P159", "subj": {"Organization"},
                     "obj": {"City", "Country", "Region"}},
    "locatedIn": {"pid": "P131", "subj": {"City", "Region", "Organization"},
                  "obj": {"City", "Region", "Country"}},
    "chiefExecutiveOfficer": {"pid": "P169", "subj": {"Organization"},
                              "obj": {"Person"}},
}


def _norm_key(surface: str) -> str:
    s = surface.strip().strip(".").strip()
    s = re.sub(r"^(the|a|an)\s+", "", s, flags=re.I)
    return s.strip().strip(".").strip().lower()


def _pascal(surface: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", surface) if w]
    return "".join(w[:1].upper() + w[1:] for w in words) or "Entity"


def _resolve(surface: str) -> dict:
    """Surface mention -> canonical item dict {label, qid, type, key}."""
    key = _norm_key(surface)
    if key in ALIASES:
        label, qid, typ = ALIASES[key]
        return {"label": label, "qid": qid, "type": typ, "key": key}
    # unknown mention: mint a local item with unknown type
    return {"label": surface.strip().strip("."), "qid": None,
            "type": "Entity", "key": key}


def _extract_qualifier(rest: str) -> tuple[str, dict]:
    """Pull a trailing Wikidata qualifier off the object span."""
    m = re.search(r"\bsince\s+(\d{4})\s*$", rest)
    if m:
        return rest[:m.start()].strip(), {"property": "startTime", "pid": "P580",
                                          "value": m.group(1)}
    m = re.search(r"\bin\s+(\d{4})\s*$", rest)
    if m:
        return rest[:m.start()].strip(), {"property": "pointInTime",
                                          "pid": "P585", "value": m.group(1)}
    return rest.strip(), {}


def _parse_sentence(sentence: str) -> Optional[dict]:
    """Deterministic candidate-triplet extraction (MOCK path)."""
    s = sentence.strip()
    if s.endswith("."):
        s = s[:-1]
    low = s.lower()
    for phrase, prop in _REL_PHRASES:
        idx = low.find(" " + phrase + " ")
        if idx == -1:
            continue
        subj = s[:idx].strip()
        rest = s[idx + len(phrase) + 2:].strip()
        obj, qual = _extract_qualifier(rest)
        if subj and obj:
            return {"subj": subj, "prop": prop, "obj": obj, "qualifier": qual}
    return None


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: parse one sentence -> candidate triplet JSON."""
    sentence = prompt.split("Sentence:")[-1].strip().splitlines()[0].strip()
    cand = _parse_sentence(sentence)
    return json.dumps(cand or {}, ensure_ascii=False)


_PROMPT = (
    "Extract ONE (subject, property, object) triplet with an optional time "
    'qualifier. Return ONLY JSON {{"subj":"...","prop":"...","obj":"...",'
    '"qualifier":{{}}}}.\nSentence: {sentence}\n'
)


class _Model:
    """Accumulated Wikidata-aligned graph (insertion order = deterministic)."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.items: list[dict] = []        # {id, label, qid, cls}
        self.statements: list[dict] = []   # {src, prop, pid, dst, qualifiers}
        self._by_key: dict[str, dict] = {}

    def add_item(self, item: dict) -> dict:
        """Normalize+dedup: return the canonical stored item for this mention."""
        key = item["key"]
        if key in self._by_key:
            return self._by_key[key]
        eid = item["qid"] or _pascal(item["label"])
        # a different surface (different key) may resolve to the same canonical
        # id (e.g. Apple / Apple Inc -> Q312): collapse onto the existing node.
        for it in self.items:
            if it["id"] == eid:
                self._by_key[key] = it
                return it
        stored = {"id": eid, "label": item["label"], "qid": item["qid"],
                  "cls": item["type"]}
        self.items.append(stored)
        self._by_key[key] = stored
        if item["type"] not in self.classes:
            self.classes.append(item["type"])
        return stored

    def add_statement(self, src: str, prop: str, pid: str, dst: str,
                      qualifiers: dict) -> bool:
        st = {"src": src, "prop": prop, "pid": pid, "dst": dst,
              "qualifiers": qualifiers}
        if any(s["src"] == src and s["prop"] == prop and s["dst"] == dst
               for s in self.statements):
            return False
        self.statements.append(st)
        return True

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for it in self.items:
            nodes.append({"data": {"id": it["id"], "label": it["label"],
                                   "type": "instance", "cls": it["cls"],
                                   "qid": it["qid"], "attributes": []}})
        edges = []
        for it in self.items:
            edges.append({"data": {"id": f"{it['id']}-instanceOf-{it['cls']}",
                                   "source": it["id"], "target": it["cls"],
                                   "label": "instanceOf"}})
        for s in self.statements:
            edges.append({"data": {
                "id": f"{s['src']}-{s['prop']}-{s['dst']}",
                "source": s["src"], "target": s["dst"], "label": s["prop"],
                "pid": s["pid"], "qualifiers": s["qualifiers"]}})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for prop in sorted({s["prop"] for s in model.statements}):
        g.add((EXN[prop], RDF.type, OWL.ObjectProperty))

    def uri(eid: str) -> URIRef:
        return EXN[eid]

    for it in model.items:
        u = uri(it["id"])
        g.add((u, RDF.type, EXN[it["cls"]]))
        g.add((u, RDFS.label, Literal(it["label"])))
        if it["qid"]:
            g.add((u, RDFS.seeAlso, URIRef(WD + it["qid"])))
    for s in model.statements:
        g.add((uri(s["src"]), EXN[s["prop"]], uri(s["dst"])))
    return g.serialize(format="turtle")


def _read_passages(input_dir: Path) -> list[str]:
    f = input_dir / "passages.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _candidates(sentence: str, llm, mock: bool) -> list[dict]:
    """Return candidate triplets [{subj,prop,obj,qualifier}] for one sentence."""
    if mock:
        raw = llm.complete(_PROMPT.format(sentence=sentence), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            cand = json.loads(raw)
        except json.JSONDecodeError:
            cand = {}
        return [cand] if cand.get("subj") and cand.get("obj") else []
    # REAL path: shared extractor; relation sanitized, no time qualifier.
    out = []
    for t in extract_triples(llm, sentence):
        prop = san_relation(t["relation"])
        out.append({"subj": t["subject"], "prop": prop, "obj": t["object"],
                    "qualifier": {}})
    return out


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    mock = is_mock(llm)
    sentences = _read_passages(input_dir)

    model = _Model()
    steps: list[dict] = []
    rejected: list[dict] = []
    raw_keys: set[str] = set()
    accepted = qualified = 0

    for i, sentence in enumerate(sentences, 1):
        added_items: list[str] = []
        added_stmt = None
        rej = None
        for cand in _candidates(sentence, llm, mock):
            subj = _resolve(cand["subj"])
            obj = _resolve(cand["obj"])
            raw_keys.add(subj["key"])
            raw_keys.add(obj["key"])
            # entity normalization (recognition happens regardless of validity)
            s_item = model.add_item(subj)
            o_item = model.add_item(obj)
            for it in (s_item, o_item):
                if it["id"] not in added_items:
                    added_items.append(it["id"])

            prop = cand["prop"]
            spec = PROPS.get(prop)
            qual = cand.get("qualifier") or {}
            if spec is not None:
                ok = (subj["type"] in spec["subj"]
                      and obj["type"] in spec["obj"])
                pid = spec["pid"]
            else:  # unknown property (real-LLM path): no constraint to enforce
                ok, pid = True, ""
            if not ok:
                rej = {"sentence": i, "edge": [s_item["id"], prop, o_item["id"]],
                       "src_type": subj["type"], "dst_type": obj["type"],
                       "reason": "violates Wikidata type/relation constraint"}
                rejected.append(rej)
                continue
            if model.add_statement(s_item["id"], prop, pid, o_item["id"], qual):
                accepted += 1
                if qual:
                    qualified += 1
                added_stmt = [s_item["id"], prop, o_item["id"]]

        steps.append({"step": i, "stage": "extract+normalize+validate",
                      "cq": sentence,
                      "added": {"items": added_items, "statement": added_stmt,
                                "rejected": rej},
                      "graph": model.to_graph()})

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "wikontic",
        "backend": llm.name,
        "input_sentences": len(sentences),
        "counts": {
            "raw_surface_forms": len(raw_keys),
            "canonical_entities": len(model.items),
            "merged": len(raw_keys) - len(model.items),
            "accepted_statements": accepted,
            "rejected_statements": len(rejected),
            "qualified_statements": qualified,
            "classes": len(model.classes),
        },
        "rejected": rejected,
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
