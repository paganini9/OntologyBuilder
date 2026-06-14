"""Tests for the CoDe-KG pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures, check the TTL is valid OWL, and
verify the coreference rule actually fired. Real-backend output is
non-deterministic and is therefore NOT asserted here.
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
    assert manifest["input_sentences"] == 6
    assert manifest["counts"]["entities"] >= 5
    assert manifest["counts"]["relations"] >= 5
    assert manifest["counts"]["triples"] >= 5
    # coreference resolved at least one pronoun
    assert manifest["coref_resolved"] >= 1


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
    # one snapshot per sentence, monotonically growing graph
    assert len(got) == 6
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_steps_schema_matches_cqbycq(tmp_path):
    """Each step must carry the keys the frontend reads (same as cqbycq)."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    for s in steps:
        assert set(("step", "cq", "added", "graph")) <= set(s.keys())
        assert set(s["added"].keys()) == {
            "classes", "object_properties", "data_properties"}
        assert set(s["graph"].keys()) == {"nodes", "edges"}
        for n in s["graph"]["nodes"]:
            assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
        for e in s["graph"]["edges"]:
            assert set(e["data"].keys()) == {"id", "source", "target", "label"}


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    assert len(g) >= 1
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    obj_prop = rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty")
    assert len(list(g.subjects(rdflib.RDF.type, obj_prop))) >= 5


def test_coreference_applied(tmp_path):
    """A pronoun ("It") must have been replaced by an entity, and that entity
    must surface as a triple subject in the resolved sentence."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    changed = [s for s in steps if s.get("coref", {}).get("changed")]
    assert changed, "expected at least one coreference replacement"
    # the step whose raw sentence starts with the pronoun "It"
    it_step = next(s for s in steps if s["coref"]["raw"].startswith("It "))
    assert "It " not in it_step["coref"]["resolved"]
    # the resolved subject (Engine) appears as a triple subject / edge source
    subjects = {e["data"]["source"] for e in it_step["graph"]["edges"]}
    assert "Engine" in subjects


def test_complexity_profiles_present(tmp_path):
    """The rule classifier must assign more than one complexity label."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    labels = {s["complexity"] for s in steps}
    assert len(labels) >= 2
    assert labels <= {"simple", "compound", "complex", "compound-complex"}


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
