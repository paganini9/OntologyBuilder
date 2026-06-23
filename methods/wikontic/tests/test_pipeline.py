"""Tests for the Wikontic pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the paper's three distinctive
features: (1) entity normalization collapses alias mentions ("Apple" / "Apple
Inc.") to ONE canonical Wikidata item, (2) Wikidata type/relation constraints
reject an ontology-invalid statement (a City cannot be foundedBy), and (3)
qualifiers (point-in-time / start-time) ride on the statements.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

METHOD_DIR = Path(__file__).resolve().parents[1]
IMPL_ROOT = METHOD_DIR.parents[1]
if str(IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPL_ROOT))

_spec = importlib.util.spec_from_file_location(
    "pipeline_" + METHOD_DIR.name.replace("-", "_"), METHOD_DIR / "pipeline.py")
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 7
    c = manifest["counts"]
    assert c["raw_surface_forms"] == 8
    assert c["canonical_entities"] == 7
    assert c["merged"] == 1            # Apple Inc. + Apple -> one item
    assert c["accepted_statements"] == 6
    assert c["rejected_statements"] == 1
    assert c["qualified_statements"] == 3
    assert c["classes"] == 5


def test_graph_matches_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "ontology.json").read_text(encoding="utf-8"))
    assert got == golden


def test_steps_match_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "steps.json").read_text(encoding="utf-8"))
    assert got == golden
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)  # graph only grows


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) == 5
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) == 4


def test_entity_normalization_dedups(tmp_path):
    """'Apple' and 'Apple Inc.' must collapse to the single item Q312."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    inst = [n["data"] for n in g["nodes"] if n["data"]["type"] == "instance"]
    apple = [n for n in inst if n["label"] == "Apple Inc."]
    assert len(apple) == 1
    assert apple[0]["id"] == "Q312" and apple[0]["qid"] == "Q312"
    # every instance node carries a Wikidata QID id
    assert all(n["id"].startswith("Q") for n in inst)


def test_constraint_rejects_invalid_statement(tmp_path):
    """A City as the subject of foundedBy violates the property's constraint."""
    manifest, out = _run(tmp_path)
    rej = manifest["rejected"]
    assert len(rej) == 1
    assert rej[0]["edge"][1] == "foundedBy"
    assert rej[0]["src_type"] == "City"
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    founded = [(e["data"]["source"], e["data"]["target"])
               for e in g["edges"] if e["data"]["label"] == "foundedBy"]
    # the rejected (Cupertino, Steve Jobs) edge is absent; valid ones survive
    assert ("Q110739", "Q19837") not in founded
    assert ("Q312", "Q19837") in founded


def test_qualifiers_present(tmp_path):
    """Time qualifiers (P585 point-in-time / P580 start-time) ride on edges."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    quals = {e["data"]["label"]: e["data"]["qualifiers"]
             for e in g["edges"] if e["data"].get("qualifiers")}
    assert quals["chiefExecutiveOfficer"]["pid"] == "P580"
    assert quals["chiefExecutiveOfficer"]["value"] == "2011"
    assert quals["foundedBy"]["pid"] == "P585"


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
