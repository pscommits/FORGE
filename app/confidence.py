"""
confidence.py -- A deterministic, retrieval-based confidence heuristic for FORGE_Application.

This is intentionally NOT a calibrated probability and does not make an extra LLM call (no
"LLM-as-judge" pass). It is a fast, free, explainable signal derived purely from what the
retrieval step actually found:

  - vector mode:  mean cosine similarity of the retrieved chunks.
  - graph mode:   how many entities were linked from the question, and how rich the resulting
                   subgraph is (nodes/edges).
  - hybrid mode:  a blend of both signals.

Any answer that reads as a refusal (per evaluate.is_correct_refusal) has its score capped low
-- a correct "I don't know" is good behavior, but it is not a confident, substantive claim, so
it should not display a high confidence score.
"""
import config
from evaluate import is_correct_refusal

HIGH_THRESHOLD = 70
MEDIUM_THRESHOLD = 40
REFUSAL_SCORE_CAP = 15


def _band(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def _vector_base(retrieval_meta: dict):
    scores = retrieval_meta.get("vector_scores") or []
    if not scores:
        return 0, "no vector hits were retrieved"
    mean_score = sum(scores) / len(scores)
    base = round(mean_score * 100)
    return base, f"vector mean similarity {mean_score:.2f} across {len(scores)} chunk(s)"


def _graph_base(retrieval_meta: dict):
    linked_entities = retrieval_meta.get("linked_entities") or []
    subgraph_nodes = retrieval_meta.get("subgraph_nodes") or 0
    subgraph_edges = retrieval_meta.get("subgraph_edges") or 0

    if not linked_entities:
        return 0, "no entities from the question were linked to the knowledge graph"

    entity_component = min(len(linked_entities) / 3, 1.0) * 60
    size_component = min(subgraph_nodes / max(config.GRAPH_MAX_NODES_IN_CONTEXT, 1), 1.0) * 25
    edge_component = min(subgraph_edges / 20, 1.0) * 15
    base = round(entity_component + size_component + edge_component)
    detail = (f"linked {len(linked_entities)} entit{'y' if len(linked_entities) == 1 else 'ies'} "
              f"into a {subgraph_nodes}-node/{subgraph_edges}-edge subgraph")
    return base, detail


def score_confidence(mode: str, retrieval_meta: dict, source_documents: list, answer_text: str) -> dict:
    """Pure function -- no I/O, no LLM calls. Returns:
        {score: int 0-100, band: "High"|"Medium"|"Low", explanation: str,
         components: {vector_base, graph_base, refusal_detected}}
    """
    retrieval_meta = retrieval_meta or {}
    vector_base, vector_detail = (None, None)
    graph_base, graph_detail = (None, None)

    if mode == "vector":
        vector_base, vector_detail = _vector_base(retrieval_meta)
        base = vector_base
        explanation = f"Vector mode: {vector_detail}."
    elif mode == "graph":
        graph_base, graph_detail = _graph_base(retrieval_meta)
        base = graph_base
        explanation = f"Graph mode: {graph_detail}."
    else:  # hybrid
        vector_base, vector_detail = _vector_base(retrieval_meta)
        graph_base, graph_detail = _graph_base(retrieval_meta)
        base = round(0.5 * vector_base + 0.5 * graph_base)
        explanation = f"Hybrid mode: {vector_detail}; {graph_detail}."

    refusal_detected = is_correct_refusal(answer_text or "")
    score = base
    if refusal_detected:
        score = min(base, REFUSAL_SCORE_CAP)
        explanation = ("The model declined to answer (correctly, if the question is truly "
                        "unanswerable from the available records), so confidence reflects "
                        "that this is not a substantive grounded claim, regardless of "
                        f"retrieval strength. {explanation}")

    score = max(0, min(100, int(score)))
    explanation += f" Blended score {score}/100."

    return {
        "score": score,
        "band": _band(score),
        "explanation": explanation,
        "components": {
            "vector_base": vector_base,
            "graph_base": graph_base,
            "refusal_detected": refusal_detected,
        },
    }
