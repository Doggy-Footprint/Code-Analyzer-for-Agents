import heapq
import json
import math
import posixpath
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence


class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE_ADD = "feature_add"
    API_CHANGE = "api_change"
    CONFIG_CHANGE = "config_change"


class SeedKind(str, Enum):
    URL = "url"
    SYMBOL = "symbol"
    ERROR = "error"
    CONFIG = "config"
    CHANGED_FILE = "changed_file"


class SearchPolicy(str, Enum):
    BFS = "bfs"
    WEIGHTED_SHORTEST = "weighted_shortest"
    BUDGET_LIMITED = "budget_limited"


@dataclass(frozen=True)
class SeedQuery:
    kind: SeedKind
    value: str

    def __post_init__(self):
        object.__setattr__(self, "kind", SeedKind(self.kind))
        if not isinstance(self.value, str) or not self.value:
            raise ValueError("seed value must be a non-empty string")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SeedQuery":
        if not isinstance(value, Mapping):
            raise ValueError("each seed must be an object")
        try:
            return cls(SeedKind(value["kind"]), value["value"])
        except KeyError as exc:
            raise ValueError(f"seed is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid seed: {exc}") from exc


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    type: TaskType
    seeds: tuple[SeedQuery, ...]
    target_node_ids: frozenset[str] = frozenset()
    impact_node_ids: frozenset[str] = frozenset()
    test_node_ids: frozenset[str] = frozenset()
    budget: Optional[float] = None

    def __post_init__(self):
        object.__setattr__(self, "type", TaskType(self.type))
        object.__setattr__(self, "seeds", tuple(
            seed if isinstance(seed, SeedQuery) else SeedQuery.from_dict(seed)
            for seed in self.seeds
        ))
        object.__setattr__(self, "target_node_ids", self._node_ids(self.target_node_ids, "target_node_ids"))
        object.__setattr__(self, "impact_node_ids", self._node_ids(self.impact_node_ids, "impact_node_ids"))
        object.__setattr__(self, "test_node_ids", self._node_ids(self.test_node_ids, "test_node_ids"))
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("task id must be a non-empty string")
        if self.budget is not None and (
            isinstance(self.budget, bool)
            or not isinstance(self.budget, (int, float))
            or not math.isfinite(self.budget)
            or self.budget < 0
        ):
            raise ValueError("task budget must be a non-negative number")

    @staticmethod
    def _node_ids(values: Any, name: str) -> frozenset[str]:
        if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
            raise ValueError(f"{name} must be a collection of node ids")
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError(f"{name} must contain non-empty strings")
        return frozenset(values)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskDefinition":
        if not isinstance(value, Mapping):
            raise ValueError("each task must be an object")
        goals = value.get("goals", {})
        if goals is None:
            goals = {}
        if not isinstance(goals, Mapping):
            raise ValueError("task goals must be an object")
        def goal(name: str, *aliases: str) -> Any:
            for key in (name, *aliases):
                if key in value:
                    return value[key]
                if key in goals:
                    return goals[key]
            return []
        try:
            if not any(key in value for key in ("seeds", "seed", "seed_clues")):
                raise ValueError("task is missing seeds")
            seeds = value.get("seeds", value.get("seed", value.get("seed_clues", [])))
            if isinstance(seeds, Mapping):
                seeds = [seeds]
            if not isinstance(seeds, list):
                raise ValueError("task seeds must be a list")
            return cls(
                id=value["id"],
                type=TaskType(value["type"]),
                seeds=tuple(SeedQuery.from_dict(item) for item in seeds),
                target_node_ids=goal("target_node_ids", "target_nodes", "targets", "target"),
                impact_node_ids=goal("impact_node_ids", "impact_nodes", "impacts", "impact"),
                test_node_ids=goal("test_node_ids", "test_nodes", "tests", "test"),
                budget=value.get("budget"),
            )
        except KeyError as exc:
            raise ValueError(f"task is missing {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(("task ", "seed ", "target_", "impact_", "test_")):
                raise
            raise ValueError(f"invalid task: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "seeds": [{"kind": seed.kind.value, "value": seed.value} for seed in self.seeds],
            "target_node_ids": sorted(self.target_node_ids),
            "impact_node_ids": sorted(self.impact_node_ids),
            "test_node_ids": sorted(self.test_node_ids),
            "budget": self.budget,
        }


@dataclass(frozen=True)
class SeedRetrieval:
    seed: SeedQuery
    node_ids: tuple[str, ...]


@dataclass(frozen=True)
class EdgeTraversal:
    edge_index: int
    from_node_id: str
    to_node_id: str
    relation: str
    confidence: str
    resolution: str


@dataclass(frozen=True)
class ExplorationPath:
    node_ids: tuple[str, ...]
    edge_indices: tuple[int, ...]
    edges: tuple[EdgeTraversal, ...] = ()


@dataclass(frozen=True)
class Visit:
    node_id: str
    path: ExplorationPath
    cumulative_effective_cost: float


@dataclass(frozen=True)
class GoalDiscovery:
    category: str
    node_id: str
    visit_index: int
    cumulative_effective_cost: float
    path: ExplorationPath


@dataclass(frozen=True)
class BranchingBurden:
    exposed_candidate_count: int
    irrelevant_candidate_count: int
    irrelevant_ratio: float


@dataclass(frozen=True)
class ContextFragmentation:
    unique_file_count: int
    unique_directory_count: int
    total_graph_distance: int
    maximum_graph_distance: int


@dataclass(frozen=True)
class EvidenceGap:
    edge_count: int
    gap_edge_count: int
    dynamic_required_count: int
    ambiguous_count: int
    unresolved_count: int
    ratio: float


@dataclass(frozen=True)
class TaskExplorationReport:
    task_id: str
    task_type: TaskType
    policy: SearchPolicy
    budget: Optional[float]
    retrievals: tuple[SeedRetrieval, ...]
    visited: tuple[Visit, ...]
    goal_discoveries: tuple[GoalDiscovery, ...]
    target_discovery_cost: Optional[float]
    impact_discovery_cost: Optional[float]
    branching_burden: BranchingBurden
    context_fragmentation: ContextFragmentation
    evidence_gap: EvidenceGap
    termination_reason: str

    @property
    def visited_order(self) -> tuple[str, ...]:
        return tuple(visit.node_id for visit in self.visited)

    def to_dict(self) -> Dict[str, Any]:
        value = self._json_value(asdict(self))
        value["visited_order"] = list(self.visited_order)
        return value

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {key: cls._json_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        return value


class TaskExplorer:
    def __init__(self, nodes: Sequence[Any], edges: Sequence[Any], project_path: Optional[str] = None):
        self.nodes = {str(self._value(node, "id")): node for node in nodes}
        self.edges = list(edges)
        self.project_path = Path(project_path).resolve() if project_path else None
        self._source_cache: Dict[Path, str] = {}
        self.adjacency: Dict[str, list[tuple[str, int]]] = {node_id: [] for node_id in self.nodes}
        for index, edge in enumerate(self.edges):
            source = str(self._edge_value(edge, "from_id", "from") or "")
            target = str(self._edge_value(edge, "to_id", "to") or "")
            if source not in self.nodes or target not in self.nodes or source == target:
                continue
            self.adjacency[source].append((target, index))
            self.adjacency[target].append((source, index))
        for node_id in self.adjacency:
            self.adjacency[node_id] = sorted(set(self.adjacency[node_id]), key=lambda item: (item[0], item[1]))

    def retrieve(self, seed: SeedQuery) -> list[str]:
        if not isinstance(seed, SeedQuery):
            seed = SeedQuery.from_dict(seed)
        query = seed.value.strip()
        query_lower = query.casefold()
        matches = []
        for node_id, node in self.nodes.items():
            values = self._search_values(node)
            lowered = [value.casefold() for value in values if value]
            score: Optional[int] = None
            if seed.kind == SeedKind.CHANGED_FILE:
                wanted = self._normalize_path(query)
                paths = {self._normalize_path(path) for path in self._file_values(node)}
                if wanted in paths:
                    score = 0
            elif seed.kind == SeedKind.ERROR:
                if any(query_lower in value for value in lowered):
                    score = 0
            elif seed.kind == SeedKind.URL:
                url_values = [str(value) for value in self._url_values(node)]
                textual = [value.casefold() for value in self._symbol_values(node)]
                textual.extend(value.casefold() for value in url_values)
                if any(query == value for value in url_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in url_values):
                    score = 1
                elif any(query == value for value in self._symbol_values(node)):
                    score = 1
                elif any(query_lower in value for value in textual):
                    score = 2
            elif seed.kind == SeedKind.CONFIG:
                config_values = self._config_values(node)
                if any(query == value for value in config_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in config_values):
                    score = 1
            else:
                symbol_values = self._symbol_values(node)
                if any(query == value for value in symbol_values):
                    score = 0
                elif any(query_lower == value.casefold() for value in symbol_values):
                    score = 1
                elif any(value.endswith("." + query_lower) or value.endswith("#" + query_lower) for value in map(str.casefold, symbol_values)):
                    score = 2
            if score is not None:
                matches.append((score, node_id))
        return [node_id for _, node_id in sorted(matches)]

    def run(
        self,
        task: TaskDefinition,
        policy: SearchPolicy,
        budget: Optional[float] = None,
    ) -> TaskExplorationReport:
        if not isinstance(task, TaskDefinition):
            task = TaskDefinition.from_dict(task)
        policy = SearchPolicy(policy)
        effective_budget = task.budget if budget is None else budget
        if effective_budget is not None and (
            isinstance(effective_budget, bool)
            or not isinstance(effective_budget, (int, float))
            or not math.isfinite(effective_budget)
            or effective_budget < 0
        ):
            raise ValueError("budget must be non-negative")
        retrievals = tuple(SeedRetrieval(seed, tuple(self.retrieve(seed))) for seed in task.seeds)
        seeds = list(dict.fromkeys(node_id for item in retrievals for node_id in item.node_ids))
        if not seeds:
            return self._empty_report(task, policy, effective_budget, retrievals, "no_seeds")
        if effective_budget == 0:
            return self._empty_report(task, policy, effective_budget, retrievals, "budget_exhausted")

        goals = {
            "target": task.target_node_ids,
            "impact": task.impact_node_ids,
            "test": task.test_node_ids,
        }
        all_goals_empty = not any(goals.values())
        visited: list[Visit] = []
        discoveries: list[GoalDiscovery] = []
        discovered = {category: set() for category in goals}
        parents: Dict[str, tuple[Optional[str], Optional[int]]] = {seed: (None, None) for seed in seeds}
        cumulative = 0.0
        exposed = 0
        irrelevant = 0
        truth = set().union(*goals.values())
        exhausted_by_budget = False

        if policy == SearchPolicy.BFS:
            frontier: Any = deque(sorted(seeds))
        else:
            frontier = []
            for seed in sorted(seeds):
                distance = self._effective_cost(self.nodes[seed])
                heapq.heappush(frontier, self._priority(policy, seed, distance, goals) + (seed, distance))
        enqueued = set(seeds)
        best_distance = {seed: self._effective_cost(self.nodes[seed]) for seed in seeds}
        seen = set()

        while frontier:
            if policy == SearchPolicy.BFS:
                node_id = frontier.popleft()
                search_distance = 0.0
            else:
                item = heapq.heappop(frontier)
                _first, _second, node_id, search_distance = item
                if search_distance != best_distance.get(node_id):
                    continue
            if node_id in seen:
                continue
            cost = self._effective_cost(self.nodes[node_id])
            if effective_budget is not None and cumulative + cost > effective_budget:
                exhausted_by_budget = True
                continue
            seen.add(node_id)
            cumulative += cost
            path = self._path(node_id, parents)
            visit = Visit(node_id, path, cumulative)
            visited.append(visit)
            for category, expected in goals.items():
                if node_id in expected and node_id not in discovered[category]:
                    discovered[category].add(node_id)
                    discoveries.append(GoalDiscovery(category, node_id, len(visited) - 1, cumulative, path))
            if not all_goals_empty and all(discovered[name] == expected for name, expected in goals.items()):
                termination = "goals_satisfied"
                break

            candidates = [item for item in self._neighbors(node_id, policy) if item[0] not in seen]
            exposed += len(candidates)
            irrelevant += sum(neighbor not in truth for neighbor, _ in candidates)
            for neighbor, edge_index in candidates:
                if policy == SearchPolicy.BFS:
                    if neighbor in enqueued:
                        continue
                    enqueued.add(neighbor)
                    parents[neighbor] = (node_id, edge_index)
                    frontier.append(neighbor)
                else:
                    edge_penalty = self._edge_penalty(self.edges[edge_index])
                    distance = search_distance + self._effective_cost(self.nodes[neighbor]) + edge_penalty
                    if distance >= best_distance.get(neighbor, float("inf")):
                        continue
                    best_distance[neighbor] = distance
                    parents[neighbor] = (node_id, edge_index)
                    heapq.heappush(frontier, self._priority(policy, neighbor, distance, goals) + (neighbor, distance))
        else:
            termination = "budget_exhausted" if exhausted_by_budget else "frontier_exhausted"

        return self._report(
            task, policy, effective_budget, retrievals, visited, discoveries, exposed, irrelevant, termination
        )

    def _neighbors(self, node_id: str, policy: SearchPolicy) -> list[tuple[str, int]]:
        selected: Dict[str, int] = {}
        for neighbor, edge_index in self.adjacency[node_id]:
            previous = selected.get(neighbor)
            if previous is None:
                selected[neighbor] = edge_index
                continue
            if policy == SearchPolicy.BFS:
                selected[neighbor] = min(previous, edge_index)
                continue
            previous_key = (self._edge_penalty(self.edges[previous]), previous)
            candidate_key = (self._edge_penalty(self.edges[edge_index]), edge_index)
            if candidate_key < previous_key:
                selected[neighbor] = edge_index
        return sorted(selected.items())

    def _priority(self, policy: SearchPolicy, node_id: str, distance: float, goals: Mapping[str, frozenset[str]]) -> tuple[float, float]:
        if policy == SearchPolicy.WEIGHTED_SHORTEST:
            return distance, 0.0
        metadata = self._value(self.nodes[node_id], "metadata", {}) or {}
        declared = metadata.get(
            "task_priority",
            metadata.get("priority", metadata.get("utility", metadata.get("task_relevance", metadata.get("relevance", 0)))),
        )
        declared = float(declared) if isinstance(declared, (int, float)) else 0.0
        return -declared, distance

    def _report(self, task, policy, budget, retrievals, visited, discoveries, exposed, irrelevant, termination):
        target_cost = self._category_completion_cost(task.target_node_ids, discoveries, "target")
        impact_cost = self._category_completion_cost(task.impact_node_ids, discoveries, "impact")
        path_edge_indices = set()
        files = set()
        directories = set()
        distances = []
        unique_discovery_paths = {}
        for discovery in discoveries:
            path_edge_indices.update(discovery.path.edge_indices)
            unique_discovery_paths.setdefault(discovery.node_id, discovery.path)
        for path in unique_discovery_paths.values():
            distances.append(len(path.edge_indices))
            for node_id in path.node_ids:
                for file_path in self._file_values(self.nodes[node_id]):
                    normalized = self._normalize_path(file_path)
                    if normalized:
                        files.add(normalized)
                        directories.add(posixpath.dirname(normalized) or ".")
        dynamic = ambiguous = unresolved = 0
        for index in path_edge_indices:
            edge = self.edges[index]
            confidence = str(self._value(edge, "confidence", ""))
            resolution = str(self._value(edge, "resolution", ""))
            dynamic += confidence == "dynamic_required"
            ambiguous += resolution == "ambiguous"
            unresolved += resolution == "unresolved"
        gap_indices = sum(
            any((
                str(self._value(self.edges[index], "confidence", "")) == "dynamic_required",
                str(self._value(self.edges[index], "resolution", "")) in {"ambiguous", "unresolved"},
            ))
            for index in path_edge_indices
        )
        edge_count = len(path_edge_indices)
        return TaskExplorationReport(
            task.id, task.type, policy, budget, retrievals, tuple(visited), tuple(discoveries),
            target_cost, impact_cost,
            BranchingBurden(exposed, irrelevant, irrelevant / exposed if exposed else 0.0),
            ContextFragmentation(len(files), len(directories), sum(distances), max(distances, default=0)),
            EvidenceGap(edge_count, gap_indices, dynamic, ambiguous, unresolved, gap_indices / edge_count if edge_count else 0.0),
            termination,
        )

    def _empty_report(self, task, policy, budget, retrievals, termination):
        return TaskExplorationReport(
            task.id, task.type, policy, budget, retrievals, (), (),
            None if task.target_node_ids else 0.0,
            None if task.impact_node_ids else 0.0,
            BranchingBurden(0, 0, 0.0), ContextFragmentation(0, 0, 0, 0),
            EvidenceGap(0, 0, 0, 0, 0, 0.0), termination,
        )

    @staticmethod
    def _category_completion_cost(expected, discoveries, category):
        if not expected:
            return 0.0
        found = [item for item in discoveries if item.category == category]
        if {item.node_id for item in found} != set(expected):
            return None
        return max(item.cumulative_effective_cost for item in found)

    def _path(self, node_id, parents):
        node_ids = []
        edge_indices = []
        current = node_id
        while current is not None:
            node_ids.append(current)
            parent, edge_index = parents[current]
            if edge_index is not None:
                edge_indices.append(edge_index)
            current = parent
        ordered_nodes = tuple(reversed(node_ids))
        ordered_indices = tuple(reversed(edge_indices))
        traversals = []
        for offset, edge_index in enumerate(ordered_indices):
            edge = self.edges[edge_index]
            traversals.append(EdgeTraversal(
                edge_index=edge_index,
                from_node_id=ordered_nodes[offset],
                to_node_id=ordered_nodes[offset + 1],
                relation=str(self._value(edge, "relation", "")),
                confidence=str(self._value(edge, "confidence", "static_certain")),
                resolution=str(self._value(edge, "resolution", "exact")),
            ))
        return ExplorationPath(ordered_nodes, ordered_indices, tuple(traversals))

    @staticmethod
    def _value(value, name, default=None):
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _edge_value(cls, edge, attribute, mapping_key):
        if isinstance(edge, Mapping):
            return edge.get(mapping_key, edge.get(attribute))
        return getattr(edge, attribute, None)

    def _effective_cost(self, node):
        metadata = self._value(node, "metadata", {}) or {}
        analysis = metadata.get("analysis", {}) if isinstance(metadata, Mapping) else {}
        explicit = analysis.get("effective_token_cost") if isinstance(analysis, Mapping) else None
        if isinstance(explicit, (int, float)) and explicit >= 0:
            return float(explicit)
        cost = self._value(node, "cost")
        tokens = self._value(cost, "token_estimate") if cost is not None else None
        if not isinstance(tokens, (int, float)):
            tokens = metadata.get("token_cost", 1) if isinstance(metadata, Mapping) else 1
        flags = {str(item).casefold() for item in (self._value(node, "flags", []) or [])}
        if isinstance(metadata, Mapping):
            flags.update(str(item).casefold() for item in (metadata.get("flags", []) or []))
        paths = self._file_values(node)
        path = next(iter(paths), "").casefold()
        multiplier = 1.0
        if "vendored" in flags or "/vendor/" in f"/{path}" or "/node_modules/" in f"/{path}":
            multiplier = 0.0
        elif "generated" in flags or "migration" in flags or "/migrations/" in f"/{path}" or "/alembic/versions/" in f"/{path}":
            multiplier = 0.1
        return float(tokens) * multiplier

    def _edge_penalty(self, edge):
        confidence = str(self._value(edge, "confidence", "static_certain"))
        resolution = str(self._value(edge, "resolution", "exact"))
        confidence_penalty = {"static_certain": 0.0, "static_inferred": 0.5, "framework_inferred": 0.75, "dynamic_required": 2.0}.get(confidence, 1.0)
        resolution_penalty = {"exact": 0.0, "unique_name": 0.25, "ambiguous": 1.5, "unresolved": 2.0}.get(resolution, 1.0)
        return confidence_penalty + resolution_penalty

    def _search_values(self, node):
        metadata = self._value(node, "metadata", {}) or {}
        values = list(self._symbol_values(node))
        values.extend(str(value) for value in self._flatten(metadata))
        values.extend(self._file_values(node))
        source = self._source_text(node)
        if source:
            values.append(source)
        return values

    def _source_text(self, node):
        file_values = self._file_values(node)
        if not file_values:
            return ""
        path = Path(file_values[0])
        if not path.is_absolute() and self.project_path:
            path = self.project_path / path
        if path not in self._source_cache:
            try:
                self._source_cache[path] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                self._source_cache[path] = ""
        source = self._source_cache[path]
        span = self._value(node, "span")
        if not source or span is None:
            return source
        start = self._value(span, "start_line")
        end = self._value(span, "end_line")
        if isinstance(start, int) and isinstance(end, int):
            return "\n".join(source.splitlines()[max(0, start - 1):end])
        return source

    def _symbol_values(self, node):
        return [str(self._value(node, name, "") or "") for name in ("label", "title", "symbol_path", "signature", "docstring")]

    def _url_values(self, node):
        metadata = self._value(node, "metadata", {}) or {}
        keys = ("url", "path", "route", "full_path", "endpoint")
        return [str(metadata[key]) for key in keys if key in metadata and isinstance(metadata[key], (str, int, float))]

    def _config_values(self, node):
        metadata = self._value(node, "metadata", {}) or {}
        values = self._symbol_values(node)
        for key, value in metadata.items():
            if key in {"key", "config_key", "environment_variable", "env", "name"}:
                values.extend((str(key), str(value)))
        return values

    def _file_values(self, node):
        values = []
        span = self._value(node, "span")
        if span is not None:
            file_path = self._value(span, "file_path")
            if file_path:
                values.append(str(file_path))
        metadata = self._value(node, "metadata", {}) or {}
        for key in ("file_path", "path", "source_file", "filename"):
            if metadata.get(key):
                values.append(str(metadata[key]))
        return list(dict.fromkeys(values))

    def _normalize_path(self, value):
        path = str(value).replace("\\", "/")
        if self.project_path:
            candidate = Path(path)
            if candidate.is_absolute():
                try:
                    path = candidate.resolve().relative_to(self.project_path).as_posix()
                except ValueError:
                    path = candidate.as_posix()
        normalized = posixpath.normpath(path)
        return normalized.removeprefix("./")

    @classmethod
    def _flatten(cls, value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                yield key
                yield from cls._flatten(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                yield from cls._flatten(item)
        elif value is not None:
            yield value


def load_task_definitions(path: str | Path) -> list[TaskDefinition]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load task set: {exc}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("tasks")
    if not isinstance(payload, list):
        raise ValueError("task set must be a list or an object containing a tasks list")
    return [TaskDefinition.from_dict(item) for item in payload]


def reports_to_dict(reports: Iterable[TaskExplorationReport]) -> Dict[str, Any]:
    return {"reports": [report.to_dict() for report in reports]}
