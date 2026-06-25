"""Tests for the MedKGent pipeline.

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
    assert manifest["input_abstracts"] == 9
    assert manifest["counts"]["classes"] >= 6
    assert manifest["counts"]["object_properties"] >= 3
    # the two agents' headline behaviours must all fire on the sample
    assert manifest["counts"]["reinforced"] >= 1
    assert manifest["counts"]["facts_superseded"] >= 1
    assert manifest["counts"]["filtered_low_confidence"] >= 1


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
    assert len(got) == 9
    # constructor builds in non-decreasing date order
    dates = [s["date"] for s in got]
    assert dates == sorted(dates)


def test_reinforcement_raises_confidence_and_support(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    by = {(e["data"]["source"], e["data"]["relation"], e["data"]["target"]): e["data"]
          for e in graph["edges"]}
    met = by[("Metformin", "treats", "Diabetes")]
    assert met["support"] == 2
    assert met["confidence"] > 0.6           # combined > a single observation
    assert met["first_seen"] < met["last_seen"]


def test_conflict_resolution_drops_weaker_polar_relation(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    rels = {(e["data"]["source"], e["data"]["relation"], e["data"]["target"])
            for e in graph["edges"]}
    # the high-confidence "reduces" must win over the earlier "increases"
    assert ("StatinZ", "reduces", "StrokeRisk") in rels
    assert ("StatinZ", "increases", "StrokeRisk") not in rels


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 6


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
