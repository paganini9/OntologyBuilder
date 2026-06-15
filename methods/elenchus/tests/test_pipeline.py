"""Tests for the Elenchus (prover-skeptic dialogue) pipeline.

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


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_claims"] == 8
    assert manifest["counts"]["claims"] == 8
    assert manifest["counts"]["accepted"] == 5
    assert manifest["counts"]["rejected"] == 3
    # accepted + rejected exhausts the claims
    assert (manifest["counts"]["accepted"]
            + manifest["counts"]["rejected"]) == manifest["counts"]["claims"]


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
    # one snapshot per claim
    assert len(got) == 8


def test_step_schema_matches_cqbycq(tmp_path):
    """steps carry the cqbycq base keys plus the prover/skeptic dialogue keys."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        # cqbycq base schema
        assert {"step", "cq", "added", "graph"} <= set(s.keys())
        assert {"classes", "object_properties", "data_properties"} == set(
            s["added"].keys())
        assert {"nodes", "edges"} == set(s["graph"].keys())
        for n in s["graph"]["nodes"]:
            assert {"id", "label", "type", "attributes"} == set(n["data"].keys())
        for e in s["graph"]["edges"]:
            assert {"id", "source", "target", "label"} == set(e["data"].keys())
        # elenchus-specific dialogue keys
        assert {"prover", "skeptic", "verdict"} <= set(s.keys())
        assert s["verdict"] in ("accepted", "rejected")
        assert set(s["skeptic"].keys()) == {"verdict", "reason"}


def test_at_least_one_rejection(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    verdicts = [s["verdict"] for s in steps]
    assert "rejected" in verdicts
    assert verdicts.count("rejected") >= 1
    # rejected steps contribute nothing to the KB
    for s in steps:
        if s["verdict"] == "rejected":
            assert s["added"]["classes"] == []
            assert s["added"]["object_properties"] == []


def test_kb_edges_only_from_accepted(tmp_path):
    """Every edge in the final KB traces back to an accepted claim; rejected
    claims' triples never appear in the graph."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))

    accepted_edges = set()
    rejected_edges = set()
    rejected_nodes = set()
    for s in steps:
        p = s["prover"]
        if not (p.get("subject") and p.get("relation") and p.get("object")):
            continue
        key = (p["subject"], p["relation"], p["object"])
        if s["verdict"] == "accepted":
            accepted_edges.add(key)
        else:
            rejected_edges.add(key)
            rejected_nodes.add(p["object"])

    graph_edges = {(e["data"]["source"], e["data"]["label"], e["data"]["target"])
                   for e in graph["edges"]}
    node_ids = {n["data"]["id"] for n in graph["nodes"]}

    # all graph edges come from accepted claims
    assert graph_edges <= accepted_edges
    # the contradicting rejected edge (Motor drives Compressor) is absent
    assert ("Motor", "drives", "Compressor") in rejected_edges
    assert ("Motor", "drives", "Compressor") not in graph_edges
    # Compressor was only ever introduced by a rejected claim -> not a node
    assert "Compressor" not in node_ids


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    props = list(g.subjects(rdflib.RDF.type, owl_op))
    assert len(props) >= 5
    # the rejected Compressor must not have leaked into the TTL
    ex = rdflib.Namespace("http://example.org/elenchus#")
    assert (ex["Compressor"], rdflib.RDF.type, owl_class) not in g


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
