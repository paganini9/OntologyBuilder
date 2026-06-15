# AutoSchemaKG — dynamic schema induction + extraction

## One-line summary
Build a knowledge graph from raw text with **zero predefined schema**: the system extracts triples *and* induces the schema (entity types + relation types) **bottom-up from the data itself**.

## Core idea
Traditional KG/ontology pipelines start from a schema a human wrote (classes, properties) and force the text into it. AutoSchemaKG (Bai et al., arXiv 2505.23628, 2025) flips this: the schema is **a product of extraction, not an input**.

- **No schema is given.** The model reads text and pulls out `(subject, relation, object)` triples first.
- **The schema emerges from the instances.** Every extracted entity is assigned a TYPE, and every relation label becomes a relation type — all induced from what was actually found in the corpus.
- This makes it suitable for open-domain, web-scale text where you cannot enumerate the schema in advance.

The key point to remember: in AutoSchemaKG the ontology/schema is **INDUCED from the data, not supplied beforehand**.

## Construction process (step by step)
1. **Stage A — Triple extraction.** Each sentence is sent to the LLM, which returns triples `(subject, relation, object)`. Subjects and objects become *instances* (concrete entities); relation labels are collected. One snapshot step per sentence shows the instance graph growing.
2. **Stage B — Schema induction (bottom-up).** Once instances exist, each one is assigned an entity TYPE by a deterministic induction rule (in the mock: a small keyword/suffix table → `Device` / `Material` / `System` / `Entity`). The distinct relation labels become relation types. A class node is added per induced type, and an `instanceOf` edge links each instance to its type. This is the one step where the *schema* appears — it was never given.
3. **Serialization.** Induced types become `owl:Class`, instances become `owl:NamedIndividual` typed by their induced class, and relations become `owl:ObjectProperty` with the corresponding triples between individuals.

## Inputs and outputs

| | File | Description |
|---|---|---|
| Input | `samples/text.txt` | Free text, one sentence per line (or `.`-separated). No schema. |
| Output | `ontology.ttl` | Induced schema + instances as OWL/Turtle (rdflib). |
| Output | `ontology.json` | Cytoscape graph: class nodes (induced types) + instance nodes + relation/`instanceOf` edges. |
| Output | `steps.json` | One snapshot per sentence (extraction) plus a final `(schema induction)` step. |
| Output | `manifest.json` | Backend, counts (instances / induced classes / triples / relations). |

## LLM backend
The extraction step (Stage A) is the only LLM call, accessed through `backend.llm.get_backend`. With `--backend mock` a deterministic `mock_responder` parses sentences into triples, so the whole pipeline runs **with no API key** and produces reproducible output. Schema induction (Stage B) is a deterministic post-process and never needs the LLM. Real backends (`api`: gemini / anthropic) can replace Stage A when keys are configured.

## Try it yourself
```bash
python methods/autoschemakg/pipeline.py methods/autoschemakg/samples runs/out --backend mock
python -m pytest methods/autoschemakg/tests/ -q
```
Open `runs/out/ontology.json` in the site viewer to watch instances get extracted first, then the induced classes appear in the final schema-induction step.
