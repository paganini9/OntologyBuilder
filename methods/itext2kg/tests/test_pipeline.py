"""Tests for the iText2KG pipeline.

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

N_DOCS = 4  # samples/text.txt has 4 blank-line-separated documents


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["method"] == "itext2kg"
    assert manifest["input_documents"] == N_DOCS
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5


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
    # one snapshot per document, monotonically growing graph (incremental)
    assert len(got) == N_DOCS
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_steps_schema_matches_cqbycq(tmp_path):
    """Each step entry must carry the cqbycq contract keys (extra keys allowed)."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert {"step", "cq", "added", "graph"} <= set(s)
        assert {"classes", "object_properties", "data_properties"} <= set(s["added"])
        assert {"nodes", "edges"} == set(s["graph"])
    # ontology.json node/edge schema == cqbycq
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    for n in graph["nodes"]:
        assert {"id", "label", "type", "attributes"} <= set(n["data"])
    for e in graph["edges"]:
        assert {"id", "source", "target", "label"} <= set(e["data"])


def test_cross_document_dedup(tmp_path):
    """A duplicate entity reused across documents must NOT spawn a second node.

    Doc1 introduces "Pump"; doc3 says "Pumps" (plural) and doc4 reuses "Pump".
    All collapse to the single canonical class "Pump"; no "Pumps" node exists.
    "Motor" (doc1) and "Torque" (doc2) are also reused later without duplication.
    """
    _, out = _run(tmp_path)
    graph = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    ids = [n["data"]["id"] for n in graph["nodes"]]
    # canonical present exactly once; variant absent
    assert ids.count("Pump") == 1
    assert "Pumps" not in ids
    assert ids.count("Motor") == 1
    assert ids.count("Torque") == 1

    # the later documents must add NO new "Pump"/"Motor"/"Torque" class
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    doc3_added = steps[2]["added"]["classes"]
    doc4_added = steps[3]["added"]["classes"]
    assert "Pump" not in doc3_added and "Pumps" not in doc3_added
    assert "Pump" not in doc4_added
    assert "Torque" not in doc4_added
    # but the deduped edge still references the canonical "Pump"
    edge_targets = {(e["data"]["source"], e["data"]["target"])
                    for e in graph["edges"]}
    assert ("Pump", "Steel") in edge_targets  # from doc3 "Pumps are made of Steel"


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 1
    owl_op = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, owl_op))) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
