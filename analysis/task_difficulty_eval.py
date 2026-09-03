import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .task_difficulty import TaskDifficultyRank, TaskDifficultyReport

__all__ = [
    "PairwiseLabel",
    "PairwiseComparison",
    "PairwiseEvaluation",
    "pairwise_accuracy",
    "load_pairwise_labels",
]


@dataclass(frozen=True)
class PairwiseLabel:
    harder_task_id: str
    easier_task_id: str
    kind: str = "strict"  # "strict" or "tie"

    def __post_init__(self):
        if self.kind not in ("strict", "tie"):
            raise ValueError(f"invalid pairwise label kind: {self.kind!r}")
        if not self.harder_task_id or not self.easier_task_id:
            raise ValueError("pairwise label task ids must be non-empty strings")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PairwiseLabel":
        if not isinstance(value, Mapping):
            raise ValueError("each pairwise label must be an object")
        try:
            return cls(
                harder_task_id=value["harder_task_id"],
                easier_task_id=value["easier_task_id"],
                kind=value.get("kind", "strict"),
            )
        except KeyError as exc:
            raise ValueError(f"pairwise label is missing {exc.args[0]}") from exc


@dataclass(frozen=True)
class PairwiseComparison:
    harder_task_id: str
    easier_task_id: str
    kind: str
    model_rank_harder: Optional[int]
    model_rank_easier: Optional[int]
    borda_harder: Optional[float]
    borda_easier: Optional[float]
    outcome: str  # "agree" | "disagree" | "incomparable"
    reason: Optional[str]
    signal_rank_diffs: Dict[str, float]  # per signal: harder's rank minus easier's rank (negative supports the label)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "harder_task_id": self.harder_task_id,
            "easier_task_id": self.easier_task_id,
            "kind": self.kind,
            "model_rank_harder": self.model_rank_harder,
            "model_rank_easier": self.model_rank_easier,
            "borda_harder": self.borda_harder,
            "borda_easier": self.borda_easier,
            "outcome": self.outcome,
            "reason": self.reason,
            "signal_rank_diffs": dict(self.signal_rank_diffs),
        }


@dataclass(frozen=True)
class PairwiseEvaluation:
    accuracy: Optional[float]
    total: int
    comparable: int
    agree: Tuple[PairwiseComparison, ...]
    disagree: Tuple[PairwiseComparison, ...]
    incomparable: Tuple[PairwiseComparison, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "total": self.total,
            "comparable": self.comparable,
            "agree": [item.to_dict() for item in self.agree],
            "disagree": [item.to_dict() for item in self.disagree],
            "incomparable": [item.to_dict() for item in self.incomparable],
        }


def pairwise_accuracy(report: TaskDifficultyReport, labels: Sequence[PairwiseLabel]) -> PairwiseEvaluation:
    rank_by_task: Dict[str, TaskDifficultyRank] = {item.task_id: item for item in report.ranks}
    agree: list[PairwiseComparison] = []
    disagree: list[PairwiseComparison] = []
    incomparable: list[PairwiseComparison] = []

    for label in labels:
        harder = rank_by_task.get(label.harder_task_id)
        easier = rank_by_task.get(label.easier_task_id)
        if harder is None or easier is None:
            missing = [
                task_id
                for task_id, resolved in ((label.harder_task_id, harder), (label.easier_task_id, easier))
                if resolved is None
            ]
            incomparable.append(PairwiseComparison(
                harder_task_id=label.harder_task_id, easier_task_id=label.easier_task_id, kind=label.kind,
                model_rank_harder=harder.rank if harder else None,
                model_rank_easier=easier.rank if easier else None,
                borda_harder=harder.borda_score if harder else None,
                borda_easier=easier.borda_score if easier else None,
                outcome="incomparable", reason=f"excluded from ranking: {', '.join(missing)}",
                signal_rank_diffs={},
            ))
            continue

        if label.kind == "tie":
            matches = harder.rank == easier.rank
        else:
            matches = harder.rank < easier.rank
        signal_rank_diffs = {
            name: harder.signal_ranks[name] - easier.signal_ranks[name]
            for name in harder.signal_ranks
            if name in easier.signal_ranks
        }
        reason = None
        if not matches:
            opposes = (lambda diff: diff != 0) if label.kind == "tie" else (lambda diff: diff >= 0)
            disagreeing = ", ".join(
                f"{name} {diff:+g}" for name, diff in sorted(signal_rank_diffs.items()) if opposes(diff)
            )
            reason = (
                f"model borda {harder.borda_score:g} vs {easier.borda_score:g}"
                + (f"; signals against the label: {disagreeing}" if disagreeing else "")
            )
        comparison = PairwiseComparison(
            harder_task_id=label.harder_task_id, easier_task_id=label.easier_task_id, kind=label.kind,
            model_rank_harder=harder.rank, model_rank_easier=easier.rank,
            borda_harder=harder.borda_score, borda_easier=easier.borda_score,
            outcome="agree" if matches else "disagree",
            reason=reason, signal_rank_diffs=signal_rank_diffs,
        )
        (agree if matches else disagree).append(comparison)

    comparable = len(agree) + len(disagree)
    accuracy = (len(agree) / comparable) if comparable else None
    return PairwiseEvaluation(
        accuracy=accuracy, total=len(labels), comparable=comparable,
        agree=tuple(agree), disagree=tuple(disagree), incomparable=tuple(incomparable),
    )


def load_pairwise_labels(path: str | Path) -> list[PairwiseLabel]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load pairwise labels: {exc}") from exc
    if isinstance(payload, Mapping):
        payload = payload.get("labels")
    if not isinstance(payload, list):
        raise ValueError("pairwise labels must be a list or an object containing a labels list")
    return [PairwiseLabel.from_dict(item) for item in payload]
