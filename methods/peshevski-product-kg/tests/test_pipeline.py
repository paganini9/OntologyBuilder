"""Tests for the Peshevski Product KG pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL
(schema + individuals). Real-backend output is non-deterministic and is
therefore NOT asserted here.
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

N_PRODUCTS = 6


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_products"] == N_PRODUCTS
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["individuals"] == N_PRODUCTS
    assert manifest["counts"]["data_properties"] >= 3
    assert manifest["steps"] == 2 * N_PRODUCTS + 1


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
    # N creation + 1 refinement + N population
    assert len(got) == 2 * N_PRODUCTS + 1


def test_graph_schema_keys_match_cqbycq(tmp_path):
    """ontology.json must use the standard cqbycq node/edge keys."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert g["nodes"] and g["edges"]
    for n in g["nodes"]:
        assert set(n["data"]).issuperset({"id", "label", "type", "attributes"})
    for e in g["edges"]:
        assert set(e["data"]).issuperset({"id", "source", "target", "label"})


def test_has_individual_nodes(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    inds = [n for n in g["nodes"] if n["data"]["type"] == "individual"]
    assert len(inds) == N_PRODUCTS


def test_refinement_merge_occurred(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    refine = [s for s in steps if s["cq"] == "(refinement)"]
    assert len(refine) == 1
    merged = refine[0]["added"].get("merged", [])
    assert merged, "expected at least one class merge during refinement"
    # the sample includes Compressor / Compressors -> must collapse to one
    assert any(m["into"] == "Compressor" for m in merged)
    classes = [n["data"]["id"] for n in
               json.loads((out / "ontology.json").read_text(encoding="utf-8"))["nodes"]
               if n["data"]["type"] == "class"]
    assert "Compressors" not in classes
    assert "Compressor" in classes


def test_ttl_is_valid_owl_with_individuals(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl = "http://www.w3.org/2002/07/owl#"
    classes = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(owl + "Class")))
    inds = list(g.subjects(rdflib.RDF.type,
                           rdflib.URIRef(owl + "NamedIndividual")))
    assert len(classes) >= 5
    assert len(inds) == N_PRODUCTS


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
