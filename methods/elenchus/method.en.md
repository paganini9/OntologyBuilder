# Elenchus — Building a Knowledge Base via Prover-Skeptic Dialogue

> Source: Bradley P. Allen, *Elenchus: Generating Knowledge Bases from Prover-Skeptic Dialogues*, arXiv:2603.06974 (2026). Code: github.com/bradleypallen/elenchus.

## 1. One-line summary
Grow a knowledge base through an **adversarial two-role dialogue**: a **prover** asserts each candidate claim, a **skeptic** challenges it, and only claims that survive the dialectic — parseable, consistent, non-redundant — are accepted; the rest are **rejected**.

## 2. Key ideas
- **Elenchus**: the Socratic method of cross-examination — knowledge is established by surviving challenges, not by assertion alone.
- **Prover (assert)**: parses a natural-language claim into a candidate triple `(subject, relation, object)` and puts it forward.
- **Skeptic (challenge)**: tests the candidate against the KB built so far and returns a verdict `accepted` / `rejected` with a reason.
- **Adversarial / bilateral, not self-critique**: unlike Ontogenia's single self-critique loop (one model criticising *its own* output), the asserting role and the challenging role are **distinct**. The verdict is contested rather than self-confirmed, so some claims are genuinely **thrown out** of the KB.
- **Survival = membership**: only accepted claims enter the KB graph and the OWL output. Rejected claims are recorded (for transparency) but excluded.

## 3. Construction process (step by step)
1. **Collect claims** — one candidate claim per line in `claims.txt`, each a natural sentence expressing a triple (e.g. "A Motor drives a Pump").
2. **Prover asserts (loop)** — for each claim the prover (LLM or MOCK heuristic) parses it into `{subject, relation, object}`.
3. **Skeptic challenges (loop)** — the skeptic rejects the candidate if it is:
   - **(a) unparseable** — cannot be read as a full subject–relation–object triple;
   - **(b) contradictory** — same subject+relation already accepted with a *different* object, or the reverse edge is already accepted;
   - **(c) redundant** — duplicates an already-accepted claim.
   Otherwise it **accepts**.
4. **Update KB** — accepted claims are added to the growing graph (their classes and the object property). Each claim produces one snapshot recording the prover's triple, the skeptic's verdict + reason, and the resulting graph — so you can replay the debate.
5. **Emit** — `ontology.ttl` (OWL/Turtle, accepted only), `ontology.json` (graph), and `steps.json` (per-claim snapshots).

## 4. Input / Output
| Kind | File | Notes |
|------|------|-------|
| Input | `claims.txt` | candidate claims (one per line, `#` comments / blanks ignored) |
| Output | `ontology.ttl` | OWL of the surviving KB (Turtle) — accepted triples only |
| Output | `ontology.json` | Cytoscape nodes/edges (for visualization) — accepted only |
| Output | `steps.json` | per-claim snapshots (prover/skeptic/verdict) — for replay |

## 5. LLM backend
- Default `mock`: runs deterministically with no key (stable test golden files). The prover extracts capitalized nouns as the subject/object and a relational verb (drives/produces/regulates/powers …) as the relation; the skeptic applies the (a)/(b)/(c) rules against the accumulated KB.
- `api` (`gemini`/`anthropic`): with a key in the env, a real LLM plays the prover and an independent LLM plays the skeptic for richer challenges. With no key it auto-falls back to MOCK.

## 6. Try it
1. Edit `samples/claims.txt` — add a claim that contradicts or duplicates another, or one that is not a full triple, and watch it get rejected.
2. Hit the site's **Run** button (or `python pipeline.py samples runs/out --backend mock`).
3. Use the step slider to watch the prover-skeptic debate and the KB grow only with accepted claims.
