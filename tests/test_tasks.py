import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analysis
from analysis import (
    SeedKind,
    SeedQuery,
    TaskDefinition,
    TaskSeedResolver,
    TaskType,
    load_task_definitions,
)
from code_analyzer.cli import load_graph_cost_config, parse_args
from language_analyzers.core.graph_models import GraphNode, NodeCost, SourceSpan


def node(node_id, label, path, **values):
    metadata = values.pop("metadata", {})
    return GraphNode(
        node_id,
        label,
        "test",
        values.pop("category", "function"),
        metadata=metadata,
        span=SourceSpan(path, values.pop("start_line", 1), values.pop("end_line", 1)),
        cost=NodeCost(1, 4, 1),
        **values,
    )


class RemovedApiTests(unittest.TestCase):
    def test_exploration_and_benchmark_apis_are_not_public(self):
        removed = {
            "AgentTrace", "BenchmarkDefinition", "BenchmarkResult", "BenchmarkSummary", "BenchmarkTask",
            "BranchingBurden", "ContextFragmentation", "CostAccuracy", "EdgeTraversal", "EvidenceGap",
            "ExplorationPath", "GoalDiscovery", "RetrievalMetrics", "SearchPolicy", "SeedRetrieval",
            "TaskExplorationReport", "TaskExplorer", "TraceAction", "TraceMetrics", "Visit",
            "evaluate_benchmark", "load_agent_traces", "load_benchmark_definition", "reports_to_dict",
            "summarize_benchmark",
        }
        self.assertTrue(removed.isdisjoint(analysis.__all__))
        for name in removed:
            with self.subTest(name=name):
                self.assertFalse(hasattr(analysis, name))

    def test_removed_modules_cannot_be_imported(self):
        for module_name in ("analysis.task_exploration", "analysis.benchmark"):
            with self.subTest(module_name=module_name), self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)


