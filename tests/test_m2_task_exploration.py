import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import (
    SearchPolicy,
    SeedKind,
    SeedQuery,
    TaskDefinition,
    TaskExplorer,
    TaskType,
    load_task_definitions,
    reports_to_dict,
)
from code_analyzer.cli import main, parse_args
from language_analyzers.core.graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    NodeCost,
    Resolution,
    SourceSpan,
)


def node(node_id, label, cost, path, **values):
    metadata = values.pop("metadata", {})
    return GraphNode(
        node_id,
        label,
        "test",
        values.pop("category", "function"),
        metadata=metadata,
        span=SourceSpan(path, 1, 1),
        cost=NodeCost(cost, cost * 4, 1),
        **values,
    )


class TaskDefinitionTests(unittest.TestCase):
    def test_enum_member_sets_are_exact(self):
        self.assertEqual({item.value for item in TaskType}, {"bug_fix", "feature_add", "api_change", "config_change"})
        self.assertEqual({item.value for item in SeedKind}, {"url", "symbol", "error", "config", "changed_file"})
        self.assertEqual({item.value for item in SearchPolicy}, {"bfs", "weighted_shortest", "budget_limited"})

    def test_json_round_trip_and_object_or_list_task_sets(self):
        value = {
            "id": "api-users",
            "type": "api_change",
            "seeds": [{"kind": "url", "value": "/users"}],
            "target_node_ids": ["route"],
            "impact_node_ids": ["client"],
            "test_node_ids": ["test"],
            "budget": 12,
        }
        task = TaskDefinition.from_dict(value)
        self.assertEqual(task.to_dict(), value)
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "tasks.json"
            for payload in ([value], {"tasks": [value]}):
                task_file.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(load_task_definitions(task_file), [task])

    def test_multi_seed_and_multi_goal_round_trip_and_distinct_seed_cost(self):
        value = {
            "id": "multi",
            "type": "bug_fix",
            "seeds": [{"kind": "symbol", "value": "one"}, {"kind": "symbol", "value": "two"}],
            "target_node_ids": ["a", "b"],
            "impact_node_ids": ["a", "b"],
            "test_node_ids": ["a", "b"],
            "budget": None,
        }
        task = TaskDefinition.from_dict(value)
        self.assertEqual(task.to_dict(), value)
        explorer = TaskExplorer([node("a", "one", 2, "a.py"), node("b", "two", 3, "b.py")], [])
        report = explorer.run(task, SearchPolicy.BFS)
        self.assertEqual(report.visited_order, ("a", "b"))
        self.assertEqual([item.cumulative_effective_cost for item in report.visited], [2.0, 5.0])
        self.assertEqual(len([item for item in report.goal_discoveries if item.node_id == "a"]), 3)
        self.assertEqual(len([item for item in report.goal_discoveries if item.node_id == "b"]), 3)
        self.assertEqual(report.termination_reason, "goals_satisfied")

    def test_list_and_object_task_sets_load_two_tasks_in_order(self):
        values = [
            {"id": "one", "type": "feature_add", "seeds": [{"kind": "symbol", "value": "one"}]},
            {"id": "two", "type": "config_change", "seeds": [{"kind": "config", "value": "TWO"}]},
        ]
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "tasks.json"
            for payload in (values, {"tasks": values}):
                task_file.write_text(json.dumps(payload), encoding="utf-8")
                loaded = load_task_definitions(task_file)
                self.assertEqual([item.id for item in loaded], ["one", "two"])
                self.assertEqual([item.type for item in loaded], [TaskType.FEATURE_ADD, TaskType.CONFIG_CHANGE])

    def test_invalid_enums_schema_and_budget_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "not a valid TaskType"):
            TaskDefinition.from_dict({"id": "x", "type": "other", "seeds": []})
        with self.assertRaisesRegex(ValueError, "seed is missing value"):
            TaskDefinition.from_dict({"id": "x", "type": "bug_fix", "seeds": [{"kind": "error"}]})
        with self.assertRaisesRegex(ValueError, "non-negative"):
            TaskDefinition("x", TaskType.BUG_FIX, (), budget=-1)
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "tasks.json"
            task_file.write_text('{"wrong": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "task set"):
                load_task_definitions(task_file)

    def test_missing_fields_wrong_containers_and_invalid_seed_kind_fail(self):
        valid = {"id": "x", "type": "bug_fix", "seeds": []}
        for key in ("id", "type", "seeds"):
            value = dict(valid)
            value.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                TaskDefinition.from_dict(value)
        for value in ([], "task", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaskDefinition.from_dict(value)
        with self.assertRaises(ValueError):
            TaskDefinition.from_dict({"id": "x", "type": "bug_fix", "seeds": "error"})
        with self.assertRaises(ValueError):
            TaskDefinition.from_dict({"id": "x", "type": "bug_fix", "seeds": [{"kind": "trace", "value": "x"}]})
        with self.assertRaises(ValueError):
            TaskDefinition.from_dict({"id": "x", "type": "bug_fix", "seeds": [], "targets": "node"})


class RetrievalTests(unittest.TestCase):
    def test_all_seed_kinds_use_their_contract_fields(self):
        nodes = [
            node("route", "GET /users", 2, "app/routes.py", metadata={"full_path": "/users"}),
            node("symbol", "create_user", 2, "app/users.py", symbol_path="app.users.create_user", signature="create_user(name: str)"),
            node("config", "DATABASE_URL", 2, "app/settings.py", category="configuration", metadata={"config_key": "DATABASE_URL"}),
            node("changed", "helper", 2, "src/helper.py"),
        ]
        explorer = TaskExplorer(nodes, [])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.URL, "/users")), ["route"])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.SYMBOL, "create_user")), ["symbol"])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.CONFIG, "DATABASE_URL")), ["config"])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.CHANGED_FILE, "./src/helper.py")), ["changed"])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.CHANGED_FILE, "helper.py")), [])

    def test_error_searches_only_the_node_source_span_and_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "app.py"
            source.write_text("safe = True\nraise ValueError('user missing')\n", encoding="utf-8")
            nodes = [
                GraphNode("safe", "safe", "g", "field", span=SourceSpan("app.py", 1, 1), cost=NodeCost(1, 1, 1)),
                GraphNode("error", "load", "g", "function", span=SourceSpan("app.py", 2, 2), cost=NodeCost(1, 1, 1)),
            ]
            explorer = TaskExplorer(nodes, [], directory)
            self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.ERROR, "user missing")), ["error"])
            self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.ERROR, "not present")), [])

    def test_dedicated_values_rank_before_label_fallback_and_casefold_is_unicode_safe(self):
        nodes = [
            node("url-field", "handler", 1, "a.py", metadata={"path": "/straße"}),
            node("url-label", "GET /STRASSE", 1, "b.py"),
            node("not-url", "unrelated", 1, "users.py"),
            node("config-field", "settings", 1, "c.py", metadata={"config_key": "Straße_Key"}),
            node("config-label", "STRASSE_KEY", 1, "d.py"),
        ]
        explorer = TaskExplorer(nodes, [])
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.URL, "/STRASSE")), ["url-field", "url-label"])
        self.assertNotIn("not-url", explorer.retrieve(SeedQuery(SeedKind.URL, "/users")))
        self.assertEqual(explorer.retrieve(SeedQuery(SeedKind.CONFIG, "STRASSE_KEY")), ["config-label", "config-field"])

    def test_duplicate_seed_queries_charge_the_seed_node_once(self):
        explorer = TaskExplorer([node("x", "symbol", 4, "x.py")], [])
        task = TaskDefinition(
            "duplicates", TaskType.BUG_FIX,
            (SeedQuery(SeedKind.SYMBOL, "symbol"), SeedQuery(SeedKind.SYMBOL, "symbol")),
        )
        report = explorer.run(task, SearchPolicy.BFS)
        self.assertEqual(len(report.retrievals), 2)
        self.assertEqual(report.visited_order, ("x",))
        self.assertEqual(report.visited[0].cumulative_effective_cost, 4.0)


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            node("s", "seed", 2, "app/start.py"),
            node("a", "expensive", 8, "lib/expensive.py"),
            node("z", "cheap", 1, "app/cheap.py"),
            node("g", "goal", 3, "tests/test_goal.py"),
        ]
        self.edges = [
            GraphEdge("s", "a", "CALLS", confidence=Confidence.DYNAMIC_REQUIRED, resolution=Resolution.AMBIGUOUS),
            GraphEdge("a", "g", "CALLS", resolution=Resolution.UNRESOLVED),
            GraphEdge("s", "z", "CALLS"),
            GraphEdge("z", "g", "CALLS"),
            GraphEdge("s", "s", "CALLS"),
            GraphEdge("missing", "g", "CALLS"),
        ]
        self.task = TaskDefinition(
            "bug", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),),
            target_node_ids=frozenset({"g"}),
        )
        self.explorer = TaskExplorer(self.nodes, self.edges)

    def test_bfs_is_deterministic_and_reports_exact_metrics(self):
        report = self.explorer.run(self.task, SearchPolicy.BFS)
        self.assertEqual(report.visited_order, ("s", "a", "z", "g"))
        self.assertEqual(report.target_discovery_cost, 14.0)
        self.assertEqual(report.termination_reason, "goals_satisfied")
        discovery = report.goal_discoveries[0]
        self.assertEqual(discovery.path.node_ids, ("s", "a", "g"))
        self.assertEqual(discovery.path.edge_indices, (0, 1))
        self.assertEqual(report.branching_burden.exposed_candidate_count, 4)
        self.assertEqual(report.branching_burden.irrelevant_candidate_count, 2)
        self.assertEqual(report.branching_burden.irrelevant_ratio, 0.5)
        self.assertEqual(report.context_fragmentation.unique_file_count, 3)
        self.assertEqual(report.context_fragmentation.unique_directory_count, 3)
        self.assertEqual(report.context_fragmentation.total_graph_distance, 2)
        self.assertEqual(report.evidence_gap.edge_count, 2)
        self.assertEqual(report.evidence_gap.gap_edge_count, 2)
        self.assertEqual(report.evidence_gap.dynamic_required_count, 1)
        self.assertEqual(report.evidence_gap.ambiguous_count, 1)
        self.assertEqual(report.evidence_gap.unresolved_count, 1)
        self.assertEqual(report.evidence_gap.ratio, 1.0)

    def test_weighted_shortest_uses_cost_and_edge_risk(self):
        report = self.explorer.run(self.task, SearchPolicy.WEIGHTED_SHORTEST)
        self.assertEqual(report.visited_order, ("s", "z", "g"))
        self.assertEqual(report.target_discovery_cost, 6.0)
        self.assertEqual(report.goal_discoveries[0].path.node_ids, ("s", "z", "g"))
        self.assertEqual(report.evidence_gap.edge_count, 2)
        self.assertEqual(report.evidence_gap.gap_edge_count, 0)

    def test_budget_limited_never_reads_a_node_over_budget(self):
        report = self.explorer.run(self.task, SearchPolicy.BUDGET_LIMITED, budget=3)
        self.assertEqual(report.visited_order, ("s", "z"))
        self.assertEqual(report.visited[-1].cumulative_effective_cost, 3.0)
        self.assertEqual(report.termination_reason, "budget_exhausted")
        self.assertIsNone(report.target_discovery_cost)

    def test_zero_budget_no_seeds_and_empty_goals_have_distinct_termination(self):
        zero = self.explorer.run(self.task, SearchPolicy.BFS, budget=0)
        self.assertEqual(zero.visited_order, ())
        self.assertEqual(zero.termination_reason, "budget_exhausted")
        missing = TaskDefinition("missing", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "none"),))
        self.assertEqual(self.explorer.run(missing, SearchPolicy.BFS).termination_reason, "no_seeds")
        empty = TaskDefinition("empty", TaskType.FEATURE_ADD, (SeedQuery(SeedKind.SYMBOL, "seed"),))
        empty_report = self.explorer.run(empty, SearchPolicy.BFS)
        self.assertEqual(empty_report.visited_order, ("s", "a", "z", "g"))
        self.assertEqual(empty_report.termination_reason, "frontier_exhausted")

    def test_adjacency_is_bidirectional_and_invalid_edges_are_ignored(self):
        reverse_task = TaskDefinition(
            "reverse", TaskType.API_CHANGE, (SeedQuery(SeedKind.SYMBOL, "goal"),),
            target_node_ids=frozenset({"s"}),
        )
        report = self.explorer.run(reverse_task, SearchPolicy.WEIGHTED_SHORTEST)
        self.assertEqual(report.goal_discoveries[0].path.node_ids, ("g", "z", "s"))
        self.assertNotIn("missing", report.visited_order)

    def test_empty_goal_categories_are_satisfied_immediately(self):
        task = TaskDefinition(
            "seed-target", TaskType.CONFIG_CHANGE, (SeedQuery(SeedKind.SYMBOL, "seed"),),
            target_node_ids=frozenset({"s"}),
        )
        report = self.explorer.run(task, SearchPolicy.BFS)
        self.assertEqual(report.visited_order, ("s",))
        self.assertEqual(report.target_discovery_cost, 2.0)
        self.assertEqual(report.impact_discovery_cost, 0.0)
        self.assertEqual(report.termination_reason, "goals_satisfied")

    def test_report_serialization_is_json_safe(self):
        report = self.explorer.run(self.task, SearchPolicy.BFS)
        payload = reports_to_dict([report])
        encoded = json.dumps(payload)
        self.assertIn('"policy": "bfs"', encoded)
        self.assertEqual(payload["reports"][0]["visited_order"], ["s", "a", "z", "g"])

    def test_all_goal_categories_and_multiple_targets_complete_at_the_last_goal(self):
        nodes = [node("s", "seed", 1, "s.py"), node("t1", "t1", 2, "t1.py"), node("t2", "t2", 3, "t2.py"), node("i", "impact", 4, "i.py"), node("test", "test", 5, "test.py")]
        edges = [GraphEdge("s", "t1", "CALLS"), GraphEdge("t1", "t2", "CALLS"), GraphEdge("t2", "i", "CALLS"), GraphEdge("i", "test", "TESTS")]
        task = TaskDefinition("all", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"t1", "t2"}), frozenset({"i"}), frozenset({"test"}))
        report = TaskExplorer(nodes, edges).run(task, SearchPolicy.BFS)
        self.assertEqual([(item.category, item.node_id, item.cumulative_effective_cost) for item in report.goal_discoveries], [("target", "t1", 3.0), ("target", "t2", 6.0), ("impact", "i", 10.0), ("test", "test", 15.0)])
        self.assertEqual(report.target_discovery_cost, 6.0)
        self.assertEqual(report.impact_discovery_cost, 10.0)
        self.assertEqual(report.visited_order[-1], "test")
        self.assertEqual(report.termination_reason, "goals_satisfied")

    def test_node_id_ties_do_not_depend_on_opposite_edges(self):
        nodes = [node("s", "seed", 1, "s.py"), node("a", "a", 1, "a.py"), node("b", "b", 1, "b.py")]
        base = [GraphEdge("s", "b", "CALLS"), GraphEdge("s", "a", "CALLS")]
        opposite = base + [GraphEdge("a", "s", "CALLS"), GraphEdge("b", "s", "CALLS")]
        task = TaskDefinition("ties", TaskType.FEATURE_ADD, (SeedQuery(SeedKind.SYMBOL, "seed"),))
        for policy in (SearchPolicy.BFS, SearchPolicy.WEIGHTED_SHORTEST):
            self.assertEqual(TaskExplorer(nodes, base).run(task, policy).visited_order, ("s", "a", "b"))
            self.assertEqual(TaskExplorer(nodes, opposite).run(task, policy).visited_order, ("s", "a", "b"))

    def test_weighted_equal_node_cost_paths_choose_lower_edge_risk(self):
        nodes = [node("s", "seed", 1, "s.py"), node("a", "a", 2, "a.py"), node("b", "b", 2, "b.py"), node("g", "goal", 1, "g.py")]
        edges = [
            GraphEdge("s", "a", "CALLS", confidence=Confidence.DYNAMIC_REQUIRED, resolution=Resolution.AMBIGUOUS),
            GraphEdge("a", "g", "CALLS"), GraphEdge("s", "b", "CALLS"), GraphEdge("b", "g", "CALLS"),
        ]
        task = TaskDefinition("risk", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"g"}))
        report = TaskExplorer(nodes, edges).run(task, SearchPolicy.WEIGHTED_SHORTEST)
        self.assertEqual(report.goal_discoveries[0].path.node_ids, ("s", "b", "g"))

    def test_duplicate_invalid_and_self_edges_never_duplicate_visit_or_cost(self):
        nodes = [node("s", "seed", 2, "s.py"), node("g", "goal", 3, "g.py")]
        edges = [GraphEdge("s", "g", "CALLS"), GraphEdge("s", "g", "CALLS"), GraphEdge("missing", "g", "CALLS"), GraphEdge("s", "missing", "CALLS"), GraphEdge("s", "s", "CALLS")]
        task = TaskDefinition("edges", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"g"}))
        report = TaskExplorer(nodes, edges).run(task, SearchPolicy.BFS)
        self.assertEqual(report.visited_order, ("s", "g"))
        self.assertEqual(report.target_discovery_cost, 5.0)
        self.assertEqual(report.branching_burden.exposed_candidate_count, 1)

    def test_task_budget_exact_insufficient_and_unspent_frontier_exhaustion(self):
        exact_task = TaskDefinition("exact", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"g"}), budget=6)
        exact = self.explorer.run(exact_task, SearchPolicy.WEIGHTED_SHORTEST)
        self.assertEqual(exact.visited_order, ("s", "z", "g"))
        self.assertEqual(exact.termination_reason, "goals_satisfied")
        short_task = TaskDefinition("short", TaskType.BUG_FIX, exact_task.seeds, frozenset({"g"}), budget=5)
        self.assertEqual(self.explorer.run(short_task, SearchPolicy.WEIGHTED_SHORTEST).termination_reason, "budget_exhausted")
        unreachable = TaskDefinition("unreachable", TaskType.BUG_FIX, exact_task.seeds, frozenset({"unknown"}), budget=100)
        self.assertEqual(self.explorer.run(unreachable, SearchPolicy.BFS).termination_reason, "frontier_exhausted")

    def test_budget_priority_prefers_relevance_metadata(self):
        nodes = [node("s", "seed", 1, "s.py"), node("a", "a", 1, "a.py"), node("b", "b", 1, "b.py", metadata={"task_relevance": 5})]
        edges = [GraphEdge("s", "a", "CALLS"), GraphEdge("s", "b", "CALLS")]
        task = TaskDefinition("priority", TaskType.FEATURE_ADD, (SeedQuery(SeedKind.SYMBOL, "seed"),), budget=2)
        report = TaskExplorer(nodes, edges).run(task, SearchPolicy.BUDGET_LIMITED)
        self.assertEqual(report.visited_order, ("s", "b"))

    def test_budget_equal_priority_and_cost_tie_is_node_id_deterministic(self):
        nodes = [node("s", "seed", 1, "s.py"), node("a", "a", 1, "a.py", metadata={"relevance": 2}), node("b", "b", 1, "b.py", metadata={"relevance": 2})]
        edge_sets = [
            [GraphEdge("s", "b", "CALLS"), GraphEdge("s", "a", "CALLS")],
            [GraphEdge("b", "s", "CALLS"), GraphEdge("a", "s", "CALLS")],
        ]
        task = TaskDefinition("tie", TaskType.FEATURE_ADD, (SeedQuery(SeedKind.SYMBOL, "seed"),), budget=3)
        for edges in edge_sets:
            self.assertEqual(TaskExplorer(nodes, edges).run(task, SearchPolicy.BUDGET_LIMITED).visited_order, ("s", "a", "b"))

    def test_all_multi_goal_paths_feed_context_and_evidence_union(self):
        nodes = [
            node("s", "seed", 1, "app/start.py"),
            node("a_t1", "target one", 1, "target/one.py"),
            node("a_t2", "target two", 1, "target/two.py"),
            node("b_i1", "impact one", 1, "impact/one.py"),
            node("b_i2", "impact two", 1, "impact/two.py"),
            node("c_x1", "test one", 1, "tests/one.py"),
            node("c_x2", "test two", 1, "tests/two.py"),
        ]
        edges = [
            GraphEdge("s", "a_t1", "CALLS"),
            GraphEdge("a_t1", "a_t2", "CALLS"),
            GraphEdge("s", "b_i1", "CALLS", confidence=Confidence.DYNAMIC_REQUIRED, resolution=Resolution.AMBIGUOUS),
            GraphEdge("b_i1", "b_i2", "CALLS"),
            GraphEdge("a_t2", "c_x1", "TESTS", resolution=Resolution.UNRESOLVED),
            GraphEdge("c_x1", "c_x2", "TESTS"),
        ]
        task = TaskDefinition(
            "union", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),),
            frozenset({"a_t1", "a_t2"}), frozenset({"b_i1", "b_i2"}), frozenset({"c_x1", "c_x2"}),
        )
        report = TaskExplorer(nodes, edges).run(task, SearchPolicy.BFS)
        self.assertEqual(
            [(item.category, item.node_id, item.path.node_ids) for item in report.goal_discoveries],
            [
                ("target", "a_t1", ("s", "a_t1")),
                ("impact", "b_i1", ("s", "b_i1")),
                ("target", "a_t2", ("s", "a_t1", "a_t2")),
                ("impact", "b_i2", ("s", "b_i1", "b_i2")),
                ("test", "c_x1", ("s", "a_t1", "a_t2", "c_x1")),
                ("test", "c_x2", ("s", "a_t1", "a_t2", "c_x1", "c_x2")),
            ],
        )
        self.assertEqual(report.context_fragmentation.unique_file_count, 7)
        self.assertEqual(report.context_fragmentation.unique_directory_count, 4)
        self.assertEqual(report.context_fragmentation.total_graph_distance, 13)
        self.assertEqual(report.context_fragmentation.maximum_graph_distance, 4)
        self.assertEqual(report.evidence_gap.edge_count, 6)
        self.assertEqual(report.evidence_gap.gap_edge_count, 2)
        self.assertEqual(report.evidence_gap.dynamic_required_count, 1)
        self.assertEqual(report.evidence_gap.ambiguous_count, 1)
        self.assertEqual(report.evidence_gap.unresolved_count, 1)
        self.assertEqual(report.evidence_gap.ratio, 1 / 3)

    def test_seed_goal_has_zero_length_path_and_zero_denominator_metrics(self):
        task = TaskDefinition("seed-goal", TaskType.BUG_FIX, (SeedQuery(SeedKind.SYMBOL, "seed"),), frozenset({"s"}))
        report = self.explorer.run(task, SearchPolicy.BFS)
        self.assertEqual(report.goal_discoveries[0].path.node_ids, ("s",))
        self.assertEqual(report.goal_discoveries[0].path.edges, ())
        self.assertEqual(report.target_discovery_cost, 2.0)
        self.assertEqual(report.branching_burden.exposed_candidate_count, 0)
        self.assertEqual(report.branching_burden.irrelevant_candidate_count, 0)
        self.assertEqual(report.branching_burden.irrelevant_ratio, 0.0)
        self.assertEqual(report.context_fragmentation.unique_file_count, 1)
        self.assertEqual(report.context_fragmentation.unique_directory_count, 1)
        self.assertEqual(report.context_fragmentation.total_graph_distance, 0)
        self.assertEqual(report.context_fragmentation.maximum_graph_distance, 0)
        self.assertEqual(report.evidence_gap.edge_count, 0)
        self.assertEqual(report.evidence_gap.gap_edge_count, 0)
        self.assertEqual(report.evidence_gap.dynamic_required_count, 0)
        self.assertEqual(report.evidence_gap.ambiguous_count, 0)
        self.assertEqual(report.evidence_gap.unresolved_count, 0)
        self.assertEqual(report.evidence_gap.ratio, 0.0)

    def test_report_dictionary_contains_exact_major_fields(self):
        payload = reports_to_dict([self.explorer.run(self.task, SearchPolicy.WEIGHTED_SHORTEST)])
        report = payload["reports"][0]
        self.assertEqual(set(report), {"task_id", "task_type", "policy", "budget", "retrievals", "visited", "goal_discoveries", "target_discovery_cost", "impact_discovery_cost", "branching_burden", "context_fragmentation", "evidence_gap", "termination_reason", "visited_order"})
        self.assertEqual(report["task_id"], "bug")
        self.assertEqual(report["task_type"], "bug_fix")
        self.assertEqual(report["policy"], "weighted_shortest")
        self.assertEqual(report["termination_reason"], "goals_satisfied")
        self.assertEqual(report["retrievals"], [{"seed": {"kind": "symbol", "value": "seed"}, "node_ids": ["s"]}])
        self.assertEqual(report["visited_order"], ["s", "z", "g"])
        self.assertEqual([item["cumulative_effective_cost"] for item in report["visited"]], [2.0, 3.0, 6.0])
        self.assertEqual(report["visited"][-1]["cumulative_effective_cost"], 6.0)
        self.assertEqual(report["goal_discoveries"], [{
            "category": "target",
            "node_id": "g",
            "visit_index": 2,
            "cumulative_effective_cost": 6.0,
            "path": {
                "node_ids": ["s", "z", "g"],
                "edge_indices": [2, 3],
                "edges": [
                    {"edge_index": 2, "from_node_id": "s", "to_node_id": "z", "relation": "CALLS", "confidence": "static_certain", "resolution": "exact"},
                    {"edge_index": 3, "from_node_id": "z", "to_node_id": "g", "relation": "CALLS", "confidence": "static_certain", "resolution": "exact"},
                ],
            },
        }])
        self.assertEqual(report["target_discovery_cost"], 6.0)
        self.assertEqual(report["impact_discovery_cost"], 0.0)
        self.assertEqual(report["branching_burden"], {"exposed_candidate_count": 3, "irrelevant_candidate_count": 2, "irrelevant_ratio": 2 / 3})
        self.assertEqual(report["context_fragmentation"], {"unique_file_count": 3, "unique_directory_count": 2, "total_graph_distance": 2, "maximum_graph_distance": 2})
        self.assertEqual(report["evidence_gap"], {"edge_count": 2, "gap_edge_count": 0, "dynamic_required_count": 0, "ambiguous_count": 0, "unresolved_count": 0, "ratio": 0.0})


