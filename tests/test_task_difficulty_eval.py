import json
import tempfile
import unittest
from pathlib import Path

from analysis import PairwiseLabel, TaskDifficultyRank, TaskDifficultyReport, load_pairwise_labels, pairwise_accuracy


def _rank(task_id, rank, borda_score=0.0, signal_ranks=None):
    return TaskDifficultyRank(
        task_id=task_id, rank=rank, borda_score=borda_score,
        signal_ranks=signal_ranks or {}, excluded=False, exclusion_reason=None,
    )


def _excluded_rank(task_id, reason="target_unreachable"):
    return TaskDifficultyRank(
        task_id=task_id, rank=None, borda_score=None, signal_ranks={},
        excluded=True, exclusion_reason=reason,
    )


def _report(*ranks, excluded=()):
    return TaskDifficultyReport(ranks=tuple(ranks), excluded=tuple(excluded))


class PairwiseLabelValidationTests(unittest.TestCase):
    def test_invalid_kind_raises_value_error(self):
        with self.assertRaises(ValueError):
            PairwiseLabel(harder_task_id="a", easier_task_id="b", kind="bogus")

    def test_empty_task_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            PairwiseLabel(harder_task_id="", easier_task_id="b")

    def test_from_dict_missing_field_raises_value_error(self):
        with self.assertRaises(ValueError):
            PairwiseLabel.from_dict({"harder_task_id": "a"})

    def test_from_dict_non_mapping_raises_value_error(self):
        with self.assertRaises(ValueError):
            PairwiseLabel.from_dict(["a", "b"])

    def test_from_dict_defaults_kind_to_strict(self):
        label = PairwiseLabel.from_dict({"harder_task_id": "a", "easier_task_id": "b"})
        self.assertEqual(label.kind, "strict")


