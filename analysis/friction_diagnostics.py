import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from language_analyzers.core.flags import is_test_path
from language_analyzers.core.graph_models import Confidence, NodeKind, RelationKind, Resolution
from language_analyzers.core.report_schema import ColumnSpec, ReportCollection

from .task_exploration import EdgeTraversal, ExplorationPath, TaskType


class DiagnosticKind(str, Enum):
    CENTRAL_LARGE_SYMBOL = "central_large_symbol"
    BRIDGE_BOTTLENECK = "bridge_bottleneck"
    REEXPORT_AMBIGUITY = "reexport_ambiguity"
    CYCLIC_DEPENDENCY = "cyclic_dependency"
    MISSING_TEST_LINK = "missing_test_link"

    def __str__(self) -> str:
        return self.value


_CONFIDENCE_RANK = {
    Confidence.STATIC_CERTAIN.value: 0,
    Confidence.STATIC_INFERRED.value: 1,
    Confidence.FRAMEWORK_INFERRED.value: 2,
    Confidence.DYNAMIC_REQUIRED.value: 3,
}

_SUBJECT_KINDS = frozenset({
    NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.FILE, NodeKind.MODULE,
})

_STRUCTURAL_RELATIONS = frozenset({
    RelationKind.IMPORTS, RelationKind.IMPORTS_SYMBOL, RelationKind.RE_EXPORTS,
    RelationKind.CALLS, RelationKind.INHERITS, RelationKind.IMPLEMENTS, RelationKind.TYPE_USES,
})

_AMBIGUOUS_RESOLUTIONS = frozenset({Resolution.AMBIGUOUS.value, Resolution.UNRESOLVED.value})

_EXPORT_RELATIONS = frozenset({
    RelationKind.RE_EXPORTS, RelationKind.EXPORTS, RelationKind.IMPORTS_SYMBOL, RelationKind.IMPORTS,
})

_TASK_TYPES_ALL = (TaskType.BUG_FIX, TaskType.FEATURE_ADD, TaskType.API_CHANGE, TaskType.CONFIG_CHANGE)

_APPLICABLE_TASK_TYPES = {
    DiagnosticKind.CENTRAL_LARGE_SYMBOL: _TASK_TYPES_ALL,
    DiagnosticKind.BRIDGE_BOTTLENECK: (TaskType.BUG_FIX, TaskType.FEATURE_ADD, TaskType.API_CHANGE),
    DiagnosticKind.REEXPORT_AMBIGUITY: (TaskType.FEATURE_ADD, TaskType.API_CHANGE, TaskType.CONFIG_CHANGE),
    DiagnosticKind.CYCLIC_DEPENDENCY: (TaskType.BUG_FIX, TaskType.FEATURE_ADD, TaskType.API_CHANGE),
    DiagnosticKind.MISSING_TEST_LINK: (TaskType.BUG_FIX, TaskType.API_CHANGE, TaskType.CONFIG_CHANGE),
}

_FALSE_POSITIVE_RISKS = {
    DiagnosticKind.CENTRAL_LARGE_SYMBOL: (
        "framework entrypoints are expected to be large and central",
        "aggregation-only modules concentrate references without concentrating logic",
    ),
    DiagnosticKind.BRIDGE_BOTTLENECK: (
        "an intentional facade or adapter boundary looks identical to a bottleneck",
        "sampled betweenness is an approximation on graphs above the exact threshold",
    ),
    DiagnosticKind.REEXPORT_AMBIGUITY: (
        "a public API barrel may be deliberate",
        "the candidate list is a static estimate, not the resolved target",
    ),
    DiagnosticKind.CYCLIC_DEPENDENCY: (
        "mutual recursion inside one file is normal",
        "dynamic relations are excluded, so the reported cycle may be incomplete",
    ),
    DiagnosticKind.MISSING_TEST_LINK: (
        "an integration test may cover the node without a name the matcher recognizes",
        "tests may live outside the analyzed repository",
    ),
}

