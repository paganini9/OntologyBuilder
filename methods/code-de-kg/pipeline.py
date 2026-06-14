"""CoDe-KG - triple extraction via coreference resolution + sentence complexity.

Method (Anuyah et al., EMNLP 2025 / arXiv 2509.17289, "CoDe-KG"):
free text is turned into a (subject, relation, object) knowledge graph through a
pipeline of coreference resolution -> sentence split/decomposition -> sentence
complexity classification (which selects the extraction prompt profile) -> triple
extraction -> KG merge. The paper routes per-complexity models (Mixtral, LLaMA)
and uses a fine-tuned BERT classifier; this implementation consolidates to a
single configurable backend and replaces the classifier with a deterministic
clause/conjunction-counting rule, so it runs with no GPU and no fine-tuning.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free-form body text; sentences are auto-split on . ! ?

Outputs (out_dir):
    ontology.ttl    - the triple-based OWL ontology (Turtle)
    ontology.json   - final graph as Cytoscape nodes/edges
    steps.json      - one snapshot per sentence, so the UI can show it being built
    manifest.json   - summary (backend, counts, file list)

The LLM step is abstracted: with a real backend (gemini/anthropic) the model
extracts triples; with MOCK a deterministic heuristic does, so the output is
reproducible and testable.
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

EX = "http://example.org/codekg#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "They", "These", "Those",
    "Their", "He", "She", "We", "I", "There", "Then", "Thus", "Both",
}

# Pronouns that the coreference rule resolves to the nearest preceding entity.
_PRONOUNS = {
    "it", "its", "they", "them", "their", "this", "that", "these", "those",
}

# relational verbs -> canonical relationship name (reused/extended from cqbycq)
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
    "drive": "drives", "drives": "drives", "driven": "drives",
    "cool": "cools", "cools": "cools",
    "control": "controls", "controls": "controls",
    "power": "powers", "powers": "powers",
    "monitor": "monitors", "monitors": "monitors",
    "regulate": "regulates", "regulates": "regulates",
    "circulate": "circulates", "circulates": "circulates",
    "connect": "connectsTo", "connects": "connectsTo",
    "feed": "feeds", "feeds": "feeds",
    "protect": "protects", "protects": "protects",
}


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _entities(sentence: str) -> list[str]:
    """Capitalized nouns (non-stopword) appearing in the sentence, in order."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", sentence):
        if t in _STOP:
            continue
        s = _singular(t)
        if s not in out:
            out.append(s)
    return out


def resolve_coreference(sentences: list[str]) -> list[tuple[str, bool]]:
    """Rule-based coreference: replace standalone pronouns with the nearest
    preceding capitalized entity. Returns (resolved_sentence, changed) per item.
    Deterministic: scans left-to-right, tracking the last seen entity."""
    last_entity: Optional[str] = None
    resolved: list[tuple[str, bool]] = []
    for sent in sentences:
        changed = False
        # entities present in this sentence so far (for after-replacement updates)
        tokens = re.findall(r"\w+|[^\w\s]", sent)
        out_tokens: list[str] = []
        running_entity = last_entity
        for tok in tokens:
            low = tok.lower()
            if low in _PRONOUNS and running_entity is not None:
                # Preserve possessive: "Its" -> "Motor's"; plain -> entity name.
                if low in ("its", "their"):
                    out_tokens.append(running_entity + "'s")
                else:
                    out_tokens.append(running_entity)
                changed = True
            else:
                out_tokens.append(tok)
                if re.fullmatch(r"[A-Z][a-zA-Z]+", tok) and tok not in _STOP:
                    running_entity = _singular(tok)
        # Re-join tokens with sensible spacing.
        text = ""
        for tok in out_tokens:
            if re.fullmatch(r"[^\w\s]", tok) or tok.startswith("'"):
                text += tok
            elif text and not text.endswith(("(", "[")):
                text += " " + tok
            else:
                text += tok
        resolved.append((text.strip(), changed))
        # carry forward the last entity seen in the (resolved) sentence
        ents = _entities(text)
        if ents:
            last_entity = ents[-1]
    return resolved


def classify_complexity(sentence: str) -> tuple[str, str]:
    """Deterministic stand-in for the BERT-Large complexity classifier.
    Returns (complexity_label, prompt_profile_name)."""
    low = sentence.lower()
    # subordinating markers -> dependent clause(s) present
    subords = len(re.findall(
        r"\b(which|that|because|when|while|although|since|if|where|who)\b", low))
    # coordinating conjunctions -> independent clauses joined
    coords = len(re.findall(r"\b(and|but|or|so|yet)\b", low))
    commas = sentence.count(",")

    has_dep = subords > 0
    has_coord = coords > 0 or commas > 0

    if has_dep and has_coord:
        label = "compound-complex"
    elif has_dep:
        label = "complex"
    elif has_coord:
        label = "compound"
    else:
        label = "simple"

    profile = {
        "simple": "direct-extract",
        "compound": "split-conjuncts-fewshot",
        "complex": "clause-decompose-cot",
        "compound-complex": "decompose-cot-fewshot",
    }[label]
    return label, profile


