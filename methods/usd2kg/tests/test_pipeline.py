"""Tests for the USD2KG pipeline.

MOCK is deterministic, so we assert graph/steps against committed golden
fixtures, check the TTL is valid OWL, and exercise the two distinctive
features: the three-strategy grounding (A name -> B context -> C geometry)
and the naming-regime transform (opaque names shift strategy toward B).
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
    assert manifest["naming_regime"] == "semantic"
    assert manifest["input_prims"] == 13
    assert manifest["counts"]["classes"] >= 10
    assert manifest["counts"]["instances"] == 13
    # the three-strategy ablation telemetry covers every prim
    s = manifest["strategies"]
    assert s["A_name_only"] + s["B_context"] + s["C_cot"] == 13


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
    # graph grows monotonically (grounding never deletes)
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 10


def test_three_strategies_used(tmp_path):
    """All three strategies (A name, B hierarchy, C geometry) get exercised."""
    manifest, _ = _run(tmp_path)
    s = manifest["strategies"]
    assert s["A_name_only"] > 0, "name-only must fire for well-named prims"
    assert s["B_context"] > 0, "hierarchy fallback must fire for obj_042"
    assert s["C_cot"] > 0, "geometry fallback must fire for unknown_blob_X"


def test_opaque_regime_shifts_strategy(tmp_path):
    """Replicates the paper's finding: with opaque names, hierarchy dominates."""
    import copy
    scene = json.loads(
        (METHOD_DIR / "samples" / "usd_scene.json").read_text(encoding="utf-8"))
    scene["naming_regime"] = "opaque"
    scene_dir = tmp_path / "opaque_in"
    scene_dir.mkdir()
    (scene_dir / "usd_scene.json").write_text(
        json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "opaque_out"
    man = pipeline.run(scene_dir, out, backend="mock")
    s = man["strategies"]
    assert s["A_name_only"] == 0, "opaque names cannot match name aliases"
    assert s["B_context"] > s["C_cot"], \
        "hierarchy should dominate geometry under opaque naming"


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