class TaskDefinitionTests(unittest.TestCase):
    def test_enum_member_sets_are_exact(self):
        self.assertEqual({item.value for item in TaskType}, {"bug_fix", "feature_add", "api_change", "config_change"})
        self.assertEqual({item.value for item in SeedKind}, {"url", "symbol", "error", "config", "changed_file"})

    def test_canonical_round_trip_and_task_set_shapes(self):
        value = {
            "id": "api-users",
            "type": "api_change",
            "seeds": [{"kind": "url", "value": "/users"}],
            "target_node_ids": ["route"],
            "impact_node_ids": ["client"],
            "test_node_ids": ["test"],
        }
        task = TaskDefinition.from_dict(value)
        self.assertEqual(task.to_dict(), value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            for payload in ([value], {"tasks": [value]}):
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(load_task_definitions(path), [task])

    def test_seed_and_goal_aliases_are_preserved(self):
        seed_aliases = ("seed", "seed_clues")
        goal_aliases = (
            ("target_nodes", "target_node_ids"), ("targets", "target_node_ids"), ("target", "target_node_ids"),
            ("impact_nodes", "impact_node_ids"), ("impacts", "impact_node_ids"), ("impact", "impact_node_ids"),
            ("test_nodes", "test_node_ids"), ("tests", "test_node_ids"), ("test", "test_node_ids"),
        )
        for alias in seed_aliases:
            task = TaskDefinition.from_dict({"id": alias, "type": "bug_fix", alias: {"kind": "symbol", "value": "run"}})
            self.assertEqual(task.seeds, (SeedQuery(SeedKind.SYMBOL, "run"),))
        for alias, field in goal_aliases:
            for nested in (False, True):
                value = {"id": alias, "type": "bug_fix", "seeds": []}
                target = value.setdefault("goals", {}) if nested else value
                target[alias] = ["n"]
                task = TaskDefinition.from_dict(value)
                self.assertEqual(getattr(task, field), frozenset({"n"}))

    def test_invalid_tasks_raise_value_error(self):
        valid = {"id": "x", "type": "bug_fix", "seeds": []}
        invalid = [
            [], "task", None,
            {"type": "bug_fix", "seeds": []},
            {"id": "x", "seeds": []},
            {"id": "x", "type": "bug_fix"},
            {"id": "x", "type": "other", "seeds": []},
            {"id": "x", "type": "bug_fix", "seeds": "bad"},
            {"id": "x", "type": "bug_fix", "seeds": [{"kind": "other", "value": "x"}]},
            {"id": "x", "type": "bug_fix", "seeds": [{"kind": "symbol"}]},
            {"id": "x", "type": "bug_fix", "seeds": [], "goals": []},
            {"id": "x", "type": "bug_fix", "seeds": [], "targets": "node"},
            {"id": "x", "type": "bug_fix", "seeds": [], "tests": [""]},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaskDefinition.from_dict(value)
        with self.assertRaises(ValueError):
            TaskDefinition("x", TaskType.BUG_FIX, None)
        with self.assertRaises(ValueError):
            SeedQuery([], "x")
        with self.assertRaises(ValueError):
            TaskDefinition.from_dict({**valid, "budget": None})
        with self.assertRaises(ValueError):
            TaskDefinition.from_dict({**valid, "budget": 10})

    def test_invalid_seed_values_raise_value_error(self):
        for value in ("", None, 1, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SeedQuery(SeedKind.SYMBOL, value)

    def test_invalid_task_ids_and_seed_members_raise_value_error(self):
        for task_id in ("", None, 1, []):
            value = {"id": task_id, "type": "bug_fix", "seeds": []}
            with self.subTest(task_id=task_id), self.assertRaises(ValueError):
                TaskDefinition.from_dict(value)
        for seed in ("symbol", None, 1):
            value = {"id": "x", "type": "bug_fix", "seeds": [seed]}
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                TaskDefinition.from_dict(value)

    def test_each_goal_rejects_empty_and_non_string_node_ids(self):
        for field in ("target_node_ids", "impact_node_ids", "test_node_ids"):
            for node_ids in ([""], [1], [None]):
                value = {"id": "x", "type": "bug_fix", "seeds": [], field: node_ids}
                with self.subTest(field=field, node_ids=node_ids), self.assertRaises(ValueError):
                    TaskDefinition.from_dict(value)

    def test_invalid_task_files_raise_value_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                load_task_definitions(root / "missing.json")
            path = root / "tasks.json"
            for payload in ("{", "{}", '{"tasks": {}}'):
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    load_task_definitions(path)


class TaskSeedResolverTests(unittest.TestCase):
    def test_all_seed_kinds_use_their_contract_fields(self):
        nodes = [
            node("route", "GET users", "app/routes.py", metadata={"full_path": "/users"}),
            node("symbol", "create_user", "app/users.py", symbol_path="app.users.create_user"),
            node("error", "load_user", "app/service.py", start_line=2, end_line=2),
            node("config", "settings", "app/settings.py", metadata={"config_key": "DATABASE_URL"}),
            node("changed", "helper", "src/helper.py"),
        ]
        source_reader = lambda path: "safe = True\nraise ValueError('user missing')\n"
        resolver = TaskSeedResolver(nodes, "/repo", source_reader)
        expected = {
            SeedQuery(SeedKind.URL, "/users"): ["route"],
            SeedQuery(SeedKind.SYMBOL, "create_user"): ["symbol"],
            SeedQuery(SeedKind.ERROR, "user missing"): ["error"],
            SeedQuery(SeedKind.CONFIG, "DATABASE_URL"): ["config"],
            SeedQuery(SeedKind.CHANGED_FILE, "./src/helper.py"): ["changed"],
        }
        for seed, node_ids in expected.items():
            with self.subTest(seed=seed):
                self.assertEqual(resolver.retrieve(seed), node_ids)

    def test_no_match_returns_empty_list(self):
        resolver = TaskSeedResolver([node("a", "run", "app.py")])
        self.assertEqual(resolver.retrieve(SeedQuery(SeedKind.SYMBOL, "missing")), [])

    def test_ties_are_ordered_by_score_then_node_id(self):
        resolver = TaskSeedResolver([
            node("z", "run", "z.py"),
            node("a", "run", "a.py"),
            node("exact", "handler", "exact.py", metadata={"full_path": "/users"}),
            node("fallback", "GET /users", "fallback.py"),
        ])
        self.assertEqual(resolver.retrieve(SeedQuery(SeedKind.SYMBOL, "run")), ["a", "z"])
        self.assertEqual(resolver.retrieve(SeedQuery(SeedKind.URL, "/users")), ["exact", "fallback"])

    def test_error_source_is_excluded_without_reader_or_when_reader_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("raise RuntimeError('hidden failure')\n", encoding="utf-8")
            subject = node("error", "run", "app.py")
            seed = SeedQuery(SeedKind.ERROR, "hidden failure")
            self.assertEqual(TaskSeedResolver([subject], root).retrieve(seed), [])
            for exception in (OSError("unavailable"), UnicodeError("invalid")):
                def failing_reader(path, error=exception):
                    raise error
                with self.subTest(exception=type(exception)):
                    self.assertEqual(TaskSeedResolver([subject], root, failing_reader).retrieve(seed), [])

    def test_error_reader_receives_project_relative_path_joined_to_root(self):
        seen = []
        resolver = TaskSeedResolver(
            [node("error", "run", "src/app.py")],
            "/repo",
            lambda path: seen.append(path) or "specific failure",
        )
        self.assertEqual(resolver.retrieve({"kind": "error", "value": "specific failure"}), ["error"])
        self.assertEqual(seen, [Path("/repo/src/app.py")])

    def test_changed_file_normalizes_absolute_and_relative_paths(self):
        resolver = TaskSeedResolver([node("changed", "run", "src/app.py")], "/repo")
        self.assertEqual(resolver.retrieve(SeedQuery(SeedKind.CHANGED_FILE, "/repo/src/app.py")), ["changed"])
        self.assertEqual(resolver.retrieve(SeedQuery(SeedKind.CHANGED_FILE, "app.py")), [])

    def test_retrieve_is_a_thin_wrapper_around_retrieve_scored(self):
        nodes = [
            node("route", "GET users", "app/routes.py", metadata={"full_path": "/users"}),
            node("symbol", "create_user", "app/users.py", symbol_path="app.users.create_user"),
            node("error", "load_user", "app/service.py", start_line=2, end_line=2),
            node("config", "settings", "app/settings.py", metadata={"config_key": "DATABASE_URL"}),
            node("changed", "helper", "src/helper.py"),
            node("z", "run", "z.py"),
            node("a", "run", "a.py"),
            node("exact", "handler", "exact.py", metadata={"full_path": "/users"}),
            node("fallback", "GET /users", "fallback.py"),
        ]
        source_reader = lambda path: "safe = True\nraise ValueError('user missing')\n"
        resolver = TaskSeedResolver(nodes, "/repo", source_reader)
        seeds = [
            SeedQuery(SeedKind.URL, "/users"),
            SeedQuery(SeedKind.SYMBOL, "create_user"),
            SeedQuery(SeedKind.SYMBOL, "run"),
            SeedQuery(SeedKind.ERROR, "user missing"),
            SeedQuery(SeedKind.CONFIG, "DATABASE_URL"),
            SeedQuery(SeedKind.CHANGED_FILE, "./src/helper.py"),
            SeedQuery(SeedKind.SYMBOL, "missing"),
        ]
        for seed in seeds:
            with self.subTest(seed=seed):
                scored = resolver.retrieve_scored(seed)
                self.assertEqual(resolver.retrieve(seed), [node_id for _score, node_id in scored])
                self.assertEqual(scored, sorted(scored))


class CliContractTests(unittest.TestCase):
    def test_graph_cost_config_default_and_valid_value(self):
        self.assertEqual(load_graph_cost_config(None), {"unresolved_inject_field_cost": 4.0})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph-cost.json"
            path.write_text('{"unresolved_inject_field_cost": 1.5}', encoding="utf-8")
            self.assertEqual(load_graph_cost_config(path), {"unresolved_inject_field_cost": 1.5})
            path.write_text('{"unresolved_inject_field_cost": 0.0}', encoding="utf-8")
            self.assertEqual(load_graph_cost_config(path), {"unresolved_inject_field_cost": 0.0})

    def test_graph_cost_config_rejects_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                load_graph_cost_config(root / "missing.json")
            path = root / "graph-cost.json"
            payloads = (
                "not json", "[]", "{}", '{"unknown": 1}',
                '{"unresolved_inject_field_cost": 4, "unknown": 1}',
                '{"unresolved_inject_field_cost": -1}',
                '{"unresolved_inject_field_cost": "4"}',
                '{"unresolved_inject_field_cost": true}',
                '{"unresolved_inject_field_cost": NaN}',
                '{"unresolved_inject_field_cost": Infinity}',
            )
            for payload in payloads:
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    load_graph_cost_config(path)

    def test_new_graph_cost_flag_parses(self):
        with patch.object(sys, "argv", ["code-analyzer", ".", "--graph-cost-config", "cost.json"]):
            args = parse_args()
        self.assertEqual(args.graph_cost_config, "cost.json")

    def test_removed_cli_flags_are_rejected(self):
        for flag, value in (
            ("--simulation-config", "cost.json"),
            ("--tasks", "tasks.json"),
            ("--task-policy", "bfs"),
            ("--task-output", "tasks.json"),
            ("--baseline-tasks", "tasks.json"),
        ):
            with self.subTest(flag=flag), patch.object(sys, "argv", ["code-analyzer", ".", flag, value]):
                with self.assertRaises(SystemExit):
                    parse_args()


if __name__ == "__main__":
    unittest.main()
