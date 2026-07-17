# HybridRAG Evaluation Set — README

`test_dataset.json` contains **134 questions** against the PRPC industrial data twin, built
for a GraphRAG-only vs VectorRAG-only vs HybridRAG ablation study. Every expected answer was
computed programmatically from `world_model.json` — none were hand-guessed — so scoring is
exact-match / entity-overlap friendly.

## Fields per question

- `category` — question type (see below).
- `eval_dimension` — which of your stated evaluation focuses this probes.
- `question` / `expected_answer` — the prompt and ground-truth answer.
- `expected_entities` — KG node IDs (`knowledge_graph/kg_nodes_edges.json`) that a correct
  answer must surface. Use this for entity-extraction and linkage-completeness scoring.
- `supporting_doc_ids` / `supporting_chunk_ids` — source documents/chunks a RAG system
  should cite.
- `ideal_retrieval_strategy` — `vector`, `graph`, or `hybrid`. This is the hypothesis for
  which pipeline *should* win on that question — use it to structure your ablation
  comparison table (e.g. "did GraphRAG-only actually outperform VectorRAG-only on the 47
  questions labeled `graph`?").
- `naive_keyword_hit_count` — number of raw documents in the corpus that mention the
  question's primary entity. A high count simulates the real "7-12 disconnected systems"
  problem: a keyword search returns many documents a human would have to read manually,
  where RAG should return one grounded answer. Use `expected_answer_time` you record during
  testing against this count as your time-to-answer-vs-traditional-search metric.
- `unanswerable` — if `true`, the correct behavior is to decline / state "not found" rather
  than hallucinate. Score hallucination resistance on these 8 items.

## Category breakdown

| Category | Count | Eval dimension | Typical ideal strategy |
|---|---|---|---|
| entity_extraction | 44 | Entity extraction accuracy across doc types | vector |
| single_hop_factual | 25 | Query answer quality (simple lookup) | vector |
| multi_hop_relational | 20 | Query answer quality + KG linkage completeness | graph |
| temporal_reasoning | 9 | Answer quality over dated/sequential events | hybrid |
| compliance_gap_detection | 9 | Compliance gap detection accuracy | graph |
| cross_functional_discovery | 19 | Cross-functional knowledge discovery | graph/hybrid |
| unanswerable | 8 | Hallucination resistance | n/a |

## Suggested scoring approach

1. **Answer quality:** exact/fuzzy match of `expected_answer`, or entity-overlap (recall of
   `expected_entities` in the system's cited sources).
2. **Entity extraction accuracy:** for `entity_extraction` items, compare the system's
   extracted entity list against `expected_entities` (precision/recall/F1).
3. **KG linkage completeness:** for `multi_hop_relational` and `compliance_gap_detection`
   items, check whether the system actually traversed the relationship (e.g. found the
   *absence* of a regulatory submission for a reportable incident — this is the hardest
   class for pure VectorRAG, since it requires reasoning over what's *missing*, not just
   what's retrievable).
4. **Compliance gap detection accuracy:** score against the 9 `compliance_gap_detection`
   items specifically — these encode real, computed gaps (overdue inspections, unreported
   incidents, compound high-criticality risk) rather than synthetic decoys.
5. **Cross-functional discovery:** score the 19 `cross_functional_discovery` items, which
   deliberately span maintenance + safety + regulatory + procurement records that would
   normally sit in separate systems.
6. **Time-to-answer vs. traditional search:** for each question, compare system latency
   against a simulated keyword search cost proportional to `naive_keyword_hit_count`
   (e.g. assume N seconds per document a human must open and read).

## Running the ablation

Run the full set through three configurations — VectorRAG-only (chunks.jsonl + embedding
index), GraphRAG-only (kg_nodes_edges.json + graph traversal), and HybridRAG (both) — and
compare scores per category. The `ideal_retrieval_strategy` field is a hypothesis, not
ground truth about your system's behavior — the whole point of the ablation is to see where
it holds and where it doesn't.
