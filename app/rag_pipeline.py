"""
rag_pipeline.py -- RAGPipeline ties a retrieval strategy (vector / graph / hybrid) to the Groq
LLM backend to answer questions grounded in the PRPC industrial data twin.

    pipeline = RAGPipeline(mode="hybrid")
    result = pipeline.answer("What is the design pressure of equipment 100-P-101?")

FORGE_Application variant: accepts an optional pre-built `retriever` instance (so the FastAPI
app can reuse one retriever singleton per mode across requests instead of rebuilding the
ChromaDB client / graph pickle on every call), and always uses backend="groq" (the local
Hugging Face backend was dropped from this standalone app).
"""
import time

from llm_client import get_llm_client
from retrievers.vector_retriever import VectorRetriever
from retrievers.graph_retriever import GraphRetriever
from retrievers.hybrid_retriever import HybridRetriever

SYSTEM_PROMPT = """You are an Industrial Knowledge Copilot for the Panchganga Refinery & \
Petrochemicals Complex (PRPC). Answer the user's question using ONLY the context provided \
below (retrieved from the plant's engineering, maintenance, inspection, safety, and \
regulatory records). Follow these rules strictly:

1. Ground every claim in the provided context. Do not use outside knowledge about refineries \
   in general -- only what is in the context.
2. Cite the specific document ID(s) or entity ID(s) (e.g. "DS-100-P-101", "INC-2025-003", \
   "EMP-0012") that support your answer.
3. If the context does not contain enough information to answer confidently, say so \
   explicitly (e.g. "I cannot find this in the available records") rather than guessing or \
   inventing information.
4. Be concise and factual -- this is used by field technicians and engineers who need a \
   fast, correct answer, not a long essay.
"""

MODE_RETRIEVER_MAP = {"vector": VectorRetriever, "graph": GraphRetriever, "hybrid": HybridRetriever}


class RAGPipeline:
    def __init__(self, mode: str, backend: str = "groq", dry_run: bool = False,
                 retriever=None, **llm_kwargs):
        """
        mode: "vector" | "graph" | "hybrid" -- which retrieval strategy to use.
        backend: always "groq" in this standalone app.
        retriever: optional pre-built retriever instance to reuse (e.g. a cached singleton
                   held by the web app) instead of constructing a fresh one per pipeline.
        llm_kwargs: passed through to GroqClient, e.g. api_key=/model=.
        """
        if mode not in MODE_RETRIEVER_MAP:
            raise ValueError(f"mode must be one of {list(MODE_RETRIEVER_MAP)}, got '{mode}'")
        self.mode = mode
        self.backend = backend
        self.retriever = retriever or MODE_RETRIEVER_MAP[mode]()
        self.llm = get_llm_client(backend=backend, dry_run=dry_run, **llm_kwargs)

    def _retrieve(self, question: str):
        if self.mode == "vector":
            hits = self.retriever.retrieve(question)
            context_text = self.retriever.format_context(hits)
            source_documents = [{"doc_id": h["doc_id"], "source_path": h["source_path"], "via": "vector"} for h in hits]
            retrieved_entity_ids = sorted({e for h in hits for e in h["entity_mentions"]})
            retrieval_meta = {
                "vector_hits": [h["chunk_id"] for h in hits],
                "vector_scores": [h["score"] for h in hits],
                "retrieved_entity_ids": retrieved_entity_ids,
            }
        elif self.mode == "graph":
            gres = self.retriever.retrieve(question)
            context_text = gres["context_text"]
            source_documents = [{"doc_id": d["node_id"], "source_path": d["file_path"], "via": "graph"} for d in gres["source_documents"]]
            retrieval_meta = {
                "linked_entities": gres["linked_entities"],
                "subgraph_nodes": gres["subgraph_nodes"],
                "subgraph_edges": gres["subgraph_edges"],
                "retrieved_entity_ids": gres["subgraph_node_ids"],
                "graph_elements": gres["graph_elements"],
            }
        else:  # hybrid
            hres = self.retriever.retrieve(question)
            context_text = hres["context_text"]
            source_documents = hres["source_documents"]
            vec_entities = {e for h in hres["vector_hits"] for e in h["entity_mentions"]}
            graph_entities = set(hres["graph_result"]["subgraph_node_ids"])
            retrieval_meta = {
                "vector_hits": [h["chunk_id"] for h in hres["vector_hits"]],
                "vector_scores": [h["score"] for h in hres["vector_hits"]],
                "linked_entities": hres["graph_result"]["linked_entities"],
                "subgraph_nodes": hres["graph_result"]["subgraph_nodes"],
                "subgraph_edges": hres["graph_result"]["subgraph_edges"],
                "retrieved_entity_ids": sorted(vec_entities | graph_entities),
                "graph_elements": hres["graph_result"]["graph_elements"],
            }
        return context_text, source_documents, retrieval_meta

    def answer(self, question: str) -> dict:
        t0 = time.time()
        context_text, source_documents, retrieval_meta = self._retrieve(question)
        t_retrieval = time.time() - t0

        user_prompt = f"CONTEXT:\n{context_text}\n\nQUESTION: {question}\n\nANSWER:"

        t1 = time.time()
        answer_text = self.llm.chat(SYSTEM_PROMPT, user_prompt)
        t_generation = time.time() - t1

        return {
            "mode": self.mode,
            "backend": self.backend,
            "question": question,
            "answer": answer_text,
            "source_documents": source_documents,
            "retrieval_meta": retrieval_meta,
            "context_char_len": len(context_text),
            "latency_retrieval_s": round(t_retrieval, 4),
            "latency_generation_s": round(t_generation, 4),
            "latency_total_s": round(t_retrieval + t_generation, 4),
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ask a single question through one RAG pipeline mode.")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument("--mode", choices=["vector", "graph", "hybrid"], default="hybrid")
    parser.add_argument("--model", default=None, help="Groq model id (defaults to config.GROQ_MODEL)")
    parser.add_argument("--dry-run", action="store_true", help="Mock the LLM call (no API key needed)")
    args = parser.parse_args()

    llm_kwargs = {"model": args.model} if args.model else {}
    pipeline = RAGPipeline(mode=args.mode, backend="groq", dry_run=args.dry_run, **llm_kwargs)
    result = pipeline.answer(args.question)
    print(f"\n[{result['mode'].upper()}] {result['question']}\n")
    print(result["answer"])
    print(f"\nSources: {[d['doc_id'] for d in result['source_documents']]}")
    print(f"Latency: retrieval={result['latency_retrieval_s']}s generation={result['latency_generation_s']}s")
