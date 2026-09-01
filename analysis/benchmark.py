import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .task_exploration import SearchPolicy, TaskDefinition, TaskExplorer


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
        object.__setattr__(self, "actions", actions)
        if any(not isinstance(action, TraceAction) for action in self.actions):
            raise ValueError("trace actions must contain TraceAction values")


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
            ))
    return tuple(results)
