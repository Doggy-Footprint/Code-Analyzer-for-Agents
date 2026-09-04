from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .cost import cost_for_span
from .graph_models import Confidence, GraphEdge, GraphNode, Resolution, SourceSpan


def annotate_nodes(
    nodes: Iterable[GraphNode],
    project_path: str,
    provenance: str,
    language: str,
) -> None:
    """Framework adapters build nodes from dataclasses that only carry line numbers.
    Lift those onto the typed span/cost fields so no later layer has to re-derive a range."""
    root = Path(project_path)
    sources: Dict[Path, Optional[str]] = {}
    for node in nodes:
        node.provenance = node.provenance or provenance
        node.language = node.language or language
        node.kind = node.kind or node.category
        metadata: Dict[str, Any] = node.metadata or {}
        raw_path = metadata.get("file_path")
        start = metadata.get("line_number")
        if not raw_path or not start:
            continue
        absolute = Path(raw_path)
        if not absolute.is_absolute():
            absolute = root / absolute
        try:
            relative = absolute.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = Path(raw_path).as_posix()
        end = metadata.get("end_line_number") or start
        span = SourceSpan(relative, int(start), int(end))
        node.span = span
        metadata["file_path"] = relative
        if absolute not in sources:
            try:
                sources[absolute] = absolute.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                sources[absolute] = None
        source = sources[absolute]
        if source is not None:
            node.cost = cost_for_span(source, span)
        if not node.symbol_path:
            module = metadata.get("module") or ""
            name = metadata.get("function_name") or metadata.get("name") or node.label
            node.symbol_path = f"{module}.{name}" if module else str(name)


def mark_edges(
    edges: Iterable[GraphEdge],
    confidence: str = Confidence.FRAMEWORK_INFERRED,
    resolution: str = Resolution.UNIQUE_NAME,
    nodes: Optional[Sequence[GraphNode]] = None,
    rule_namespace: Optional[str] = None,
    rule_specificity: Optional[Mapping[str, str]] = None,
) -> None:
    by_id = {node.id: node for node in nodes or []}
    specificity = rule_specificity or {}
    for edge in edges:
        edge.confidence = confidence
        edge.resolution = resolution
        if rule_namespace and edge.relation in specificity:
            edge.metadata = edge.metadata or {}
            edge.metadata.setdefault("framework_rule", {
                "id": f"{rule_namespace}.{edge.relation.lower()}",
                "specificity": specificity[edge.relation],
            })
        if edge.evidence is None:
            source = by_id.get(edge.from_id) or by_id.get(edge.to_id)
            if source is not None and source.span is not None:
                edge.evidence = SourceSpan(
                    source.span.file_path,
                    source.span.start_line,
                    source.span.start_line,
                )
            else:
                edge.evidence = SourceSpan("<framework-inference>", 1, 1)
