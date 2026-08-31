from pathlib import Path
from typing import Any, Dict, Iterable, Optional

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
) -> None:
    for edge in edges:
        edge.confidence = confidence
        edge.resolution = resolution
