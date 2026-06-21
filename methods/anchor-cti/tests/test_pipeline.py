"""Tests for the ANCHOR-CTI pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the two distinctive
features: hybrid ontology discovery (navigation across schemas) and SHACL-style
demotion to the validating ancestor when the value fails its constraint.
"""
import importlib.util
import json
import os
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
    assert manifest["schema"] == "UCO"
    assert manifest["input_sentences"] == 6
    assert manifest["counts"]["classes"] >= 8
    assert manifest["counts"]["instances"] >= 10
    assert manifest["counts"]["relations"] >= 4
    # every recorded instance was either SHACL-validated or demoted
    assert (manifest["shacl"]["passes"] + manifest["shacl"]["demotions"]
            == manifest["counts"]["instances"])


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
    # graph grows monotonically (discovery never deletes)
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 8


def test_hybrid_ontology_discovery():
    """Search-and-navigate finds the seed class and records the climb path."""
    uco = pipeline._SCHEMAS["uco"]
    # 'ransomware' alias -> seed=Ransomware; value passes -> stays at Ransomware
    d = pipeline._discover(uco, "Ransomware", "Ransomware")
    assert d["seed"] == "Ransomware"
    assert d["class"] == "Ransomware"
    assert d["path"][0] == "Ransomware"  # search seeded at the leaf
    assert d["shacl_demoted"] is False
    # IPAddress seed with a malformed value -> SHACL fails -> navigate to parent
    bad = pipeline._discover(uco, "IPAddress", "not-an-ip")
    assert bad["seed"] == "IPAddress"
    assert bad["class"] == "Indicator"           # one step up
    assert bad["shacl_demoted"] is True
    assert bad["path"] == ["IPAddress", "Indicator"]


def test_schema_agnostic_runs(tmp_path):
    """Same pipeline runs on STIX without code changes (flat hierarchy)."""
    os.environ["LLM_SCHEMA"] = "stix"
    try:
        out = tmp_path / "stix"
        man = pipeline.run(METHOD_DIR / "samples", out, backend="mock")
    finally:
        os.environ.pop("LLM_SCHEMA", None)
    assert man["schema"] == "STIX"
    # STIX schema is flatter -> strictly fewer subClassOf edges than UCO
    assert man["counts"]["subclass_of"] < 11
    # still produced a graph
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert any(n["data"].get("type") == "instance" for n in g["nodes"])


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
