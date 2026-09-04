import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .cost import cost_for_text
from .flags import is_test_path
from .graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    NodeKind,
    RelationKind,
    Resolution,
    SourceSpan,
)


_CODE_SUFFIXES = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".kt", ".kts"}
_CONFIG_NAMES = {".env"}
_CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".properties"}
STRING_RE = re.compile(r"(?P<quote>['\"])(?P<value>[^'\"\r\n]+)(?P=quote)")


def enrich_repository(architecture: Any) -> Any:
    root = Path(architecture.project_path)
    nodes: List[GraphNode] = architecture.nodes
    edges: List[GraphEdge] = architecture.edges
    _add_test_relations(root, nodes, edges)
    _add_configuration_relations(root, nodes, edges)
    return architecture


def _path_for(node: GraphNode) -> str:
    if node.span is not None:
        return node.span.file_path
    return str((node.metadata or {}).get("file_path", ""))


def _is_test_node(node: GraphNode) -> bool:
    return "test" in (node.flags or []) or is_test_path(_path_for(node))


def _add_test_relations(root: Path, nodes: Sequence[GraphNode], edges: List[GraphEdge]) -> None:
    by_id = {node.id: node for node in nodes}
    existing = {(edge.from_id, edge.to_id, edge.relation) for edge in edges}
    test_nodes = [node for node in nodes if _is_test_node(node)]
    production = [node for node in nodes if not _is_test_node(node)]

    for edge in list(edges):
        source = by_id.get(edge.from_id)
        target = by_id.get(edge.to_id)
        if source is None or target is None or not _is_test_node(source) or _is_test_node(target):
            continue
        _append_edge(edges, existing, source.id, target.id, RelationKind.TESTS,
                     edge.confidence, edge.resolution, edge.evidence, edge.candidates)

    source_cache: Dict[str, str] = {}
    for test in test_nodes:
        path = _path_for(test)
        if not path or Path(path).suffix.lower() not in _CODE_SUFFIXES:
            continue
        if path not in source_cache:
            try:
                source_cache[path] = (root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                source_cache[path] = ""
        file_text = source_cache[path]
        if not file_text:
            continue
        lines = file_text.splitlines()
        start = test.span.start_line if test.span is not None else 1
        end = test.span.end_line if test.span is not None else len(lines)
        text = "\n".join(lines[max(0, start - 1):end])
        referenced_names: Dict[str, List[GraphNode]] = {}
        for target in production:
            if target.kind not in (NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.FILE, NodeKind.MODULE):
                continue
            if len(target.label) > 2 and re.search(rf"\b{re.escape(target.label)}\b", text):
                referenced_names.setdefault(target.label, []).append(target)
        for name, matches in referenced_names.items():
            target = matches[0]
            line = start + _first_line(text, name) - 1
            resolution = Resolution.UNIQUE_NAME if len(matches) == 1 else Resolution.AMBIGUOUS
            _append_edge(
                edges, existing, test.id, target.id, RelationKind.TESTS,
                Confidence.STATIC_INFERRED, resolution,
                SourceSpan(path, line, line), [item.id for item in matches[1:]],
            )
        if referenced_names:
            continue
        stem = Path(path).stem
        fallback_name = re.sub(r"(^test_|_test$|Test$|\.(test|spec)$)", "", stem, flags=re.I)
        matches = [
            target for target in production
            if target.label.lower() == fallback_name.lower()
            and target.kind in (NodeKind.CLASS, NodeKind.FILE, NodeKind.MODULE)
        ]
        matches.sort(key=lambda target: (target.kind != NodeKind.CLASS, target.id))
        if len(matches) == 1:
            _append_edge(
                edges, existing, test.id, matches[0].id, RelationKind.TESTS,
                Confidence.STATIC_INFERRED, Resolution.UNIQUE_NAME,
                SourceSpan(path, 1, 1), [],
            )


def _add_configuration_relations(root: Path, nodes: List[GraphNode], edges: List[GraphEdge]) -> None:
    existing = {(edge.from_id, edge.to_id, edge.relation) for edge in edges}
    existing_node_ids = {node.id for node in nodes}
    code_nodes_by_path: Dict[str, List[GraphNode]] = {}
    for node in nodes:
        path = _path_for(node)
        if path and node.kind != NodeKind.CONFIGURATION and Path(path).suffix.lower() in _CODE_SUFFIXES:
            code_nodes_by_path.setdefault(path, []).append(node)

    for path in _discover_config_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for index, (key, line) in enumerate(config_keys(path, text)):
            node_id = f"config:{relative}:{line}:{index}:{key}"
            config_node = GraphNode(
                id=node_id,
                label=key,
                group=NodeKind.CONFIGURATION,
                category=NodeKind.CONFIGURATION,
                kind=NodeKind.CONFIGURATION,
                language="configuration",
                span=SourceSpan(relative, line, line),
                cost=cost_for_text(key),
                symbol_path=f"{relative}:{key}",
                provenance="repository-enrichment",
                metadata={"file_path": relative, "key": key},
            )
            if node_id not in existing_node_ids:
                nodes.append(config_node)
                existing_node_ids.add(node_id)
            for code_path, candidates in code_nodes_by_path.items():
                try:
                    code_text = (root / code_path).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
                matches = [match for match in STRING_RE.finditer(code_text) if match.group("value") == key]
                for match in matches:
                    use_line = code_text.count("\n", 0, match.start()) + 1
                    consumer = smallest_node_at_line(candidates, use_line)
                    if consumer is not None:
                        _append_edge(
                            edges, existing, node_id, consumer.id, RelationKind.CONFIGURES,
                            Confidence.STATIC_CERTAIN, Resolution.EXACT,
                            SourceSpan(code_path, use_line, use_line), [],
                        )


def _discover_config_files(root: Path) -> Iterable[Path]:
    ignored = {".git", "node_modules", "build", "dist", ".gradle", ".idea"}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.relative_to(root).parts):
            continue
        lower_name = path.name.lower()
        if lower_name in _CONFIG_NAMES or path.suffix.lower() in _CONFIG_SUFFIXES or lower_name.endswith((".gradle", ".gradle.kts")):
            yield path


