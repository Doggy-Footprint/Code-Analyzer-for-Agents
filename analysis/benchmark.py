import json
import math
from collections.abc import Sequence as AbcSequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .task_exploration import SearchPolicy, TaskDefinition, TaskExplorationReport, TaskExplorer


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class BenchmarkTask:
    repository: str
    revision: str
    task: TaskDefinition

    def __post_init__(self) -> None:
        _non_empty_string(self.repository, "repository")
        _non_empty_string(self.revision, "revision")
        if not isinstance(self.task, TaskDefinition):
            raise ValueError("task must be a TaskDefinition")


@dataclass(frozen=True)
class BenchmarkDefinition:
    tasks: tuple[BenchmarkTask, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tasks", tuple(self.tasks))
        if not self.tasks:
            raise ValueError("benchmarks must not be empty")
        if any(not isinstance(item, BenchmarkTask) for item in self.tasks):
            raise ValueError("benchmarks must contain BenchmarkTask values")
        keys = [(item.repository, item.revision, item.task.id) for item in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("benchmark task ids must be unique per repository revision")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BenchmarkDefinition":
        if not isinstance(value, Mapping) or set(value) != {"benchmarks"}:
            raise ValueError("benchmark definition must contain only benchmarks")
        entries = value["benchmarks"]
        if not isinstance(entries, list):
            raise ValueError("benchmarks must be a list")
        tasks = []
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {"repository", "revision", "task"}:
                raise ValueError("each benchmark must contain repository, revision, and task")
            task = entry["task"]
            if isinstance(task, Mapping):
                task = TaskDefinition.from_dict(task)
            elif not isinstance(task, TaskDefinition):
                raise ValueError("benchmark task must be a TaskDefinition or object")
            tasks.append(BenchmarkTask(entry["repository"], entry["revision"], task))
        return cls(tuple(tasks))


def load_benchmark_definition(path: str | Path) -> BenchmarkDefinition:
    try:
        with Path(path).open(encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load benchmark definition: {exc}") from exc
    return BenchmarkDefinition.from_dict(value)


@dataclass(frozen=True)
class TraceAction:
    kind: str
    target: str
    tokens: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"search", "open"}:
            raise ValueError("trace action kind must be search or open")
        _non_empty_string(self.target, "trace action target")
        if self.tokens is not None and (
            isinstance(self.tokens, bool)
            or not isinstance(self.tokens, (int, float))
            or not math.isfinite(self.tokens)
            or self.tokens < 0
        ):
            raise ValueError("trace action tokens must be a non-negative finite real number")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceAction":
        if not isinstance(value, Mapping) or not set(value) <= {"kind", "target", "tokens"} or "kind" not in value or "target" not in value:
            raise ValueError("each trace action must be an object with kind and target")
        try:
            return cls(value["kind"], value["target"], value.get("tokens"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid trace action: {exc}") from exc


@dataclass(frozen=True)
class AgentTrace:
    repository: str
    revision: str
    task_id: str
    actions: tuple[TraceAction, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.repository, "repository")
        _non_empty_string(self.revision, "revision")
        _non_empty_string(self.task_id, "task id")
        try:
            actions = tuple(self.actions)
        except TypeError as exc:
            raise ValueError("trace actions must be an iterable of TraceAction values") from exc
        object.__setattr__(self, "actions", tuple(
            action if isinstance(action, TraceAction) else TraceAction.from_dict(action)
            for action in actions
        ))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentTrace":
        if not isinstance(value, Mapping) or set(value) != {"repository", "revision", "task_id", "actions"}:
            raise ValueError("each trace must contain repository, revision, task_id, and actions")
        actions = value["actions"]
        if not isinstance(actions, list):
            raise ValueError("trace actions must be a list")
        try:
            return cls(value["repository"], value["revision"], value["task_id"], tuple(actions))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(("repository", "revision", "task id", "trace")):
                raise
            raise ValueError(f"invalid trace: {exc}") from exc


def load_agent_traces(path: str | Path) -> tuple[AgentTrace, ...]:
    try:
        with Path(path).open(encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load agent traces: {exc}") from exc
    if not isinstance(value, Mapping) or set(value) != {"traces"} or not isinstance(value["traces"], list):
        raise ValueError("agent trace file must contain only a traces list")
    return tuple(AgentTrace.from_dict(entry) for entry in value["traces"])


@dataclass(frozen=True)
class TraceMetrics:
    tool_call_count: int
    search_count: int
    open_count: int
    unique_open_target_count: int
    unique_open_token_cost: float
    backtracking_count: int


@dataclass(frozen=True)
class BenchmarkResult:
    repository: str
    revision: str
    task_id: str
    policy: SearchPolicy
    predicted_target_discovery_cost: float | None
    predicted_impact_discovery_cost: float | None
    trace_metrics: TraceMetrics | None
    target_node_ids: frozenset[str]
    impact_node_ids: frozenset[str]
    report: TaskExplorationReport


def _trace_metrics(trace: AgentTrace) -> TraceMetrics:
    opened = set()
    unique_cost = 0.0
    backtracking = 0
    previous_open_target: str | None = None
    for action in trace.actions:
        if action.kind != "open":
            continue
        if action.target in opened:
            if action.target != previous_open_target:
                backtracking += 1
        else:
            opened.add(action.target)
            unique_cost += action.tokens or 0.0
        previous_open_target = action.target
    return TraceMetrics(
        tool_call_count=len(trace.actions),
        search_count=sum(action.kind == "search" for action in trace.actions),
        open_count=sum(action.kind == "open" for action in trace.actions),
        unique_open_target_count=len(opened),
        unique_open_token_cost=unique_cost,
        backtracking_count=backtracking,
    )


def evaluate_benchmark(
    definition: BenchmarkDefinition,
    explorer_by_repository_revision: Mapping[tuple[str, str], TaskExplorer],
    traces: Iterable[AgentTrace],
    policies: Iterable[SearchPolicy] = tuple(SearchPolicy),
) -> tuple[BenchmarkResult, ...]:
    if not isinstance(definition, BenchmarkDefinition):
        raise ValueError("definition must be a BenchmarkDefinition")
    policy_values = tuple(SearchPolicy(policy) for policy in policies)
    trace_by_key: dict[tuple[str, str, str], AgentTrace] = {}
    benchmark_keys = {(item.repository, item.revision, item.task.id) for item in definition.tasks}
    for trace in traces:
        if not isinstance(trace, AgentTrace):
            raise ValueError("traces must contain AgentTrace values")
        key = (trace.repository, trace.revision, trace.task_id)
        if key not in benchmark_keys:
            raise ValueError("trace does not match a benchmark task")
        if key in trace_by_key:
            raise ValueError("multiple traces match a benchmark task")
        trace_by_key[key] = trace
    results = []
    for benchmark in definition.tasks:
        explorer_key = (benchmark.repository, benchmark.revision)
        explorer = explorer_by_repository_revision.get(explorer_key)
        if not isinstance(explorer, TaskExplorer):
            raise ValueError("missing TaskExplorer for benchmark repository revision")
        goal_node_ids = (
            benchmark.task.target_node_ids
            | benchmark.task.impact_node_ids
            | benchmark.task.test_node_ids
        )
        if not goal_node_ids.issubset(explorer.nodes):
            raise ValueError("benchmark task contains unknown node id")
        trace = trace_by_key.get((benchmark.repository, benchmark.revision, benchmark.task.id))
        metrics = _trace_metrics(trace) if trace is not None else None
        for policy in policy_values:
            report = explorer.run(benchmark.task, policy)
            results.append(BenchmarkResult(
                benchmark.repository,
                benchmark.revision,
                benchmark.task.id,
                policy,
                report.target_discovery_cost,
                report.impact_discovery_cost,
                metrics,
                benchmark.task.target_node_ids,
                benchmark.task.impact_node_ids,
                report,
            ))
    return tuple(results)


_CATEGORY_ATTRS = {
    "target": ("predicted_target_discovery_cost", "target_node_ids"),
    "impact": ("predicted_impact_discovery_cost", "impact_node_ids"),
}


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average_rank = (index + end) / 2.0 + 1.0
        for offset in range(index, end + 1):
            ranks[order[offset]] = average_rank
        index = end + 1
    return ranks


def _spearman(predicted: Sequence[float], actual: Sequence[float]) -> float | None:
    count = len(predicted)
    if count < 2:
        return None
    predicted_ranks = _ranks(predicted)
    actual_ranks = _ranks(actual)
    if len(set(predicted_ranks)) == 1 or len(set(actual_ranks)) == 1:
        return None
    mean_predicted = sum(predicted_ranks) / count
    mean_actual = sum(actual_ranks) / count
    covariance = sum(
        (p - mean_predicted) * (a - mean_actual) for p, a in zip(predicted_ranks, actual_ranks)
    )
    predicted_variance = sum((p - mean_predicted) ** 2 for p in predicted_ranks)
    actual_variance = sum((a - mean_actual) ** 2 for a in actual_ranks)
    denominator = math.sqrt(predicted_variance * actual_variance)
    if denominator == 0:
        return None
    return covariance / denominator


@dataclass(frozen=True)
class CostAccuracy:
    policy: SearchPolicy
    category: str
    pair_count: int
    rank_correlation: float | None
    mean_absolute_error: float | None
    mean_relative_error: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.value,
            "category": self.category,
            "pair_count": self.pair_count,
            "rank_correlation": self.rank_correlation,
            "mean_absolute_error": self.mean_absolute_error,
            "mean_relative_error": self.mean_relative_error,
        }


@dataclass(frozen=True)
class RetrievalMetrics:
    policy: SearchPolicy
    category: str
    k: int
    task_count: int
    recall_at_k: float
    precision_at_k: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy.value,
            "category": self.category,
            "k": self.k,
            "task_count": self.task_count,
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
        }


@dataclass(frozen=True)
class BenchmarkSummary:
    cost_accuracy: tuple[CostAccuracy, ...]
    retrieval_metrics: tuple[RetrievalMetrics, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_accuracy": [item.to_dict() for item in self.cost_accuracy],
            "retrieval_metrics": [item.to_dict() for item in self.retrieval_metrics],
        }


def summarize_benchmark(
    results: Sequence[BenchmarkResult],
    k_values: Sequence[int] = (5, 10, 20),
) -> BenchmarkSummary:
    if not isinstance(results, AbcSequence) or isinstance(results, (str, bytes)):
        raise ValueError("results must be a Sequence of BenchmarkResult")
    results = list(results)
    if any(not isinstance(item, BenchmarkResult) for item in results):
        raise ValueError("results must contain BenchmarkResult values")

    if not isinstance(k_values, AbcSequence) or isinstance(k_values, (str, bytes)):
        raise ValueError("k_values must be a Sequence of positive integers")
    k_list = list(k_values)
    seen_k: set[int] = set()
    for k in k_list:
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError("k_values must contain positive integers")
        if k in seen_k:
            raise ValueError("k_values must not contain duplicates")
        seen_k.add(k)

    if not results:
        return BenchmarkSummary((), ())

    policy_order: list[SearchPolicy] = []
    seen_policies = set()
    for result in results:
        if result.policy not in seen_policies:
            seen_policies.add(result.policy)
            policy_order.append(result.policy)

    cost_accuracy: list[CostAccuracy] = []
    retrieval_metrics: list[RetrievalMetrics] = []
    for policy in policy_order:
        policy_results = [result for result in results if result.policy == policy]
        for category in ("target", "impact"):
            predicted_attr, label_attr = _CATEGORY_ATTRS[category]
            pairs = [
                (getattr(result, predicted_attr), result.trace_metrics.unique_open_token_cost)
                for result in policy_results
                if getattr(result, predicted_attr) is not None and result.trace_metrics is not None
            ]
            pair_count = len(pairs)
            if pair_count == 0:
                cost_accuracy.append(CostAccuracy(policy, category, 0, None, None, None))
            else:
                predicted_values = [predicted for predicted, _ in pairs]
                actual_values = [actual for _, actual in pairs]
                mean_absolute_error = sum(abs(predicted - actual) for predicted, actual in pairs) / pair_count
                nonzero_pairs = [(predicted, actual) for predicted, actual in pairs if actual > 0]
                mean_relative_error = (
                    sum(abs(predicted - actual) / actual for predicted, actual in nonzero_pairs) / len(nonzero_pairs)
                    if nonzero_pairs
                    else None
                )
                rank_correlation = _spearman(predicted_values, actual_values)
                cost_accuracy.append(CostAccuracy(
                    policy, category, pair_count, rank_correlation, mean_absolute_error, mean_relative_error,
                ))

            eligible = [result for result in policy_results if getattr(result, label_attr)]
            if not eligible:
                continue
            for k in k_list:
                recalls = []
                precisions = []
                for result in eligible:
                    label_set = getattr(result, label_attr)
                    found = {
                        discovery.node_id
                        for discovery in result.report.goal_discoveries
                        if discovery.category == category and discovery.visit_index < k
                    }
                    recalls.append(len(found & label_set) / len(label_set))
                    denominator = min(k, len(result.report.visited_order))
                    precisions.append((len(found & label_set) / denominator) if denominator else 0.0)
                retrieval_metrics.append(RetrievalMetrics(
                    policy,
                    category,
                    k,
                    len(eligible),
                    sum(recalls) / len(recalls),
                    sum(precisions) / len(precisions),
                ))

    return BenchmarkSummary(tuple(cost_accuracy), tuple(retrieval_metrics))
