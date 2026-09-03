import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import (
    TaskDifficultyAnalyzer,
    TaskDifficultyRank,
    TaskDifficultyReport,
    TaskDifficultySignals,
    TargetDiscoveryCost,
    TaskExplorationCostReport,
    load_pairwise_labels,
    pairwise_accuracy,
)
from code_analyzer.cli import main

EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples" / "realworld_app"
TASK_SET_PATH = Path(__file__).resolve().parent.parent / "examples" / "realworld_app_tasks.json"
LABELS_PATH = Path(__file__).resolve().parent.parent / "examples" / "realworld_app_difficulty_labels.json"


def _cost(
    task_id, min_cost, expected_cost, max_cost, ball_size, target_count=1,
    status="ok", confidence_costs=(),
):
    ball_node_ids = tuple(f"{task_id}-n{i}" for i in range(ball_size))
    target_node_ids = tuple(f"{task_id}-target{i}" for i in range(target_count))
    return TargetDiscoveryCost(
        task_id=task_id, task_type="bug_fix", target_node_id=target_node_ids[0] if target_node_ids else None,
        status=status, start_frontier_node_ids=(f"{task_id}-seed",), unresolved_seed_count=0,
        min_cost=min_cost, expected_cost=expected_cost, max_cost=max_cost,
        min_path_node_ids=(), ball_node_ids=ball_node_ids, target_node_ids=target_node_ids,
        confidence_costs=confidence_costs,
    )


def _report(*results):
    return TaskExplorationCostReport(tuple(results))


