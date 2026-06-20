"""Tests for the TRACE-KG pipeline.

MOCK backend is fully deterministic, so we assert graph/steps against committed
golden fixtures, check the TTL is valid OWL, and check the two distinctive
features: conditional qualifiers on relations and per-edge source traceability.
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
    assert manifest["input_sentences"] == 8
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["relations"] >= 2
    assert manifest["counts"]["subclass_of"] >= 2
    assert manifest["counts"]["qualified_relations"] >= 1


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
    # monotonically growing graph (one snapshot per sentence)
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_qualifiers_and_traceability(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    qualified = [e for e in g["edges"] if e["data"].get("qualifier")]
    assert qualified, "expected at least one conditional qualifier on a relation"
    # every edge carries a source-sentence provenance (traceability)
    assert all(e["data"].get("provenance") for e in g["edges"])


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
