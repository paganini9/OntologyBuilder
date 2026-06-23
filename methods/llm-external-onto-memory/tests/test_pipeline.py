"""Tests for the LLM External Ontology Memory pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the paper's distinctive
features: (1) heterogeneous ingestion (document / api / dialogue), (2) the
generation-verification-CORRECTION loop with three outcomes — accept, correct
(non-ISO date repaired to xsd:date), reject (sh:class + sh:pattern violations) —
and (3) continuous updates with entity normalization (Eng / Engineering -> one
Department node).
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
    assert manifest["input_sources"] == 4
    assert manifest["source_types"] == {"document": 2, "api": 1, "dialogue": 1}
    c = manifest["counts"]
    assert c["recognized_entities"] == 5
    assert c["accepted_assertions"] == 8
    assert c["corrected_assertions"] == 2
    assert c["rejected_assertions"] == 2
    assert c["classes"] == 2


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
    # continuous updates: node count never shrinks across sources
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    data_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#DatatypeProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) == 2
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) == 1
    assert len(list(g.subjects(rdflib.RDF.type, data_prop))) == 2


def test_heterogeneous_provenance(tmp_path):
    """Entities carry the source (document/api/dialogue) they came from."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    prov = {n["data"]["label"]: n["data"].get("provenance")
            for n in g["nodes"] if n["data"]["type"] == "instance"}
    assert prov["Alice"] == "doc-1"      # document
    assert prov["Bob"] == "api-1"        # api record
    assert prov["Carol"] == "chat-1"     # dialogue log


def test_correction_repairs_non_iso_dates(tmp_path):
    """The verification-correction loop fixes non-ISO dates to xsd:date."""
    manifest, out = _run(tmp_path)
    fixes = {c["subj"]: (c["raw"], c["fixed"]) for c in manifest["corrected"]}
    assert fixes["Alice"] == ("March 3, 2021", "2021-03-03")
    assert fixes["Bob"] == ("2020/07/15", "2020-07-15")
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    alice = [n["data"] for n in g["nodes"] if n["data"]["label"] == "Alice"][0]
    assert "joinedOn=2021-03-03" in alice["attributes"]
    # an already-ISO date is accepted WITHOUT being logged as a correction
    assert "Dave" not in fixes


def test_rejects_unfixable_violations(tmp_path):
    """sh:class (worksIn -> non-Department) and sh:pattern (bad e-mail) reject."""
    manifest, out = _run(tmp_path)
    reasons = {(r["subj"], r["prop"]): r["reason"] for r in manifest["rejected"]}
    assert reasons[("Carol", "worksIn")].startswith("sh:class")
    assert reasons[("Carol", "email")] == "sh:pattern violated"
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    # Carol exists (recognized) but has NO worksIn edge and NO email attribute
    carol = [n["data"] for n in g["nodes"] if n["data"]["label"] == "Carol"][0]
    assert carol["attributes"] == []
    work_srcs = [e["data"]["source"] for e in g["edges"]
                 if e["data"]["label"] == "worksIn"]
    assert "Carol" not in work_srcs


def test_entity_normalization_dedups_department(tmp_path):
    """'Eng' and 'Engineering' collapse into a single Department node."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    depts = [n for n in g["nodes"]
             if n["data"].get("cls") == "Department"]
    assert len(depts) == 1
    assert depts[0]["data"]["label"] == "Engineering"


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
