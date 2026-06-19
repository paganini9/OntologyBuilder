"""Tests for the RAGA (Read-Search-Verify-Construct agent) pipeline.

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
    assert manifest["method"] == "raga"
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 6
    assert manifest["counts"]["candidates"] >= manifest["counts"]["verified"]
    assert manifest["counts"]["dropped"] >= 1
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 4


def test_graph_matches_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "ontology.json").read_text(encoding="utf-8"))
    assert got == golden
    # final graph is non-empty
    assert len(got["nodes"]) >= 1 and len(got["edges"]) >= 1


def test_steps_match_golden(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    golden = json.loads(
        (METHOD_DIR / "fixtures" / "steps.json").read_text(encoding="utf-8"))
    assert got == golden


def test_schema_matches_cqbycq(tmp_path):
    """Graph schema must match cqbycq's _Model.to_graph() so the frontend renders."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(g.keys()) == {"nodes", "edges"}
    for n in g["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
        assert n["data"]["type"] == "class"
    for e in g["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}


def test_per_sentence_steps_have_react_keys(tmp_path):
    """One step per sentence, each carrying the Read/Search/Verify trace and cq."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    sentences = (METHOD_DIR / "samples" / "text.txt").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(steps) == len([s for s in sentences if s.strip()])
    for i, s in enumerate(steps, 1):
        assert s["step"] == i
        assert isinstance(s["cq"], str) and s["cq"]
        assert "read" in s and "candidates" in s["read"]
        assert "search" in s and "existing_entities" in s["search"]
        assert "verify" in s and "kept" in s["verify"] and "dropped" in s["verify"]
        assert "graph" in s


def test_at_least_one_dropped_by_verify(tmp_path):
    """The sample is constructed so VERIFY drops >=1 candidate (implied object)."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    dropped = [d for s in steps for d in s["verify"]["dropped"]]
    assert len(dropped) >= 1
    # every drop has an evidence-anchoring reason
    for d in dropped:
        assert "anchored" in d["reason"]


def test_final_edges_are_all_verified(tmp_path):
    """Every final edge must correspond to a VERIFY-kept (constructed) triple."""
    _, out = _run(tmp_path)
    g = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    kept = {(k["subject"], k["relation"], k["object"])
            for s in steps for k in s["verify"]["kept"]}
    dropped = {(d["subject"], d["relation"], d["object"])
               for s in steps for d in s["verify"]["dropped"]}
    for e in g["edges"]:
        triple = (e["data"]["source"], e["data"]["label"], e["data"]["target"])
        assert triple in kept
        assert triple not in dropped


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_op))) >= 4


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
