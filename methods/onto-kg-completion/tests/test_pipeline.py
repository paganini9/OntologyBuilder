"""Tests for the Ontology-Enhanced KG Completion pipeline.

With the MOCK backend the completion is deterministic rule-based inference
(transitivity / inverse / symmetry over the seed KG), so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL.
The defining property of this method is COMPLETION: the final graph must have
MORE edges than the seed (missing links were predicted), without inventing new
classes. Real-backend output is non-deterministic and is NOT asserted here.
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
    assert manifest["method"] == "onto-kg-completion"
    assert manifest["seed_classes"] == 5
    assert manifest["seed_edges"] == 4
    # completion adds links beyond the seed, but no new classes
    assert manifest["counts"]["classes"] == 5
    assert manifest["counts"]["inferred_edges"] >= 1
    assert manifest["counts"]["edges"] > manifest["counts"]["seed_edges"]


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


def test_load_and_complete_steps_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    assert len(steps) == 2
    assert steps[0]["phase"] == "load"
    assert steps[0]["cq"] == "(load) seed KG"
    assert steps[1]["phase"] == "complete"
    assert steps[1]["cq"] == "(complete) inferred edges"


def test_graph_schema_matches_cqbycq(tmp_path):
    """Final graph must use the shared cqbycq node/edge schema (plus origin)."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    for n in graph["nodes"]:
        d = n["data"]
        assert {"id", "label", "type", "attributes"} <= set(d.keys())
        assert d["type"] == "class"
        assert d["origin"] in ("seed", "inferred")
    for e in graph["edges"]:
        d = e["data"]
        assert {"id", "source", "target", "label"} <= set(d.keys())
        assert d["origin"] in ("seed", "inferred")


def test_completion_adds_missing_edges(tmp_path):
    """The point of the method: final edges > seed edges, all inferred edges new
    and grounded in existing seed classes."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    class_ids = {n["data"]["id"] for n in graph["nodes"]}
    seed_edges = [e for e in graph["edges"] if e["data"]["origin"] == "seed"]
    inferred = [e for e in graph["edges"] if e["data"]["origin"] == "inferred"]
    assert len(inferred) > 0
    assert len(graph["edges"]) > len(seed_edges)
    # every inferred edge connects EXISTING classes (grounded completion)
    for e in inferred:
        assert e["data"]["source"] in class_ids
        assert e["data"]["target"] in class_ids
    # at least one transitive completion (e.g. Bolt -> Assembly via Bracket)
    assert any(e["data"]["source"] == "Bolt" and e["data"]["target"] == "Assembly"
               for e in inferred)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    props = list(g.subjects(rdflib.RDF.type, owl_op))
    assert len(classes) == 5
    # seed (4) + inferred (6) edges each get a property declaration
    assert len(props) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
