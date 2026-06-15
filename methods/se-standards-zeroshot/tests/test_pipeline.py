"""Tests for the se-standards-zeroshot pipeline.

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

# Graph schema must match cqbycq exactly (front-end renders both the same way).
NODE_DATA_KEYS = {"id", "label", "type", "attributes"}
EDGE_DATA_KEYS = {"id", "source", "target", "label"}


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["method"] == "se-standards-zeroshot"
    assert manifest["input_sections"] == 3
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5
    assert manifest["counts"]["aligned_terms"] >= 1


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
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    assert graph["nodes"]
    for n in graph["nodes"]:
        assert set(n["data"].keys()) == NODE_DATA_KEYS
        assert n["data"]["type"] == "class"
    for e in graph["edges"]:
        assert set(e["data"].keys()) == EDGE_DATA_KEYS


def test_section_steps_and_alignment_step(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    # one snapshot per section ...
    section_steps = [s for s in steps if s["cq"].startswith("section:")]
    assert len(section_steps) == 3
    # ... plus a final normalize+align snapshot
    align_steps = [s for s in steps if s["cq"] == "(normalize+align)"]
    assert len(align_steps) == 1
    assert align_steps[0]["aligned_terms"]  # at least one cross-section term
    # graph grows monotonically across the section steps
    sizes = [len(s["graph"]["nodes"]) for s in section_steps]
    assert sizes == sorted(sizes)


def test_cross_section_term_merged_once(tmp_path):
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    aligned = next(s for s in steps if s["cq"] == "(normalize+align)")["aligned_terms"]
    ids = [n["data"]["id"] for n in graph["nodes"]]
    # every node id is unique (alignment merged duplicates)
    assert len(ids) == len(set(ids))
    # a term reported as appearing in >1 section exists exactly once as a node
    for term, sections in aligned.items():
        assert len(sections) > 1
        assert ids.count(term) == 1


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