def config_keys(path: Path, text: str) -> List[Tuple[str, int]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        keys: List[str] = []
        _json_keys(parsed, keys)
        return [(key, _first_key_line(text, key)) for key in keys]
    results: List[Tuple[str, int]] = []
    separator = r"\s*=\s*" if path.name == ".env" or suffix == ".properties" else r"\s*[:=]\s*"
    pattern = re.compile(rf"^\s*([A-Za-z_][\w.-]*){separator}")
    for line_number, line in enumerate(text.splitlines(), 1):
        match = pattern.match(line)
        if match and not line.lstrip().startswith(("#", "//")):
            results.append((match.group(1), line_number))
        if path.name.lower().endswith((".gradle", ".gradle.kts")):
            call = re.search(r"\b(?:buildConfigField|resValue)\s*\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]", line)
            if call:
                results.append((call.group(1), line_number))
    return results


def _json_keys(value: Any, output: List[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            output.append(str(key))
            _json_keys(nested, output)
    elif isinstance(value, list):
        for nested in value:
            _json_keys(nested, output)


def _first_key_line(text: str, key: str) -> int:
    match = re.search(rf"['\"]{re.escape(key)}['\"]\s*:", text)
    return text.count("\n", 0, match.start()) + 1 if match else 1


def _first_line(text: str, value: str) -> int:
    match = re.search(rf"\b{re.escape(value)}\b", text)
    return text.count("\n", 0, match.start()) + 1 if match else 1


def smallest_node_at_line(nodes: Sequence[GraphNode], line: int) -> Optional[GraphNode]:
    matches = [
        node for node in nodes
        if node.span is not None and node.span.start_line <= line <= node.span.end_line
    ]
    if not matches:
        return None
    return min(matches, key=lambda node: node.span.end_line - node.span.start_line)


def _append_edge(
    edges: List[GraphEdge], existing: set, source: str, target: str, relation: str,
    confidence: str, resolution: str, evidence: Optional[SourceSpan], candidates: List[str],
) -> None:
    key = (source, target, relation)
    if source == target or key in existing:
        return
    existing.add(key)
    edges.append(GraphEdge(
        from_id=source,
        to_id=target,
        relation=relation,
        confidence=confidence,
        resolution=resolution,
        evidence=evidence,
        candidates=list(candidates),
    ))
