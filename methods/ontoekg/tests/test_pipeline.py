"""Tests for the OntoEKG pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL with
BOTH object properties and a subClassOf hierarchy. Real-backend output is
non-deterministic and is therefore NOT asserted here.
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
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 1
    assert manifest["counts"]["subclass_of"] >= 1


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


def test_graph_schema_matches_cqbycq(tmp_path):
    """Graph format must match cqbycq: nodes{data:{id,label,type,attributes}},
    edges{data:{id,source,target,label}}."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(g.keys()) == {"nodes", "edges"}
    for n in g["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
    for e in g["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}


def test_extraction_and_entailment_steps_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    phases = [s["phase"] for s in steps]
    assert phases.count("extraction") == 6  # one per sentence
    assert phases.count("entailment") == 1  # one entailment step
    # entailment is the last step
    assert steps[-1]["phase"] == "entailment"
    assert steps[-1]["cq"] == "(entail) hierarchy"
    assert all(s["cq"].startswith("(extract) ")
               for s in steps if s["phase"] == "extraction")
    # the entailment step actually added subclass_of links
    assert len(steps[-1]["added"]["subclass_of"]) >= 1


def test_both_object_property_and_subclassof_edges(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    subs = [e for e in g["edges"] if e["data"]["label"] == "subClassOf"]
    ops = [e for e in g["edges"] if e["data"]["label"] != "subClassOf"]
    assert len(subs) >= 1, "expected at least one subClassOf edge (Phase B)"
    assert len(ops) >= 1, "expected at least one object-property edge (Phase A)"
    # the entailment must include a non-trivial (non-root) compound-tail subclass
    nonroot = [e for e in subs if e["data"]["target"] != "Entity"]
    assert len(nonroot) >= 1, "expected at least one compound-tail subClassOf"


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    objprops = list(g.subjects(rdflib.RDF.type, obj_prop))
    subclassof = list(g.subject_objects(rdflib.RDFS.subClassOf))
    assert len(classes) >= 5
    assert len(objprops) >= 1
    assert len(subclassof) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
