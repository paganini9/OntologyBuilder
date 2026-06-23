"""Tests for the LKD-KGC pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the three distinctive
features of the paper: (1) inferred knowledge dependencies + topological read
order (foundational docs first), (2) autoregressive schema induction that
*clusters* synonymous type labels (raw candidates >> canonical classes), and
(3) schema-guided relation extraction.
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
    assert manifest["input_documents"] == 5
    c = manifest["counts"]
    assert c["canonical_classes"] == 9
    assert c["instances"] == 10
    assert c["relations"] >= 4


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
    # graph grows monotonically (schema induction never deletes)
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 9
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) >= 1


def test_read_order_respects_dependencies(tmp_path):
    """Distinctive feature 1: foundational docs are processed before dependents.

    For every inferred dependency edge (B, A), B must appear before A in the
    read order (topological order over the knowledge-dependency DAG).
    """
    manifest, _ = _run(tmp_path)
    order = manifest["read_order"]
    pos = {d: i for i, d in enumerate(order)}
    edges = [tuple(e) for e in manifest["dependency_edges"]]
    assert edges, "the sample must induce at least one dependency"
    for (b, a) in edges:
        assert pos[b] < pos[a], f"{b} must be read before {a}"
    # the two foundational notes (Sensors=d1, Controllers=d2) come before the
    # procedure note (d4) that cites them
    assert pos["d1"] < pos["d4"] and pos["d2"] < pos["d4"]


def test_schema_clustering_collapses_synonyms(tmp_path):
    """Distinctive feature 2: clustering collapses plural/synonym type labels.

    Raw type candidates (Sensors/Sensor, Pumps/Pump, Protocol->Procedure...)
    are far more numerous than the canonical schema classes they cluster into.
    """
    manifest, _ = _run(tmp_path)
    c = manifest["counts"]
    assert c["raw_type_candidates"] > c["canonical_classes"]
    # the Protocol candidate must canonicalise onto the Procedure class
    cls = pipeline._canon_type("Protocol")
    assert cls == "Procedure"
    # plural collapses too
    assert pipeline._canon_type("Sensors") == "Sensor"


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