class BordaAggregationTests(unittest.TestCase):
    def test_task_dominating_every_signal_is_ranked_hardest(self):
        # Confidence steps are deliberately asymmetric across min/expected/max (unlike a uniform
        # +2/+5 step) so a test bug that computed evidence_gap from expected_cost instead of
        # max_cost would produce a different, distinguishable number -- see
        # test_evidence_gap_signal below for the direct check.
        harder = _cost(
            "harder", min_cost=10, expected_cost=20, max_cost=30, ball_size=5,
            confidence_costs=(("optimistic", 8, 15, 25), ("baseline", 10, 20, 30), ("pessimistic", 12, 25, 45)),
        )
        easier = _cost(
            "easier", min_cost=1, expected_cost=2, max_cost=3, ball_size=2,
            confidence_costs=(("optimistic", 0.5, 1.5, 2.5), ("baseline", 1, 2, 3), ("pessimistic", 1.5, 2.5, 5)),
        )
        report = TaskDifficultyAnalyzer().compute(_report(harder, easier))

        self.assertEqual([item.task_id for item in report.ranks], ["harder", "easier"])
        harder_rank, easier_rank = report.ranks
        self.assertEqual(harder_rank.rank, 1)
        self.assertEqual(easier_rank.rank, 2)
        self.assertEqual(harder_rank.borda_score, 6.0)
        self.assertEqual(easier_rank.borda_score, 12.0)
        self.assertTrue(all(value == 1.0 for value in harder_rank.signal_ranks.values()))
        self.assertTrue(all(value == 2.0 for value in easier_rank.signal_ranks.values()))
        self.assertEqual(report.excluded, ())

    def test_tied_tasks_share_rank_and_next_rank_skips(self):
        # a/b share every raw value including their confidence scenario (so evidence_gap ties
        # too); c is strictly weaker on every one of the 6 signals, evidence_gap included.
        tied_confidence = (("optimistic", 1, 1.5, 2), ("baseline", 1, 2, 3), ("pessimistic", 1, 2.5, 4))
        weaker_confidence = (("optimistic", 1, 1, 1), ("baseline", 1, 1, 1), ("pessimistic", 1, 1, 1))
        a = _cost("a", min_cost=8, expected_cost=9, max_cost=10, ball_size=3, confidence_costs=tied_confidence)
        b = _cost("b", min_cost=8, expected_cost=9, max_cost=10, ball_size=3, confidence_costs=tied_confidence)
        c = _cost("c", min_cost=1, expected_cost=1, max_cost=1, ball_size=1, confidence_costs=weaker_confidence)
        report = TaskDifficultyAnalyzer().compute(_report(a, b, c))

        ranks_by_task = {item.task_id: item for item in report.ranks}
        self.assertEqual(ranks_by_task["a"].rank, 1)
        self.assertEqual(ranks_by_task["b"].rank, 1)
        self.assertEqual(ranks_by_task["a"].borda_score, ranks_by_task["b"].borda_score)
        self.assertEqual(ranks_by_task["c"].rank, 3)
        self.assertGreater(ranks_by_task["c"].borda_score, ranks_by_task["a"].borda_score)

        # Contract: "동일 값은 평균 순위를 공유" (fractional/average ranking, not dense/min ranking).
        # For a 2-way tie at the top the shared per-signal rank must be exactly (1+2)/2 = 1.5,
        # not 1 (min ranking) and not 2 (max ranking).
        self.assertTrue(all(value == 1.5 for value in ranks_by_task["a"].signal_ranks.values()))
        self.assertTrue(all(value == 1.5 for value in ranks_by_task["b"].signal_ranks.values()))
        self.assertEqual(ranks_by_task["a"].borda_score, 9.0)
        self.assertTrue(all(value == 3.0 for value in ranks_by_task["c"].signal_ranks.values()))
        self.assertEqual(ranks_by_task["c"].borda_score, 18.0)

    def test_all_tasks_tied_on_every_signal_share_the_average_rank(self):
        # A full n-way tie must average over all n positions: (1+2+3+4)/4 = 2.5 per signal.
        confidence = (("optimistic", 5, 5, 5), ("baseline", 5, 5, 5), ("pessimistic", 5, 5, 5))
        tasks = [
            _cost(task_id, min_cost=5, expected_cost=5, max_cost=5, ball_size=2, confidence_costs=confidence)
            for task_id in ("a", "b", "c", "d")
        ]
        report = TaskDifficultyAnalyzer().compute(_report(*tasks))

        self.assertEqual(len(report.ranks), 4)
        for item in report.ranks:
            self.assertEqual(item.rank, 1)
            self.assertEqual(item.borda_score, 15.0)  # 2.5 average rank * 6 signals
            self.assertTrue(all(value == 2.5 for value in item.signal_ranks.values()))

    def test_single_task_gets_rank_one_with_full_borda_score(self):
        only = _cost(
            "only", min_cost=5, expected_cost=6, max_cost=7, ball_size=2,
            confidence_costs=(("optimistic", 4, 5, 6), ("baseline", 5, 6, 7), ("pessimistic", 6, 7, 8)),
        )
        report = TaskDifficultyAnalyzer().compute(_report(only))
        self.assertEqual(len(report.ranks), 1)
        self.assertEqual(report.ranks[0].rank, 1)
        self.assertEqual(report.ranks[0].borda_score, 6.0)

    def test_unreachable_pessimistic_scenario_makes_evidence_gap_unbounded_and_hardest(self):
        confidence = (("optimistic", 1, 2, 3), ("baseline", 1, 2, 3), ("pessimistic", 1, 2, 3))
        stable = _cost("stable", min_cost=1, expected_cost=1, max_cost=1, ball_size=1, confidence_costs=confidence)
        unresolved = _cost(
            "unresolved", min_cost=1, expected_cost=1, max_cost=1, ball_size=1,
            confidence_costs=(("optimistic", 1, 2, 3), ("baseline", 1, 2, 3), ("pessimistic", None, None, None)),
        )
        report = TaskDifficultyAnalyzer().compute(_report(stable, unresolved))
        ranks_by_task = {item.task_id: item for item in report.ranks}
        self.assertEqual(ranks_by_task["unresolved"].signal_ranks["evidence_gap"], 1.0)
        self.assertEqual(ranks_by_task["stable"].signal_ranks["evidence_gap"], 2.0)

    def test_multi_target_branching_subtracts_target_count(self):
        confidence = (("optimistic", 1, 1, 1), ("baseline", 1, 1, 1), ("pessimistic", 1, 1, 1))
        wide = _cost("wide", min_cost=1, expected_cost=1, max_cost=1, ball_size=12, target_count=2, confidence_costs=confidence)
        narrow = _cost("narrow", min_cost=1, expected_cost=1, max_cost=1, ball_size=5, target_count=1, confidence_costs=confidence)
        report = TaskDifficultyAnalyzer().compute(_report(wide, narrow))
        ranks_by_task = {item.task_id: item for item in report.ranks}
        # wide: 12 ball - 2 targets = 10 branching; narrow: 5 ball - 1 target = 4 branching.
        self.assertEqual(ranks_by_task["wide"].signal_ranks["branching"], 1.0)
        self.assertEqual(ranks_by_task["narrow"].signal_ranks["branching"], 2.0)
        self.assertEqual(ranks_by_task["wide"].rank, 1)

    def test_non_ok_tasks_are_excluded_with_reason_and_not_ranked(self):
        ok_task = _cost(
            "ok-task", min_cost=1, expected_cost=1, max_cost=1, ball_size=1,
            confidence_costs=(("optimistic", 1, 1, 1), ("baseline", 1, 1, 1), ("pessimistic", 1, 1, 1)),
        )
        unreachable = TargetDiscoveryCost(
            task_id="unreachable-task", task_type="bug_fix", target_node_id="ghost",
            status="target_unreachable", start_frontier_node_ids=("seed",), unresolved_seed_count=0,
            min_cost=None, expected_cost=None, max_cost=None, min_path_node_ids=(), ball_node_ids=(),
            target_node_ids=("ghost",),
        )
        report = TaskDifficultyAnalyzer().compute(_report(ok_task, unreachable))
        self.assertEqual([item.task_id for item in report.ranks], ["ok-task"])
        self.assertEqual(len(report.excluded), 1)
        excluded = report.excluded[0]
        self.assertEqual(excluded.task_id, "unreachable-task")
        self.assertTrue(excluded.excluded)
        self.assertEqual(excluded.exclusion_reason, "target_unreachable")
        self.assertIsNone(excluded.rank)
        self.assertIsNone(excluded.borda_score)
        self.assertEqual(excluded.signal_ranks, {})

    def test_no_ok_tasks_returns_empty_ranks_without_raising(self):
        empty_frontier = TargetDiscoveryCost(
            task_id="t1", task_type="bug_fix", target_node_id="x", status="empty_start_frontier",
            start_frontier_node_ids=(), unresolved_seed_count=1, min_cost=None, expected_cost=None,
            max_cost=None, min_path_node_ids=(), ball_node_ids=(), target_node_ids=("x",),
        )
        empty_target = TargetDiscoveryCost(
            task_id="t2", task_type="bug_fix", target_node_id=None, status="empty_target_set",
            start_frontier_node_ids=(), unresolved_seed_count=None, min_cost=None, expected_cost=None,
            max_cost=None, min_path_node_ids=(), ball_node_ids=(),
        )
        report = TaskDifficultyAnalyzer().compute(_report(empty_frontier, empty_target))
        self.assertEqual(report.ranks, ())
        self.assertEqual(len(report.excluded), 2)


