# HF-Local Demo — Real On-Device Ontology Extraction

> Project demo. With NO cloud and NO API key, run a **HuggingFace open model directly on this machine's GPU** to extract triples (an ontology) from text.

## 1. One-line summary
For each sentence, ask a local LLM to return (subject, relation, object) triples as JSON, then assemble them into an ontology graph. The same code switches between **MOCK** (no key/GPU, deterministic) and **hf_local** (real GPU inference).

## 2. Key ideas
- **Local inference**: no external API — download an open model (default `Qwen/Qwen2.5-1.5B-Instruct`) via `transformers` and run it on the GPU (`device_map="auto"`). Works with no key and offline (after the first download).
- **Dual backend**: `mock` does rule-based deterministic extraction (stable test goldens); `hf_local` has the real model emit JSON triples. Pick `hf_local` in the site's backend dropdown to run the real model.
- **Robust JSON parsing**: safely extract the `{"triples":[...]}` block from the model response (ignore surrounding prose).

## 3. Construction process (step by step)
1. **Text input** — `text.txt` (auto-split into sentences).
2. **Sentence → triples (loop)** — send each sentence to the LLM (mock or hf_local) and get JSON triples.
3. **Graph merge** — subjects/objects become class nodes, relations become edges, accumulated (deduped). Snapshot per sentence.
4. **Emit** — `ontology.ttl`, `ontology.json`, `steps.json`.

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Free text (auto sentence split) |
| Output | `ontology.ttl` | OWL (Turtle) |
| Output | `ontology.json` | Cytoscape nodes/edges |
| Output | `steps.json` | Per-sentence snapshots |

## 5. LLM backend
- Default `mock`: deterministic with no key/GPU (capitalized subject / relation verb / capitalized object). For tests and the keyless site.
- **`hf_local` (real run)**: downloads `HF_MODEL` (default Qwen2.5-1.5B-Instruct) via `transformers` and runs GPU inference. First run downloads the model (a few GB). Override with env `HF_MODEL` (e.g. `Qwen/Qwen2.5-3B-Instruct`).
- If `transformers`/`torch` are missing it auto-falls back to MOCK (loop never breaks).

## 6. Try it
1. (For real runs) `pip install torch transformers accelerate` — prefer CUDA torch on a GPU.
2. Local: `python pipeline.py samples runs/out --backend hf_local` (downloads once, then GPU inference).
3. Site: choose **hf_local** in the backend dropdown, then **Run**. (Leave it on mock for instant deterministic output.)