def _decompose(sentence: str) -> list[str]:
    """Split a (resolved) sentence into simpler clauses for one-fact extraction.
    Splits on coordinating conjunctions and relative markers, deterministically."""
    # normalise the relative pronoun "which/that" into clause boundaries
    parts = re.split(r"\s*,\s*|\s+\band\b\s+|\s+\bwhich\b\s+|\s+\bthat\b\s+",
                     sentence)
    clauses = [p.strip(" .") for p in parts if p.strip(" .")]
    return clauses or [sentence]


def _extract_triples_from_clause(clause: str, carry_subject: Optional[str]) -> list[dict]:
    """Subject (capitalized noun) - relation verb - object (capitalized noun).
    If a clause has no explicit subject (e.g. a relative clause), reuse the
    carried subject from the main clause."""
    ents = _entities(clause)
    words = re.findall(r"[a-zA-Z]+", clause.lower())
    class_words = {e.lower() for e in ents} | {e.lower() + "s" for e in ents}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    triples: list[dict] = []
    if rel is None:
        return triples
    if len(ents) >= 2:
        triples.append({"entity_1": ents[0], "relationship": rel,
                        "entity_2": ents[1]})
    elif len(ents) == 1 and carry_subject and ents[0] != carry_subject:
        triples.append({"entity_1": carry_subject, "relationship": rel,
                        "entity_2": ents[0]})
    return triples


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM triple extractor.

    Parses the (coreference-resolved) sentence carried in the prompt, decomposes
    it into clauses, and returns a JSON list of {entity_1, relationship,
    entity_2} triples."""
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    main_ents = _entities(sentence)
    carry = main_ents[0] if main_ents else None
    triples: list[dict] = []
    for clause in _decompose(sentence):
        for tr in _extract_triples_from_clause(clause, carry):
            if tr not in triples:
                triples.append(tr)
    return json.dumps({"triples": triples}, ensure_ascii=False)


_PROMPT = (
    "You are a knowledge-graph extractor. Using the {profile} prompt profile for "
    "a {complexity} sentence, extract every (entity_1, relationship, entity_2) "
    "fact. Return ONLY JSON: {{\"triples\": [{{\"entity_1\":..., "
    "\"relationship\":..., \"entity_2\":...}}]}}.\n"
    "Sentence: {sentence}\n"
)


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    lines = []
    for line in f.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            lines.append(s)
    return " ".join(lines)


class _Model:
    """Accumulated triple-based graph, in insertion order for deterministic output."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []      # {name, domain, range}
        self.data_props: list[dict] = []     # always empty here; kept for schema parity
        self.triples: list[tuple[str, str, str]] = []

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

    def add_triple(self, s: str, r: str, o: str) -> None:
        t = (s, r, o)
        if t not in self.triples:
            self.triples.append(t)

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

    # entities as both owl:Class and a named individual instance of that class,
    # so the asserted triples connect real resources.
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
        g.add((EXN[c + "_ind"], RDF.type, OWL.NamedIndividual))
        g.add((EXN[c + "_ind"], RDF.type, EXN[c]))

    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))

    # assert each extracted triple between the individuals
    for s, r, o in model.triples:
        g.add((EXN[s + "_ind"], EXN[r], EXN[o + "_ind"]))

    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_text(input_dir)

    raw_sentences = _split_sentences(text)
    resolved = resolve_coreference(raw_sentences)

    model = _Model()
    steps = []
    for i, ((sentence, changed), raw) in enumerate(zip(resolved, raw_sentences), 1):
        complexity, profile = classify_complexity(sentence)
        prompt = _PROMPT.format(profile=profile, complexity=complexity,
                                sentence=sentence)
        raw_out = llm.complete(prompt, temperature=0.0,
                               json_schema={"type": "object"})
        try:
            parsed = json.loads(raw_out)
            triples = parsed.get("triples", parsed) if isinstance(parsed, dict) \
                else parsed
        except json.JSONDecodeError:
            triples = []

        added_c, added_o = [], []
        for tr in triples:
            s = _singular(str(tr.get("entity_1", "")).strip())
            r = str(tr.get("relationship", "")).strip()
            o = _singular(str(tr.get("entity_2", "")).strip())
            if not (s and r and o):
                continue
            if model.add_class(s):
                added_c.append(s)
            if model.add_class(o):
                added_c.append(o)
            prop = {"name": r, "domain": s, "range": o}
            if model.add_obj(prop):
                added_o.append(prop)
            model.add_triple(s, r, o)

        steps.append({
            "step": i,
            "cq": sentence,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": []},
            "graph": model.to_graph(),
            # method-specific diagnostics (extra keys are ignored by the frontend)
            "coref": {"raw": raw, "resolved": sentence, "changed": changed},
            "complexity": complexity,
            "prompt_profile": profile,
        })

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "code-de-kg",
        "backend": llm.name,
        "input_sentences": len(raw_sentences),
        "coref_resolved": sum(1 for _, ch in resolved if ch),
        "counts": {
            "entities": len(model.classes),
            "relations": len(model.obj_props),
            "triples": len(model.triples),
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
