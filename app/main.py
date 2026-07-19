"""
main.py -- FastAPI backend for the FORGE_Deployment Vercel app.

Serves both the JSON API (/api/entities, /api/ask, /api/source/{path}) AND the
frontend itself (index.html, style.css, script.js, graph.js under ../public/) from this one
ASGI app. Vercel's docs recommend letting the public/ directory serve statics directly instead
of mounting them in FastAPI (for CDN caching), but that requires the platform to route
non-API paths to public/ before ever reaching this function -- in practice that didn't happen
reliably (every path, including "/", was landing on this app with no matching route). Rather
than depend on undocumented routing precedence, this app is self-contained: it serves
everything itself, exactly like local dev (see README/Instructions) -- a small perf tradeoff
(static assets go through the function instead of the CDN) for a setup that doesn't depend on
Vercel routing internals working a particular way.

Retriever instances (in-memory vector index, NetworkX graph + entity registry) are expensive
to build, so one singleton per mode is built once per warm function instance (via FastAPI's
lifespan) and reused across requests within that instance; a fresh, cheap GroqClient is built
per request, always against the fixed model in config.GROQ_MODEL (no per-user model choice).

Local dev:  uvicorn app.main:app --reload --port 8000   (run from the FORGE_Deployment/ root)
"""
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

# Vercel may invoke this module in ways that don't put its own directory on sys.path (e.g. as
# `app.main` from the project root). Insert it explicitly so the bare `import config` style
# imports below -- shared with the sibling retrievers/*.py modules -- always resolve.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from confidence import score_confidence
from evaluate import REFUSAL_PHRASES  # noqa: F401 -- re-exported for potential debug use
from llm_client import GroqClientError
from rag_pipeline import RAGPipeline
from retrievers.graph_retriever import GraphRetriever
from retrievers.hybrid_retriever import HybridRetriever
from retrievers.vector_retriever import VectorRetriever

RETRIEVERS = {}
ENTITIES = {}  # {"equipment": [...], "units": [...]} -- populated at startup from the KG


def _load_entities():
    import json
    with open(config.KG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    equipment, units = [], []
    for n in data["nodes"]:
        props = n.get("properties", {})
        if n["type"] == "Equipment":
            equipment.append({
                "id": n["id"],
                "tag": props.get("tag"),
                "name": props.get("name"),
                "unit_id": props.get("unit_id"),
                "unit_name": props.get("unit_name"),
                "unit_short": props.get("unit_short"),
            })
        elif n["type"] == "ProcessUnit":
            units.append({
                "id": n["id"],
                "unit_id": props.get("unit_id"),
                "name": props.get("name"),
                "short": props.get("short"),
            })
    equipment.sort(key=lambda e: (e["unit_id"] or "", e["tag"] or ""))
    units.sort(key=lambda u: u["unit_id"] or "")
    return {"equipment": equipment, "units": units}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] building retriever singletons (vector / graph / hybrid)...")
    RETRIEVERS["vector"] = VectorRetriever()
    RETRIEVERS["graph"] = GraphRetriever()
    RETRIEVERS["hybrid"] = HybridRetriever()
    ENTITIES.update(_load_entities())
    print("[startup] ready.")
    yield
    RETRIEVERS.clear()


app = FastAPI(title="FORGE Industrial Knowledge Copilot", lifespan=lifespan)


# Frontend assets live in app/webui/ (deliberately NOT named "public" or living outside app/).
# Two production crashes got here: (1) a sibling FORGE_Deployment/public/ wasn't bundled at
# all -- Vercel's Python builder only bundles files inside the function file's own directory
# tree (confirmed: app/data/ and app/local_db/ *were* bundled correctly). (2) moving it to
# app/public/ *still* wasn't bundled ("RuntimeError: Directory '/var/task/app/public/static'
# does not exist") even though app/data and app/local_db were -- the one difference being the
# directory name "public" itself, which Vercel treats as a reserved static-hosting convention
# at any nesting depth, pulling it out of the function bundle. Renaming to "webui" avoids that.
WEBUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")


class AskRequest(BaseModel):
    question: str
    mode: Literal["vector", "graph", "hybrid"]


@app.get("/")
def index():
    return FileResponse(os.path.join(WEBUI_DIR, "index.html"))


@app.get("/api/entities")
def api_entities():
    return ENTITIES


@app.post("/api/ask")
def api_ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")

    retriever = RETRIEVERS[req.mode]

    try:
        pipeline = RAGPipeline(mode=req.mode, backend="groq", retriever=retriever)
        result = pipeline.answer(question)
    except GroqClientError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 -- surface any Groq/network failure as a clean 502
        raise HTTPException(status_code=502, detail=f"{e.__class__.__name__}: {e}")

    sources = []
    for d in result["source_documents"]:
        source_path = d.get("source_path")
        sources.append({
            "doc_id": d.get("doc_id"),
            "source_path": source_path,
            "via": d.get("via"),
            "url": f"/api/source/{source_path}" if source_path else None,
        })

    confidence = score_confidence(
        mode=req.mode,
        retrieval_meta=result["retrieval_meta"],
        source_documents=result["source_documents"],
        answer_text=result["answer"],
    )

    graph_elements = result["retrieval_meta"].get("graph_elements") or {"nodes": [], "edges": []}

    return {
        "question": result["question"],
        "mode": result["mode"],
        "model": pipeline.llm.model,
        "answer": result["answer"],
        "sources": sources,
        "confidence": confidence,
        "graph": graph_elements,
        "retrieval_meta": result["retrieval_meta"],
        "timing": {
            "retrieval_s": result["latency_retrieval_s"],
            "generation_s": result["latency_generation_s"],
            "total_s": result["latency_total_s"],
        },
    }


_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.get("/api/source/{file_path:path}")
def api_source(file_path: str):
    raw_root = os.path.realpath(config.RAW_DOCS_ROOT)
    resolved = os.path.realpath(os.path.join(config.DATA_ROOT, file_path))

    if os.path.commonpath([resolved, raw_root]) != raw_root:
        raise HTTPException(status_code=403, detail="Access to this path is not permitted.")
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="Source file not found.")

    ext = os.path.splitext(resolved)[1].lower()
    media_type = _MIME_TYPES.get(ext, "application/octet-stream")
    return FileResponse(resolved, media_type=media_type, filename=os.path.basename(resolved))


# Mounted last so it never shadows the explicit /api/* routes above (Starlette checks routes
# in registration order, and only falls through to a mount if nothing more specific matched).
app.mount("/static", StaticFiles(directory=os.path.join(WEBUI_DIR, "static")), name="static")


@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(status_code=404, content={"error": "Not found."})
