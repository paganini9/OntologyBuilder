"""Tests for the AGENTiGraph pipeline.

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
    sys.path.insert(0, str(IMPL_ROOT))  # for `backend.llm`

# Load this method's pipeline under a UNIQUE module name to avoid colliding with
# other methods' top-level `pipeline` module when the whole suite runs.
_spec = importlib.util.spec_from_file_location(
    "pipeline_" + METHOD_DIR.name.replace("-", "_"), METHOD_DIR / "pipeline.py")
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)

# the cqbycq graph/step contract: every node/step must carry these keys
_NODE_KEYS = {"id", "label", "type", "attributes"}
_EDGE_KEYS = {"id", "source", "target", "label"}
_STEP_KEYS = {"step", "cq", "added", "graph"}
_ADDED_KEYS = {"classes", "object_properties", "data_properties"}


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_turns"] == 8
    assert manifest["counts"]["classes"] >= 4
    assert manifest["counts"]["object_properties"] >= 3


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
    # one snapshot per turn, monotonically growing graph
    assert len(got) == 8
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_schema_matches_cqbycq(tmp_path):
    """Graph/step schema must match the cqbycq contract (extra keys allowed)."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    for n in graph["nodes"]:
        assert _NODE_KEYS.issubset(n["data"].keys())
    for e in graph["edges"]:
        assert _EDGE_KEYS.issubset(e["data"].keys())
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert _STEP_KEYS.issubset(s.keys())
        assert _ADDED_KEYS.issubset(s["added"].keys())
        # graph snapshot uses the same node/edge schema
        assert {"nodes", "edges"}.issubset(s["graph"].keys())


def test_steps_count_equals_turns(tmp_path):
    manifest, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    assert len(steps) == manifest["input_turns"]


def test_intents_vary(tmp_path):
    """AGENTiGraph classifies intent per turn; the sample must exercise >=2."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    intents = {s["intent"] for s in steps}
    assert len(intents) >= 2
    # a query turn must leave the graph unchanged from the previous snapshot
    for prev, cur in zip(steps, steps[1:]):
        if cur["intent"] == "query":
            assert cur["added"]["classes"] == []
            assert cur["added"]["object_properties"] == []
            assert cur["graph"] == prev["graph"]


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
