"""Tests for hf-local-demo. The MOCK backend is deterministic (golden-tested).
The real hf_local backend is non-deterministic and is NOT asserted here — prove
it with `python pipeline.py samples runs/out --backend hf_local`.
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


def test_manifest(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 5
    assert manifest["counts"]["object_properties"] >= 4


def test_graph_matches_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    gold = json.loads((METHOD_DIR / "fixtures" / "ontology.json").read_text(encoding="utf-8"))
    assert got == gold


def test_steps_match_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    gold = json.loads((METHOD_DIR / "fixtures" / "steps.json").read_text(encoding="utf-8"))
    assert got == gold


def test_schema_matches_cqbycq(tmp_path):
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(g["nodes"][0]["data"]) == {"id", "label", "type", "attributes"}
    assert set(g["edges"][0]["data"]) == {"id", "source", "target", "label"}


def test_ttl_valid(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph(); g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 5


def test_determinism(tmp_path):
    _, a = _run(tmp_path / "a")
    _, b = _run(tmp_path / "b")
    assert (a / "ontology.json").read_text(encoding="utf-8") == \
           (b / "ontology.json").read_text(encoding="utf-8")
