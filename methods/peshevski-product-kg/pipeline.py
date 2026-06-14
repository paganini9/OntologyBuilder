"""Peshevski Product KG - AI-agent-driven product knowledge graph (3 agents).

Method (Peshevski, Stojanov, Trajanov, GOBLIN Workshop 2025 / arXiv:2511.11017,
*An AI Agent-Driven Framework for Automated Product Knowledge Graph Construction
in E-Commerce*): with no predefined schema, three dedicated LLM agents build a
product KG from product-description text:

    Stage 1  creation/expansion (per product) - extract classes / object
             properties / data properties from each description and grow an
             accumulated SCHEMA model.                                  -> N steps
    Stage 2  refinement (one pass) - merge case/plural-variant duplicate
             classes and standardize names (ontogenia-style deterministic
             rules).                                                    -> 1 step
    Stage 3  population (per product) - instantiate each product as an
             individual of its main class, attaching extracted specs as
             data-property values and parts/relations as object links.  -> N steps

So steps.json holds N + 1 + N = 2*N + 1 snapshots for N products.

Contract (shared by every method in this project):
    run(input_dir, out_dir, backend=None) -> manifest dict

Inputs  (input_dir):
    product_descriptions.txt  - one product description per line
                                (blank lines / # comments ignored)

Outputs (out_dir):
    ontology.ttl    - schema (classes/properties) + individuals, OWL (Turtle)
    ontology.json   - final graph (class + individual nodes) as Cytoscape json
    steps.json      - per-stage snapshots (expansion / refinement / population)
    manifest.json   - summary (backend, counts, file list)

The MOCK backend keeps everything deterministic so the golden fixtures are stable.
With a real backend (gemini/anthropic) the three agents run on an LLM; with no
key it auto-falls back to MOCK.
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

EX = "http://example.org/product#"

_STOP = {
    "What", "Which", "Who", "Where", "When", "How", "Why", "Is", "Are", "Does",
    "Do", "Can", "The", "A", "An", "Of", "For", "And", "Or", "To", "In", "On",
    "By", "With", "That", "This", "Each", "Its", "It", "From", "At",
}

# relational verbs -> canonical object-property name (reused from cqbycq, plus
# product-domain relations like "powered/cooled/driven").
_REL = {
    "consist": "consistsOf", "consists": "consistsOf",
    "made": "madeOf", "compose": "composedOf", "composed": "composedOf",
    "has": "has", "have": "has", "having": "has",
    "produce": "produces", "produces": "produces", "produced": "produces",
    "require": "requires", "requires": "requires", "required": "requires",
    "contain": "contains", "contains": "contains",
    "use": "uses", "uses": "uses", "used": "uses", "using": "uses",
    "belong": "belongsTo", "belongs": "belongsTo",
    "part": "partOf",
    "include": "includes", "includes": "includes", "including": "includes",
    "perform": "performs", "performs": "performs",
    "satisfy": "satisfies", "satisfies": "satisfies",
    "supply": "supplies", "supplies": "supplies",
    "assemble": "assembledFrom", "assembled": "assembledFrom",
    "power": "poweredBy", "powered": "poweredBy",
    "drive": "drivenBy", "driven": "drivenBy",
    "cool": "cools", "cools": "cools", "cooled": "cools",
    "feature": "features", "features": "features", "featuring": "features",
}

# spec keywords -> data property (extends cqbycq's _DATA with product specs).
_DATA = {
    "name", "id", "identifier", "weight", "price", "cost", "color", "colour",
    "size", "dimension", "dimensions", "quantity", "length", "width", "height",
    "code", "version", "tolerance",
    # product / e-commerce specs
    "voltage", "capacity", "power", "wattage", "efficiency", "rating",
    "warranty", "material", "speed", "frequency", "pressure", "flow",
    "temperature", "noise", "current", "model",
}

# Spec values that may follow a keyword in a description, captured for population.
# e.g. "220 voltage", "1.5 capacity", "9000 power", "white color".
_SPEC_VALUE = re.compile(
    r"(?P<val>[A-Za-z0-9.]+)\s+(?P<key>"
    + "|".join(sorted(_DATA, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def _singular(w: str) -> str:
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _extract_classes(text: str) -> list[str]:
    out: list[str] = []
    for t in re.findall(r"\b[A-Z][a-zA-Z]+\b", text):
        if t in _STOP:
            continue
        if t not in out:
            out.append(t)
    return out


def mock_responder(prompt: str) -> str:
    """Deterministic stand-in for the LLM creation/expansion agent.

    Parse ONE product description -> ontology fragment JSON. The first
    capitalized noun is treated as the product's main class. Refinement and
    population are handled deterministically inside `run()`.
    """
    desc = prompt.split("Product description:")[-1].split("\n")[0].strip()
    classes = _extract_classes(desc)
    words = re.findall(r"[a-zA-Z]+", desc.lower())

    class_words = {c.lower() for c in classes} | {c.lower() + "s" for c in classes}
    rel = next((_REL[w] for w in words if w in _REL and w not in class_words), None)
    object_properties = []
    if rel and len(classes) >= 2:
        object_properties.append(
            {"name": rel, "domain": classes[0], "range": classes[1]}
        )

    data_properties = []
    if classes:
        for w in words:
            if w in _DATA:
                dp = {"name": w, "domain": classes[0], "datatype": "string"}
                if dp not in data_properties:
                    data_properties.append(dp)

    return json.dumps(
        {
            "main_class": classes[0] if classes else "",
            "classes": classes,
            "object_properties": object_properties,
            "data_properties": data_properties,
        },
        ensure_ascii=False,
    )


_PROMPT = (
    "You are the ontology creation/expansion agent for a product knowledge "
    "graph. Read ONE product description and extract an ontology fragment. "
    "Return ONLY JSON with keys: main_class (the product's primary class, "
    "PascalCase), classes (list of PascalCase class names incl. parts), "
    "object_properties (list of {{name, domain, range}}), data_properties "
    "(list of {{name, domain, datatype}}).\n"
    "Product description: {desc}\n"
)


def _read_products(input_dir: Path) -> list[str]:
    f = input_dir / "product_descriptions.txt"
    if not f.exists():
        raise FileNotFoundError(f"missing input: {f}")
    products = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            products.append(line)
    return products


# --- refinement helpers (deterministic, ontogenia-style) --------------------

# Irregular / hard plurals the naive `_singular` misses, mapping to canonical.
_IRREGULAR = {
    "Compressors": "Compressor",
    "Batteries": "Battery", "Batterie": "Battery",
    "Properties": "Property", "Propertie": "Property",
    "Categories": "Category", "Categorie": "Category",
    "Companies": "Company", "Companie": "Company",
    "Accessories": "Accessory", "Accessorie": "Accessory",
}


def _norm_key(name: str) -> str:
    """Canonical comparison key: lower-cased, naive-singularized, irregular-aware."""
    fixed = _IRREGULAR.get(name, name)
    return _singular(fixed.lower())


def _canonical_name(name: str) -> str:
    """Preferred display form of a class (irregular-plural -> singular)."""
    return _IRREGULAR.get(name, name)


class _Model:
    """Accumulated ontology (schema + individuals), insertion-ordered."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.obj_props: list[dict] = []
        self.data_props: list[dict] = []
        # individuals: {id, label, cls, data: {prop: value}, links: [{name, target}]}
        self.individuals: list[dict] = []

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

    def add_data(self, p: dict) -> bool:
        if p not in self.data_props:
            self.data_props.append(p)
            return True
        return False

    def add_individual(self, ind: dict) -> None:
        self.individuals.append(ind)

    def find_match(self, name: str) -> Optional[str]:
        """Return an existing class that is a case/plural variant of `name`."""
        key = _norm_key(name)
        for c in self.classes:
            if _norm_key(c) == key:
                return c
        return None

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

        # individual nodes (type "individual") + their typing/links/data attrs
        for ind in self.individuals:
            ind_attrs = [f"{k}={v}" for k, v in ind["data"].items()]
            nodes.append({"data": {
                "id": ind["id"], "label": ind["label"], "type": "individual",
                "attributes": ind_attrs,
            }})
            # instanceOf edge to its class
            edges.append({"data": {
                "id": f"{ind['id']}-instanceOf-{ind['cls']}",
                "source": ind["id"], "target": ind["cls"], "label": "instanceOf",
            }})
            for link in ind["links"]:
                edges.append({"data": {
                    "id": f"{ind['id']}-{link['name']}-{link['target']}",
                    "source": ind["id"], "target": link["target"],
                    "label": link["name"],
                }})
        return {"nodes": nodes, "edges": edges}


