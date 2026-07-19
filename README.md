# FORGE — Industrial Knowledge Copilot

A **HybridRAG** prototype over a synthetic industrial data twin (the "Panchganga Refinery &
Petrochemicals Complex"): ask a question, pick a retrieval strategy, and get an LLM answer
grounded in retrieved context — with full transparency into *why* the system answered that
way, via cited sources, a retrieval-based confidence score, and an interactive visualization of
the exact knowledge-graph entities used.

**Live demo:** not yet deployed. This repo is fully prepared and ready to deploy — see
[Instructions.md](Instructions.md) §4 (takes about a minute via the Vercel CLI, or connect
this repo on vercel.com for automatic deploys). Works on desktop and mobile, no login.

## What this is

The underlying data twin is a synthetic refinery: equipment, personnel, incidents, work
orders, inspection reports, SOPs, safety procedures, and regulatory submissions, cross-linked
into a knowledge graph and chunked into a document corpus. Three retrieval strategies compete
for the same questions:

- **Vector** — semantic + lexical search over document chunks.
- **Graph** — entity linking into the knowledge graph, then subgraph traversal.
- **Hybrid** — both, merged into one context window.

The LLM (via [Groq](https://console.groq.com)) answers strictly from whatever context was
retrieved and is instructed to say so when it can't find an answer, rather than guess.

## Features

- Single-page chat interface — mode selector, an equipment/unit picker with ready-made
  suggested questions for the current selection, Enter-to-ask. The model is fixed
  (`llama-3.1-8b-instant`, see `app/config.py`) — no model picker.
- **Sources panel** — every retrieved document/entity, tagged by which retrieval path
  surfaced it, linking to the original source document.
- **Confidence score** — a 0–100, explained, retrieval-based heuristic (vector similarity
  strength / graph linkage richness / a refusal check), clearly labeled as a heuristic and not
  a calibrated probability — no extra LLM call needed to compute it.
- **Interactive knowledge-graph viewer** — renders *only* the graph entities and relationships
  actually retrieved for the current question (not the full ~400-node graph). Scroll/pinch to
  zoom, drag to pan, click any node or edge to inspect its properties and connections.
- Fully responsive — usable from a phone up to a wide desktop monitor.

## Architecture

```
app/                       FastAPI backend (Vercel Python serverless function)
  main.py                    /api/entities, /api/ask, /api/source/{path},
                                 and serves webui/ itself (index.html, /static/*)
  rag_pipeline.py             retrieval -> prompt -> Groq
  retrievers/                 vector / graph / hybrid retrieval strategies
  confidence.py                 retrieval-based confidence heuristic
  data/, local_db/               knowledge graph + document corpus + precomputed vectors
  webui/                          single-page chat UI (index.html, static/*.css/js) -- lives
                                       inside app/, deliberately not named "public" (Vercel
                                       treats that name as a reserved static-hosting convention
                                       at any nesting depth and excludes it from the function)

scripts/build_vectors.py   Rebuild the precomputed vector store after editing data/
```

### A deliberate tradeoff: no vector database

This deployment does **not** use a vector database (e.g. ChromaDB) or a real embedding model.
At 667 document chunks, a full vector DB is unnecessary — instead, each chunk is embedded once
with a small, dependency-free hashed bag-of-words function (`app/embeddings.py`) and stored as
a flat JSON file (`app/local_db/vectors.json`, ~2.6MB). At query time, retrieval does an
in-memory cosine-similarity search over that file with plain numpy (a few milliseconds for 667
vectors), plus a lexical fast path for questions that name a specific document ID or equipment
tag directly.

This is a conscious quality/reliability tradeoff for serverless deployment: a real embedding
model (e.g. the ONNX MiniLM model ChromaDB bundles) plus its native runtime dependencies add
150–250MB and real risk of exceeding Vercel's serverless function size limit, plus ChromaDB's
SQLite persistence can hit read-only-filesystem issues on that platform. Hashing embeddings
have no synonym/paraphrase understanding, so Vector-mode semantic search here is noticeably
less precise than a real embedding model would be — Graph mode is unaffected (no embeddings
involved), and the lexical/tag fast paths keep "which equipment is X" style questions reliable
regardless.

## Tech stack

FastAPI, Groq API, NetworkX, numpy — deployed on Vercel. No database, no build step for the
frontend (vanilla HTML/CSS/JS), no external JS libraries.

## Data

All data is synthetic, generated for this project — no real refinery, real people, or real
incidents are represented. See `app/data/eval/test_dataset_readme.md` for how the evaluation
questions were constructed.
