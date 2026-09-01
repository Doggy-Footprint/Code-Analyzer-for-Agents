import json
import math
import tempfile
import unittest
from pathlib import Path

from analysis.benchmark import (
    AgentTrace,
    BenchmarkDefinition,
    BenchmarkTask,
    TraceAction,
    evaluate_benchmark,
    load_benchmark_definition,
)
from analysis.task_exploration import SearchPolicy, SeedKind, SeedQuery, TaskDefinition, TaskExplorer, TaskType
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