class CliContractTests(unittest.TestCase):
    def test_task_options_parse_and_policy_repeats(self):
        argv = ["code-analyzer", ".", "--tasks", "tasks.json", "--task-policy", "bfs", "--task-policy", "weighted_shortest", "--task-output", "out.json"]
        with patch.object(sys, "argv", argv):
            args = parse_args()
        self.assertEqual(args.tasks, "tasks.json")
        self.assertEqual(args.task_policy, ["bfs", "weighted_shortest"])
        self.assertEqual(args.task_output, "out.json")

    def test_invalid_policy_is_an_argparse_error(self):
        with patch.object(sys, "argv", ["code-analyzer", "--task-policy", "random"]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_main_runs_task_file_with_default_policies_and_preserves_no_task_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("def target():\n    return 1\n", encoding="utf-8")
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps({"tasks": [{"id": "cli", "type": "feature_add", "seeds": [{"kind": "symbol", "value": "target"}], "target_node_ids": ["py:main#target"]}]}), encoding="utf-8")
            task_output = root / "task-output.json"
            html_output = root / "with-tasks.html"
            argv = ["code-analyzer", str(root), "--language", "python", "--tasks", str(tasks), "--task-output", str(task_output), "--output", str(html_output)]
            with patch.object(sys, "argv", argv):
                main()
            payload = json.loads(task_output.read_text(encoding="utf-8"))
            self.assertEqual([item["policy"] for item in payload["reports"]], ["bfs", "weighted_shortest", "budget_limited"])
            for report in payload["reports"]:
                self.assertEqual(report["task_id"], "cli")
                self.assertEqual(report["task_type"], "feature_add")
                self.assertEqual(report["retrievals"], [{"seed": {"kind": "symbol", "value": "target"}, "node_ids": ["py:main#target"]}])
                self.assertEqual(report["visited_order"], ["py:main#target"])
                self.assertEqual(report["goal_discoveries"], [{
                    "category": "target",
                    "node_id": "py:main#target",
                    "visit_index": 0,
                    "cumulative_effective_cost": 7.0,
                    "path": {"node_ids": ["py:main#target"], "edge_indices": [], "edges": []},
                }])
                self.assertEqual(report["target_discovery_cost"], 7.0)
                self.assertEqual(report["termination_reason"], "goals_satisfied")
            self.assertTrue(html_output.exists())
            repeated_output = root / "repeated-task-output.json"
            repeated_html = root / "repeated.html"
            repeated_argv = [
                "code-analyzer", str(root), "--language", "python", "--tasks", str(tasks),
                "--task-policy", "budget_limited", "--task-policy", "bfs",
                "--task-output", str(repeated_output), "--output", str(repeated_html),
            ]
            with patch.object(sys, "argv", repeated_argv):
                main()
            repeated_payload = json.loads(repeated_output.read_text(encoding="utf-8"))
            self.assertEqual(len(repeated_payload["reports"]), 2)
            self.assertEqual([item["policy"] for item in repeated_payload["reports"]], ["budget_limited", "bfs"])
            plain_output = root / "plain.html"
            with patch.object(sys, "argv", ["code-analyzer", str(root), "--language", "python", "--output", str(plain_output)]):
                main()
            self.assertTrue(plain_output.exists())
            self.assertFalse((root / "task-exploration.json").exists())

    def test_main_runs_two_tasks_from_list_and_object_for_each_selected_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "main.py").write_text("def one():\n    return 1\n\ndef two():\n    return 2\n", encoding="utf-8")
            task_values = [
                {"id": "one", "type": "feature_add", "seeds": [{"kind": "symbol", "value": "one"}], "target_node_ids": ["py:main#one"]},
                {"id": "two", "type": "bug_fix", "seeds": [{"kind": "symbol", "value": "two"}], "target_node_ids": ["py:main#two"]},
            ]
            for index, task_payload in enumerate((task_values, {"tasks": task_values})):
                task_file = root / f"tasks-{index}.json"
                task_file.write_text(json.dumps(task_payload), encoding="utf-8")
                output = root / f"reports-{index}.json"
                html = root / f"report-{index}.html"
                argv = [
                    "code-analyzer", str(project), "--language", "python", "--tasks", str(task_file),
                    "--task-policy", "weighted_shortest", "--task-policy", "bfs",
                    "--task-output", str(output), "--output", str(html),
                ]
                with patch.object(sys, "argv", argv):
                    main()
                reports = json.loads(output.read_text(encoding="utf-8"))["reports"]
                self.assertEqual(
                    [(item["task_id"], item["policy"]) for item in reports],
                    [("one", "weighted_shortest"), ("one", "bfs"), ("two", "weighted_shortest"), ("two", "bfs")],
                )


if __name__ == "__main__":
    unittest.main()
