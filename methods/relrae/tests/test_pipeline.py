"""Tests for the RELRaE pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL.
Real-backend output is non-deterministic and is therefore NOT asserted here.
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
    assert manifest["input_elements"] == 5
    assert manifest["raw_relationships"] == 12
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5
    # refinement/evaluation must drop at least one raw relationship
    assert manifest["counts"]["rejected"] >= 1


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
    # one snapshot per raw relationship, monotonically non-decreasing graph
    assert len(got) == 12
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_every_accepted_relation_scored_above_threshold(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert graph["edges"], "expected at least one accepted relationship"
    for e in graph["edges"]:
        assert e["data"]["accepted"] is True
        assert e["data"]["score"] >= pipeline.ACCEPT_THRESHOLD
        assert e["data"]["kind"] in ("nest", "ref")


def test_reference_label_is_verb_like(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    labels = {e["data"]["label"] for e in graph["edges"]}
    # the instrumentRef reference must be surfaced as a meaningful relation
    assert "measuredWith" in labels


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
