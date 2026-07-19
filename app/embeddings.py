"""
embeddings.py -- Embedding function factory for the local vector store.

Two backends are supported (selected via config.EMBEDDING_BACKEND / EMBEDDING_BACKEND env var):

  "onnx"    -- Chroma's bundled all-MiniLM-L6-v2 ONNX model. Real semantic embeddings,
               good retrieval quality. Downloads a small ONNX model (~80MB) the first time
               it's used, so it needs internet access once. This is the recommended default.

  "hashing" -- A dependency-free, fully offline, deterministic hashed bag-of-words embedding.
               No network access or model download required. Retrieval quality is noticeably
               lower than real semantic embeddings (no synonym/paraphrase understanding) but
               it keeps the whole pipeline runnable in air-gapped or firewalled environments,
               and is what this package falls back to for its own self-test.

Both implementations satisfy Chroma's EmbeddingFunction protocol (__call__ + name()).
"""
import hashlib
import re

import numpy as np

import config


class HashingEmbeddingFunction:
    """Deterministic hashed bag-of-words + bigrams, L2-normalized. No external calls."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def name(self) -> str:
        return f"hashing-bow-{self.dim}"

    @staticmethod
    def _tokenize(text: str):
        return re.findall(r"[a-z0-9][a-z0-9\-_.]*", text.lower())

    def _hash_bucket(self, token: str):
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        idx = h % self.dim
        sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
        return idx, sign

    def _embed_one(self, text: str):
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = self._tokenize(text)
        for tok in tokens:
            idx, sign = self._hash_bucket(tok)
            vec[idx] += sign
        for a, b in zip(tokens, tokens[1:]):
            idx, sign = self._hash_bucket(a + "_" + b)
            vec[idx] += 0.5 * sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def __call__(self, input):
        return [self._embed_one(t) for t in input]

    def embed_query(self, input):
        return self.__call__(input)

    def is_legacy(self):
        return False


def get_embedding_function(backend: str = None):
    backend = backend or config.EMBEDDING_BACKEND
    if backend == "hashing":
        return HashingEmbeddingFunction()
    if backend == "onnx":
        from chromadb.utils import embedding_functions
        return embedding_functions.DefaultEmbeddingFunction()
    raise ValueError(f"Unknown EMBEDDING_BACKEND '{backend}'. Use 'onnx' or 'hashing'.")
