import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

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


def _build_adjacency(edges: Sequence[Any], node_ids: set) -> Dict[str, set]:
    adjacency: Dict[str, set] = {node_id: set() for node_id in node_ids}
    for edge in edges:
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
    target: str,
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
        # keep draining past the target so every node tied with its distance is finalized too
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
        adjacency = _build_adjacency(edges, node_ids)
        resolver = TaskSeedResolver(nodes, project_path, source_reader)
        results = tuple(
            self._compute_task(task, adjacency, node_metrics, resolver) for task in tasks
        )
        return TaskExplorationCostReport(results)

    def _compute_task(
        self,
        task: TaskDefinition,
        adjacency: Mapping[str, set],
        node_metrics: Mapping[str, Mapping[str, Any]],
        resolver: TaskSeedResolver,
    ) -> TargetDiscoveryCost:
        if len(task.target_node_ids) != 1:
            return TargetDiscoveryCost(
                task_id=task.id, task_type=task.type.value, target_node_id=None,
                status="unsupported_multi_target", start_frontier_node_ids=(),
                unresolved_seed_count=None, min_cost=None, expected_cost=None, max_cost=None,
                min_path_node_ids=(), ball_node_ids=(),
            )
        target = next(iter(task.target_node_ids))

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
                max_cost=None, min_path_node_ids=(), ball_node_ids=(),
            )

        dist, parent = _dijkstra(frontier, adjacency, node_metrics, target)
        if target not in dist:
            return TargetDiscoveryCost(
                task_id=task.id, task_type=task.type.value, target_node_id=target,
                status="target_unreachable", start_frontier_node_ids=tuple(sorted(frontier)),
                unresolved_seed_count=unresolved_seed_count, min_cost=None, expected_cost=None,
                max_cost=None, min_path_node_ids=(), ball_node_ids=(),
            )

        min_cost = dist[target]
        ball = tuple(sorted(node_id for node_id, value in dist.items() if value <= min_cost))
        max_cost = sum(_node_cost(node_metrics, node_id) for node_id in ball)
        expected_cost = (
            sum(_node_cost(node_metrics, node_id) for node_id in ball if dist[node_id] < min_cost)
            + _node_cost(node_metrics, target)
            + 0.5 * sum(
                _node_cost(node_metrics, node_id)
                for node_id in ball
                if dist[node_id] == min_cost and node_id != target
            )
        )
        return TargetDiscoveryCost(
            task_id=task.id, task_type=task.type.value, target_node_id=target,
            status="ok", start_frontier_node_ids=tuple(sorted(frontier)),
            unresolved_seed_count=unresolved_seed_count, min_cost=min_cost, expected_cost=expected_cost,
            max_cost=max_cost, min_path_node_ids=_reconstruct_path(target, parent), ball_node_ids=ball,
        )


def exploration_cost_to_dict(report: TaskExplorationCostReport) -> Dict[str, Any]:
    return report.to_dict()


def exploration_cost_collection(report: TaskExplorationCostReport, nodes: Sequence[Any]) -> ReportCollection:
    labels = {str(_value(node, "id")): str(_value(node, "label", "") or _value(node, "id")) for node in nodes}
    rows = []
    for result in report.results:
        rows.append({
            "id": result.task_id,
            "task_type": result.task_type,
            "target": labels.get(result.target_node_id, result.target_node_id) if result.target_node_id is not None else "",
            "status": result.status,
            "seeds": [labels.get(node_id, node_id) for node_id in result.start_frontier_node_ids],
            "min_cost": f"{result.min_cost:g}" if result.min_cost is not None else "",
            "expected_cost": f"{result.expected_cost:g}" if result.expected_cost is not None else "",
            "max_cost": f"{result.max_cost:g}" if result.max_cost is not None else "",
            "min_path_length": len(result.min_path_node_ids) if result.status == "ok" else "",
            "cost_spread": f"{result.max_cost - result.min_cost:g}" if result.status == "ok" else "",
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
        ],
        rows=rows,
    )
