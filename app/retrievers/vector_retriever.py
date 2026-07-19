"""VectorRAG retrieval -- deployment variant.

FORGE_Application's VectorRetriever uses ChromaDB with real ONNX/MiniLM embeddings. On
Vercel's serverless Python runtime that combination risks exceeding the function size limit
(chromadb + onnxruntime pull in a large native dependency tree) and ChromaDB's SQLite
persistence can hit read-only-filesystem issues in that environment. At this corpus size (667
chunks) a full vector database is unnecessary anyway.

This variant loads a small precomputed, flat JSON vector store (local_db/vectors.json, built by
scripts/build_vectors.py using the same dependency-free HashingEmbeddingFunction from
embeddings.py) once into memory, and does brute-force cosine similarity with numpy -- trivial
at this scale (<5ms), no native dependencies beyond numpy, no filesystem writes.

The public interface (retrieve/format_context, hit shape) is identical to FORGE_Application's
VectorRetriever, so graph_retriever.py, hybrid_retriever.py, and rag_pipeline.py need no
changes to work with this variant.
"""
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from embeddings import get_embedding_function

# Matches a quoted document ID like 'DS-100-P-101' or "WO-2024-0002" inside a question -- see
# FORGE_Application/retrievers/vector_retriever.py for why this lexical fast path exists.
_DOC_ID_RE = re.compile(r"['\"]([A-Za-z]{2,6}-[A-Za-z0-9][A-Za-z0-9\-]{2,})['\"]")

# Matches a bare (unquoted) equipment/instrument tag like "100-V-105" or "300-TUR-302" inside
# a question -- e.g. "What is the design pressure of equipment 100-V-105?". Hashing embeddings
# have no notion of exact-ID matching (the digits get diluted among far more common boilerplate
# words shared by every equipment datasheet), so without this a query naming a specific tag but
# not quoting a full document ID can retrieve chunks for the wrong equipment entirely -- this
# lexical tag match keeps that common query shape reliable without needing real embeddings.
_TAG_RE = re.compile(r"\b(\d{2,4}-[A-Za-z]{1,4}-\d{2,4})\b")

VECTORS_PATH = os.path.join(config.LOCAL_DB_DIR, "vectors.json")
EMBED_DIM = 384
QUANT_SCALE = 10000  # must match scripts/build_vectors.py's QUANT_SCALE


class VectorRetriever:
    def __init__(self, vectors_path=None):
        vectors_path = vectors_path or VECTORS_PATH
        if not os.path.exists(vectors_path):
            raise FileNotFoundError(
                f"No precomputed vector store found at {vectors_path}. Run "
                "`python scripts/build_vectors.py` first."
            )
        with open(vectors_path, encoding="utf-8") as f:
            self.records = json.load(f)
        self.matrix = self._build_matrix(self.records)
        self.ef = get_embedding_function(backend="hashing")

    @staticmethod
    def _build_matrix(records):
        # Each record stores its vector sparse + integer-quantized (vi = nonzero indices,
        # vv = round(value * QUANT_SCALE)) to keep vectors.json small -- see
        # scripts/build_vectors.py. Reconstruct the dense float matrix once, here, so
        # _semantic_search's cosine similarity stays a single fast matrix-vector product.
        matrix = np.zeros((len(records), EMBED_DIM), dtype=np.float32)
        for row, r in enumerate(records):
            vi, vv = r.get("vi"), r.get("vv")
            if vi is not None and vv is not None:
                matrix[row, vi] = np.array(vv, dtype=np.float32) / QUANT_SCALE
            elif r.get("vector") is not None:  # back-compat with an older dense format
                matrix[row] = r["vector"]
        return matrix

    def retrieve(self, query: str, top_k: int = None):
        top_k = top_k or config.VECTOR_TOP_K

        lexical_hits = self._lexical_doc_id_lookup(query, top_k)
        if lexical_hits:
            return lexical_hits

        tag_hits = self._tag_lookup(query, top_k)
        if tag_hits:
            return tag_hits

        return self._semantic_search(query, top_k)

    def _lexical_doc_id_lookup(self, query: str, top_k: int):
        match = _DOC_ID_RE.search(query)
        if not match:
            return []
        candidate = match.group(1)
        matches = [r for r in self.records if r["doc_id"] == candidate][:top_k]
        return [self._to_hit(r, score=1.0) for r in matches]

    def _tag_lookup(self, query: str, top_k: int):
        match = _TAG_RE.search(query)
        if not match:
            return []
        tag = match.group(1)
        matches = [
            r for r in self.records
            if tag in r["text"] or any(e.endswith("-" + tag) or e == tag for e in (r.get("entity_mentions") or []))
        ][:top_k]
        return [self._to_hit(r, score=1.0) for r in matches]

    def _semantic_search(self, query: str, top_k: int):
        if not self.records:
            return []
        query_vec = np.array(self.ef._embed_one(query), dtype=np.float32)
        # vectors are already L2-normalized, so the dot product is the cosine similarity
        scores = self.matrix @ query_vec
        top_idx = np.argsort(-scores)[:top_k]
        return [self._to_hit(self.records[i], score=float(scores[i])) for i in top_idx]

    @staticmethod
    def _to_hit(record, score):
        return {
            "chunk_id": record["chunk_id"],
            "doc_id": record["doc_id"],
            "doc_type": record["doc_type"],
            "source_path": record["source_path"],
            "entity_mentions": record.get("entity_mentions") or [],
            "text": record["text"],
            "score": score,
        }

    def format_context(self, hits) -> str:
        lines = []
        for h in hits:
            lines.append(f"[{h['chunk_id']} | {h['doc_type']} | {h['doc_id']}]\n{h['text']}")
        return "\n\n".join(lines)
