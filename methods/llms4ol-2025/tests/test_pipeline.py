"""Tests for the LLMs4OL-2025 ontology-learning pipeline.

MOCK backend is fully deterministic, so we assert graph/steps against committed
golden fixtures, check the TTL is valid OWL, and check the distinctive feature:
retrieval-augmented term typing (Task B) — an unseen term gets a type by its
nearest already-typed example, plus is-a taxonomy (Task C).
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

METHOD_DIR = Path(__file__).resolve().parents[1]
IMPL_ROOT = METHOD_DIR.parents[1]
if str(IMPL_ROOT) not in sys.path:
    sys.path.insert(0, str(IMPL_ROOT))

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
    assert manifest["input_documents"] == 12
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["typed_examples"] >= 3      # Task A
    assert manifest["counts"]["taxonomy_edges"] >= 3      # Task C
    assert manifest["counts"]["inferred_typings"] >= 2    # Task B


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
    # three OL subtasks appear in order, graph grows monotonically
    stages = [s["stage"] for s in got]
    assert stages == sorted(stages, key=lambda s: {"extract(A)": 0, "taxonomy(C)": 1,
                                                   "typing(B)": 2}[s])
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_retrieval_typing_and_taxonomy(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    edges = [e["data"] for e in g["edges"]]
    # Task C: at least one subClassOf edge
    assert any(e["label"] == "subClassOf" for e in edges)
    # Task B: at least one inferred (retrieval-typed) instanceOf edge with a
    # recorded neighbour it was matched against.
    inferred = [e for e in edges if e.get("inferred")]
    assert inferred and all(e.get("via") for e in inferred)
    # the unseen "axial pump" should be typed Pump via "centrifugal pump"
    ap = [e for e in inferred if e["source"] == "axial pump"]
    assert ap and ap[0]["target"] == "Pump" and ap[0]["via"] == "centrifugal pump"


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