_IMPROVEMENTS = {
    DiagnosticKind.CENTRAL_LARGE_SYMBOL: (
        ("split_symbol",
         "Splitting the symbol lets an agent read only the part a task needs.",
         ("effective_token_cost", "hop_2_token_cost", "target_discovery_cost")),
    ),
    DiagnosticKind.BRIDGE_BOTTLENECK: (
        ("document_entrypoint",
         "Naming what crosses this boundary removes a blind traversal through it.",
         ("betweenness_centrality", "context_fragmentation.total_graph_distance")),
    ),
    DiagnosticKind.REEXPORT_AMBIGUITY: (
        ("narrow_reexport",
         "Re-exporting explicit names makes the target resolvable without a search.",
         ("evidence_gap.ratio", "branching_burden.irrelevant_ratio")),
    ),
    DiagnosticKind.CYCLIC_DEPENDENCY: (
        ("break_cycle",
         "Breaking the cycle gives exploration a termination point.",
         ("betweenness_centrality", "branching_burden.exposed_candidate_count")),
    ),
    DiagnosticKind.MISSING_TEST_LINK: (
        ("add_focused_test",
         "A focused test names the expected behaviour and bounds the impact check.",
         ("impact_discovery_cost",)),
    ),
}


@dataclass(frozen=True)
class DiagnosticsConfig:
    percentile: float = 0.95
    min_effective_token_cost: float = 400.0
    min_fan_in: int = 4
    min_betweenness: float = 0.0
    min_ambiguous_candidates: int = 2
    max_cycle_length: int = 8
    max_evidence_paths: int = 3
    max_findings_per_kind: int = 20

    def __post_init__(self):
        if isinstance(self.percentile, bool) or not isinstance(self.percentile, (int, float)):
            raise ValueError("percentile must be a number in [0, 1)")
        if not math.isfinite(self.percentile) or not 0.0 <= self.percentile < 1.0:
            raise ValueError("percentile must be a number in [0, 1)")
        for name in ("min_effective_token_cost", "min_betweenness"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a non-negative number")
        for name in ("min_fan_in", "max_evidence_paths", "max_findings_per_kind"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if isinstance(self.min_ambiguous_candidates, bool) or not isinstance(self.min_ambiguous_candidates, int) or self.min_ambiguous_candidates < 1:
            raise ValueError("min_ambiguous_candidates must be a positive integer")
        if isinstance(self.max_cycle_length, bool) or not isinstance(self.max_cycle_length, int) or self.max_cycle_length < 2:
            raise ValueError("max_cycle_length must be an integer of at least 2")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "percentile": self.percentile,
            "min_effective_token_cost": self.min_effective_token_cost,
            "min_fan_in": self.min_fan_in,
            "min_betweenness": self.min_betweenness,
            "min_ambiguous_candidates": self.min_ambiguous_candidates,
            "max_cycle_length": self.max_cycle_length,
            "max_evidence_paths": self.max_evidence_paths,
            "max_findings_per_kind": self.max_findings_per_kind,
        }


@dataclass(frozen=True)
class ImprovementCandidate:
    action: str
    rationale: str
    linked_metrics: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "rationale": self.rationale, "linked_metrics": list(self.linked_metrics)}


@dataclass(frozen=True)
class Finding:
    kind: DiagnosticKind
    node_ids: Tuple[str, ...]
    metrics: Mapping[str, float]
    evidence_paths: Tuple[ExplorationPath, ...]
    applicable_task_types: Tuple[TaskType, ...]
    confidence: str
    false_positive_risks: Tuple[str, ...]
    improvements: Tuple[ImprovementCandidate, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "node_ids": list(self.node_ids),
            "metrics": dict(self.metrics),
            "evidence_paths": [_path_to_dict(path) for path in self.evidence_paths],
            "applicable_task_types": [item.value for item in self.applicable_task_types],
            "confidence": self.confidence,
            "false_positive_risks": list(self.false_positive_risks),
            "improvements": [item.to_dict() for item in self.improvements],
        }


@dataclass(frozen=True)
class DiagnosticsReport:
    findings: Tuple[Finding, ...]
    thresholds: Mapping[str, float]
    config: DiagnosticsConfig

    def counts(self) -> Dict[str, int]:
        counts = {kind.value: 0 for kind in DiagnosticKind}
        for finding in self.findings:
            counts[finding.kind.value] += 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "findings": [finding.to_dict() for finding in self.findings],
            "thresholds": dict(self.thresholds),
            "config": self.config.to_dict(),
            "counts": self.counts(),
        }