def _to_ttl(model: _Model) -> str:
    from rdflib import Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef

    g = Graph()
    EXN = Namespace(EX)
    g.bind("ex", EXN)
    g.bind("owl", OWL)
    onto = URIRef(EX.rstrip("#"))
    g.add((onto, RDF.type, OWL.Ontology))

    # --- schema ---
    for c in model.classes:
        g.add((EXN[c], RDF.type, OWL.Class))
    for p in model.obj_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.ObjectProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, EXN[p["range"]]))
    for p in model.data_props:
        pr = EXN[p["name"]]
        g.add((pr, RDF.type, OWL.DatatypeProperty))
        g.add((pr, RDFS.domain, EXN[p["domain"]]))
        g.add((pr, RDFS.range, XSD.string))

    # --- individuals ---
    for ind in model.individuals:
        iri = EXN[ind["id"]]
        g.add((iri, RDF.type, OWL.NamedIndividual))
        g.add((iri, RDF.type, EXN[ind["cls"]]))
        g.add((iri, RDFS.label, Literal(ind["label"])))
        for k, v in ind["data"].items():
            g.add((iri, EXN[k], Literal(v)))
        for link in ind["links"]:
            g.add((iri, EXN[link["name"]], EXN[link["target"]]))
    return g.serialize(format="turtle")


