import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Set

from language_analyzers.core.cost import estimate_tokens
from language_analyzers.core.enrichment import STRING_RE, config_keys
from language_analyzers.core.graph_models import GraphNode

from .models import Occurrence, QueryNode, ReadableNode
from .occurrence import OccurrenceIndex, enclosing_node_id, file_context_kind
from .profile import Profile

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_RAISE_RE = re.compile(r"\b(raise|throw)\b")


@dataclass
class Clue:
    term: str
    clue_kinds: Set[str] = field(default_factory=set)
    origin_node_ids: Set[str] = field(default_factory=set)


def query_node_id(kind: str, term: str, version: int) -> str:
    return hashlib.sha256(f"{kind}|{term}|{version}".encode("utf-8")).hexdigest()[:16]


def _add(clues: Dict[str, Clue], term: str, kind: str, origin: str, profile: Profile) -> None:
    term = term.strip()
    if not term or "\n" in term or "\r" in term or len(term) < profile.min_term_length:
        return
    clue = clues.get(term)
    if clue is None:
        clue = Clue(term=term)
        clues[term] = clue
    clue.clue_kinds.add(kind)
    if origin:
        clue.origin_node_ids.add(origin)


def extract_clues(
    nodes: Sequence[GraphNode],
    readable: Sequence[ReadableNode],
    contents: Mapping[str, str],
    profile: Profile,
) -> Dict[str, Clue]:
    clues: Dict[str, Clue] = {}
    readable_ids = {node.id for node in readable}
    nodes_by_file: Dict[str, List[ReadableNode]] = {}
    for node in readable:
        nodes_by_file.setdefault(node.file_path, []).append(node)

    for node in sorted(nodes, key=lambda item: item.id):
        origin = node.id if node.id in readable_ids else ""
        _add(clues, node.label, "identifier", origin, profile)
        if node.symbol_path and node.symbol_path != node.label:
            _add(clues, node.symbol_path, "qualified_name", origin, profile)

    for path in sorted(contents):
        text = contents[path]
        origin_for_file = enclosing_node_id(nodes_by_file.get(path, []), path, 1)
        _add(clues, path, "path", origin_for_file, profile)
        without_suffix = str(Path(path).with_suffix("").as_posix())
        if without_suffix != path:
            _add(clues, without_suffix, "path", origin_for_file, profile)

        kind = file_context_kind(path)
        if kind == "config":
            for key, line in config_keys(Path(path), text):
                _add(clues, key, "config_key", enclosing_node_id(nodes_by_file.get(path, []), path, line), profile)
            continue
        if kind == "doc":
            if Path(path).suffix.lower() == ".md":
                for match in _BACKTICK_RE.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    origin = enclosing_node_id(nodes_by_file.get(path, []), path, line)
                    _add(clues, match.group(1), "doc_mention", origin, profile)
            continue

        lines = text.splitlines()
        for match in STRING_RE.finditer(text):
            value = match.group("value")
            line = text.count("\n", 0, match.start()) + 1
            origin = enclosing_node_id(nodes_by_file.get(path, []), path, line)
            _add(clues, value, "literal", origin, profile)
            if value.strip().startswith("/"):
                _add(clues, value, "route", origin, profile)
            if 1 <= line <= len(lines) and _RAISE_RE.search(lines[line - 1]):
                _add(clues, value, "error_message", origin, profile)

    return clues


def make_query_node(
    *,
    term: str,
    kind: str,
    clue: Clue,
    occurrences: List[Occurrence],
    profile: Profile,
    rule_id=None,
    source_terms=(),
) -> QueryNode:
    arrivals = sorted({occurrence.enclosing_node_id for occurrence in occurrences})
    excluded = len(arrivals) > profile.max_arrival_nodes
    output_tokens = estimate_tokens(
        "\n".join(f"{item.file_path}:{item.line}:{item.matched_text}" for item in occurrences)
    )
    return QueryNode(
        id=query_node_id(kind, term, profile.ref.version),
        term=term,
        kind=kind,
        clue_kinds=sorted(clue.clue_kinds),
        origin_node_ids=sorted(clue.origin_node_ids),
        rule_id=rule_id,
        source_terms=sorted(source_terms),
        occurrences=occurrences,
        arrival_node_ids=arrivals,
        output_tokens=output_tokens,
        excluded=excluded,
        exclusion_reason="too_many_arrival_nodes" if excluded else None,
    )


def build_exact_queries(
    clues: Mapping[str, Clue],
    index: OccurrenceIndex,
    profile: Profile,
) -> List[QueryNode]:
    queries: List[QueryNode] = []
    for term in sorted(clues):
        occurrences = index.find(term)
        if not occurrences:
            continue
        queries.append(make_query_node(
            term=term, kind="exact", clue=clues[term],
            occurrences=occurrences, profile=profile,
        ))
    queries.sort(key=lambda item: item.id)
    return queries
