import json
import math
import tempfile
import unittest
from pathlib import Path

from analysis.benchmark import (
    AgentTrace,
    BenchmarkDefinition,
    BenchmarkResult,
    BenchmarkSummary,
    BenchmarkTask,
    CostAccuracy,
    TraceAction,
    TraceMetrics,
    evaluate_benchmark,
    load_agent_traces,
    load_benchmark_definition,
    summarize_benchmark,
)
from analysis.task_exploration import (
    BranchingBurden,
    ContextFragmentation,
    EvidenceGap,
    ExplorationPath,
    GoalDiscovery,
    SearchPolicy,
    SeedKind,
    SeedQuery,
    TaskDefinition,
    TaskExplorationReport,
    TaskExplorer,
    TaskType,
    Visit,
)
from language_analyzers.core.graph_models import GraphEdge, GraphNode, NodeCost, SourceSpan


def node(node_id, label, cost, path):
    return GraphNode(node_id, label, "test", "function", span=SourceSpan(path, 1, 1), cost=NodeCost(cost, cost, 1))


def task(task_id="task"):
    return TaskDefinition(task_id, TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"target"}), frozenset({"impact"}))


class BenchmarkDefinitionTests(unittest.TestCase):
    def test_validates_required_exact_schema_and_unique_scoped_ids(self):
        first = BenchmarkTask("org/repo", "a1", task())
        second = BenchmarkTask("org/repo", "b2", task())
        definition = BenchmarkDefinition.from_dict({"benchmarks": [
            {"repository": "org/repo", "revision": "a1", "task": first.task.to_dict()},
            {"repository": "org/repo", "revision": "b2", "task": second.task.to_dict()},
        ]})
        self.assertEqual(definition.tasks, (first, second))
        with self.assertRaises(ValueError):
            BenchmarkDefinition((first, first))
        for value in ([], {"extra": []}, {"benchmarks": []}, {"benchmarks": "bad"}, {"benchmarks": [{"repository": "x", "revision": "r", "task": task(), "extra": 1}]}, {"benchmarks": [{"repository": "x", "task": task()}]}, {"benchmarks": ["bad"]}, {"benchmarks": [{"repository": 1, "revision": "r", "task": task()}]}, {"benchmarks": [{"repository": "", "revision": "r", "task": task()}]}, {"benchmarks": [{"repository": "x", "revision": None, "task": task()}]}, {"benchmarks": [{"repository": "x", "revision": "", "task": task()}]}, {"benchmarks": [{"repository": "x", "revision": "r", "task": "bad"}]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BenchmarkDefinition.from_dict(value)

        duplicate = {"benchmarks": [
            {"repository": "org/repo", "revision": "a1", "task": first.task.to_dict()},
            {"repository": "org/repo", "revision": "a1", "task": first.task.to_dict()},
        ]}
        with self.assertRaises(ValueError):
            BenchmarkDefinition.from_dict(duplicate)
        invalid_task = {"benchmarks": [{
            "repository": "org/repo", "revision": "a1",
            "task": {"id": "bad", "type": "invalid", "seeds": []},
        }]}
        with self.assertRaises(ValueError):
            BenchmarkDefinition.from_dict(invalid_task)

    def test_task_and_load_errors_are_value_errors(self):
        for repository, revision, value in (("", "r", task()), ("r", "", task()), ("r", "v", object())):
            with self.subTest(repository=repository, revision=revision), self.assertRaises(ValueError):
                BenchmarkTask(repository, revision, value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmarks.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_benchmark_definition(path)
            with self.assertRaises(ValueError):
                load_benchmark_definition(path.parent / "missing.json")
            path.write_text(json.dumps({"benchmarks": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_benchmark_definition(path)
            payload = {"benchmarks": [{"repository": "org/repo", "revision": "v1", "task": task().to_dict()}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(load_benchmark_definition(path).tasks[0], BenchmarkTask("org/repo", "v1", task()))


class TraceTests(unittest.TestCase):
    def test_action_validation_and_metrics(self):
        for kind, target, tokens in (("edit", "x", None), ("open", "", None), ("search", "x", True), ("open", "x", -1), ("open", "x", math.inf), ("open", "x", math.nan)):
            with self.subTest(kind=kind, target=target, tokens=tokens), self.assertRaises(ValueError):
                TraceAction(kind, target, tokens)
        self.assertEqual(TraceAction("open", "zero", 0).tokens, 0)
        self.assertEqual(TraceAction("open", "fraction", 0.5).tokens, 0.5)
        for repository, revision, task_id, actions in (("", "r", "task", ()), ("repo", "", "task", ()), ("repo", "r", "", ()), ("repo", "r", "task", None), ("repo", "r", "task", "not-actions")):
            with self.subTest(repository=repository, revision=revision, task_id=task_id, actions=actions), self.assertRaises(ValueError):
                AgentTrace(repository, revision, task_id, actions)
        with self.assertRaises(ValueError):
            AgentTrace("repo", "r", "task", (TraceAction("open", "a.py"), object()))
        trace = AgentTrace("org/repo", "r1", "task", (
            TraceAction("search", "needle"), TraceAction("open", "a.py", 3),
            TraceAction("open", "a.py", 8), TraceAction("open", "b.py"),
            TraceAction("search", "other"), TraceAction("open", "a.py", 2),
        ))
        definition = BenchmarkDefinition((BenchmarkTask("org/repo", "r1", task()),))
        result = evaluate_benchmark(definition, {("org/repo", "r1"): self.explorer()}, (trace,), (SearchPolicy.BFS,))[0]
        self.assertEqual(result.trace_metrics.tool_call_count, 6)
        self.assertEqual(result.trace_metrics.search_count, 2)
        self.assertEqual(result.trace_metrics.open_count, 4)
        self.assertEqual(result.trace_metrics.unique_open_target_count, 2)
        self.assertEqual(result.trace_metrics.unique_open_token_cost, 3.0)
        self.assertEqual(result.trace_metrics.backtracking_count, 1)

    def test_permitted_action_kinds_and_multi_backtracking(self):
        self.assertEqual(TraceAction("search", "needle").kind, "search")
        self.assertEqual(TraceAction("open", "file.py").kind, "open")
        trace = AgentTrace("org/repo", "r1", "task", tuple(
            TraceAction("open", target) for target in ("a.py", "b.py", "a.py", "b.py", "b.py", "a.py")
        ))
        definition = BenchmarkDefinition((BenchmarkTask("org/repo", "r1", task()),))
        metrics = evaluate_benchmark(definition, {("org/repo", "r1"): self.explorer()}, (trace,), (SearchPolicy.BFS,))[0].trace_metrics
        self.assertEqual(metrics.backtracking_count, 3)

    def test_tokenless_first_open_and_search_between_repeats(self):
        trace = AgentTrace("org/repo", "r1", "task", (
            TraceAction("open", "a.py"), TraceAction("search", "needle"), TraceAction("open", "a.py", 7),
        ))
        definition = BenchmarkDefinition((BenchmarkTask("org/repo", "r1", task()),))
        metrics = evaluate_benchmark(definition, {("org/repo", "r1"): self.explorer()}, (trace,), (SearchPolicy.BFS,))[0].trace_metrics
        self.assertEqual(metrics.unique_open_token_cost, 0.0)
        self.assertEqual(metrics.backtracking_count, 0)

    @staticmethod
    def explorer():
        return TaskExplorer([node("seed", "seed", 1, "seed.py"), node("target", "target", 2, "target.py"), node("impact", "impact", 3, "impact.py")], [])

    def test_load_agent_traces_round_trips_and_validates(self):
        payload = {"traces": [
            {"repository": "org/repo", "revision": "r1", "task_id": "task", "actions": [
                {"kind": "search", "target": "needle"},
                {"kind": "open", "target": "a.py", "tokens": 3},
            ]},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            traces = load_agent_traces(path)
        self.assertEqual(traces, (AgentTrace("org/repo", "r1", "task", (
            TraceAction("search", "needle"), TraceAction("open", "a.py", 3),
        )),))

    def test_load_agent_traces_rejects_malformed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.json"
            for payload in ("{bad", json.dumps([]), json.dumps({"traces": "bad"}), json.dumps({"traces": [], "extra": 1})):
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    load_agent_traces(path)
            with self.assertRaises(ValueError):
                load_agent_traces(path.parent / "missing.json")

    def test_agent_trace_from_dict_rejects_bad_shapes(self):
        for value in (
            {"repository": "r", "revision": "v", "task_id": "t"},
            {"repository": "r", "revision": "v", "task_id": "t", "actions": "not-a-list"},
            {"repository": "r", "revision": "v", "task_id": "t", "actions": [{"kind": "bad", "target": "x"}]},
            {"repository": "r", "revision": "v", "task_id": "t", "actions": [], "extra": 1},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AgentTrace.from_dict(value)


class EvaluationTests(unittest.TestCase):
    def test_propagates_reachable_target_and_impact_costs(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = TaskExplorer(
            [node("seed", "seed", 1, "seed.py"), node("target", "target", 2, "target.py"), node("impact", "impact", 3, "impact.py")],
            [GraphEdge("seed", "target", "CALLS"), GraphEdge("target", "impact", "CALLS")],
        )
        result = evaluate_benchmark(definition, {("repo", "rev"): explorer}, (), (SearchPolicy.BFS,))[0]
        self.assertEqual(result.predicted_target_discovery_cost, 3.0)
        self.assertEqual(result.predicted_impact_discovery_cost, 6.0)

    def test_orders_manifest_then_policies_and_preserves_missing_trace(self):
        first = BenchmarkTask("one", "r", task("first"))
        second = BenchmarkTask("two", "r", task("second"))
        definition = BenchmarkDefinition((first, second))
        explorer = TaskExplorer([
            node("seed", "seed", 1, "seed.py"), node("target", "target", 2, "target.py"),
            node("impact", "impact", 3, "impact.py"),
        ], [])
        results = evaluate_benchmark(definition, {("one", "r"): explorer, ("two", "r"): explorer}, (), (SearchPolicy.BUDGET_LIMITED, SearchPolicy.BFS))
        self.assertEqual([(item.task_id, item.policy) for item in results], [("first", SearchPolicy.BUDGET_LIMITED), ("first", SearchPolicy.BFS), ("second", SearchPolicy.BUDGET_LIMITED), ("second", SearchPolicy.BFS)])
        self.assertTrue(all(item.trace_metrics is None for item in results))

    def test_attaches_distinct_traces_for_tasks_sharing_repository_revision(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task("one")), BenchmarkTask("repo", "rev", task("two"))))
        explorer = {("repo", "rev"): TaskExplorer([
            node("seed", "seed", 1, "s.py"), node("target", "target", 2, "t.py"),
            node("impact", "impact", 3, "i.py"),
        ], [])}
        traces = (AgentTrace("repo", "rev", "one", (TraceAction("search", "one"),)), AgentTrace("repo", "rev", "two", (TraceAction("open", "two.py", 2),)))
        results = evaluate_benchmark(definition, explorer, traces, (SearchPolicy.BFS,))
        self.assertEqual([item.trace_metrics.search_count for item in results], [1, 0])
        self.assertEqual([item.trace_metrics.unique_open_token_cost for item in results], [0.0, 2.0])

    def test_rejects_unmatched_or_multiple_traces_and_missing_explorer(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = {("repo", "rev"): TaskExplorer([
            node("seed", "seed", 1, "s.py"), node("target", "target", 2, "t.py"),
            node("impact", "impact", 3, "i.py"),
        ], [])}
        matching = AgentTrace("repo", "rev", "task", ())
        unmatched = AgentTrace("repo", "other", "task", ())
        unknown_task = AgentTrace("repo", "rev", "unknown", ())
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, (unmatched,))
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, (unknown_task,))
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, (matching, matching))
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, {}, ())

    def test_rejects_task_goal_node_ids_absent_from_explorer(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = {("repo", "rev"): TaskExplorer([node("seed", "seed", 1, "s.py")], [])}
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, ())

    def test_rejects_unknown_test_node_id(self):
        task_with_test = TaskDefinition(
            "task", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),),
            test_node_ids=frozenset({"missing-test"}),
        )
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task_with_test),))
        explorer = {("repo", "rev"): TaskExplorer([node("seed", "seed", 1, "s.py")], [])}
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, ())

    def test_rejects_invalid_policy_and_empty_policies_return_no_results(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = {("repo", "rev"): TaskExplorer([
            node("seed", "seed", 1, "s.py"), node("target", "target", 2, "t.py"),
            node("impact", "impact", 3, "i.py"),
        ], [])}
        with self.assertRaises(ValueError):
            evaluate_benchmark(definition, explorer, (), ("invalid",))
        self.assertEqual(evaluate_benchmark(definition, explorer, (), ()), ())

    def test_evaluate_benchmark_populates_new_result_fields(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = TaskExplorer(
            [node("seed", "seed", 1, "seed.py"), node("target", "target", 2, "target.py"), node("impact", "impact", 3, "impact.py")],
            [GraphEdge("seed", "target", "CALLS"), GraphEdge("target", "impact", "CALLS")],
        )
        result = evaluate_benchmark(definition, {("repo", "rev"): explorer}, (), (SearchPolicy.BFS,))[0]
        self.assertEqual(result.target_node_ids, frozenset({"target"}))
        self.assertEqual(result.impact_node_ids, frozenset({"impact"}))
        self.assertIsInstance(result.report, TaskExplorationReport)
        self.assertEqual(result.report.task_id, "task")


def make_report(discoveries=(), visited_count=1, task_id="t", policy=SearchPolicy.BFS):
    visited = tuple(Visit(f"n{i}", ExplorationPath((f"n{i}",), ()), 0.0) for i in range(visited_count))
    return TaskExplorationReport(
        task_id, TaskType.BUG_FIX, policy, None, (), visited, tuple(discoveries),
        None, None,
        BranchingBurden(0, 0, 0.0), ContextFragmentation(0, 0, 0, 0), EvidenceGap(0, 0, 0, 0, 0, 0.0),
        "goals_satisfied",
    )


def make_metrics(unique_open_token_cost):
    return TraceMetrics(0, 0, 0, 0, unique_open_token_cost, 0)


def make_result(
    task_id="t",
    policy=SearchPolicy.BFS,
    predicted_target=None,
    predicted_impact=None,
    trace_metrics=None,
    target_node_ids=(),
    impact_node_ids=(),
    report=None,
):
    if report is None:
        report = make_report(task_id=task_id, policy=policy)
    return BenchmarkResult(
        "repo", "rev", task_id, policy,
        predicted_target, predicted_impact, trace_metrics,
        frozenset(target_node_ids), frozenset(impact_node_ids), report,
    )


class SummarizeBenchmarkTests(unittest.TestCase):
    def test_empty_results_returns_empty_summary(self):
        self.assertEqual(summarize_benchmark(()), BenchmarkSummary((), ()))

    def test_rejects_non_benchmark_result_items_and_non_sequence(self):
        with self.assertRaises(ValueError):
            summarize_benchmark([object()])
        with self.assertRaises(ValueError):
            summarize_benchmark("not-a-sequence-of-results")
        with self.assertRaises(ValueError):
            summarize_benchmark(None)

    def test_rejects_invalid_k_values(self):
        result = make_result(predicted_target=1.0, trace_metrics=make_metrics(1.0))
        for k_values in ((0,), (-1,), (2, 2), (True,), (1, 2, 2)):
            with self.subTest(k_values=k_values), self.assertRaises(ValueError):
                summarize_benchmark([result], k_values)

    def test_empty_k_values_yields_no_retrieval_metrics_but_keeps_cost_accuracy(self):
        result = make_result(predicted_target=2.0, trace_metrics=make_metrics(1.0))
        summary = summarize_benchmark([result], k_values=())
        self.assertEqual(summary.retrieval_metrics, ())
        self.assertEqual(len(summary.cost_accuracy), 2)

    def test_pair_count_zero_when_no_trace_metrics_present(self):
        result = make_result(predicted_target=2.0, predicted_impact=3.0, trace_metrics=None)
        summary = summarize_benchmark([result])
        self.assertIn(CostAccuracy(SearchPolicy.BFS, "target", 0, None, None, None), summary.cost_accuracy)
        self.assertIn(CostAccuracy(SearchPolicy.BFS, "impact", 0, None, None, None), summary.cost_accuracy)

    def test_single_pair_has_no_rank_correlation(self):
        result = make_result(predicted_target=5.0, trace_metrics=make_metrics(3.0))
        summary = summarize_benchmark([result])
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        self.assertEqual(target_entry.pair_count, 1)
        self.assertIsNone(target_entry.rank_correlation)
        self.assertAlmostEqual(target_entry.mean_absolute_error, 2.0)
        self.assertAlmostEqual(target_entry.mean_relative_error, 2.0 / 3.0)

    def test_tied_predicted_values_have_no_rank_correlation(self):
        results = [
            make_result(task_id="a", predicted_target=5.0, trace_metrics=make_metrics(3.0)),
            make_result(task_id="b", predicted_target=5.0, trace_metrics=make_metrics(7.0)),
        ]
        summary = summarize_benchmark(results)
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        self.assertEqual(target_entry.pair_count, 2)
        self.assertIsNone(target_entry.rank_correlation)
        self.assertAlmostEqual(target_entry.mean_absolute_error, (abs(5 - 3) + abs(5 - 7)) / 2)

    def test_tied_actual_values_have_no_rank_correlation(self):
        results = [
            make_result(task_id="a", predicted_target=2.0, trace_metrics=make_metrics(5.0)),
            make_result(task_id="b", predicted_target=8.0, trace_metrics=make_metrics(5.0)),
        ]
        summary = summarize_benchmark(results)
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        self.assertIsNone(target_entry.rank_correlation)

    def test_rank_correlation_matches_hand_computed_spearman(self):
        results = [
            make_result(task_id="a", predicted_target=2.0, trace_metrics=make_metrics(1.0)),
            make_result(task_id="b", predicted_target=4.0, trace_metrics=make_metrics(5.0)),
            make_result(task_id="c", predicted_target=6.0, trace_metrics=make_metrics(3.0)),
        ]
        summary = summarize_benchmark(results)
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        self.assertEqual(target_entry.pair_count, 3)
        self.assertAlmostEqual(target_entry.rank_correlation, 0.5)
        self.assertAlmostEqual(target_entry.mean_absolute_error, 5.0 / 3.0)
        self.assertAlmostEqual(target_entry.mean_relative_error, 2.2 / 3.0)

    def test_actual_all_zero_pairs_have_no_relative_error(self):
        results = [
            make_result(task_id="a", predicted_target=2.0, trace_metrics=make_metrics(0.0)),
            make_result(task_id="b", predicted_target=4.0, trace_metrics=make_metrics(0.0)),
        ]
        summary = summarize_benchmark(results)
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        self.assertIsNone(target_entry.mean_relative_error)
        self.assertAlmostEqual(target_entry.mean_absolute_error, 3.0)

    def test_empty_label_set_excludes_task_and_missing_category_emits_no_retrieval_metrics(self):
        report_a = make_report(
            discoveries=(GoalDiscovery("target", "n0", 0, 1.0, ExplorationPath((), ())),),
            visited_count=1, task_id="a",
        )
        report_b = make_report(visited_count=1, task_id="b")
        result_a = make_result(task_id="a", target_node_ids={"n0"}, impact_node_ids=(), report=report_a)
        result_b = make_result(task_id="b", target_node_ids=(), impact_node_ids=(), report=report_b)
        summary = summarize_benchmark([result_a, result_b], k_values=(1,))
        target_entries = [item for item in summary.retrieval_metrics if item.category == "target"]
        self.assertEqual(len(target_entries), 1)
        self.assertEqual(target_entries[0].task_count, 1)
        self.assertEqual(target_entries[0].recall_at_k, 1.0)
        impact_entries = [item for item in summary.retrieval_metrics if item.category == "impact"]
        self.assertEqual(impact_entries, [])

    def test_precision_denominator_clamps_to_visited_count(self):
        report = make_report(
            discoveries=(GoalDiscovery("target", "n0", 0, 1.0, ExplorationPath((), ())),),
            visited_count=2, task_id="a",
        )
        result = make_result(task_id="a", target_node_ids={"n0"}, report=report)
        summary = summarize_benchmark([result], k_values=(20,))
        entry = next(item for item in summary.retrieval_metrics if item.category == "target")
        self.assertEqual(entry.recall_at_k, 1.0)
        self.assertAlmostEqual(entry.precision_at_k, 0.5)

    def test_macro_average_recall_and_precision_across_tasks(self):
        report_a = make_report(
            discoveries=(GoalDiscovery("target", "a0", 0, 1.0, ExplorationPath((), ())),),
            visited_count=4, task_id="a",
        )
        report_b = make_report(
            discoveries=(GoalDiscovery("target", "c0", 1, 2.0, ExplorationPath((), ())),),
            visited_count=3, task_id="b",
        )
        result_a = make_result(task_id="a", target_node_ids={"a0", "b0"}, report=report_a)
        result_b = make_result(task_id="b", target_node_ids={"c0"}, report=report_b)
        summary = summarize_benchmark([result_a, result_b], k_values=(2,))
        entry = next(item for item in summary.retrieval_metrics if item.category == "target")
        self.assertEqual(entry.task_count, 2)
        self.assertAlmostEqual(entry.recall_at_k, 0.75)
        self.assertAlmostEqual(entry.precision_at_k, 0.5)

    def test_multiple_policies_grouped_and_ordered_by_first_appearance(self):
        weighted = make_result(
            task_id="a", policy=SearchPolicy.WEIGHTED_SHORTEST,
            predicted_target=10.0, trace_metrics=make_metrics(2.0),
            report=make_report(task_id="a", policy=SearchPolicy.WEIGHTED_SHORTEST),
        )
        bfs = make_result(
            task_id="b", policy=SearchPolicy.BFS,
            predicted_target=4.0, trace_metrics=make_metrics(8.0),
            report=make_report(task_id="b", policy=SearchPolicy.BFS),
        )
        summary = summarize_benchmark([weighted, bfs])
        self.assertEqual(
            [(item.policy, item.category) for item in summary.cost_accuracy],
            [
                (SearchPolicy.WEIGHTED_SHORTEST, "target"), (SearchPolicy.WEIGHTED_SHORTEST, "impact"),
                (SearchPolicy.BFS, "target"), (SearchPolicy.BFS, "impact"),
            ],
        )
        weighted_target = next(item for item in summary.cost_accuracy if item.policy == SearchPolicy.WEIGHTED_SHORTEST and item.category == "target")
        bfs_target = next(item for item in summary.cost_accuracy if item.policy == SearchPolicy.BFS and item.category == "target")
        self.assertEqual(weighted_target.pair_count, 1)
        self.assertAlmostEqual(weighted_target.mean_absolute_error, 8.0)
        self.assertEqual(bfs_target.pair_count, 1)
        self.assertAlmostEqual(bfs_target.mean_absolute_error, 4.0)

    def test_predicted_none_excludes_only_that_category_pair(self):
        result = make_result(predicted_target=2.0, predicted_impact=None, trace_metrics=make_metrics(1.0))
        summary = summarize_benchmark([result])
        target_entry = next(item for item in summary.cost_accuracy if item.category == "target")
        impact_entry = next(item for item in summary.cost_accuracy if item.category == "impact")
        self.assertEqual(target_entry.pair_count, 1)
        self.assertEqual(impact_entry, CostAccuracy(SearchPolicy.BFS, "impact", 0, None, None, None))

    def test_category_filter_does_not_mix_target_and_impact_discoveries(self):
        report = make_report(
            discoveries=(
                GoalDiscovery("impact", "shared", 0, 1.0, ExplorationPath((), ())),
                GoalDiscovery("target", "other", 1, 2.0, ExplorationPath((), ())),
            ),
            visited_count=2,
        )
        result = make_result(target_node_ids={"shared"}, impact_node_ids={"shared"}, report=report)
        summary = summarize_benchmark([result], k_values=(2,))
        target_entry = next(item for item in summary.retrieval_metrics if item.category == "target")
        impact_entry = next(item for item in summary.retrieval_metrics if item.category == "impact")
        self.assertAlmostEqual(target_entry.recall_at_k, 0.0)
        self.assertAlmostEqual(impact_entry.recall_at_k, 1.0)

    def test_visit_index_equal_to_k_is_not_found(self):
        report = make_report(
            discoveries=(GoalDiscovery("target", "n0", 2, 1.0, ExplorationPath((), ())),),
            visited_count=3,
        )
        result = make_result(target_node_ids={"n0"}, report=report)
        summary = summarize_benchmark([result], k_values=(2,))
        entry = next(item for item in summary.retrieval_metrics if item.category == "target")
        self.assertAlmostEqual(entry.recall_at_k, 0.0)

    def test_empty_visited_report_yields_zero_precision_without_division_error(self):
        report = make_report(discoveries=(), visited_count=0)
        result = make_result(target_node_ids={"n0"}, report=report)
        summary = summarize_benchmark([result], k_values=(5,))
        entry = next(item for item in summary.retrieval_metrics if item.category == "target")
        self.assertAlmostEqual(entry.recall_at_k, 0.0)
        self.assertAlmostEqual(entry.precision_at_k, 0.0)

    def test_multiple_k_values_each_produce_a_distinct_entry_in_order(self):
        report = make_report(
            discoveries=(GoalDiscovery("target", "n0", 1, 1.0, ExplorationPath((), ())),),
            visited_count=5,
        )
        result = make_result(target_node_ids={"n0"}, report=report)
        summary = summarize_benchmark([result], k_values=(1, 2, 20))
        target_entries = [item for item in summary.retrieval_metrics if item.category == "target"]
        self.assertEqual([item.k for item in target_entries], [1, 2, 20])
        self.assertAlmostEqual(target_entries[0].recall_at_k, 0.0)
        self.assertAlmostEqual(target_entries[1].recall_at_k, 1.0)
        self.assertAlmostEqual(target_entries[2].recall_at_k, 1.0)

    def test_evaluate_benchmark_report_matches_the_policy_specific_run(self):
        definition = BenchmarkDefinition((BenchmarkTask("repo", "rev", task()),))
        explorer = TaskExplorer(
            [node("seed", "seed", 1, "seed.py"), node("target", "target", 2, "target.py"), node("impact", "impact", 3, "impact.py")],
            [GraphEdge("seed", "target", "CALLS"), GraphEdge("target", "impact", "CALLS")],
        )
        weighted_result, bfs_result = evaluate_benchmark(
            definition, {("repo", "rev"): explorer}, (),
            (SearchPolicy.WEIGHTED_SHORTEST, SearchPolicy.BFS),
        )
        self.assertEqual(weighted_result.report.policy, SearchPolicy.WEIGHTED_SHORTEST)
        self.assertEqual(bfs_result.report.policy, SearchPolicy.BFS)
        self.assertEqual(weighted_result.report.target_discovery_cost, weighted_result.predicted_target_discovery_cost)
        self.assertEqual(bfs_result.report.impact_discovery_cost, bfs_result.predicted_impact_discovery_cost)
