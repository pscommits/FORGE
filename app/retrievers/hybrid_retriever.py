"""HybridRAG retrieval: combine VectorRAG chunk hits with GraphRAG subgraph context, dedupe
source documents, and produce one merged context block for the LLM."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from retrievers.vector_retriever import VectorRetriever
from retrievers.graph_retriever import GraphRetriever


class HybridRetriever:
    def __init__(self):
        self.vector = VectorRetriever()
        self.graph = GraphRetriever()

    def retrieve(self, query: str, vector_top_k: int = None, graph_max_nodes: int = None, graph_hops: int = None):
        vector_top_k = vector_top_k or config.HYBRID_VECTOR_TOP_K
        graph_max_nodes = graph_max_nodes or config.HYBRID_GRAPH_MAX_NODES
        graph_hops = graph_hops or config.GRAPH_MAX_HOPS

        vec_hits = self.vector.retrieve(query, top_k=vector_top_k)
        graph_result = self.graph.retrieve(query, hops=graph_hops, max_nodes=graph_max_nodes)

        source_docs = {}
        for h in vec_hits:
            source_docs[h["doc_id"]] = {"doc_id": h["doc_id"], "source_path": h["source_path"], "via": "vector"}
        for d in graph_result["source_documents"]:
            key = d["node_id"]
            source_docs.setdefault(key, {"doc_id": key, "source_path": d["file_path"], "via": "graph"})

        context_text = (
            "=== STRUCTURED KNOWLEDGE GRAPH CONTEXT ===\n"
            f"{graph_result['context_text']}\n\n"
            "=== RETRIEVED DOCUMENT PASSAGES (VECTOR SEARCH) ===\n"
            f"{self.vector.format_context(vec_hits)}"
        )

        return {
            "vector_hits": vec_hits,
            "graph_result": graph_result,
            "context_text": context_text,
            "source_documents": list(source_docs.values()),
        }
