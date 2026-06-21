"""ANCHOR - schema-agnostic CTI knowledge graph construction via hybrid
ontology discovery.

Method (ANCHOR: Schema-Agnostic Knowledge Graph Construction via Hybrid
Ontology Discovery for Cyber Threat Intelligence, arXiv:2606.01208, Kim et al.):
classical CTI pipelines need a schema-specific prompt per ontology (UCO, STIX,
MALOnt). ANCHOR instead **discovers** the right ontology class via a
search-and-navigate walk over the schema tree (instead of dumping the whole
schema in the prompt), then **validates** the assigned type with SHACL-style
constraints. The result is the same code path across multiple schemas.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    text.txt  - free CTI body text (split into sentences by . ! ?)

Outputs (out_dir):
    ontology.ttl    - OWL: instances typed by rdf:type with class hierarchy
    ontology.json   - final graph as Cytoscape nodes/edges (entity instances
                      + their type edges + relation edges, schema-tagged)
    steps.json      - one snapshot per sentence (the UI replays the discovery)
    manifest.json   - summary (backend, counts, schema used, SHACL stats)

Three faithful, deterministic-on-MOCK ingredients per sentence:
    * extract candidate entities (PascalCase tokens + value patterns);
    * **hybrid ontology discovery** = lexical-first search of the schema
      catalogue, then *navigate* up/down the class tree (siblings via parent,
      ancestors via subClassOf) until a class accepts the entity, falling back
      to the most specific applicable superclass when no leaf matches;
    * **SHACL-style validation**: each class has 1+ structural constraint
      (pattern/required-property). Entities that fail are demoted to the
      validated superclass and flagged `shacl_demoted=true`.

Schema-agnostic: the same logic runs on the built-in UCO / STIX / MALOnt mini
schemas (selected via `LLM_SCHEMA` env or the default `uco`). With a real
backend the model picks the seed class; the navigate/validate stages are
identical, so the graph stays stable.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

_IMPL_ROOT = Path(__file__).resolve().parents[2]
if str(_IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPL_ROOT))

from backend.llm import get_backend  # noqa: E402
from backend.llm.extract import is_mock  # noqa: E402

EX = "http://example.org/cti#"

# ---- Built-in mini schemas (UCO/STIX/MALOnt-style, deliberately small) ----
# Each schema is a tree: child -> parent. SHACL rule = a callable constraint on
# the entity's name/value. Aliases are extra lexical cues for the discovery.
_SCHEMAS = {
    "uco": {
        "name": "UCO",
        "root": "Entity",
        "tree": {
            "Actor": "Entity",
            "ThreatActor": "Actor",
            "Malware": "Entity",
            "Trojan": "Malware",
            "Ransomware": "Malware",
            "Vulnerability": "Entity",
            "Indicator": "Entity",
            "IPAddress": "Indicator",
            "Domain": "Indicator",
            "FileHash": "Indicator",
            "Tool": "Entity",
            "System": "Entity",
        },
        "aliases": {
            "ThreatActor": ["apt", "actor", "group"],
            "Ransomware": ["ransomware"],
            "Trojan": ["trojan"],
            "Malware": ["malware", "strain"],
            "Vulnerability": ["cve", "vulnerability"],
            "IPAddress": ["ipaddress", "ip"],
            "Domain": ["domain"],
            "FileHash": ["filehash", "hash"],
            "Tool": ["tool"],
            "System": ["system", "server"],
            "Indicator": ["indicator", "ioc"],
        },
        # SHACL-style: a value pattern OR `True` (no value constraint).
        "shacl": {
            "Vulnerability": re.compile(r"^CVE-\d{4}-\d{4,}$", re.I),
            "IPAddress": re.compile(
                r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),
            "Domain": re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.I),
            "FileHash": re.compile(r"^[0-9a-f]{32,64}$", re.I),
        },
    },
    "stix": {
        "name": "STIX",
        "root": "STIXObject",
        "tree": {
            "ThreatActor": "STIXObject",
            "Malware": "STIXObject",
            "Vulnerability": "STIXObject",
            "Indicator": "STIXObject",
            "Tool": "STIXObject",
        },
        "aliases": {
            "ThreatActor": ["apt", "actor"],
            "Malware": ["ransomware", "trojan", "malware", "strain"],
            "Vulnerability": ["cve", "vulnerability"],
            "Indicator": ["ipaddress", "ip", "domain", "filehash", "hash",
                          "indicator", "ioc"],
            "Tool": ["tool"],
        },
        "shacl": {
            "Vulnerability": re.compile(r"^CVE-\d{4}-\d{4,}$", re.I),
        },
    },
    "malont": {
        "name": "MALOnt",
        "root": "MalOntEntity",
        "tree": {
            "ThreatActor": "MalOntEntity",
            "Malware": "MalOntEntity",
            "Ransomware": "Malware",
            "Trojan": "Malware",
            "Vulnerability": "MalOntEntity",
            "Indicator": "MalOntEntity",
            "Target": "MalOntEntity",
        },
        "aliases": {
            "ThreatActor": ["apt", "actor"],
            "Ransomware": ["ransomware"],
            "Trojan": ["trojan"],
            "Malware": ["malware", "strain"],
            "Vulnerability": ["cve", "vulnerability"],
            "Indicator": ["ipaddress", "ip", "domain", "filehash", "hash"],
            "Target": ["target", "system", "server", "org"],
        },
        "shacl": {
            "Vulnerability": re.compile(r"^CVE-\d{4}-\d{4,}$", re.I),
        },
    },
}

# Relation verbs we recognise in CTI text.
_REL = {
    "deploy": "deploys", "deployed": "deploys", "deploys": "deploys",
    "exfiltrate": "exfiltrates", "exfiltrates": "exfiltrates",
    "affect": "affects", "affects": "affects",
    "host": "hosts", "hosts": "hosts",
    "exploit": "exploits", "exploits": "exploits",
    "use": "uses", "uses": "uses",
    "associate": "associatedWith", "associated": "associatedWith",
    "target": "targets", "targets": "targets",
    "drop": "drops", "drops": "drops",
}

_STOP = {
    "The", "A", "An", "This", "That", "These", "Those", "Of", "In", "On",
    "For", "And", "Or", "With", "By", "To", "Using", "Against",
}


def _caps(text: str) -> list[str]:
    """PascalCase / ALLCAPS tokens, in order, deduped."""
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][A-Za-z0-9_]+\b", text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def _values(text: str) -> list[str]:
    """Pull out indicator values (IP / hash / domain / CVE) verbatim."""
    out: list[str] = []
    for pat in (
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",     # IPv4
        r"\bCVE-\d{4}-\d{4,}\b",                       # CVE id
        r"\b[0-9a-fA-F]{32,64}\b",                     # md5/sha
        r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b",             # domain
    ):
        for v in re.findall(pat, text):
            if v not in out:
                out.append(v)
    return out


# ---------- Hybrid ontology discovery ----------
def _ancestors(schema: dict, cls: str) -> list[str]:
    chain = [cls]
    cur = cls
    while cur in schema["tree"]:
        cur = schema["tree"][cur]
        chain.append(cur)
    return chain


def _seed_class(schema: dict, token: str) -> Optional[str]:
    """Lexical-first match: explicit alias > class-name substring."""
    low = token.lower().strip("_-")
    for cls, aliases in schema["aliases"].items():
        for a in aliases:
            if low == a or a in low:
                return cls
    for cls in schema["tree"]:
        if cls.lower() == low or cls.lower() in low:
            return cls
    if low == schema["root"].lower():
        return schema["root"]
    return None


def _validate(schema: dict, cls: str, value: str) -> bool:
    """SHACL-style structural constraint check; True = satisfied."""
    rule = schema.get("shacl", {}).get(cls)
    if rule is None:
        return True
    return bool(rule.fullmatch(value))


def _discover(schema: dict, token: str, value: str) -> dict:
    """search-and-navigate over the schema tree, then SHACL-validate.

    Returns {"class","path","seed","shacl_demoted","root_only"}.
    `path` records the navigation steps (seed class + climbed ancestors).
    """
    seed = _seed_class(schema, token)
    if seed is None:
        # navigate up from the root only -> most general
        return {"class": schema["root"], "path": [schema["root"]],
                "seed": None, "shacl_demoted": False, "root_only": True}

    chain = _ancestors(schema, seed)
    val = value or token
    # walk the chain (seed -> root), pick the most specific that validates
    for cls in chain:
        if _validate(schema, cls, val):
            return {"class": cls, "path": chain[: chain.index(cls) + 1],
                    "seed": seed, "shacl_demoted": (cls != seed),
                    "root_only": False}
    return {"class": schema["root"], "path": chain + [schema["root"]],
            "seed": seed, "shacl_demoted": True, "root_only": False}


# ---------- Relation extraction ----------
def _relation(sentence: str, entities: list[dict]) -> Optional[dict]:
    if len(entities) < 2:
        return None
    low = sentence.lower()
    words = re.findall(r"[a-zA-Z]+", low)
    for w in words:
        if w in _REL:
            return {"subject": entities[0]["name"], "relation": _REL[w],
                    "object": entities[1]["name"]}
    return None


# ---------- LLM bridge ----------
def mock_responder(prompt: str) -> str:
    """Deterministic stand-in: return the list of candidate entity tokens."""
    sentence = prompt.split("Sentence:")[-1].split("\n")[0].strip()
    tokens = _caps(sentence) + _values(sentence)
    return json.dumps({"candidates": tokens}, ensure_ascii=False)


_PROMPT = (
    "You extract candidate CTI entities for ontology discovery. "
    "Return ONLY JSON of the form {{\"candidates\":[\"...\",...]}}. "
    "Include CTI value tokens (IP, CVE id, hash, domain) verbatim. "
    "Sentence: {sentence}\n"
)


def _read_text(input_dir: Path) -> str:
    f = input_dir / "text.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("#")]
    return "\n".join(lines)


def _split_sentences(text: str) -> list[str]:
    # Split on sentence terminators that are followed by whitespace/end (not on
    # dots inside IPs, CVE ids, domains, or hashes).
    out = [p.strip() for p in re.split(r"[.!?]+(?=\s|$)", text) if p.strip()]
    return out


# ---------- Graph model ----------
class _Model:
    def __init__(self, schema: dict) -> None:
        self.schema = schema
        self.classes: list[str] = []        # ontology classes touched
        self.instances: list[dict] = []     # {name, class, schema, path, value}
        self.relations: list[dict] = []     # {s, r, o, source}
        self.subclass: list[tuple[str, str]] = []  # (child, parent)

    def add_class(self, c: str) -> None:
        if c and c not in self.classes:
            self.classes.append(c)
        # also record the full subClassOf chain so the graph shows hierarchy
        for child in list(self.schema["tree"]):
            if child == c:
                parent = self.schema["tree"][c]
                if parent not in self.classes:
                    self.classes.append(parent)
                if (child, parent) not in self.subclass:
                    self.subclass.append((child, parent))

    def add_instance(self, name: str, cls: str, path: list[str],
                     value: str, shacl_demoted: bool, source: int) -> bool:
        for i in self.instances:
            if i["name"] == name:
                return False
        self.instances.append({"name": name, "class": cls,
                               "schema": self.schema["name"], "path": path,
                               "value": value, "shacl_demoted": shacl_demoted,
                               "source": source})
        self.add_class(cls)
        # also record any ancestor links so the type chain is visible
        cur = cls
        while cur in self.schema["tree"]:
            parent = self.schema["tree"][cur]
            if parent not in self.classes:
                self.classes.append(parent)
            if (cur, parent) not in self.subclass:
                self.subclass.append((cur, parent))
            cur = parent
        return True

    def add_relation(self, r: dict) -> bool:
        if r in self.relations:
            return False
        self.relations.append(r)
        return True

    def to_graph(self) -> dict:
        nodes = [{"data": {"id": c, "label": c, "type": "class",
                           "attributes": []}} for c in self.classes]
        for i in self.instances:
            nodes.append({"data": {
                "id": i["name"], "label": i["name"], "type": "instance",
                "schema": i["schema"], "value": i["value"],
                "shacl_demoted": i["shacl_demoted"], "attributes": []}})
        edges = []
        for i in self.instances:
            edges.append({"data": {
                "id": f"{i['name']}-type-{i['class']}",
                "source": i["name"], "target": i["class"], "label": "type",
                "schema": i["schema"], "provenance": i["source"]}})
        for child, parent in self.subclass:
            edges.append({"data": {
                "id": f"{child}-subClassOf-{parent}",
                "source": child, "target": parent, "label": "subClassOf",
                "schema": self.schema["name"], "provenance": 0}})
        for r in self.relations:
            edges.append({"data": {
                "id": f"{r['subject']}-{r['relation']}-{r['object']}",
                "source": r["subject"], "target": r["object"],
                "label": r["relation"], "schema": self.schema["name"],
                "provenance": r["source"]}})
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
    for child, parent in model.subclass:
        g.add((EXN[child], RDFS.subClassOf, EXN[parent]))
    for i in model.instances:
        g.add((EXN[i["name"]], RDF.type, EXN[i["class"]]))
    seen = set()
    for r in model.relations:
        pr = r["relation"]
        if pr not in seen:
            g.add((EXN[pr], RDF.type, OWL.ObjectProperty))
            seen.add(pr)
        g.add((EXN[r["subject"]], EXN[pr], EXN[r["object"]]))
    return g.serialize(format="turtle")


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    schema_key = (os.getenv("LLM_SCHEMA") or "uco").strip().lower()
    if schema_key not in _SCHEMAS:
        schema_key = "uco"
    schema = _SCHEMAS[schema_key]

    llm = get_backend(backend, mock_responder=mock_responder)
    text = _read_text(input_dir)
    sentences = _split_sentences(text)

    mock = is_mock(llm)
    model = _Model(schema)
    steps: list[dict] = []
    shacl_passes = 0
    shacl_demotions = 0

    for i, sent in enumerate(sentences, 1):
        # LLM seeds the candidate list, then deterministic
        # search-and-navigate + SHACL validate.
        added_instances, added_rels = [], []
        if mock:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0,
                               json_schema={"type": "object"})
        else:
            raw = llm.complete(_PROMPT.format(sentence=sent), temperature=0.0)
        try:
            cands = json.loads(raw).get("candidates", [])
        except json.JSONDecodeError:
            cands = _caps(sent) + _values(sent)
        # Pair each token with a value (IP/CVE/hash/domain) if present
        values = _values(sent)
        # Match values to nearest token: if it's already a value, value=itself
        sent_entities = []
        for tok in cands:
            if tok in values:
                disc = _discover(schema, tok, tok)
                name = tok
            else:
                # token like "IPAddress" pairs with first IP in sentence
                # so the SHACL pattern actually has something to validate.
                paired = ""
                for v in values:
                    if _validate(schema, _seed_class(schema, tok) or "", v):
                        paired = v
                        break
                disc = _discover(schema, tok, paired or tok)
                name = tok
            ok = model.add_instance(name=name, cls=disc["class"],
                                    path=disc["path"],
                                    value=(name if name in values else ""),
                                    shacl_demoted=disc["shacl_demoted"],
                                    source=i)
            if ok:
                added_instances.append({"name": name, "class": disc["class"],
                                        "path": disc["path"],
                                        "seed": disc["seed"],
                                        "shacl_demoted": disc["shacl_demoted"]})
                if disc["shacl_demoted"]:
                    shacl_demotions += 1
                else:
                    shacl_passes += 1
            sent_entities.append({"name": name})

        rel = _relation(sent, sent_entities)
        if rel is not None:
            rel["source"] = i
            if model.add_relation(rel):
                added_rels.append(rel)

        steps.append({"step": i, "stage": "discover", "cq": sent,
                      "added": {"instances": added_instances,
                                "relations": added_rels},
                      "graph": model.to_graph()})

    graph = model.to_graph()
    ttl = _to_ttl(model)

    (out_dir / "ontology.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "steps.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "ontology.ttl").write_text(ttl, encoding="utf-8")

    manifest = {
        "method": "anchor-cti",
        "backend": llm.name,
        "schema": schema["name"],
        "input_sentences": len(sentences),
        "counts": {
            "classes": len(model.classes),
            "instances": len(model.instances),
            "relations": len(model.relations),
            "subclass_of": len(model.subclass),
        },
        "shacl": {"passes": shacl_passes, "demotions": shacl_demotions},
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
    print(json.dumps(run(a.input_dir, a.out_dir, a.backend),
                     ensure_ascii=False))
 