def _path_to_dict(path: ExplorationPath) -> Dict[str, Any]:
    return {
        "node_ids": list(path.node_ids),
        "edge_indices": list(path.edge_indices),
        "edges": [
            {
                "edge_index": edge.edge_index,
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "relation": edge.relation,
                "confidence": edge.confidence,
                "resolution": edge.resolution,
            }
            for edge in path.edges
        ],
    }


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _edge_value(edge: Any, attribute: str, mapping_key: str) -> Any:
    if isinstance(edge, Mapping):
        return edge.get(mapping_key, edge.get(attribute))
    return getattr(edge, attribute, None)


def _node_path(node: Any) -> str:
    span = _value(node, "span")
    if span is not None:
        path = _value(span, "file_path")
        if path:
            return str(path).replace("\\", "/")
    metadata = _value(node, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        for key in ("file_path", "path", "source_file", "filename"):
            if metadata.get(key):
                return str(metadata[key]).replace("\\", "/")
    return ""


def _node_flags(node: Any) -> Set[str]:
    flags = {str(flag).casefold() for flag in (_value(node, "flags", []) or [])}
    metadata = _value(node, "metadata", {}) or {}
    if isinstance(metadata, Mapping):
        flags.update(str(flag).casefold() for flag in (metadata.get("flags", []) or []))
    return flags


def _is_excluded(node: Any) -> bool:
    flags = _node_flags(node)
    path = f"/{_node_path(node).casefold()}"
    if "vendored" in flags or "/vendor/" in path or "/node_modules/" in path:
        return True
    return "generated" in flags or "migration" in flags or "/migrations/" in path or "/alembic/versions/" in path


def _is_test(node: Any) -> bool:
    path = _node_path(node)
    return "test" in _node_flags(node) or (bool(path) and is_test_path(path))


def _top_level_directory(node: Any) -> str:
    path = _node_path(node)
    if not path:
        return ""
    parts = [part for part in path.split("/") if part not in ("", ".")]
    return parts[0] if len(parts) > 1 else "."


def _quantile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil(percentile * (len(ordered) - 1))
    return float(ordered[index])


def _weakest_confidence(paths: Iterable[ExplorationPath]) -> str:
    weakest = Confidence.STATIC_CERTAIN.value
    rank = 0
    for path in paths:
        for edge in path.edges:
            candidate = _CONFIDENCE_RANK.get(edge.confidence, len(_CONFIDENCE_RANK))
            if candidate > rank:
                rank = candidate
                weakest = edge.confidence
    return weakest


class FrictionDiagnoser:
    def __init__(self, config: Optional[DiagnosticsConfig] = None):
        self.config = config or DiagnosticsConfig()

    def diagnose(
        self,
        nodes: Sequence[Any],
        edges: Sequence[Any],
        node_metrics: Mapping[str, Mapping[str, Any]],
    ) -> DiagnosticsReport:
        state = _GraphState(nodes, edges, node_metrics)
        thresholds = self._thresholds(state)
        findings: List[Finding] = []
        findings.extend(self._central_large_symbols(state, thresholds))
        findings.extend(self._bridge_bottlenecks(state, thresholds))
        findings.extend(self._reexport_ambiguities(state))
        findings.extend(self._cyclic_dependencies(state))
        findings.extend(self._missing_test_links(state, thresholds))
        return DiagnosticsReport(tuple(findings), thresholds, self.config)

    def _thresholds(self, state: "_GraphState") -> Dict[str, float]:
        population = state.population
        config = self.config
        return {
            "effective_token_cost": max(
                _quantile([state.metric(item, "effective_token_cost") for item in population], config.percentile),
                float(config.min_effective_token_cost),
            ),
            "pagerank": _quantile([state.metric(item, "pagerank") for item in population], config.percentile),
            "betweenness_centrality": max(
                _quantile([state.metric(item, "betweenness_centrality") for item in population], config.percentile),
                float(config.min_betweenness),
            ),
            "weighted_centrality_cost": _quantile(
                [state.metric(item, "weighted_centrality_cost") for item in population], config.percentile
            ),
        }

    def _finding(self, kind: DiagnosticKind, node_ids, metrics, paths) -> Finding:
        paths = tuple(paths)
        return Finding(
            kind=kind,
            node_ids=tuple(node_ids),
            metrics=dict(metrics),
            evidence_paths=paths,
            applicable_task_types=_APPLICABLE_TASK_TYPES[kind],
            confidence=_weakest_confidence(paths),
            false_positive_risks=_FALSE_POSITIVE_RISKS[kind],
            improvements=tuple(
                ImprovementCandidate(action, rationale, metric_names)
                for action, rationale, metric_names in _IMPROVEMENTS[kind]
            ),
        )

    def _limit(self, findings: List[Finding]) -> List[Finding]:
        return findings[: self.config.max_findings_per_kind]

    def _central_large_symbols(self, state: "_GraphState", thresholds) -> List[Finding]:
        selected = []
        for node_id in state.population:
            if str(_value(state.nodes[node_id], "kind", "") or _value(state.nodes[node_id], "category", "")) not in _SUBJECT_KINDS:
                continue
            cost = state.metric(node_id, "effective_token_cost")
            pagerank = state.metric(node_id, "pagerank")
            fan_in = state.metric(node_id, "fan_in")
            if cost < thresholds["effective_token_cost"]:
                continue
            if pagerank < thresholds["pagerank"] and fan_in < self.config.min_fan_in:
                continue
            selected.append((cost, node_id, pagerank, fan_in))
        selected.sort(key=lambda item: (-item[0], item[1]))
        return self._limit([
            self._finding(
                DiagnosticKind.CENTRAL_LARGE_SYMBOL,
                (node_id,),
                {"effective_token_cost": cost, "pagerank": pagerank, "fan_in": fan_in},
                state.incoming_paths(node_id, self.config.max_evidence_paths),
            )
            for cost, node_id, pagerank, fan_in in selected
        ])

    def _bridge_bottlenecks(self, state: "_GraphState", thresholds) -> List[Finding]:
        selected = []
        for node_id in state.population:
            betweenness = state.metric(node_id, "betweenness_centrality")
            if betweenness <= 0.0 or betweenness < thresholds["betweenness_centrality"]:
                continue
            pairs = state.crossing_pairs(node_id, self.config.max_evidence_paths)
            if not pairs:
                continue
            directories = sorted({
                _top_level_directory(state.nodes[neighbor])
                for neighbor, _ in state.incoming[node_id] + state.outgoing[node_id]
                if neighbor in state.population_set
            })
            selected.append((betweenness, node_id, pairs, len(directories)))
        selected.sort(key=lambda item: (-item[0], item[1]))
        return self._limit([
            self._finding(
                DiagnosticKind.BRIDGE_BOTTLENECK,
                (node_id,),
                {
                    "betweenness_centrality": betweenness,
                    "crossing_pair_count": float(len(pairs)),
                    "neighbor_directory_count": float(directory_count),
                },
                pairs,
            )
            for betweenness, node_id, pairs, directory_count in selected
        ])

    def _reexport_ambiguities(self, state: "_GraphState") -> List[Finding]:
        sites: Dict[str, Dict[str, Any]] = {}

        def site(node_id: str) -> Dict[str, Any]:
            return sites.setdefault(
                node_id, {"reexport_edges": [], "ambiguous_edges": [], "candidate_count": 0, "flagged": False}
            )

        for node_id in state.population:
            if "reexport" in _node_flags(state.nodes[node_id]):
                site(node_id)["flagged"] = True

        for index, edge in enumerate(state.edges):
            source = state.endpoint(edge, "from")
            if source is None or source not in state.population_set:
                continue
            relation = str(_value(edge, "relation", "") or "")
            resolution = str(_value(edge, "resolution", "") or "")
            candidates = list(_value(edge, "candidates", []) or [])
            if relation == RelationKind.RE_EXPORTS:
                site(source)["reexport_edges"].append(index)
            if resolution in _AMBIGUOUS_RESOLUTIONS and len(candidates) >= self.config.min_ambiguous_candidates:
                entry = site(source)
                entry["ambiguous_edges"].append(index)
                entry["candidate_count"] = max(entry["candidate_count"], len(candidates))

        selected: List[Tuple[int, Tuple[str, ...], Dict[str, float], Tuple[ExplorationPath, ...]]] = []
        for node_id, entry in sites.items():
            edge_indices = sorted(set(entry["reexport_edges"] + entry["ambiguous_edges"]))
            weight = len(edge_indices)
            if not edge_indices:
                edge_indices = state.export_edges(node_id)
            selected.append((
                weight,
                (node_id,),
                {
                    "reexport_edge_count": float(len(entry["reexport_edges"])),
                    "ambiguous_edge_count": float(len(entry["ambiguous_edges"])),
                    "candidate_count": float(entry["candidate_count"]),
                    "collision_count": 0.0,
                },
                state.edge_paths(edge_indices[: self.config.max_evidence_paths]),
            ))

        for label, members in state.name_collisions():
            selected.append((
                len(members),
                members,
                {
                    "reexport_edge_count": 0.0,
                    "ambiguous_edge_count": 0.0,
                    "candidate_count": 0.0,
                    "collision_count": float(len(members)),
                },
                state.reference_paths(members, self.config.max_evidence_paths),
            ))

        selected.sort(key=lambda item: (-item[0], item[1][0]))
        return self._limit([
            self._finding(DiagnosticKind.REEXPORT_AMBIGUITY, node_ids, metrics, paths)
            for _weight, node_ids, metrics, paths in selected
        ])

    def _cyclic_dependencies(self, state: "_GraphState") -> List[Finding]:
        selected = []
        for component in state.strongly_connected_components():
            if not 2 <= len(component) <= self.config.max_cycle_length:
                continue
            paths = state.cycle_path(component)
            same_file = len({_node_path(state.nodes[item]) for item in component}) == 1
            selected.append((len(component), sorted(component), paths, same_file))
        selected.sort(key=lambda item: (-item[0], item[1][0]))
        return self._limit([
            self._finding(
                DiagnosticKind.CYCLIC_DEPENDENCY,
                members,
                {"size": float(size), "same_file": 1.0 if same_file else 0.0},
                paths[: self.config.max_evidence_paths],
            )
            for size, members, paths, same_file in selected
        ])

    def _missing_test_links(self, state: "_GraphState", thresholds) -> List[Finding]:
        selected = []
        for node_id in state.population:
            if state.tested[node_id]:
                continue
            cost = state.metric(node_id, "effective_token_cost")
            weighted = state.metric(node_id, "weighted_centrality_cost")
            if cost < self.config.min_effective_token_cost:
                continue
            if weighted < thresholds["weighted_centrality_cost"]:
                continue
            selected.append((weighted, node_id, cost))
        selected.sort(key=lambda item: (-item[0], item[1]))
        return self._limit([
            self._finding(
                DiagnosticKind.MISSING_TEST_LINK,
                (node_id,),
                {"weighted_centrality_cost": weighted, "effective_token_cost": cost},
                state.incoming_paths(node_id, self.config.max_evidence_paths),
            )
            for weighted, node_id, cost in selected
        ])


class _GraphState:
    def __init__(self, nodes, edges, node_metrics):
        self.nodes = {str(_value(node, "id")): node for node in nodes}
        self.edges = list(edges)
        self.node_metrics = node_metrics
        self.outgoing: Dict[str, List[Tuple[str, int]]] = {node_id: [] for node_id in self.nodes}
        self.incoming: Dict[str, List[Tuple[str, int]]] = {node_id: [] for node_id in self.nodes}
        self.tested: Dict[str, bool] = {node_id: False for node_id in self.nodes}
        for index, edge in enumerate(self.edges):
            source = self.endpoint(edge, "from")
            target = self.endpoint(edge, "to")
            if source is None or target is None or source == target:
                continue
            self.outgoing[source].append((target, index))
            self.incoming[target].append((source, index))
            if str(_value(edge, "relation", "") or "") == RelationKind.TESTS:
                self.tested[target] = True
        for mapping in (self.outgoing, self.incoming):
            for node_id in mapping:
                mapping[node_id] = sorted(set(mapping[node_id]))
        self.population = tuple(sorted(
            node_id for node_id, node in self.nodes.items()
            if node_id in node_metrics and not _is_excluded(node) and not _is_test(node)
        ))

    def endpoint(self, edge, side: str) -> Optional[str]:
        raw = _edge_value(edge, "from_id" if side == "from" else "to_id", side)
        if raw is None:
            return None
        node_id = str(raw)
        return node_id if node_id in self.nodes else None

    def metric(self, node_id: str, name: str) -> float:
        value = (self.node_metrics.get(node_id) or {}).get(name, 0.0)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    def traversal(self, edge_index: int, source: str, target: str) -> EdgeTraversal:
        edge = self.edges[edge_index]
        return EdgeTraversal(
            edge_index=edge_index,
            from_node_id=source,
            to_node_id=target,
            relation=str(_value(edge, "relation", "") or ""),
            confidence=str(_value(edge, "confidence", Confidence.STATIC_CERTAIN.value)),
            resolution=str(_value(edge, "resolution", Resolution.EXACT.value)),
        )

    def _path(self, node_ids: Sequence[str], edge_indices: Sequence[int]) -> ExplorationPath:
        traversals = tuple(
            self.traversal(edge_index, node_ids[offset], node_ids[offset + 1])
            for offset, edge_index in enumerate(edge_indices)
        )
        return ExplorationPath(tuple(node_ids), tuple(edge_indices), traversals)

    def incoming_paths(self, node_id: str, limit: int) -> Tuple[ExplorationPath, ...]:
        candidates = [
            (source, index) for source, index in self.incoming[node_id]
            if str(_value(self.edges[index], "relation", "") or "") != RelationKind.CONTAINS
        ] or self.incoming[node_id]
        return tuple(
            self._path((source, node_id), (index,))
            for source, index in candidates[:limit]
        )

    def edge_paths(self, edge_indices: Sequence[int]) -> Tuple[ExplorationPath, ...]:
        paths = []
        for index in edge_indices:
            source = self.endpoint(self.edges[index], "from")
            target = self.endpoint(self.edges[index], "to")
            if source is None or target is None:
                continue
            paths.append(self._path((source, target), (index,)))
        return tuple(paths)

    def name_collisions(self) -> List[Tuple[str, Tuple[str, ...]]]:
        by_label: Dict[str, List[str]] = {}
        for node_id in self.population:
            node = self.nodes[node_id]
            if "ambiguous_name" not in _node_flags(node):
                continue
            by_label.setdefault(str(_value(node, "label", "") or node_id), []).append(node_id)
        return [
            (label, tuple(sorted(members)))
            for label, members in sorted(by_label.items())
            if len(members) >= 2
        ]

    def reference_paths(self, node_ids: Sequence[str], limit: int) -> Tuple[ExplorationPath, ...]:
        paths: List[ExplorationPath] = []
        for node_id in node_ids:
            for path in self.incoming_paths(node_id, limit - len(paths)):
                paths.append(path)
                if len(paths) >= limit:
                    return tuple(paths)
        return tuple(paths)

    def export_edges(self, node_id: str) -> List[int]:
        return sorted(
            index for _target, index in self.outgoing[node_id]
            if str(_value(self.edges[index], "relation", "") or "") in _EXPORT_RELATIONS
        )

    def crossing_pairs(self, node_id: str, limit: int) -> Tuple[ExplorationPath, ...]:
        paths = []
        for source, in_index in self.incoming[node_id]:
            if source not in self.population_set:
                continue
            source_directory = _top_level_directory(self.nodes[source])
            for target, out_index in self.outgoing[node_id]:
                if target == source or target not in self.population_set:
                    continue
                if source_directory == _top_level_directory(self.nodes[target]):
                    continue
                paths.append(self._path((source, node_id, target), (in_index, out_index)))
                if len(paths) >= limit:
                    return tuple(paths)
        return tuple(paths)

    def _structural_successors(self, node_id: str) -> List[Tuple[str, int]]:
        return [
            (target, index) for target, index in self.outgoing[node_id]
            if str(_value(self.edges[index], "relation", "") or "") in _STRUCTURAL_RELATIONS
            and target in self.population_set
        ]

    @property
    def population_set(self) -> Set[str]:
        if not hasattr(self, "_population_set"):
            self._population_set = set(self.population)
        return self._population_set

    def strongly_connected_components(self) -> List[List[str]]:
        index_of: Dict[str, int] = {}
        low: Dict[str, int] = {}
        on_stack: Set[str] = set()
        stack: List[str] = []
        components: List[List[str]] = []
        counter = 0

        for root in self.population:
            if root in index_of:
                continue
            work: List[Tuple[str, int]] = [(root, 0)]
            while work:
                node_id, child = work[-1]
                if child == 0:
                    index_of[node_id] = low[node_id] = counter
                    counter += 1
                    stack.append(node_id)
                    on_stack.add(node_id)
                successors = self._structural_successors(node_id)
                if child < len(successors):
                    work[-1] = (node_id, child + 1)
                    successor = successors[child][0]
                    if successor not in index_of:
                        work.append((successor, 0))
                    elif successor in on_stack:
                        low[node_id] = min(low[node_id], index_of[successor])
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node_id])
                if low[node_id] == index_of[node_id]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node_id:
                            break
                    components.append(sorted(component))
        return components

    def cycle_path(self, component: Sequence[str]) -> Tuple[ExplorationPath, ...]:
        members = set(component)
        start = min(component)
        parents: Dict[str, Tuple[str, int]] = {}
        queue = [start]
        closing: Optional[Tuple[str, int]] = None
        seen = {start}
        while queue and closing is None:
            next_queue = []
            for node_id in queue:
                for target, index in self._structural_successors(node_id):
                    if target not in members:
                        continue
                    if target == start:
                        closing = (node_id, index)
                        break
                    if target not in seen:
                        seen.add(target)
                        parents[target] = (node_id, index)
                        next_queue.append(target)
                if closing is not None:
                    break
            queue = sorted(next_queue)
        if closing is None:
            return ()
        node_ids = [closing[0]]
        edge_indices = [closing[1]]
        current = closing[0]
        while current != start:
            parent, index = parents[current]
            node_ids.append(parent)
            edge_indices.append(index)
            current = parent
        node_ids.reverse()
        edge_indices.reverse()
        return (self._path(tuple(node_ids) + (start,), tuple(edge_indices)),)


