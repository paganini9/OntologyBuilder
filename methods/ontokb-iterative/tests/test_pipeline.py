"""Tests for the ontokb-iterative pipeline.

MOCK backend is deterministic: assert graph/steps against golden fixtures, check
the TTL is valid OWL, and check the distinctive draft->refine behaviour (a refine
step that adds subClassOf hierarchy and data attributes on top of the draft).
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
    assert manifest["iterations"] == 2
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 3
    assert manifest["counts"]["subclass_of"] >= 1
    assert manifest["counts"]["data_properties"] >= 2


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


def test_draft_then_refine(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    stages = [s["stage"] for s in steps]
    assert stages[-1] == "refine"
    assert stages[:-1] == ["draft"] * (len(steps) - 1)
    refine = steps[-1]
    # refinement must actually enrich the draft
    assert refine["added"]["subclass_of"], "refine should induce subClassOf"
    assert refine["added"]["data_properties"], "refine should attach attributes"


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
