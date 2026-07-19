"""
Central configuration for the FORGE_Deployment app.

Self-contained: the data twin (knowledge graph, eval set, raw source documents) lives in
./data alongside this file. Set INDUSTRIAL_TWIN_DATA_DIR to point at a different data root if
you regenerate the data twin elsewhere.
"""
import os

PKG_ROOT = os.path.dirname(os.path.abspath(__file__))          # .../FORGE_Deployment/app
PROJECT_ROOT = os.path.dirname(PKG_ROOT)                        # .../FORGE_Deployment


def _load_dotenv(path):
    """Minimal .env loader (no python-dotenv dependency): sets os.environ defaults from a
    simple KEY=VALUE file, skipping blank lines/comments. Existing env vars always win. Only
    relevant for local dev -- on Vercel, GROQ_API_KEY is set as a real Project Environment
    Variable, and os.environ already has it before this module ever runs."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# .env lives at the project root (alongside vercel.json), not inside app/, so it sits next to
# where `uvicorn app.main:app` / `vercel dev` are actually run from.
_load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Data twin location (default: ./data, bundled inside this package)
# ---------------------------------------------------------------------------
DATA_ROOT = os.environ.get(
    "INDUSTRIAL_TWIN_DATA_DIR",
    os.path.join(PKG_ROOT, "data"),
)

KG_PATH = os.path.join(DATA_ROOT, "knowledge_graph", "kg_nodes_edges.json")
TEST_DATASET_PATH = os.path.join(DATA_ROOT, "eval", "test_dataset.json")
RAW_DOCS_ROOT = os.path.join(DATA_ROOT, "raw_documents")

# ---------------------------------------------------------------------------
# Local databases
# ---------------------------------------------------------------------------
LOCAL_DB_DIR = os.path.join(PKG_ROOT, "local_db")
GRAPH_PICKLE_PATH = os.path.join(LOCAL_DB_DIR, "graph.gpickle")

# This deployment only ships the dependency-free "hashing" embedding backend (see
# embeddings.py) -- chromadb + onnxruntime (needed for the alternative "onnx" backend used by
# FORGE_Application) are deliberately not installed here, to keep the app small and reliable
# on Vercel's serverless Python runtime. See README.md for the tradeoff.
EMBEDDING_BACKEND = os.environ.get("EMBEDDING_BACKEND", "hashing")

# ---------------------------------------------------------------------------
# Groq LLM settings
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_TEMPERATURE = 0.1
GROQ_MAX_TOKENS = 700
# Kept well under vercel.json's 60s function maxDuration: worst case here is one 20s attempt +
# 1s backoff + one more 20s attempt = ~41s, leaving headroom for retrieval and Vercel's own
# invocation overhead so a stuck Groq call fails cleanly with our own error instead of Vercel
# killing the function mid-retry and returning a raw platform timeout.
GROQ_TIMEOUT_S = 20
GROQ_MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Retrieval settings
# ---------------------------------------------------------------------------
VECTOR_TOP_K = 6
GRAPH_MAX_HOPS = 2
GRAPH_MAX_NODES_IN_CONTEXT = 25
HYBRID_VECTOR_TOP_K = 4
HYBRID_GRAPH_MAX_NODES = 15
