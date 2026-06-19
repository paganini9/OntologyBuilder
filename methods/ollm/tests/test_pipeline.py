"""Tests for the OLLM (end-to-end taxonomy/ontology learning) pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
taxonomy graph/steps against committed golden fixtures and check the TTL is valid
OWL with rdfs:subClassOf. Real-backend output is non-deterministic and is
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


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["method"] == "ollm"
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 6
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["subclass_of"] >= 2


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


def test_schema_matches_cqbycq(tmp_path):
    """Graph schema must match the cqbycq node/edge shape the frontend renders."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(g.keys()) == {"nodes", "edges"}
    for n in g["nodes"]:
        d = n["data"]
        assert set(d.keys()) == {"id", "label", "type", "attributes"}
        assert d["type"] == "class"
    for e in g["edges"]:
        d = e["data"]
        assert set(d.keys()) == {"id", "source", "target", "label"}


def test_step_stages_present(tmp_path):
    """Concept steps (one per sentence) + one taxonomy induction step."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    stages = [s["stage"] for s in steps]
    assert stages.count("concepts") == 6
    assert stages.count("taxonomy") == 1
    assert stages[-1] == "taxonomy"
    concept_steps = [s for s in steps if s["stage"] == "concepts"]
    assert all(s["cq"].startswith("(concepts) ") for s in concept_steps)
    tax_step = steps[-1]
    assert tax_step["cq"] == "(taxonomy) induce hierarchy"


def test_taxonomy_has_subclass_edges(tmp_path):
    """At least 2 subClassOf edges incl. compound-tail ones; root Entity present."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    sub_edges = [e for e in g["edges"] if e["data"]["label"] == "subClassOf"]
    assert len(sub_edges) >= 2
    pairs = {(e["data"]["source"], e["data"]["target"]) for e in sub_edges}
    # compound-tail links
    assert ("ElectricMotor", "Motor") in pairs
    assert ("CoolantPump", "Pump") in pairs
    # synthetic root present as a node and as a parent
    node_ids = {n["data"]["id"] for n in g["nodes"]}
    assert "Entity" in node_ids
    assert any(t == "Entity" for _, t in pairs)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    subclass_triples = list(g.triples((None, rdflib.RDFS.subClassOf, None)))
    assert len(subclass_triples) >= 2


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
