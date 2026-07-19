"""
evaluate.py -- Deterministic, reproducible scoring for the HybridRAG ablation benchmark.
No extra Groq calls are used for scoring (see README for the optional LLM-as-judge variant).

Three signals are computed per question:
  1. entity_recall     -- fraction of `expected_entities` (KG node IDs) that the retrieval
                           step actually surfaced (via retrieved_entity_ids). This measures
                           retrieval/linkage quality independent of how the LLM phrased its
                           answer -- the right signal for entity_extraction_accuracy and
                           kg_linkage_completeness.
  2. answer_overlap     -- normalized token overlap between the generated answer and the
                           expected_answer string. A rough, fast proxy for answer_quality.
  3. refusal_correct    -- for `unanswerable` questions only: did the system correctly
                           decline / say it couldn't find the information, instead of
                           fabricating an answer? Measures hallucination_resistance.
"""
import re
from collections import defaultdict

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is", "was", "were",
    "be", "been", "with", "as", "by", "this", "that", "it", "its", "are", "which", "who",
    "what", "when", "how", "does", "do", "did", "has", "have", "had", "not", "no", "any",
}

REFUSAL_PHRASES = [
    "cannot find", "can't find", "not present", "not available", "no information",
    "not found", "does not contain", "doesn't contain", "unable to find", "no record",
    "not mentioned", "not in the", "insufficient information", "cannot answer",
    "don't have", "do not have", "no data", "not documented",
]


def _tokenize(text: str):
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


def entity_recall(expected_entities, retrieved_entity_ids):
    if not expected_entities:
        return None, [], []
    retrieved = set(retrieved_entity_ids or [])
    matched = [e for e in expected_entities if e in retrieved]
    missing = [e for e in expected_entities if e not in retrieved]
    return len(matched) / len(expected_entities), matched, missing


def answer_overlap(expected_answer: str, generated_answer: str):
    exp_tokens = set(_tokenize(expected_answer))
    gen_tokens = set(_tokenize(generated_answer))
    if not exp_tokens:
        return None
    return len(exp_tokens & gen_tokens) / len(exp_tokens)


def is_correct_refusal(generated_answer: str) -> bool:
    lower = generated_answer.lower()
    return any(phrase in lower for phrase in REFUSAL_PHRASES)


def score_result(question_spec: dict, pipeline_result: dict) -> dict:
    """Score one (question, pipeline_result) pair. `question_spec` is a row from
    eval/test_dataset.json; `pipeline_result` is the dict returned by RAGPipeline.answer()."""
    expected_entities = question_spec.get("expected_entities", [])
    retrieved_entity_ids = pipeline_result.get("retrieval_meta", {}).get("retrieved_entity_ids", [])
    recall, matched, missing = entity_recall(expected_entities, retrieved_entity_ids)

    overlap = answer_overlap(question_spec.get("expected_answer", ""), pipeline_result.get("answer", ""))

    refusal_ok = None
    if question_spec.get("unanswerable"):
        refusal_ok = is_correct_refusal(pipeline_result.get("answer", ""))

    return {
        "test_id": question_spec["test_id"],
        "category": question_spec["category"],
        "eval_dimension": question_spec["eval_dimension"],
        "mode": pipeline_result["mode"],
        "entity_recall": recall,
        "entities_matched": matched,
        "entities_missing": missing,
        "answer_token_overlap": overlap,
        "refusal_correct": refusal_ok,
        "naive_keyword_hit_count": question_spec.get("naive_keyword_hit_count", 0),
        "latency_total_s": pipeline_result.get("latency_total_s"),
        "latency_retrieval_s": pipeline_result.get("latency_retrieval_s"),
        "latency_generation_s": pipeline_result.get("latency_generation_s"),
    }


def aggregate_scores(scored_rows: list) -> dict:
    """Aggregate per-question scores into summary tables: overall, by mode, by category,
    by mode x category, and by mode x eval_dimension."""
    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    by_mode = defaultdict(list)
    by_mode_category = defaultdict(list)
    by_mode_dimension = defaultdict(list)
    for r in scored_rows:
        by_mode[r["mode"]].append(r)
        by_mode_category[(r["mode"], r["category"])].append(r)
        by_mode_dimension[(r["mode"], r["eval_dimension"])].append(r)

    def summarize(rows):
        refusal_rows = [r for r in rows if r["refusal_correct"] is not None]
        return {
            "n_questions": len(rows),
            "avg_entity_recall": _avg([r["entity_recall"] for r in rows]),
            "avg_answer_token_overlap": _avg([r["answer_token_overlap"] for r in rows]),
            "refusal_accuracy": (_avg([1.0 if r["refusal_correct"] else 0.0 for r in refusal_rows])
                                  if refusal_rows else None),
            "avg_latency_total_s": _avg([r["latency_total_s"] for r in rows]),
            "avg_naive_keyword_hit_count": _avg([r["naive_keyword_hit_count"] for r in rows]),
        }

    return {
        "by_mode": {mode: summarize(rows) for mode, rows in sorted(by_mode.items())},
        "by_mode_category": {f"{mode} / {cat}": summarize(rows)
                              for (mode, cat), rows in sorted(by_mode_category.items())},
        "by_mode_dimension": {f"{mode} / {dim}": summarize(rows)
                               for (mode, dim), rows in sorted(by_mode_dimension.items())},
    }
