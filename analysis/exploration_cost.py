import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from language_analyzers.core.report_schema import ColumnSpec, ReportCollection

from .tasks import TaskDefinition, TaskSeedResolver


@dataclass(frozen=True)
class TargetDiscoveryCost:
    task_id: str
    task_type: str
    target_node_id: Optional[str]
    status: str
    start_frontier_node_ids: Tuple[str, ...]
    unresolved_seed_count: Optional[int]
    min_cost: Optional[float]
    expected_cost: Optional[float]
    max_cost: Optional[float]
    min_path_node_ids: Tuple[str, ...]
    ball_node_ids: Tuple[str, ...]
    target_node_ids: Tuple[str, ...] = ()
    unreachable_target_node_ids: Tuple[str, ...] = ()
    target_min_path_node_ids: Tuple[Tuple[str, Tuple[str, ...]], ...] = ()
    confidence_costs: Tuple[Tuple[str, Optional[float], Optional[float], Optional[float]], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "target_node_id": self.target_node_id,
            "status": self.status,
            "start_frontier_node_ids": list(self.start_frontier_node_ids),
            "unresolved_seed_count": self.unresolved_seed_count,
            "min_cost": self.min_cost,
            "expected_cost": self.expected_cost,
            "max_cost": self.max_cost,
            "min_path_node_ids": list(self.min_path_node_ids),
            "ball_node_ids": list(self.ball_node_ids),
            "target_node_ids": list(self.target_node_ids),
            "unreachable_target_node_ids": list(self.unreachable_target_node_ids),
            "target_min_path_node_ids": {
                target: list(path) for target, path in self.target_min_path_node_ids
            },
            "confidence_costs": {
                name: {"min_cost": minimum, "expected_cost": expected, "max_cost": maximum}
                for name, minimum, expected, maximum in self.confidence_costs
            },
        }


@dataclass(frozen=True)
class TaskExplorationCostReport:
    results: Tuple[TargetDiscoveryCost, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"results": [item.to_dict() for item in self.results]}


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _edge_value(edge: Any, attribute: str, mapping_key: str) -> Any:
    if isinstance(edge, Mapping):
        return edge.get(mapping_key, edge.get(attribute))
    return getattr(edge, attribute, None)