def _merge_fragment(model: _Model, frag: dict) -> tuple[list, list, list]:
    """Fold a creation fragment into the model; return newly added items."""
    added_c, added_o, added_d = [], [], []
    for c in frag.get("classes", []):
        if model.add_class(c):
            added_c.append(c)
    for p in frag.get("object_properties", []):
        for k in ("domain", "range"):
            if model.add_class(p.get(k, "")):
                added_c.append(p[k])
        if model.add_obj(p):
            added_o.append(p)
    for p in frag.get("data_properties", []):
        if model.add_class(p.get("domain", "")):
            added_c.append(p["domain"])
        if model.add_data(p):
            added_d.append(p)
    return added_c, added_o, added_d


def _refine(model: _Model) -> dict:
    """Stage 2 refinement: merge case/plural-variant duplicate classes into a
    single canonical class and standardize irregular-plural names. Rewrites the
    class list and all property domains/ranges. Returns a change log."""
    # Build rename map: each class -> its canonical surviving name.
    rename: dict[str, str] = {}
    survivors: list[str] = []
    by_key: dict[str, str] = {}
    for c in model.classes:
        key = _norm_key(c)
        if key in by_key:
            # duplicate variant -> merge into the first-seen survivor
            rename[c] = by_key[key]
        else:
            canon = _canonical_name(c)
            survivors.append(canon)
            by_key[key] = canon
            if canon != c:
                rename[c] = canon

    merged = [{"from": k, "into": v} for k, v in rename.items()
              if _norm_key(k) == _norm_key(v) and k != v
              and k in {x for x in model.classes}]
    # Distinguish a pure rename (standardize) vs. merge-into-existing.
    merges, renames = [], []
    for old, new in rename.items():
        # was there already another class with that canonical key before `old`?
        idx_old = model.classes.index(old)
        prior = [c for c in model.classes[:idx_old] if _norm_key(c) == _norm_key(old)]
        if prior:
            merges.append({"from": old, "into": new})
        else:
            renames.append({"from": old, "to": new})

    if not rename:
        return {"merged": [], "renamed": []}

    # apply: classes (dedup, preserve order)
    new_classes: list[str] = []
    for c in model.classes:
        nc = rename.get(c, c)
        if nc not in new_classes:
            new_classes.append(nc)
    model.classes = new_classes

    # apply to object/data properties
    new_obj: list[dict] = []
    for p in model.obj_props:
        p = dict(p)
        p["domain"] = rename.get(p["domain"], p["domain"])
        p["range"] = rename.get(p["range"], p["range"])
        if p not in new_obj:
            new_obj.append(p)
    model.obj_props = new_obj

    new_data: list[dict] = []
    for p in model.data_props:
        p = dict(p)
        p["domain"] = rename.get(p["domain"], p["domain"])
        if p not in new_data:
            new_data.append(p)
    model.data_props = new_data

    return {"merged": merges, "renamed": renames, "rename_map": rename}


