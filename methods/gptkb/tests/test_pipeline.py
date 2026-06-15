"""Tests for the GPTKB pipeline.

With the MOCK backend the recursive expansion is fully deterministic (a built-in
knowledge table answers each query), so we assert the graph/steps against
committed golden fixtures, check that recursion actually happened, that entities
are consolidated (no duplicate nodes), and that the TTL is valid OWL.
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

CQBYCQ_KEYS = {"nodes", "edges"}
NODE_DATA_KEYS = {"id", "label", "type", "attributes"}
EDGE_DATA_KEYS = {"id", "source", "target", "label"}


def _run(tmp_path):
    out = tmp_path / "out"
    return pipeline.run(METHOD_DIR / "samples", out, backend="mock"), out


def _seeds():
    txt = (METHOD_DIR / "samples" / "seed_entities.txt").read_text(encoding="utf-8")
    return [l.strip() for l in txt.splitlines()
            if l.strip() and not l.strip().startswith("#")]


def test_manifest_counts(tmp_path):
    manifest, _ = _run(tmp_path)
    assert manifest["backend"] == "mock"
    assert manifest["input_seeds"] == 2
    assert manifest["depth_limit"] == 2
    assert manifest["counts"]["entities"] >= 5
    assert manifest["counts"]["relations"] >= 5


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
    # monotonically growing graph as the crawl expands
    sizes = [len(s["graph"]["nodes"]) for s in got]
    assert sizes == sorted(sizes)


def test_graph_schema_matches_cqbycq(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    assert set(got.keys()) == CQBYCQ_KEYS
    assert got["nodes"], "expected non-empty nodes"
    for n in got["nodes"]:
        assert set(n["data"].keys()) == NODE_DATA_KEYS
    for e in got["edges"]:
        assert set(e["data"].keys()) == EDGE_DATA_KEYS


def test_recursion_grew_beyond_seeds(tmp_path):
    manifest, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    ids = [n["data"]["id"] for n in got["nodes"]]
    seeds = _seeds()
    # recursion must have discovered entities not present in the seed list
    assert len(ids) > len(seeds)
    assert set(ids) - set(seeds), "recursion produced no new entities"


def test_entities_are_consolidated(tmp_path):
    _, out = _run(tmp_path)
    got = json.loads((out / "ontology.json").read_text(encoding="utf-8"))
    ids = [n["data"]["id"] for n in got["nodes"]]
    # consolidation/dedup: an entity appears at most once even if many triples
    # reach it.
    assert len(ids) == len(set(ids))


def test_expansion_beyond_depth0(tmp_path):
    _, out = _run(tmp_path)
    steps = json.loads((out / "steps.json").read_text(encoding="utf-8"))
    deeper = [s for s in steps if s["depth"] > 0]
    assert len(deeper) >= 1, "expected at least one expansion step beyond depth 0"


def test_ttl_is_valid_owl(tmp_path):
    _, out = _run(tmp_path)
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(out / "ontology.ttl", format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = list(g.subjects(rdflib.RDF.type, owl_class))
    assert len(classes) >= 5


def test_determinism(tmp_path):
    _, out1 = _run(tmp_path / "a")
    _, out2 = _run(tmp_path / "b")
    assert (out1 / "ontology.json").read_text(encoding="utf-8") == \
           (out2 / "ontology.json").read_text(encoding="utf-8")
    assert (out1 / "steps.json").read_text(encoding="utf-8") == \
           (out2 / "steps.json").read_text(encoding="utf-8")
