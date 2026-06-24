"""Tests for the ATOM temporal-KG pipeline.

MOCK backend is fully deterministic, so we assert graph/steps against committed
golden fixtures, check the TTL is valid OWL, and check the two distinctive
features: dual-time (observed vs valid) tagging and atomic-fact merging that
widens a fact's validity interval across re-observations.
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
    assert manifest["input_notes"] == 5
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["temporal_facts"] >= 6
    assert manifest["counts"]["dual_timed"] >= 1
    assert manifest["counts"]["bounded_intervals"] >= 1


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
    # one snapshot per note, monotonically growing graph
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_dual_time_and_merge(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    edges = [e["data"] for e in g["edges"]]
    # dual-time: every relation has an observed time; some have a valid_from that
    # differs from observed (info observed at one time, valid since another).
    assert all(e.get("observed") for e in edges)
    assert any(e.get("valid_from") and e["valid_from"] != e["observed"] for e in edges)
    # at least one bounded validity interval (both valid_from and valid_until)
    assert any(e.get("valid_from") and e.get("valid_until") for e in edges)
    # merge: the re-observed "supplies" fact carries the widened upper bound 2026
    supplies = [e for e in edges if e["label"].startswith("supplies")]
    assert supplies and supplies[0]["valid_until"] == "2026"


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
