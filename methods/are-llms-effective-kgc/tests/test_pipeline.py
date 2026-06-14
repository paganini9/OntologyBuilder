"""Tests for the hierarchical-extraction pipeline (Are LLMs Effective KGC?).

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL
with a class hierarchy. Real-backend output is non-deterministic and is NOT
asserted here.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

METHOD_DIR = Path(__file__).resolve().parents[1]
IMPL_ROOT = METHOD_DIR.parents[1]
if str(IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPL_ROOT))  # for `backend.llm`

# Load this method's pipeline under a UNIQUE module name to avoid colliding with
# other methods' top-level `pipeline` module when the whole suite runs.
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
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 2
    assert manifest["counts"]["subclass_of"] >= 1


def test_graph_matches_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "ontology.json").read_text(encoding="utf-8"))
    assert got == golden


def test_graph_schema_matches_cqbycq(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(got.keys()) == {"nodes", "edges"}
    for n in got["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
    for e in got["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}


def test_steps_match_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "steps.json").read_text(encoding="utf-8"))
    assert got == golden
    # monotonically growing graph across the whole multi-level run
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_steps_have_all_levels(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    levels = [s["level"] for s in got]
    assert "L1" in levels and "L2" in levels and "L3" in levels
    # exactly one L2 and one L3 phase; the rest are per-sentence L1
    assert levels.count("L2") == 1
    assert levels.count("L3") == 1
    assert levels.count("L1") == 7
    # L1 phases come before L2 which comes before L3
    assert levels.index("L1") < levels.index("L2") < levels.index("L3")


def test_subclass_edges_present(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    subs = [e for e in got["edges"] if e["data"]["label"] == "subClassOf"]
    assert len(subs) >= 1


def test_ttl_is_valid_owl_with_hierarchy(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    subs = list(g.triples((None, rdflib.RDFS.subClassOf, None)))
    assert len(subs) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
