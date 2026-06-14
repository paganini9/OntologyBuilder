# CoDe-KG — Triple Extraction via Coreference Resolution + Sentence Decomposition

> Source: Anuyah, Kaushik, Dwarampudi, Shiradkar, Durresi, Chakraborty, *Automated Knowledge Graph Construction using Large Language Models and Sentence Complexity Modelling* (CoDe-KG), EMNLP 2025 (arXiv:2509.17289). Code: github.com/KaushikMahmud/CoDe-KG_EMNLP_2025.

## 1. One-line summary
Process free text as **coreference resolution → sentence decomposition → complexity-based prompt selection → triple extraction → KG merge**, so that even long, pronoun-heavy text yields a robust (subject, relation, object) triple-based ontology.

## 2. Key ideas
- **Coreference Resolution**: replace referring expressions ("it", "this part") with the actual entity names. The paper uses Mixtral + FICL prompts to build a shortened-term → full-referent JSON map and substitutes tokens. This stage lifts recall on rare relations by over 20 points.
- **Sentence Decomposition**: break complex sentences into simpler clauses so the extractor handles one fact at a time, raising accuracy.
- **Complexity-based prompt selection**: classify each sentence by complexity (simple / compound / complex / compound-complex) and pick the matching prompt–model combination (hybrid chain-of-thought + few-shot). The paper uses a fine-tuned BERT-Large classifier; this implementation replaces it with a deterministic rule classifier (clause/conjunction counts) so it runs with no GPU and no fine-tuning.
- **Triple**: (entity_1, relationship, entity_2). These become the nodes (entities/classes) and edges (relations) of the ontology graph.

## 3. Construction process (step by step)
1. **Collect text** — one `text.txt` with free-form body (paragraphs); blank lines separate paragraphs.
2. **Coreference resolution** — replace pronouns / shortened references with their nearest antecedent entity (LLM backend or MOCK rule).
3. **Sentence split & decompose** — split the resolved text into sentences and break complex ones into simpler clauses.
4. **Complexity classification → prompt selection** — classify each (decomposed) sentence as simple/compound/complex/compound-complex and select the matching extraction prompt.
5. **Triple extraction** — with the selected prompt, extract (entity_1, relationship, entity_2) triples from each sentence.
6. **KG/ontology merge** — accumulate triples into a growing graph; identical entities collapse into one node (class), duplicate triples are dropped. A snapshot is recorded per sentence so you can watch the graph grow.
7. **Emit** — write `ontology.ttl` (OWL/Turtle), `ontology.json` (Cytoscape graph), and `steps.json` (per-step snapshots).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `text.txt` | Free-form body text (paragraphs); blanks separate paragraphs, sentences auto-split |
| Output | `ontology.ttl` | Triple-based OWL ontology (Turtle) |
| Output | `ontology.json` | Cytoscape nodes (entities/classes) / edges (relations) for visualization |
| Output | `steps.json` | Per-sentence (per-step) snapshots — for step replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable test goldens). Coreference uses a simple rule (pronoun → nearest preceding capitalized noun phrase); triples use a "subject (capitalized noun) – relation verb – object (capitalized noun)" pattern.
- `gemini`/`anthropic` (api): if a key is in the env, a real LLM performs coreference, decomposition and extraction more precisely. With no key it auto-falls back to MOCK.
- The paper routes different models per complexity (Mixtral, LLaMA-3.1-8B, LLaMA-3.3-70B). This implementation consolidates to a single configurable backend and reflects complexity only through prompt selection (no fine-tuning, no GPU).

## 6. Try it
1. Replace `samples/text.txt` with your own document (manual, description, etc.).
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch triples get added and the graph grow as each sentence is processed.