def _node_cost(node_metrics: Mapping[str, Mapping[str, Any]], node_id: str) -> float:
    value = (node_metrics.get(node_id) or {}).get("effective_token_cost", 0.0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


_CONFIDENCE_SCENARIOS = {
    "optimistic": {"static_certain", "static_inferred", "framework_inferred", "dynamic_required"},
    "baseline": {"static_certain", "static_inferred", "framework_inferred"},
    "pessimistic": {"static_certain"},
}


def _build_adjacency(
    edges: Sequence[Any], node_ids: set, allowed_confidences: Optional[set[str]] = None,
) -> Dict[str, set]:
    adjacency: Dict[str, set] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        confidence = str(_edge_value(edge, "confidence", "confidence") or "static_certain")
        if allowed_confidences is not None and confidence not in allowed_confidences:
            continue
        source = _edge_value(edge, "from_id", "from")
        target = _edge_value(edge, "to_id", "to")
        if source is None or target is None:
            continue
        source, target = str(source), str(target)
        if source not in node_ids or target not in node_ids or source == target:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def _dijkstra(
    seeds: set,
    adjacency: Mapping[str, set],
    node_metrics: Mapping[str, Mapping[str, Any]],
    target: Optional[str] = None,
) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
    dist: Dict[str, float] = {s: _node_cost(node_metrics, s) for s in seeds}
    parent: Dict[str, Optional[str]] = {s: None for s in seeds}
    settled: set = set()
    heap = [(dist[s], s) for s in seeds]
    heapq.heapify(heap)
    target_dist: Optional[float] = None
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")) or u in settled:
            continue
        if target_dist is not None and d > target_dist:
            break
        settled.add(u)
        if u == target:
            target_dist = d
        for v in adjacency.get(u, ()):
            if v in settled or v in seeds:
                continue
            candidate = d + _node_cost(node_metrics, v)
            if v not in dist or candidate < dist[v]:
                dist[v] = candidate
                parent[v] = u
                heapq.heappush(heap, (candidate, v))
            elif candidate == dist[v] and u < parent[v]:
                parent[v] = u
    return dist, parent


def _minimum_tree_cost(
    seeds: Iterable[str], targets: Iterable[str], adjacency: Mapping[str, set],
    node_metrics: Mapping[str, Mapping[str, Any]],
) -> Optional[float]:
    target_ids = tuple(sorted(set(targets)))
    if not target_ids:
        return None
    best: Optional[float] = None
    node_ids = tuple(sorted(adjacency))
    for seed in sorted(set(seeds)):
        terminals = (seed, *target_ids)
        if len(set(terminals)) != len(terminals):
            terminals = tuple(dict.fromkeys(terminals))
        full_mask = (1 << len(terminals)) - 1
        states: Dict[int, Dict[str, float]] = {}
        for index, terminal in enumerate(terminals):
            distances, _parents = _dijkstra({terminal}, adjacency, node_metrics)
            states[1 << index] = distances
        for mask in range(1, full_mask + 1):
            if mask & (mask - 1) == 0:
                continue
            values: Dict[str, float] = {}
            part = (mask - 1) & mask
            while part:
                other = mask ^ part
                if other and part < other:
                    for node_id in node_ids:
                        left = states[part].get(node_id)
                        right = states[other].get(node_id)
                        if left is not None and right is not None:
                            candidate = left + right - _node_cost(node_metrics, node_id)
                            if candidate < values.get(node_id, float("inf")):
                                values[node_id] = candidate
                part = (part - 1) & mask
            if not values:
                continue
            distances = dict(values)
            heap = [(value, node_id) for node_id, value in values.items()]
            heapq.heapify(heap)
            while heap:
                value, node_id = heapq.heappop(heap)
                if value != distances.get(node_id):
                    continue
                for neighbor in adjacency.get(node_id, ()):
                    candidate = value + _node_cost(node_metrics, neighbor)
                    if candidate < distances.get(neighbor, float("inf")):
                        distances[neighbor] = candidate
                        heapq.heappush(heap, (candidate, neighbor))
            states[mask] = distances
        candidate = min(states.get(full_mask, {}).values(), default=None)
        if candidate is not None and (best is None or candidate < best):
            best = candidate
    return best


def _reconstruct_path(target: str, parent: Mapping[str, Optional[str]]) -> Tuple[str, ...]:
    path = []
    current: Optional[str] = target
    while current is not None:
        path.append(current)
        current = parent.get(current)
    path.reverse()
    return tuple(path)


class ExplorationCostAnalyzer:
    def compute(
        self,
        tasks: Sequence[TaskDefinition],
        nodes: Sequence[Any],
        edges: Sequence[Any],
        node_metrics: Mapping[str, Mapping[str, Any]],
        project_path: Optional[str | Path] = None,
        source_reader: Optional[Callable[[Path], str]] = None,
    ) -> TaskExplorationCostReport:
        node_ids = {str(_value(node, "id")) for node in nodes}
        adjacencies = {
            name: _build_adjacency(edges, node_ids, confidences)
            for name, confidences in _CONFIDENCE_SCENARIOS.items()
        }
        resolver = TaskSeedResolver(nodes, project_path, source_reader)
        results = tuple(
            self._compute_task(task, adjacencies, node_metrics, resolver) for task in tasks
        )
        return TaskExplorationCostReport(results)

    def _compute_task(
        self,
        task: TaskDefinition,
        adjacencies: Mapping[str, Mapping[str, set]],
        node_metrics: Mapping[str, Mapping[str, Any]],
        resolver: TaskSeedResolver,
    ) -> TargetDiscoveryCost:
        targets = tuple(sorted(task.target_node_ids))
        target = targets[0] if len(targets) == 1 else None
        if not targets:
            return TargetDiscoveryCost(
                task_id=task.id, task_type=task.type.value, target_node_id=None,
                status="empty_target_set", start_frontier_node_ids=(), unresolved_seed_count=None,
                min_cost=None, expected_cost=None, max_cost=None, min_path_node_ids=(), ball_node_ids=(),
            )

        frontier: set = set()
        unresolved_seed_count = 0
        for seed in task.seeds:
            scored = resolver.retrieve_scored(seed)
            if not scored:
                unresolved_seed_count += 1
                continue
            best_score = scored[0][0]
            frontier.update(node_id for score, node_id in scored if score == best_score)

        if not frontier:
            return TargetDiscoveryCost(
                task_id=task.id, task_type=task.type.value, target_node_id=target,
                status="empty_start_frontier", start_frontier_node_ids=(),
                unresolved_seed_count=unresolved_seed_count, min_cost=None, expected_cost=None,
                max_cost=None, min_path_node_ids=(), ball_node_ids=(), target_node_ids=targets,
            )
        baseline = self._costs_for_adjacency(frontier, targets, adjacencies["baseline"], node_metrics)
        status, min_cost, expected_cost, max_cost, ball, paths, unreachable = baseline
        confidence_costs = tuple(
            (name, *self._costs_for_adjacency(frontier, targets, adjacency, node_metrics)[1:4])
            for name, adjacency in adjacencies.items()
        )
        return TargetDiscoveryCost(
            task_id=task.id, task_type=task.type.value, target_node_id=target,
            status=status, start_frontier_node_ids=tuple(sorted(frontier)),
            unresolved_seed_count=unresolved_seed_count, min_cost=min_cost, expected_cost=expected_cost,
            max_cost=max_cost, min_path_node_ids=paths[0][1] if target is not None and paths else (),
            ball_node_ids=ball, target_node_ids=targets, unreachable_target_node_ids=unreachable,
            target_min_path_node_ids=paths, confidence_costs=confidence_costs,
        )

    @staticmethod
    def _costs_for_adjacency(
        frontier: set, targets: Tuple[str, ...], adjacency: Mapping[str, set],
        node_metrics: Mapping[str, Mapping[str, Any]],
    ) -> Tuple[str, Optional[float], Optional[float], Optional[float], Tuple[str, ...], Tuple[Tuple[str, Tuple[str, ...]], ...], Tuple[str, ...]]:
        dist, parent = _dijkstra(frontier, adjacency, node_metrics)
        unreachable = tuple(target for target in targets if target not in dist)
        paths = tuple(
            (target, _reconstruct_path(target, parent)) for target in targets if target in dist
        )
        if unreachable:
            return "target_unreachable", None, None, None, (), paths, unreachable
        radius = max(dist[target] for target in targets)
        ball = tuple(sorted(node_id for node_id, value in dist.items() if value <= radius))
        final_targets = {target for target in targets if dist[target] == radius}
        minimum = _minimum_tree_cost(frontier, targets, adjacency, node_metrics)
        maximum = sum(_node_cost(node_metrics, node_id) for node_id in ball)
        expected = sum(
            _node_cost(node_metrics, node_id)
            for node_id in ball
            if dist[node_id] < radius or node_id in final_targets
        ) + (len(final_targets) / (len(final_targets) + 1)) * sum(
            _node_cost(node_metrics, node_id)
            for node_id in ball
            if dist[node_id] == radius and node_id not in final_targets
        )
        return "ok", minimum, expected, maximum, ball, paths, ()


def exploration_cost_to_dict(report: TaskExplorationCostReport) -> Dict[str, Any]:
    return report.to_dict()


def exploration_cost_collection(report: TaskExplorationCostReport, nodes: Sequence[Any]) -> ReportCollection:
    labels = {str(_value(node, "id")): str(_value(node, "label", "") or _value(node, "id")) for node in nodes}
    rows = []
    for result in report.results:
        scenarios = {name: (minimum, expected, maximum) for name, minimum, expected, maximum in result.confidence_costs}

        def scenario_cost(name: str) -> str:
            values = scenarios.get(name)
            if values is None or any(value is None for value in values):
                return ""
            return " / ".join(f"{value:g}" for value in values)

        rows.append({
            "id": result.task_id,
            "task_type": result.task_type,
            "target": ", ".join(labels.get(node_id, node_id) for node_id in result.target_node_ids),
            "status": result.status,
            "seeds": [labels.get(node_id, node_id) for node_id in result.start_frontier_node_ids],
            "min_cost": f"{result.min_cost:g}" if result.min_cost is not None else "",
            "expected_cost": f"{result.expected_cost:g}" if result.expected_cost is not None else "",
            "max_cost": f"{result.max_cost:g}" if result.max_cost is not None else "",
            "min_path_length": len(result.min_path_node_ids) if result.status == "ok" else "",
            "cost_spread": f"{result.max_cost - result.min_cost:g}" if result.status == "ok" else "",
            "optimistic_costs": scenario_cost("optimistic"),
            "pessimistic_costs": scenario_cost("pessimistic"),
        })
    return ReportCollection(
        key="exploration_cost",
        label="Exploration Cost",
        view="table",
        columns=[
            ColumnSpec("id", "Task"),
            ColumnSpec("task_type", "Type"),
            ColumnSpec("target", "Target", "mono"),
            ColumnSpec("status", "Status"),
            ColumnSpec("seeds", "Seeds", "list"),
            ColumnSpec("min_cost", "Min Cost", "mono"),
            ColumnSpec("expected_cost", "Expected Cost", "mono"),
            ColumnSpec("max_cost", "Max Cost", "mono"),
            ColumnSpec("min_path_length", "Min Path Length", "mono"),
            ColumnSpec("cost_spread", "Max − Min Gap", "mono"),
            ColumnSpec("optimistic_costs", "Optimistic (Min / Expected / Max)", "mono"),
            ColumnSpec("pessimistic_costs", "Pessimistic (Min / Expected / Max)", "mono"),
        ],
        rows=rows,
    )
