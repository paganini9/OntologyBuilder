"""Tests for the Ontology-Grounded-Wikidata pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures, check the Wikidata grounding fired,
and that the TTL is valid OWL with a Wikidata link. Real-backend output is
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
    assert manifest["input_cqs"] == 7
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5
    assert manifest["counts"]["grounded_properties"] >= 1


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
    # one authoring snapshot per CQ + one final grounding snapshot
    assert len(got) == 8


def test_schema_matches_cqbycq_keys(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    for n in graph["nodes"]:
        assert set(n["data"].keys()) >= {"id", "label", "type", "attributes"}
    for e in graph["edges"]:
        assert set(e["data"].keys()) >= {"id", "source", "target", "label"}
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert set(s.keys()) >= {"step", "cq", "added", "graph"}
        assert set(s["added"].keys()) >= {
            "classes", "object_properties", "data_properties"}
        assert set(s["graph"].keys()) == {"nodes", "edges"}


def test_at_least_one_edge_grounded(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    grounded = [e for e in graph["edges"]
                if e["data"].get("wikidata", "").startswith("P")]
    assert grounded, "expected at least one edge grounded to a Wikidata P-id"
    # label is annotated with the P-id
    assert any("(P" in e["data"]["label"] for e in grounded)


def test_grounding_step_exists(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    grounding = [s for s in steps if s["cq"] == "(wikidata grounding)"]
    assert len(grounding) == 1
    assert grounding[0]["added"]["grounded"], "grounding step should summarize hits"


def test_ttl_is_valid_owl_with_wikidata(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    assert any("wikidata.org" in str(o) for o in g.objects()), \
        "TTL should link a grounded property to a Wikidata URI"


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
