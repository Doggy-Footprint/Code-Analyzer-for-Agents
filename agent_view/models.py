from dataclasses import dataclass, field
from typing import List, Optional

from language_analyzers.core.graph_models import NodeCost

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class ProfileRef:
    id: str
    version: int
    content_hash: str


@dataclass(frozen=True)
class ReadableNode:
    id: str
    file_path: str
    symbol_id: Optional[str]
    label: str
    kind: str
    start_line: Optional[int]
    end_line: Optional[int]
    read_cost: NodeCost
    flags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Occurrence:
    file_path: str
    line: int
    col: int
    matched_text: str
    context: str
    enclosing_node_id: str


@dataclass(frozen=True)
class QueryNode:
    id: str
    term: str
    kind: str
    clue_kinds: List[str]
    origin_node_ids: List[str]
    rule_id: Optional[str]
    source_terms: List[str]
    occurrences: List[Occurrence]
    arrival_node_ids: List[str]
    output_tokens: int
    excluded: bool
    exclusion_reason: Optional[str]


@dataclass(frozen=True)
class FrameworkLink:
    id: str
    from_node_id: str
    rule_id: str
    specificity: str
    resolution: str
    to_node_ids: List[str]
    candidate_node_ids: List[str]
    query_id: Optional[str]
    evidence_file: str
    evidence_line: int


@dataclass(frozen=True)
class ExcludedFile:
    file_path: str
    reason: str


@dataclass(frozen=True)
class ScanReport:
    ignore_source: str
    scanned_file_count: int
    excluded_files: List[ExcludedFile]
    unknown_framework_edges: List[str]


@dataclass(frozen=True)
class AgentViewGraph:
    schema_version: str
    project_name: str
    project_path: str
    profile: ProfileRef
    readable_nodes: List[ReadableNode]
    query_nodes: List[QueryNode]
    framework_links: List[FrameworkLink]
    unreachable_node_ids: List[str]
    scan: ScanReport
