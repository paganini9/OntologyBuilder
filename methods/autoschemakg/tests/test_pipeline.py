"""Tests for the AutoSchemaKG pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the induced schema +
TTL. The defining property of AutoSchemaKG -- the schema is INDUCED from data,
not given -- is checked via the induced type classes and `instanceOf` edges.
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
    assert manifest["input_sentences"] == 6
    assert manifest["counts"]["instances"] >= 5
    assert manifest["counts"]["induced_classes"] >= 2
    assert manifest["counts"]["triples"] >= 5


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


def test_graph_schema_matches_cqbycq_keys(tmp_path):
    """Node/edge/step keys must equal cqbycq's so the front end renders them."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    for n in graph["nodes"]:
        assert set(n["data"].keys()) >= {"id", "label", "type", "attributes"}
    for e in graph["edges"]:
        assert set(e["data"].keys()) >= {"id", "source", "target", "label"}
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert {"step", "cq", "added", "graph"} <= set(s.keys())
        assert {"classes", "object_properties", "data_properties"} <= set(
            s["added"].keys())


def test_schema_is_induced(tmp_path):
    """Defining property: >=2 induced type classes and >=1 instanceOf edge."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    classes = [n for n in graph["nodes"] if n["data"]["type"] == "class"]
    assert len(classes) >= 2
    instances = [n for n in graph["nodes"] if n["data"]["type"] == "instance"]
    assert len(instances) >= 1
    instance_of = [e for e in graph["edges"]
                   if e["data"]["label"] == "instanceOf"]
    assert len(instance_of) >= 1


def test_schema_induction_step_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    induction = [s for s in steps if s["cq"] == "(schema induction)"]
    assert len(induction) == 1
    # the induced classes only appear at the schema-induction step
    assert len(induction[0]["added"]["classes"]) >= 2


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl = "http://www.w3.org/2002/07/owl#"
    classes = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(owl + "Class")))
    individuals = list(
        g.subjects(rdflib.RDF.type, rdflib.URIRef(owl + "NamedIndividual")))
    assert len(classes) >= 1
    assert len(individuals) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
