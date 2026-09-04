from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .derived_query import build_derived_queries, derive_terms
from .exact_query import build_exact_queries, extract_clues
from .framework_link import build_framework_links
from .models import (
    SCHEMA_VERSION,
    AgentViewGraph,
    ExcludedFile,
    FrameworkLink,
    Occurrence,
    ProfileRef,
    QueryNode,
    ReadableNode,
    ScanReport,
)
from .occurrence import OccurrenceIndex
from .profile import Profile, ProfileError, Transform, default_profile_path, load_profile
from .readable import build_readable_nodes
from .scan import list_repository_files, read_file, scan_files
from .serialize import graph_to_dict, graph_to_json

__all__ = [
    "SCHEMA_VERSION",
    "AgentViewGraph",
    "ExcludedFile",
    "FrameworkLink",
    "Occurrence",
    "OccurrenceIndex",
    "Profile",
    "ProfileError",
    "ProfileRef",
    "QueryNode",
    "ReadableNode",
    "ScanReport",
    "Transform",
    "build_agent_view",
    "build_derived_queries",
    "build_exact_queries",
    "build_framework_links",
    "build_readable_nodes",
    "default_profile_path",
    "derive_terms",
    "diff_agent_view",
    "extract_clues",
    "graph_to_dict",
    "graph_to_json",
    "list_repository_files",
    "load_profile",
    "scan_files",
]

_READABLE_DIFF_FIELDS = ("read_cost.token_estimate", "flags", "start_line", "end_line")
_QUERY_DIFF_FIELDS = ("arrival_node_ids", "output_tokens", "excluded", "origin_node_ids")
_LINK_DIFF_FIELDS = ("to_node_ids", "specificity", "query_id")


def build_agent_view(
    architecture: Any,
    *,
    profile: Optional[Profile] = None,
    file_reader: Optional[Callable[[Path], Optional[str]]] = None,
    file_lister: Optional[Callable[[Path], Tuple[str, List[str]]]] = None,
) -> AgentViewGraph:
    active = profile if profile is not None else load_profile(default_profile_path())
    root = Path(architecture.project_path)
    reader = file_reader or read_file
    lister = file_lister or (lambda path: list_repository_files(path, respect_gitignore=active.respect_gitignore))

    ignore_source, relative_paths = lister(root)
    scanned, excluded, contents = scan_files(
        root, relative_paths,
        max_file_bytes=active.max_file_bytes,
        reader=reader,
        include_agent_docs=active.include_agent_docs,
    )

    readable_nodes, _ = build_readable_nodes(architecture.nodes, scanned, contents)
    readable_by_id = {node.id: node for node in readable_nodes}
    nodes_by_file: Dict[str, List[ReadableNode]] = {}
    for node in readable_nodes:
        nodes_by_file.setdefault(node.file_path, []).append(node)

    index = OccurrenceIndex(contents, nodes_by_file)
    clues = extract_clues(architecture.nodes, readable_nodes, contents, active)
    exact = build_exact_queries(clues, index, active)
    by_term = {query.term: query for query in exact}
    derived = build_derived_queries(clues, index, active, by_term)
    framework_links, framework_queries, unknown_edges = build_framework_links(
        architecture.edges, readable_by_id, index, active
    )

    query_nodes = sorted(
        list(by_term.values()) + derived + framework_queries,
        key=lambda query: query.id,
    )

    arrivals = set()
    for query in query_nodes:
        if not query.excluded:
            arrivals.update(query.arrival_node_ids)
    for link in framework_links:
        arrivals.update(link.to_node_ids)
    # ROADMAP 그래프 모델: 한 symbol을 읽으면 같은 파일의 모든 symbol을 읽은 것으로 처리한다.
    reached_files = {readable_by_id[node_id].file_path for node_id in arrivals if node_id in readable_by_id}
    unreachable = sorted(
        node.id for node in readable_nodes if node.file_path not in reached_files
    )

    return AgentViewGraph(
        schema_version=SCHEMA_VERSION,
        project_name=getattr(architecture, "project_name", ""),
        project_path=str(architecture.project_path),
        profile=active.ref,
        readable_nodes=readable_nodes,
        query_nodes=query_nodes,
        framework_links=framework_links,
        unreachable_node_ids=unreachable,
        scan=ScanReport(
            ignore_source=ignore_source,
            scanned_file_count=len(scanned),
            excluded_files=excluded,
            unknown_framework_edges=unknown_edges,
        ),
    )


def _value(entry: Dict[str, Any], field: str) -> Any:
    if "." in field:
        head, _, tail = field.partition(".")
        return (entry.get(head) or {}).get(tail)
    return entry.get(field)


def _section(before, after, fields, id_key: str = "id") -> Dict[str, Any]:
    before_map = {entry[id_key]: entry for entry in before}
    after_map = {entry[id_key]: entry for entry in after}
    changed = []
    for identifier in sorted(set(before_map) & set(after_map)):
        differences = {}
        for field in fields:
            old = _value(before_map[identifier], field)
            new = _value(after_map[identifier], field)
            if old != new:
                differences[field] = {"before": old, "after": new}
        if differences:
            changed.append({"id": identifier, "fields": dict(sorted(differences.items()))})
    return {
        "added": sorted(set(after_map) - set(before_map)),
        "removed": sorted(set(before_map) - set(after_map)),
        "changed": changed,
    }


def diff_agent_view(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "readable_nodes": _section(
            before.get("readable_nodes", []), after.get("readable_nodes", []), _READABLE_DIFF_FIELDS
        ),
        "query_nodes": _section(
            before.get("query_nodes", []), after.get("query_nodes", []), _QUERY_DIFF_FIELDS
        ),
        "framework_links": _section(
            before.get("framework_links", []), after.get("framework_links", []), _LINK_DIFF_FIELDS
        ),
        "profile": {"before": before.get("profile", {}), "after": after.get("profile", {})},
    }
