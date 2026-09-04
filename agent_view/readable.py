from typing import Dict, List, Mapping, Sequence, Tuple

from language_analyzers.core.cost import cost_for_text
from language_analyzers.core.flags import path_flags
from language_analyzers.core.graph_models import GraphNode

from .models import ReadableNode


def build_readable_nodes(
    nodes: Sequence[GraphNode],
    scanned_paths: Sequence[str],
    contents: Mapping[str, str],
) -> Tuple[List[ReadableNode], Dict[str, List[str]]]:
    scanned = set(scanned_paths)
    costs = {path: cost_for_text(contents.get(path, "")) for path in scanned}

    candidates = [
        node for node in nodes
        if node.span is not None and node.span.file_path in scanned
    ]
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.id, item.span.file_path, item.span.start_line, item.span.end_line, item.label,
        ),
    )

    by_id: Dict[str, ReadableNode] = {}
    for node in ordered:
        if node.id in by_id:
            continue
        path = node.span.file_path
        by_id[node.id] = ReadableNode(
            id=node.id,
            file_path=path,
            symbol_id=node.id,
            label=node.label,
            kind=node.kind,
            start_line=node.span.start_line,
            end_line=node.span.end_line,
            read_cost=costs[path],
            flags=sorted(path_flags(path)),
        )

    covered = {node.file_path for node in by_id.values()}
    for path in sorted(scanned - covered):
        node_id = f"file:{path}"
        by_id[node_id] = ReadableNode(
            id=node_id,
            file_path=path,
            symbol_id=None,
            label=path,
            kind="file",
            start_line=None,
            end_line=None,
            read_cost=costs[path],
            flags=sorted(path_flags(path)),
        )

    readable = sorted(by_id.values(), key=lambda item: item.id)
    nodes_by_file: Dict[str, List[str]] = {}
    for node in readable:
        nodes_by_file.setdefault(node.file_path, []).append(node.id)
    return readable, nodes_by_file
