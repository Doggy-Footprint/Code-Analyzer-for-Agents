from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from language_analyzers.core.report_schema import ColumnSpec, ReportCollection

from .exploration_cost import TaskExplorationCostReport

__all__ = [
    "TaskDifficultySignals",
    "TaskDifficultyRank",
    "TaskDifficultyReport",
    "TaskDifficultyAnalyzer",
    "task_difficulty_to_dict",
    "task_difficulty_collection",
]

SIGNAL_NAMES: Tuple[str, ...] = (
    "min_cost",
    "expected_cost",
    "max_cost",
    "cost_spread",
    "branching",
    "evidence_gap",
)


@dataclass(frozen=True)
class TaskDifficultySignals:
    task_id: str
    min_cost: float
    expected_cost: float
    max_cost: float
    cost_spread: float
    branching: int
    evidence_gap: Optional[float]


@dataclass(frozen=True)
class TaskDifficultyRank:
    task_id: str
    rank: Optional[int]
    borda_score: Optional[float]
    signal_ranks: Dict[str, float]
    excluded: bool
    exclusion_reason: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "rank": self.rank,
            "borda_score": self.borda_score,
            "signal_ranks": dict(self.signal_ranks),
            "excluded": self.excluded,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class TaskDifficultyReport:
    ranks: Tuple[TaskDifficultyRank, ...]
    excluded: Tuple[TaskDifficultyRank, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ranks": [item.to_dict() for item in self.ranks],
            "excluded": [item.to_dict() for item in self.excluded],
        }


def _fractional_ranks_desc(values: Mapping[str, float]) -> Dict[str, float]:
    """Rank 1 goes to the largest value; ties share the average of their positions."""
    ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    ranks: Dict[str, float] = {}
    index = 0
    total = len(ordered)
    while index < total:
        end = index
        while end + 1 < total and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_position = (index + 1 + end + 1) / 2
        for offset in range(index, end + 1):
            ranks[ordered[offset][0]] = average_position
        index = end + 1
    return ranks


def _competition_ranks(scores: Mapping[str, float]) -> Dict[str, int]:
    ordered = sorted(scores.items(), key=lambda item: (item[1], item[0]))
    ranks: Dict[str, int] = {}
    for position, (task_id, score) in enumerate(ordered):
        if position == 0:
            ranks[task_id] = 1
            continue
        previous_id, previous_score = ordered[position - 1]
        ranks[task_id] = ranks[previous_id] if score == previous_score else position + 1
    return ranks


class TaskDifficultyAnalyzer:
    def compute(self, cost_report: TaskExplorationCostReport) -> TaskDifficultyReport:
        signals: Dict[str, TaskDifficultySignals] = {}
        excluded: list[TaskDifficultyRank] = []
        for result in cost_report.results:
            if result.status != "ok":
                excluded.append(TaskDifficultyRank(
                    task_id=result.task_id, rank=None, borda_score=None,
                    signal_ranks={}, excluded=True, exclusion_reason=result.status,
                ))
                continue
            signals[result.task_id] = TaskDifficultySignals(
                task_id=result.task_id,
                min_cost=result.min_cost,
                expected_cost=result.expected_cost,
                max_cost=result.max_cost,
                cost_spread=result.max_cost - result.min_cost,
                branching=len(result.ball_node_ids) - len(result.target_node_ids),
                evidence_gap=self._evidence_gap(result.confidence_costs),
            )

        if not signals:
            return TaskDifficultyReport(ranks=(), excluded=tuple(excluded))

        per_signal_ranks = {
            name: _fractional_ranks_desc(self._signal_values(signals, name))
            for name in SIGNAL_NAMES
        }

        borda_scores: Dict[str, float] = {}
        signal_ranks_by_task: Dict[str, Dict[str, float]] = {}
        for task_id in signals:
            task_signal_ranks = {name: per_signal_ranks[name][task_id] for name in SIGNAL_NAMES}
            signal_ranks_by_task[task_id] = task_signal_ranks
            borda_scores[task_id] = sum(task_signal_ranks.values())

        final_ranks = _competition_ranks(borda_scores)
        ranks = tuple(
            TaskDifficultyRank(
                task_id=task_id,
                rank=final_ranks[task_id],
                borda_score=borda_scores[task_id],
                signal_ranks=signal_ranks_by_task[task_id],
                excluded=False,
                exclusion_reason=None,
            )
            for task_id in sorted(signals, key=lambda task_id: (final_ranks[task_id], task_id))
        )
        return TaskDifficultyReport(ranks=ranks, excluded=tuple(excluded))

    @staticmethod
    def _evidence_gap(
        confidence_costs: Tuple[Tuple[str, Optional[float], Optional[float], Optional[float]], ...],
    ) -> Optional[float]:
        scenarios = {name: (minimum, expected, maximum) for name, minimum, expected, maximum in confidence_costs}
        optimistic = scenarios.get("optimistic")
        pessimistic = scenarios.get("pessimistic")
        if optimistic is None or pessimistic is None:
            return None
        optimistic_max, pessimistic_max = optimistic[2], pessimistic[2]
        if optimistic_max is None or pessimistic_max is None:
            return None
        return pessimistic_max - optimistic_max

    @staticmethod
    def _signal_values(signals: Mapping[str, TaskDifficultySignals], name: str) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for task_id, signal in signals.items():
            value = getattr(signal, name)
            if value is None:
                value = float("inf") if name == "evidence_gap" else 0.0
            values[task_id] = float(value)
        return values


def task_difficulty_to_dict(report: TaskDifficultyReport) -> Dict[str, Any]:
    return report.to_dict()


def task_difficulty_collection(report: TaskDifficultyReport) -> ReportCollection:
    def signal_cell(rank: TaskDifficultyRank, name: str) -> str:
        value = rank.signal_ranks.get(name)
        return f"{value:g}" if value is not None else ""

    rows = []
    for rank in report.ranks:
        row = {
            "id": rank.task_id,
            "rank": rank.rank,
            "borda_score": f"{rank.borda_score:g}" if rank.borda_score is not None else "",
            "excluded": "",
        }
        row.update({name: signal_cell(rank, name) for name in SIGNAL_NAMES})
        rows.append(row)
    for rank in report.excluded:
        row = {"id": rank.task_id, "rank": "", "borda_score": "", "excluded": rank.exclusion_reason or "excluded"}
        row.update({name: "" for name in SIGNAL_NAMES})
        rows.append(row)

    return ReportCollection(
        key="task_difficulty",
        label="Task Difficulty",
        view="table",
        columns=[
            ColumnSpec("id", "Task"),
            ColumnSpec("rank", "Rank", "mono"),
            ColumnSpec("borda_score", "Borda Score", "mono"),
            ColumnSpec("min_cost", "Min Cost Rank", "mono"),
            ColumnSpec("expected_cost", "Expected Cost Rank", "mono"),
            ColumnSpec("max_cost", "Max Cost Rank", "mono"),
            ColumnSpec("cost_spread", "Cost Spread Rank", "mono"),
            ColumnSpec("branching", "Branching Rank", "mono"),
            ColumnSpec("evidence_gap", "Evidence Gap Rank", "mono"),
            ColumnSpec("excluded", "Excluded", "text"),
        ],
        rows=rows,
    )
