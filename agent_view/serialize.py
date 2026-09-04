import json
from dataclasses import asdict
from typing import Any, Dict

from .models import AgentViewGraph


def graph_to_dict(graph: AgentViewGraph) -> Dict[str, Any]:
    return {
        "schema_version": graph.schema_version,
        "project_name": graph.project_name,
        "profile": asdict(graph.profile),
        "readable_nodes": [asdict(node) for node in graph.readable_nodes],
        "query_nodes": [asdict(node) for node in graph.query_nodes],
        "framework_links": [asdict(link) for link in graph.framework_links],
        "unreachable_node_ids": list(graph.unreachable_node_ids),
        "scan": asdict(graph.scan),
    }


def graph_to_json(graph: AgentViewGraph) -> str:
    return json.dumps(graph_to_dict(graph), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
