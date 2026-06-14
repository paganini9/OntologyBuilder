"""Tests for the ODKE+ 5-stage pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the generation-
verification separation (a candidate is dropped at the grounder) plus TTL
validity. Real-backend output is non-deterministic and is NOT asserted here.
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
    assert manifest["method"] == "odke-plus"
    assert manifest["backend"] == "mock"
    assert manifest["input_entities"] == 4
    c = manifest["counts"]
    assert c["candidates"] >= 1
    assert c["verified"] >= 1
    # generation-verification separation: some candidates are dropped.
    assert c["dropped"] >= 1
    assert c["verified"] < c["candidates"]
    assert c["verified"] + c["dropped"] == c["candidates"]


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
    """ontology.json / steps graph entries use the same keys as cqbycq."""
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(graph.keys()) == {"nodes", "edges"}
    for n in graph["nodes"]:
        assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
    for e in graph["edges"]:
        assert set(e["data"].keys()) == {"id", "source", "target", "label"}
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert "step" in s and "cq" in s and "graph" in s
        assert set(s["graph"].keys()) == {"nodes", "edges"}


def test_five_stages_present(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    assert len(steps) == 5
    assert [s["step"] for s in steps] == [1, 2, 3, 4, 5]
    assert [s["stage"] for s in steps] == [
        "extraction-initiator", "evidence-retriever", "hybrid-extractor",
        "grounder", "corroborator"]
    assert [s["cq"] for s in steps] == [
        "(initiate)", "(retrieve)", "(extract)", "(ground/verify)",
        "(corroborate)"]


def test_candidate_dropped_at_grounder(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    extract = next(s for s in steps if s["stage"] == "hybrid-extractor")
    ground = next(s for s in steps if s["stage"] == "grounder")
    extracted = extract["detail"]["candidates"]
    kept = ground["detail"]["kept"]
    dropped = ground["detail"]["dropped"]
    assert len(dropped) >= 1
    assert len(kept) == len(extracted) - len(dropped)
    assert len(kept) < len(extracted)


def test_final_graph_only_verified(tmp_path):
    """Final graph edges must all correspond to grounder-kept candidates."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    ground = next(s for s in steps if s["stage"] == "grounder")
    kept = {(c["subject"], c["relation"], c["object"])
            for c in ground["detail"]["kept"]}
    dropped = {(c["subject"], c["relation"], c["object"])
               for c in ground["detail"]["dropped"]}
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    for e in graph["edges"]:
        d = e["data"]
        triple = (d["source"], d["label"], d["target"])
        assert triple in kept
        assert triple not in dropped
    # an object that was ONLY ever dropped must not appear as a node.
    kept_terms = {t for tr in kept for t in (tr[0], tr[2])}
    node_ids = {n["data"]["id"] for n in graph["nodes"]}
    for (_, _, o) in dropped:
        if o not in kept_terms:
            assert o not in node_ids


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_class))) >= 4
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    for fn in ("ontology.json", "steps.json", "ontology.ttl"):
        assert (out1 / fn).read_text(encoding="utf-8") == \
               (out2 / fn).read_text(encoding="utf-8")