def _extract_spec_values(desc: str) -> dict:
    """Pull data-property values out of a description, e.g. '220 voltage'."""
    out: dict[str, str] = {}
    for m in _SPEC_VALUE.finditer(desc):
        key = m.group("key").lower()
        if key not in out:
            out[key] = m.group("val")
    return out


def run(input_dir, out_dir, backend: Optional[str] = None) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = get_backend(backend, mock_responder=mock_responder)
    products = _read_products(input_dir)

    model = _Model()
    steps = []
    step_no = 0

    # ---- Stage 1: creation / expansion (one step per product) --------------
    frags: list[dict] = []
    for desc in products:
        raw = llm.complete(_PROMPT.format(desc=desc), temperature=0.0,
                           json_schema={"type": "object"})
        try:
            frag = json.loads(raw)
        except json.JSONDecodeError:
            frag = {"main_class": "", "classes": [],
                    "object_properties": [], "data_properties": []}
        frags.append(frag)

        added_c, added_o, added_d = _merge_fragment(model, frag)
        step_no += 1
        steps.append({
            "step": step_no,
            "cq": desc,
            "added": {"classes": added_c, "object_properties": added_o,
                      "data_properties": added_d},
            "graph": model.to_graph(),
        })

    # ---- Stage 2: refinement (one pass) ------------------------------------
    changes = _refine(model)
    rename_map: dict = changes.pop("rename_map", {})
    step_no += 1
    steps.append({
        "step": step_no,
        "cq": "(refinement)",
        "added": {"classes": [], "object_properties": [], "data_properties": [],
                  "merged": changes["merged"], "renamed": changes["renamed"]},
        "graph": model.to_graph(),
    })

    # ---- Stage 3: population (one step per product) ------------------------
    def _canon(name: str) -> str:
        return rename_map.get(name, _canonical_name(name))

    for idx, (desc, frag) in enumerate(zip(products, frags), 1):
        main = frag.get("main_class") or (
            frag.get("classes") or [""])[0]
        main = _canon(main)
        if not main:
            # no extractable class -> skip individual but still emit a step
            step_no += 1
            steps.append({
                "step": step_no, "cq": f"(populate) {desc}",
                "added": {"classes": [], "object_properties": [],
                          "data_properties": [], "individuals": []},
                "graph": model.to_graph(),
            })
            continue

        ind_id = f"{main}_{idx}"
        data_vals = _extract_spec_values(desc)
        # keep only data values whose key is a declared data property
        declared = {dp["name"] for dp in model.data_props}
        data_vals = {k: v for k, v in data_vals.items() if k in declared}

        # object links: connect the individual to the OTHER classes it mentions
        links = []
        frag_classes = [_canon(c) for c in frag.get("classes", [])]
        for p in frag.get("object_properties", []):
            tgt = _canon(p.get("range", ""))
            if tgt and tgt != main:
                link = {"name": p["name"], "target": tgt}
                if link not in links:
                    links.append(link)

        individual = {
            "id": ind_id, "label": desc[:48], "cls": main,
            "data": data_vals, "links": links,
        }
        model.add_individual(individual)

        step_no += 1
        steps.append({
            "step": step_no,
            "cq": f"(populate) {desc}",
            "added": {
                "classes": [], "object_properties": [], "data_properties": [],
                "individuals": [{"id": ind_id, "class": main,
                                 "data": data_vals, "links": links}],
            },
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
        "method": "peshevski-product-kg",
        "backend": llm.name,
        "input_products": len(products),
        "steps": len(steps),
        "counts": {
            "classes": len(model.classes),
            "object_properties": len(model.obj_props),
            "data_properties": len(model.data_props),
            "individuals": len(model.individuals),
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
