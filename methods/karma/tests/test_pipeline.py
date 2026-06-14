"""Tests for the KARMA multi-agent KG-enrichment pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the four agent stages,
schema alignment, conflict resolution, and valid OWL TTL. Real-backend output is
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
    assert manifest["method"] == "karma"
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 7
    assert manifest["seed_classes"] == 2
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5
    assert manifest["counts"]["aligned"] >= 1
    assert manifest["counts"]["conflicts_removed"] >= 1


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
    """ontology.json nodes/edges use the SAME keys as cqbycq (extras allowed)."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    for n in graph["nodes"]:
        d = n["data"]
        assert {"id", "label", "type", "attributes"} <= set(d.keys())
        assert d["origin"] in ("seed", "new")  # karma extra
    for e in graph["edges"]:
        d = e["data"]
        assert {"id", "source", "target", "label"} <= set(d.keys())
        assert d["origin"] in ("seed", "new")  # karma extra


def test_four_agent_stages_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    stages = [s["stage"] for s in steps]
    assert stages == [
        "entity-discovery", "relation-extraction",
        "schema-alignment", "conflict-resolution",
    ]
    cqs = [s["cq"] for s in steps]
    assert cqs == ["(discover)", "(extract)", "(align)", "(resolve)"]
    # each snapshot carries the cqbycq graph shape
    for s in steps:
        assert set(s["graph"].keys()) == {"nodes", "edges"}


def test_schema_alignment_merged_a_variant(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    align = next(s for s in steps if s["stage"] == "schema-alignment")
    assert len(align["merged"]) >= 1
    rec = align["merged"][0]
    assert rec["variant"] != rec["merged_into"]
    # the merged-away variant must NOT be a node in the final graph
    final_ids = {n["data"]["id"]
                 for n in steps[-1]["graph"]["nodes"]}
    assert rec["variant"] not in final_ids
    assert rec["merged_into"] in final_ids


def test_conflict_resolution_removed_an_edge(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    resolve = next(s for s in steps if s["stage"] == "conflict-resolution")
    assert len(resolve["removed"]) >= 1
    assert all(
        r["reason"] in ("duplicate", "reverse-duplicate")
        for r in resolve["removed"])


def test_seed_origin_present(tmp_path):
    """Enrichment over a seed: at least one seed node and one new node."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    origins = {n["data"]["origin"] for n in graph["nodes"]}
    assert "seed" in origins
    assert "new" in origins


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    ops = list(g.subjects(rdflib.RDF.type, owl_op))
    assert len(classes) >= 5
    assert len(ops) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
