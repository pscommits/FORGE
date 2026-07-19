"""
graph_store.py -- The "local graph database" for GraphRAG: a NetworkX MultiDiGraph built
from knowledge_graph/kg_nodes_edges.json, persisted to disk as a pickle (full fidelity) and
a GraphML export (for inspection in tools like Gephi/yEd), plus an entity-linking registry
and subgraph-to-text serialization used by graph_retriever.py.

Why NetworkX instead of a graph server (Neo4j etc.)? At this corpus size (~400 nodes / ~800
edges) an in-process graph with a flat-file persistence layer is simpler to set up, ships
with zero extra infrastructure, and is trivially portable -- appropriate for a "local
database, for now" per the brief. Swapping in Neo4j/Memgraph later only requires
reimplementing this module's public functions against a Cypher driver.
"""
import json
import os
import pickle

import networkx as nx

import config


# ---------------------------------------------------------------------------
# Build / persist / load
# ---------------------------------------------------------------------------
def build_graph_from_kg(kg: dict) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for n in kg["nodes"]:
        g.add_node(n["id"], type=n["type"], label=n["label"],
                   properties=n.get("properties", {}), file_path=n.get("file_path"))
    for e in kg["edges"]:
        if e["source"] in g and e["target"] in g:
            g.add_edge(e["source"], e["target"], relation=e["relation"],
                       properties=e.get("properties", {}))
    return g


def load_kg_json() -> dict:
    with open(config.KG_PATH) as f:
        return json.load(f)


def save_graph(g: nx.MultiDiGraph, pickle_path=None, graphml_path=None):
    pickle_path = pickle_path or config.GRAPH_PICKLE_PATH
    graphml_path = graphml_path or config.GRAPH_GRAPHML_PATH
    os.makedirs(os.path.dirname(pickle_path), exist_ok=True)
    with open(pickle_path, "wb") as f:
        pickle.dump(g, f)

    # GraphML requires primitive attribute values -> flatten dict/list properties to JSON strings
    flat = nx.MultiDiGraph()
    for node_id, data in g.nodes(data=True):
        flat_data = {"type": data.get("type", ""), "label": data.get("label", "")}
        flat_data["properties_json"] = json.dumps(data.get("properties", {}), default=str)
        flat_data["file_path"] = data.get("file_path") or ""
        flat.add_node(node_id, **flat_data)
    for u, v, data in g.edges(data=True):
        flat.add_edge(u, v, relation=data.get("relation", ""),
                       properties_json=json.dumps(data.get("properties", {}), default=str))
    nx.write_graphml(flat, graphml_path)


def load_graph(pickle_path=None) -> nx.MultiDiGraph:
    pickle_path = pickle_path or config.GRAPH_PICKLE_PATH
    if not os.path.exists(pickle_path):
        raise FileNotFoundError(
            f"No local graph DB found at {pickle_path}. Run `python build_graph_db.py` first."
        )
    with open(pickle_path, "rb") as f:
        return pickle.load(f)


def build_or_load_graph() -> nx.MultiDiGraph:
    """Convenience helper for retrievers: use the persisted graph if present, else build
    it fresh from kg_nodes_edges.json in-memory (without writing to disk)."""
    if os.path.exists(config.GRAPH_PICKLE_PATH):
        return load_graph()
    return build_graph_from_kg(load_kg_json())


# ---------------------------------------------------------------------------
# Entity-linking registry: surface string -> node id
# ---------------------------------------------------------------------------
def build_entity_registry(g: nx.MultiDiGraph) -> dict:
    """Map human-readable surface strings (equipment tags, IDs, personnel names, unit
    names...) to KG node IDs, so a free-text question can be linked to graph nodes."""
    registry = {}
    for node_id, data in g.nodes(data=True):
        props = data.get("properties", {})
        # the raw domain ID is usually the suffix after the node-type prefix, e.g.
        # "EQ-100-P-101" -> "100-P-101"; also index common property fields.
        for key in ("tag", "emp_id", "sop_id", "sp_id", "wo_id", "ir_id", "incident_id",
                    "reg_id", "sl_id", "eml_id", "pl_id", "name", "title"):
            val = props.get(key)
            if isinstance(val, str) and val:
                registry[val] = node_id
        if data.get("label"):
            registry.setdefault(data["label"], node_id)
        registry[node_id] = node_id
    # sort longest-first at lookup time (done in find_entities)
    return registry


def find_entities(text: str, registry: dict, max_results: int = 15):
    """Substring-match entity linking. Longest surface strings are checked first so full
    IDs are preferred over accidental short substrings."""
    found = []
    seen_nodes = set()
    for surface in sorted(registry.keys(), key=len, reverse=True):
        if not surface or len(surface) < 3:
            continue
        if surface in text and registry[surface] not in seen_nodes:
            found.append((surface, registry[surface]))
            seen_nodes.add(registry[surface])
        if len(found) >= max_results:
            break
    return found


# ---------------------------------------------------------------------------
# Subgraph extraction + serialization for LLM context
# ---------------------------------------------------------------------------
def ego_subgraph(g: nx.MultiDiGraph, node_ids, hops: int = 2, max_nodes: int = 25):
    undirected = g.to_undirected()
    keep = set()
    for nid in node_ids:
        if nid in g:
            keep |= set(nx.ego_graph(undirected, nid, radius=hops).nodes)
    if not keep:
        return g.subgraph([])
    sub = g.subgraph(keep).copy()
    if sub.number_of_nodes() > max_nodes:
        # prioritize: seed nodes first, then closest by shortest path to any seed
        dist = {}
        for nid in node_ids:
            if nid in undirected:
                lengths = nx.single_source_shortest_path_length(undirected, nid, cutoff=hops)
                for k, d in lengths.items():
                    dist[k] = min(dist.get(k, 1e9), d)
        ranked = sorted(sub.nodes, key=lambda n: dist.get(n, 1e9))[:max_nodes]
        sub = g.subgraph(ranked).copy()
    return sub


def subgraph_to_context_text(sub: nx.MultiDiGraph, source_node_ids=None) -> str:
    """Serialize a subgraph into a compact, LLM-readable text block: entities with key
    properties, then relationships. This is the 'context' GraphRAG hands to the LLM."""
    source_node_ids = set(source_node_ids or [])
    lines = ["ENTITIES:"]
    for node_id, data in sub.nodes(data=True):
        props = data.get("properties", {})
        prop_str = ", ".join(f"{k}={v}" for k, v in list(props.items())
                              if not isinstance(v, (list, dict)) and v not in (None, ""))
        marker = " [QUERY ENTITY]" if node_id in source_node_ids else ""
        lines.append(f"- {node_id} ({data.get('type')}){marker}: {data.get('label')}. {prop_str}")

    lines.append("\nRELATIONSHIPS:")
    seen_edges = set()
    for u, v, data in sub.edges(data=True):
        key = (u, data.get("relation"), v)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        lines.append(f"- {u} --[{data.get('relation')}]--> {v}")

    return "\n".join(lines)


def collect_source_documents(sub: nx.MultiDiGraph):
    """Return the distinct (node_id, file_path) pairs in a subgraph that have provenance
    documents attached -- used for citations."""
    docs = []
    for node_id, data in sub.nodes(data=True):
        if data.get("file_path"):
            docs.append({"node_id": node_id, "file_path": data["file_path"], "type": data.get("type")})
    return docs
