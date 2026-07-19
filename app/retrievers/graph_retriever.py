"""GraphRAG retrieval: entity-link the question to KG nodes, pull an ego-subgraph, and
serialize it into LLM-readable context text with provenance."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import graph_store as gs


class GraphRetriever:
    def __init__(self):
        self.graph = gs.build_or_load_graph()
        self.registry = gs.build_entity_registry(self.graph)

    def retrieve(self, query: str, hops: int = None, max_nodes: int = None):
        hops = hops or config.GRAPH_MAX_HOPS
        max_nodes = max_nodes or config.GRAPH_MAX_NODES_IN_CONTEXT

        linked = gs.find_entities(query, self.registry)
        node_ids = [nid for _, nid in linked]

        if not node_ids:
            return {
                "linked_entities": [],
                "subgraph_nodes": 0,
                "subgraph_edges": 0,
                "subgraph_node_ids": [],
                "context_text": "(No entities from the knowledge graph were matched in this question.)",
                "source_documents": [],
                "graph_elements": {"nodes": [], "edges": []},
            }

        sub = gs.ego_subgraph(self.graph, node_ids, hops=hops, max_nodes=max_nodes)
        context_text = gs.subgraph_to_context_text(sub, source_node_ids=node_ids)
        docs = gs.collect_source_documents(sub)

        return {
            "linked_entities": [{"surface": s, "node_id": n} for s, n in linked],
            "subgraph_nodes": sub.number_of_nodes(),
            "subgraph_edges": sub.number_of_edges(),
            "subgraph_node_ids": list(sub.nodes),
            "context_text": context_text,
            "source_documents": docs,
            "graph_elements": _serialize_subgraph(sub, source_node_ids=node_ids),
        }


def _clean_properties(props):
    """Keep only primitive (non-list/dict, non-empty) property values -- the same filter
    graph_store.subgraph_to_context_text uses for the LLM-facing context text -- so the
    frontend's node/edge detail panel shows readable key/value pairs, not nested structures."""
    return {
        k: v for k, v in (props or {}).items()
        if not isinstance(v, (list, dict)) and v not in (None, "")
    }


def _serialize_subgraph(sub, source_node_ids):
    """Serialize only the ego-subgraph actually retrieved for this question -- id/type/label
    plus properties and provenance per node, and deduped relation edges with their own
    properties -- so the frontend can render a small, focused, click-to-inspect knowledge-graph
    diagram scoped to what was retrieved, not the full ~400-node knowledge graph."""
    source_node_ids = set(source_node_ids or [])
    nodes = [
        {
            "id": node_id,
            "type": data.get("type"),
            "label": data.get("label") or node_id,
            "is_query_entity": node_id in source_node_ids,
            "properties": _clean_properties(data.get("properties")),
            "file_path": data.get("file_path"),
        }
        for node_id, data in sub.nodes(data=True)
    ]
    edges = []
    seen = set()
    for u, v, data in sub.edges(data=True):
        key = (u, data.get("relation"), v)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "source": u,
            "target": v,
            "relation": data.get("relation"),
            "properties": _clean_properties(data.get("properties")),
        })
    return {"nodes": nodes, "edges": edges}