class PairwiseAccuracyTests(unittest.TestCase):
    def test_strict_label_agrees_when_model_confirms_order(self):
        report = _report(_rank("a", 1, 10.0), _rank("b", 2, 20.0))
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(evaluation.accuracy, 1.0)
        self.assertEqual(len(evaluation.agree), 1)
        self.assertEqual(evaluation.disagree, ())

    def test_strict_label_disagrees_when_model_contradicts(self):
        report = _report(_rank("a", 2, 20.0), _rank("b", 1, 10.0))
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(evaluation.accuracy, 0.0)
        self.assertEqual(len(evaluation.disagree), 1)
        self.assertIsNotNone(evaluation.disagree[0].reason)

    def test_tie_label_agrees_when_model_ranks_equal(self):
        report = _report(_rank("a", 1, 9.0), _rank("b", 1, 9.0))
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b", kind="tie")])
        self.assertEqual(evaluation.accuracy, 1.0)

    def test_tie_label_disagrees_when_model_ranks_differ(self):
        report = _report(_rank("a", 1, 9.0), _rank("b", 2, 18.0))
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b", kind="tie")])
        self.assertEqual(evaluation.accuracy, 0.0)

    def test_excluded_task_is_incomparable_and_excluded_from_accuracy_denominator(self):
        report = _report(_rank("a", 1, 10.0), _rank("b", 2, 20.0))
        evaluation = pairwise_accuracy(report, [
            PairwiseLabel("a", "missing-task"),
            PairwiseLabel("a", "b"),
        ])
        self.assertEqual(evaluation.total, 2)
        self.assertEqual(evaluation.comparable, 1)
        self.assertEqual(len(evaluation.incomparable), 1)
        self.assertIn("missing-task", evaluation.incomparable[0].reason)

    def test_accuracy_divides_by_comparable_pairs_not_total_labels(self):
        report = _report(_rank("a", 1, 10.0), _rank("b", 2, 20.0))
        evaluation = pairwise_accuracy(report, [
            PairwiseLabel("a", "b"),
            PairwiseLabel("a", "ghost"),
        ])
        self.assertEqual(evaluation.total, 2)
        self.assertEqual(evaluation.comparable, 1)
        self.assertEqual(evaluation.accuracy, 1.0)

    def test_no_labels_yields_none_accuracy(self):
        report = _report(_rank("a", 1, 10.0))
        evaluation = pairwise_accuracy(report, [])
        self.assertIsNone(evaluation.accuracy)
        self.assertEqual(evaluation.total, 0)
        self.assertEqual(evaluation.comparable, 0)

    def test_one_task_excluded_from_ranking_is_incomparable(self):
        # Contract edge case: a task that TaskDifficultyAnalyzer excluded (status != "ok")
        # must not silently fall back to being treated as comparable.
        report = _report(_rank("a", 1, 10.0), excluded=[_excluded_rank("b")])
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(evaluation.comparable, 0)
        self.assertEqual(len(evaluation.incomparable), 1)
        self.assertEqual(evaluation.incomparable[0].outcome, "incomparable")
        self.assertIn("b", evaluation.incomparable[0].reason)
        self.assertIsNone(evaluation.accuracy)

    def test_both_tasks_excluded_from_ranking_is_incomparable(self):
        report = _report(excluded=[_excluded_rank("a"), _excluded_rank("b", reason="empty_start_frontier")])
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(evaluation.total, 1)
        self.assertEqual(evaluation.comparable, 0)
        self.assertEqual(len(evaluation.incomparable), 1)
        self.assertEqual(evaluation.incomparable[0].model_rank_harder, None)
        self.assertEqual(evaluation.incomparable[0].model_rank_easier, None)
        self.assertIn("a", evaluation.incomparable[0].reason)
        self.assertIn("b", evaluation.incomparable[0].reason)
        self.assertIsNone(evaluation.accuracy)

    def test_disagreement_evidence_names_the_signals_and_rank_gap_that_oppose_the_label(self):
        # Contract: "결과는 항상 근거(불일치한 쌍과 그 쌍의 신호별 순위 차이)를 함께 반환한다" --
        # the model ranks "b" harder than "a" (rank 1 vs 2), contradicting a label that claims
        # "a" is harder. Every signal opposes the label, so every signal must show up as evidence.
        report = _report(
            _rank("a", 2, 15.0, signal_ranks={"min_cost": 2.0, "expected_cost": 2.0, "max_cost": 2.0}),
            _rank("b", 1, 6.0, signal_ranks={"min_cost": 1.0, "expected_cost": 1.0, "max_cost": 1.0}),
        )
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(len(evaluation.disagree), 1)
        comparison = evaluation.disagree[0]
        self.assertEqual(
            comparison.signal_rank_diffs,
            {"min_cost": 1.0, "expected_cost": 1.0, "max_cost": 1.0},
        )
        for name in ("min_cost", "expected_cost", "max_cost"):
            self.assertIn(name, comparison.reason)

    def test_agreement_signal_rank_diffs_are_populated_too(self):
        report = _report(
            _rank("a", 1, 6.0, signal_ranks={"min_cost": 1.0, "branching": 1.0}),
            _rank("b", 2, 12.0, signal_ranks={"min_cost": 2.0, "branching": 2.0}),
        )
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "b")])
        self.assertEqual(len(evaluation.agree), 1)
        self.assertEqual(evaluation.agree[0].signal_rank_diffs, {"min_cost": -1.0, "branching": -1.0})

    def test_incomparable_pairs_carry_no_signal_rank_diffs(self):
        report = _report(_rank("a", 1, 10.0, signal_ranks={"min_cost": 1.0}))
        evaluation = pairwise_accuracy(report, [PairwiseLabel("a", "missing")])
        self.assertEqual(evaluation.incomparable[0].signal_rank_diffs, {})


class LoadPairwiseLabelsTests(unittest.TestCase):
    def test_round_trips_a_json_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.json"
            path.write_text(json.dumps([
                {"harder_task_id": "a", "easier_task_id": "b"},
                {"harder_task_id": "c", "easier_task_id": "d", "kind": "tie"},
            ]), encoding="utf-8")
            labels = load_pairwise_labels(path)
        self.assertEqual(len(labels), 2)
        self.assertEqual(labels[0], PairwiseLabel("a", "b"))
        self.assertEqual(labels[1], PairwiseLabel("c", "d", kind="tie"))

    def test_accepts_an_object_with_a_labels_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.json"
            path.write_text(json.dumps({"labels": [{"harder_task_id": "a", "easier_task_id": "b"}]}), encoding="utf-8")
            labels = load_pairwise_labels(path)
        self.assertEqual(labels, [PairwiseLabel("a", "b")])

    def test_malformed_json_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_pairwise_labels(path)

    def test_non_list_payload_without_labels_key_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.json"
            path.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_pairwise_labels(path)

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_pairwise_labels("/nonexistent/labels.json")


if __name__ == "__main__":
    unittest.main()