class SignalComputationTests(unittest.TestCase):
    """Contract dataclass and per-signal computation, in isolation from the Borda ranking."""

    def test_task_difficulty_signals_dataclass_holds_the_contract_fields(self):
        signals = TaskDifficultySignals(
            task_id="t", min_cost=1.0, expected_cost=2.0, max_cost=3.0,
            cost_spread=2.0, branching=5, evidence_gap=None,
        )
        self.assertEqual(signals.task_id, "t")
        self.assertEqual(signals.min_cost, 1.0)
        self.assertEqual(signals.expected_cost, 2.0)
        self.assertEqual(signals.max_cost, 3.0)
        self.assertEqual(signals.cost_spread, 2.0)
        self.assertEqual(signals.branching, 5)
        self.assertIsNone(signals.evidence_gap)

    def test_evidence_gap_is_computed_from_max_cost_not_expected_cost(self):
        # optimistic->pessimistic max_cost step (20) deliberately differs from the
        # expected_cost step (10), so a max_cost/expected_cost mix-up in the implementation
        # would fail this exact-value assertion.
        confidence_costs = (
            ("optimistic", 8, 15, 20),
            ("baseline", 10, 20, 30),
            ("pessimistic", 12, 25, 40),
        )
        gap = TaskDifficultyAnalyzer._evidence_gap(confidence_costs)
        self.assertEqual(gap, 20.0)  # pessimistic.max(40) - optimistic.max(20)

    def test_evidence_gap_is_none_when_optimistic_scenario_missing(self):
        confidence_costs = (("baseline", 1, 2, 3), ("pessimistic", 1, 2, 3))
        self.assertIsNone(TaskDifficultyAnalyzer._evidence_gap(confidence_costs))

    def test_evidence_gap_is_none_when_optimistic_max_cost_is_none(self):
        confidence_costs = (("optimistic", 1, 2, None), ("baseline", 1, 2, 3), ("pessimistic", 1, 2, 4))
        self.assertIsNone(TaskDifficultyAnalyzer._evidence_gap(confidence_costs))