def diagnostics_to_dict(report: DiagnosticsReport) -> Dict[str, Any]:
    return report.to_dict()


def diagnostics_collection(report: DiagnosticsReport, nodes: Sequence[Any]) -> ReportCollection:
    labels = {str(_value(node, "id")): str(_value(node, "label", "") or _value(node, "id")) for node in nodes}
    rows = []
    for finding in report.findings:
        subject = ", ".join(labels.get(node_id, node_id) for node_id in finding.node_ids)
        evidence = [
            " -> ".join(labels.get(node_id, node_id) for node_id in path.node_ids)
            for path in finding.evidence_paths
        ]
        rows.append({
            "id": finding.node_ids[0] if finding.node_ids else "",
            "kind": finding.kind.value,
            "subject": subject,
            "metrics": ", ".join(f"{key}={value:g}" for key, value in sorted(finding.metrics.items())),
            "task_types": [item.value for item in finding.applicable_task_types],
            "confidence": finding.confidence,
            "improvement": ", ".join(item.action for item in finding.improvements),
            "false_positive_risks": list(finding.false_positive_risks),
            "evidence": evidence,
        })
    return ReportCollection(
        key="diagnostics",
        label="Diagnostics",
        view="table",
        columns=[
            ColumnSpec("kind", "Diagnostic"),
            ColumnSpec("subject", "Subject", "mono"),
            ColumnSpec("metrics", "Metrics", "mono"),
            ColumnSpec("task_types", "Task Types", "list"),
            ColumnSpec("confidence", "Confidence"),
            ColumnSpec("improvement", "Improvement"),
            ColumnSpec("false_positive_risks", "False Positive Risk", "list"),
            ColumnSpec("evidence", "Evidence Path", "list"),
        ],
        rows=rows,
    )
