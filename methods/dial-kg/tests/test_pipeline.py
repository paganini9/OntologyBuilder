"""Tests for the DIAL-KG pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL.
We also assert the method's distinctive behaviour: a per-document closed loop
(governance adjudication recording a cross-document dedup) and dynamic schema
evolution (>=2 induced types). Real-backend output is non-deterministic and is
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
    assert manifest["backend"] == "mock"
    assert manifest["input_documents"] == 4
    assert manifest["counts"]["entity_classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 4
    assert manifest["counts"]["induced_types"] >= 2
    assert manifest["counts"]["governance_merged"] >= 1


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


def test_graph_schema_is_cqbycq_compatible(tmp_path):
    """nodes carry id/label/type/attributes; edges carry id/source/target/label."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(g.keys()) == {"nodes", "edges"}
    for n in g["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
    for e in g["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}
    # at least one instanceOf edge (entity -> induced type) from schema evolution
    assert any(e["data"]["label"] == "instanceOf" for e in g["edges"])


def test_per_document_steps_and_final_schema_step(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    # one step per document + one final Meta-KB schema step
    assert len(steps) == 4 + 1
    assert steps[-1]["cq"] == "(schema) Meta-KB"
    assert steps[-1]["stage"] == "schema_evolution"
    # every step carries governance + schema_types keys (the method's signature)
    for s in steps:
        assert "governance" in s and "schema_types" in s
    # monotonically growing graph across the document steps
    sizes = [len(s["graph"]["nodes"]) for s in steps]
    assert sizes == sorted(sizes)


def test_governance_dedup_occurred(tmp_path):
    """A cross-document variant (e.g. Pumps) must merge to an existing canonical."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    merges = [m for s in steps for m in s["governance"]["merged_entities"]]
    assert merges, "expected at least one governance merge"
    # the merged variant maps to a DIFFERENT canonical already in the Meta-KB
    assert all(m["variant"] != m["canonical"] for m in merges)


def test_at_least_two_induced_types(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    types = steps[-1]["schema_types"]
    assert len(types) >= 2
    # schema evolution must have fired across more than one document step
    evolved_steps = [s for s in steps if s.get("evolved_types")]
    assert len(evolved_steps) >= 2


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert list(g.subjects(rdflib.RDF.type, owl_op))


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
