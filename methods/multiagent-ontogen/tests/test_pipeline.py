"""Tests for the Multi-Agent Ontology Generation pipeline.

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
    assert manifest["backend"] == "mock"
    assert manifest["input_sentences"] == 7
    assert manifest["roles"] == ["DomainExpert", "Manager", "Coder", "QA"]
    assert manifest["counts"]["classes"] >= 5
    assert manifest["counts"]["object_properties"] >= 5
    assert manifest["counts"]["qa_removed"] >= 0


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


def test_step_schema_matches_cqbycq(tmp_path):
    """Every step must carry the shared cqbycq schema keys + a valid graph."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert {"step", "cq", "added", "graph"} <= set(s)
        assert {"classes", "object_properties", "data_properties"} <= set(s["added"])
        g = s["graph"]
        assert set(g) == {"nodes", "edges"}
        for n in g["nodes"]:
            assert {"id", "label", "type", "attributes"} <= set(n["data"])
        for e in g["edges"]:
            assert {"id", "source", "target", "label"} <= set(e["data"])


def test_four_role_phases_present(tmp_path):
    """All four artifact-driven roles must appear as step phases, in order."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    roles = [s.get("role") for s in steps]
    assert "DomainExpert" in roles
    assert "Manager" in roles
    assert "Coder" in roles
    assert "QA" in roles
    # planning-first ordering: experts, then plan, then code, then QA last.
    assert roles.index("Manager") < roles.index("Coder") < roles.index("QA")
    assert all(r == "DomainExpert" for r in roles[:roles.index("Manager")])
    # the cq labels are role-tagged
    assert any(s["cq"].startswith("(DomainExpert)") for s in steps)
    assert any(s["cq"] == "(Manager) plan" for s in steps)
    assert any(s["cq"] == "(Coder) emit" for s in steps)
    assert any(s["cq"] == "(QA) validate" for s in steps)


def test_qa_prunes(tmp_path):
    """The QA step must exist and report a (>=0) removal list."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    qa = [s for s in steps if s.get("role") == "QA"]
    assert len(qa) == 1
    removed = qa[0]["removed"]
    assert isinstance(removed, list)
    assert len(removed) >= 0
    # the sample text is crafted so QA actually prunes a duplicate + a self-loop
    reasons = {r["reason"] for r in removed}
    assert "duplicate" in reasons
    assert "self-loop" in reasons


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
