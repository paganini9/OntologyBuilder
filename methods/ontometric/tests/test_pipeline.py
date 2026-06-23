"""Tests for the OntoMetric pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the paper's two distinctive
features: (1) two-phase validation — semantic type verification rejects a
hallucinated type, rule-based schema checking rejects an illegal edge — and
(2) deterministic identifiers + page provenance on every entity.
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
    assert manifest["framework"] == "SASB"
    assert manifest["input_segments"] == 6
    c = manifest["counts"]
    assert c["accepted_entities"] == 8
    assert c["accepted_relations"] == 6
    assert c["classes"] == 6  # ESGEntity root + 5 ESGMKG classes


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
    # graph grows monotonically (validation never deletes already-accepted nodes)
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) == 6
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) >= 3


def test_phase1_rejects_hallucinated_type(tmp_path):
    """Semantic type verification drops an entity whose type is not in ESGMKG."""
    manifest, _ = _run(tmp_path)
    rej = manifest["rejected_entities"]
    assert len(rej) == 1
    assert rej[0]["proposed_type"] == "Tagline"
    # the rejected entity must NOT appear in the graph
    _, out = _run(tmp_path / "g")
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    labels = [n["data"]["label"] for n in g["nodes"]]
    assert "Net Zero Leader" not in labels


def test_phase2_rejects_illegal_edge(tmp_path):
    """Rule-based schema check drops a CalculationModel->Industry relation."""
    manifest, _ = _run(tmp_path)
    rej = manifest["rejected_relations"]
    assert len(rej) == 1
    assert rej[0]["src_type"] == "CalculationModel"
    assert rej[0]["edge"][1] == "appliesToIndustry"
    # the illegal edge must NOT be in the graph; the legal Metric->Industry one is
    _, out = _run(tmp_path / "g")
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    rels = [(e["data"]["source"], e["data"]["label"], e["data"]["target"])
            for e in g["edges"] if e["data"]["label"] == "appliesToIndustry"]
    assert all(s.startswith("MET:") for (s, _l, _t) in rels)
    assert rels, "the legal Metric appliesToIndustry edge must survive"


def test_deterministic_ids_and_provenance(tmp_path):
    """Distinctive feature 2: deterministic id prefixes + page provenance."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    inst = [n["data"] for n in g["nodes"] if n["data"]["type"] == "instance"]
    prefixes = {"ReportingFramework": "RF:", "MetricCategory": "CAT:",
                "Metric": "MET:", "CalculationModel": "CM:", "Industry": "IND:"}
    for n in inst:
        assert n["id"].startswith(prefixes[n["cls"]])
        assert n["provenance"].startswith("p")  # page-level provenance


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
