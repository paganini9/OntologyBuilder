"""Tests for the SAC-KG pipeline.

With the MOCK backend the Generator -> Verifier -> Pruner multi-level loop is
fully deterministic, so we assert the graph/steps against committed golden
fixtures and check the TTL is valid OWL. The real SAC-KG Pruner is a GPU
T5-LoRA model; that is NOT exercised here (this is a deterministic MOCK
simplification).
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
    assert manifest["method"] == "sac-kg"
    assert manifest["seeds"] == 1
    assert manifest["levels"] == 2
    assert manifest["counts"]["classes"] >= 4
    assert manifest["counts"]["object_properties"] >= 4


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
    """ontology.json schema must be identical to cqbycq's (frontend renders it
    directly)."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    for n in graph["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
    for e in graph["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}


def test_multiple_levels_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    levels = {s["level"] for s in steps}
    assert levels == {1, 2}
    # each level runs generate -> verify -> prune in order
    stages = [(s["level"], s["stage"]) for s in steps]
    assert (1, "generate") in stages
    assert (1, "verify") in stages
    assert (1, "prune") in stages
    assert (2, "generate") in stages
    assert (2, "prune") in stages


def test_verifier_dropped_at_least_one(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    dropped = sum(
        len(s["added"]["dropped"]) for s in steps if s["stage"] == "verify")
    assert dropped >= 1


def test_pruner_removed_at_least_one(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    dropped = sum(
        len(s["added"]["dropped"]) for s in steps if s["stage"] == "prune")
    assert dropped >= 1


def test_graph_grew_beyond_seeds(tmp_path):
    manifest, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    # final node count strictly exceeds the seed count
    final_nodes = len(steps[-1]["graph"]["nodes"])
    assert final_nodes > manifest["seeds"]
    # node count is monotonically non-decreasing across the loop
    sizes = [len(s["graph"]["nodes"]) for s in steps]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    props = list(g.subjects(rdflib.RDF.type, owl_op))
    assert len(classes) >= 4
    assert len(props) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