PROJECT_SOURCE = {
    "app/__init__.py": "",
    "app/service.py": "def helper():\n    return 1\n\n\ndef run():\n    return helper()\n",
}


class CliFlagWiringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = self.root / "project"
        for relative, source in PROJECT_SOURCE.items():
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        self.task_set_path = self.root / "tasks.json"
        self.task_set_path.write_text(json.dumps([
            {
                "id": "reach-run", "type": "bug_fix",
                "seeds": [{"kind": "symbol", "value": "helper"}],
                "target_node_ids": ["py:app.service#run"],
            },
            {
                "id": "reach-helper", "type": "bug_fix",
                "seeds": [{"kind": "symbol", "value": "run"}],
                "target_node_ids": ["py:app.service#helper"],
            },
        ]), encoding="utf-8")

    def _run(self, *extra):
        argv = [
            "code-analyzer", str(self.project), "--language", "python",
            "-o", str(self.root / "report.html"), *extra,
        ]
        with patch.object(sys, "argv", argv):
            main()

    def test_task_difficulty_without_exploration_cost_exits_via_parser_error(self):
        argv = [
            "code-analyzer", str(self.project), "--language", "python",
            "--task-set", str(self.task_set_path), "--task-difficulty",
        ]
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)

    def test_task_difficulty_flag_writes_report_stats_and_collection(self):
        output = self.root / "task-difficulty.json"
        self._run(
            "--json", "--task-set", str(self.task_set_path),
            "--exploration-cost", "--exploration-cost-output", str(self.root / "exploration-cost.json"),
            "--task-difficulty", "--task-difficulty-output", str(output),
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual({item["task_id"] for item in payload["ranks"]}, {"reach-run", "reach-helper"})
        self.assertEqual(payload["excluded"], [])

        exported = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertIn("task_difficulty", exported["stats"])
        self.assertIn("task_difficulty", exported["collections"])
        self.assertEqual(exported["collections"]["task_difficulty"]["view"], "table")


class PairwiseAccuracyOnRealWorldFixtureTests(unittest.TestCase):
    """Integration: real examples/realworld_app task set + manual labels (contract's validation dataset)."""

    def _run_cli(self, output_dir: Path):
        argv = [
            "code-analyzer", str(EXAMPLES_ROOT),
            "-f", "fastapi",
            "-o", str(output_dir / "report.html"),
            "--json",
            "--task-set", str(TASK_SET_PATH),
            "--exploration-cost", "--exploration-cost-output", str(output_dir / "exploration-cost.json"),
            "--task-difficulty", "--task-difficulty-output", str(output_dir / "task-difficulty.json"),
        ]
        with patch.object(sys, "argv", argv):
            main()

    def test_real_world_task_set_ranks_all_tasks_and_matches_manual_labels_reasonably(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            self._run_cli(output_dir)
            payload = json.loads((output_dir / "task-difficulty.json").read_text(encoding="utf-8"))

        expected_task_ids = {task["id"] for task in json.loads(TASK_SET_PATH.read_text(encoding="utf-8"))}
        ranked_task_ids = {item["task_id"] for item in payload["ranks"]}
        self.assertEqual(ranked_task_ids, expected_task_ids)
        self.assertEqual(payload["excluded"], [])

        ranks = tuple(
            TaskDifficultyRank(
                task_id=item["task_id"], rank=item["rank"], borda_score=item["borda_score"],
                signal_ranks=item["signal_ranks"], excluded=item["excluded"],
                exclusion_reason=item["exclusion_reason"],
            )
            for item in sorted(payload["ranks"], key=lambda item: item["rank"])
        )
        report = TaskDifficultyReport(ranks=ranks, excluded=())

        labels = load_pairwise_labels(LABELS_PATH)
        evaluation = pairwise_accuracy(report, labels)

        self.assertEqual(evaluation.comparable, evaluation.total)
        self.assertEqual(evaluation.incomparable, ())
        # First-slice bar: the model must resolve most manually labeled pairs correctly, though
        # perfect agreement isn't expected -- graph reach and human difficulty intuition diverge
        # by design on at least one task in this fixture (see disagree entries for evidence).
        self.assertGreaterEqual(evaluation.accuracy, 0.5)


if __name__ == "__main__":
    unittest.main()
