"""Tests for the Ontogenia pipeline.

With the MOCK backend the pipeline is fully deterministic, so we assert the
graph/steps against committed golden fixtures and check the TTL is valid OWL.
Ontogenia adds a metacognitive self-critique pass per CQ plus a final
whole-ontology refinement pass, so we additionally assert the step count is
~2N+1 and that a self-critique merge actually unified a near-duplicate class.
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

# number of CQs in the sample (non-blank, non-comment lines)
_N_CQS = len([
    ln for ln in (METHOD_DIR / "samples" / "competency_questions.txt")
    .read_text(encoding="utf-8").splitlines()
    if ln.strip() and not ln.strip().startswith("#")
])


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["method"] == "ontogenia"
    assert manifest["input_cqs"] == _N_CQS
    assert manifest["steps"] == 2 * _N_CQS + 1
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


def test_steps_schema_and_count(tmp_path):
    """Steps use the same schema as CQbyCQ (frontend reads these keys) and there
    are ~2N+1 of them (draft + critique per CQ, plus a final refinement)."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    assert len(steps) == 2 * _N_CQS + 1
    assert len(steps) > _N_CQS  # strictly more than CQbyCQ would produce
    for s in steps:
        assert set(s.keys()) == {"step", "cq", "added", "graph"}
        # the cqbycq-compatible 'added' keys are always present
        for k in ("classes", "object_properties", "data_properties"):
            assert k in s["added"]
        assert set(s["graph"].keys()) == {"nodes", "edges"}
        for n in s["graph"]["nodes"]:
            assert set(n["data"].keys()) == {"id", "label", "type", "attributes"}
        for e in s["graph"]["edges"]:
            assert set(e["data"].keys()) == {"id", "source", "target", "label"}
    # the critique and final steps exist and are labelled
    assert any(s["cq"].startswith("(self-critique)") for s in steps)
    assert steps[-1]["cq"] == "(final refinement)"


def test_self_critique_merged_a_duplicate(tmp_path):
    """A drafted near-duplicate ('Subassemblie' from plural 'Subassemblies') is
    merged by self-critique into the existing 'Subassembly'."""
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    merges = [m for s in steps for m in s["added"].get("merged", [])]
    assert merges, "expected at least one self-critique merge"
    assert {"from": "Subassemblie", "into": "Subassembly"} in merges

    # the merged variant must NOT survive in the final ontology; the canonical
    # class must appear exactly once.
    onto = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    ids = [n["data"]["id"] for n in onto["nodes"]]
    assert "Subassemblie" not in ids
    assert ids.count("Subassembly") == 1


def test_final_refinement_attaches_orphan(tmp_path):
    """The final pass connects an orphan class to the generic Entity root."""
    _, out = _run(tmp_path)
    onto = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    ids = [n["data"]["id"] for n in onto["nodes"]]
    assert "Entity" in ids
    sub_edges = [e for e in onto["edges"] if e["data"]["label"] == "subClassOf"]
    assert sub_edges, "expected at least one subClassOf edge from the final pass"
    assert any(e["data"]["target"] == "Entity" for e in sub_edges)


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5
    # subClassOf is emitted as rdfs:subClassOf, not as an owl:ObjectProperty
    subclass_triples = list(g.triples((None, rdflib.RDFS.subClassOf, None)))
    assert len(subclass_triples) >= 1


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
