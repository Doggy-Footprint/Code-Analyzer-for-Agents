import json
import tempfile
import unittest
from pathlib import Path

from analysis import (
    cost_diff_to_dict,
    diff_repository_cost,
    diff_task_reports,
    load_analysis_export,
    load_task_export,
    unmatched_task_pairs,
)
from language_analyzers.core.serialization import SCHEMA_VERSION


def node(node_id, symbol_path="", label="", kind="function", path="app/module.py"):
    return {
        "id": node_id,
        "label": label or node_id,
        "kind": kind,
        "symbol_path": symbol_path,
        "span": {"file_path": path, "start_line": 1, "end_line": 1, "start_col": 0, "end_col": 0},
        "metadata": {},
    }


def metrics(**values):
    base = {
        "token_cost": 0.0,
        "effective_token_cost": 0.0,
        "pagerank": 0.0,
        "betweenness_centrality": 0.0,
        "weighted_centrality_cost": 0.0,
        "hop_2_token_cost": 0.0,
        "hop_3_token_cost": 0.0,
        "fan_in": 0.0,
        "fan_out": 0.0,
    }
    base.update(values)
    return base


def export(nodes, node_metrics=None, totals=None, diagnostics=None):
    analysis = {
        "node_metrics": node_metrics or {},
        "total_token_cost": (totals or {}).get("total_token_cost", 0),
        "total_effective_token_cost": (totals or {}).get("total_effective_token_cost", 0),
    }
    stats = {"analysis": analysis}
    if diagnostics is not None:
        stats["diagnostics"] = diagnostics
    return {
        "schema_version": SCHEMA_VERSION,
        "project_name": "sample",
        "project_path": "/sample",
        "stats": stats,
        "nodes": nodes,
        "edges": [],
        "collections": {},
        "git_diff": None,
    }


def finding(kind, node_ids):
    return {"kind": kind, "node_ids": list(node_ids), "metrics": {}, "evidence_paths": []}


def task_report(task_id="t1", policy="bfs", **values):
    report = {
        "task_id": task_id,
        "task_type": "bug_fix",
        "policy": policy,
        "target_discovery_cost": 10.0,
        "impact_discovery_cost": 20.0,
        "branching_burden": {"exposed_candidate_count": 8, "irrelevant_candidate_count": 4, "irrelevant_ratio": 0.5},
        "context_fragmentation": {"unique_file_count": 3, "unique_directory_count": 2,
                                  "total_graph_distance": 6, "maximum_graph_distance": 3},
        "evidence_gap": {"edge_count": 4, "gap_edge_count": 1, "dynamic_required_count": 0,
                         "ambiguous_count": 1, "unresolved_count": 0, "ratio": 0.25},
        "termination_reason": "goals_satisfied",
    }
    report.update(values)
    return report


class ExportLoadingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def _write(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_a_valid_export(self):
        path = self._write("a.json", export([node("a")]))
        self.assertEqual(load_analysis_export(path)["project_name"], "sample")

    def test_missing_schema_version_raises(self):
        payload = export([node("a")])
        del payload["schema_version"]
        with self.assertRaises(ValueError):
            load_analysis_export(self._write("b.json", payload))

    def test_wrong_schema_version_raises(self):
        payload = export([node("a")])
        payload["schema_version"] = "1"
        with self.assertRaises(ValueError):
            load_analysis_export(self._write("c.json", payload))

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_analysis_export(self.root / "absent.json")

    def test_malformed_json_raises_value_error(self):
        path = self.root / "broken.json"
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_analysis_export(path)

    def test_task_export_requires_reports_list(self):
        with self.assertRaises(ValueError):
            load_task_export(self._write("t.json", {"tasks": []}))

    def test_task_export_round_trip(self):
        path = self._write("t2.json", {"reports": [task_report()]})
        self.assertEqual(len(load_task_export(path)["reports"]), 1)


class RepositoryDiffTests(unittest.TestCase):
    def test_identical_exports_produce_zero_deltas(self):
        payload = export(
            [node("a", symbol_path="app.a")],
            {"a": metrics(token_cost=10.0, weighted_centrality_cost=1.0)},
            {"total_token_cost": 10, "total_effective_token_cost": 10},
        )
        diff = diff_repository_cost(payload, payload)
        self.assertEqual(diff.totals, {"total_token_cost": 0.0, "total_effective_token_cost": 0.0})
        self.assertEqual(diff.top_movers, ())
        self.assertEqual(diff.node_counts, {"added": 0, "removed": 0, "matched": 1})
        self.assertEqual(diff.match_strategy_counts, {"id": 1, "symbol_path": 0, "kind_label_path": 0})
        self.assertIsNone(diff.diagnostics)

    def test_invalid_top_movers_raises(self):
        payload = export([])
        with self.assertRaises(ValueError):
            diff_repository_cost(payload, payload, top_movers=-1)

    def test_non_mapping_export_raises(self):
        with self.assertRaises(ValueError):
            diff_repository_cost([], export([]))

    def test_added_nodes_are_counted(self):
        baseline = export([node("a")], {"a": metrics()}, {"total_token_cost": 10, "total_effective_token_cost": 10})
        current = export(
            [node("a"), node("b")],
            {"a": metrics(), "b": metrics(token_cost=5.0, weighted_centrality_cost=2.0)},
            {"total_token_cost": 15, "total_effective_token_cost": 15},
        )
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.node_counts, {"added": 1, "removed": 0, "matched": 1})
        self.assertEqual(diff.totals["total_token_cost"], 5.0)
        self.assertEqual([item.node_id for item in diff.top_movers], ["b"])
        self.assertEqual(diff.top_movers[0].status, "added")
        self.assertEqual(diff.top_movers[0].deltas["weighted_centrality_cost"], 2.0)

    def test_removed_nodes_are_counted(self):
        baseline = export([node("a"), node("b")], {"a": metrics(), "b": metrics(weighted_centrality_cost=3.0)})
        current = export([node("a")], {"a": metrics()})
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.node_counts, {"added": 0, "removed": 1, "matched": 1})
        self.assertEqual(diff.top_movers[0].status, "removed")
        self.assertEqual(diff.top_movers[0].deltas["weighted_centrality_cost"], -3.0)

    def test_changed_node_is_a_mover_and_unchanged_is_not(self):
        baseline = export([node("a"), node("b")], {"a": metrics(weighted_centrality_cost=1.0), "b": metrics()})
        current = export([node("a"), node("b")], {"a": metrics(weighted_centrality_cost=4.0), "b": metrics()})
        diff = diff_repository_cost(baseline, current)
        self.assertEqual([item.node_id for item in diff.top_movers], ["a"])
        self.assertEqual(diff.top_movers[0].status, "changed")
        self.assertEqual(diff.top_movers[0].deltas["weighted_centrality_cost"], 3.0)

    def test_top_movers_are_limited_and_ordered_by_absolute_change(self):
        baseline = export(
            [node(name) for name in ("a", "b", "c")],
            {name: metrics() for name in ("a", "b", "c")},
        )
        current = export(
            [node(name) for name in ("a", "b", "c")],
            {
                "a": metrics(weighted_centrality_cost=1.0),
                "b": metrics(weighted_centrality_cost=-5.0),
                "c": metrics(weighted_centrality_cost=3.0),
            },
        )
        diff = diff_repository_cost(baseline, current, top_movers=2)
        self.assertEqual([item.node_id for item in diff.top_movers], ["b", "c"])

    def test_renamed_id_matches_on_symbol_path(self):
        baseline = export([node("a:1", symbol_path="app.a")], {"a:1": metrics(weighted_centrality_cost=1.0)})
        current = export([node("a:9", symbol_path="app.a")], {"a:9": metrics(weighted_centrality_cost=1.0)})
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.node_counts, {"added": 0, "removed": 0, "matched": 1})
        self.assertEqual(diff.match_strategy_counts["symbol_path"], 1)

    def test_renamed_id_and_symbol_path_match_on_shape(self):
        baseline = export([node("a:1", label="run", path="app/x.py")], {"a:1": metrics()})
        current = export([node("a:9", label="run", path="app/x.py")], {"a:9": metrics()})
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.match_strategy_counts["kind_label_path"], 1)
        self.assertEqual(diff.node_counts["matched"], 1)

    def test_ambiguous_symbol_path_is_not_matched(self):
        baseline = export([node("a:1", symbol_path="app.a", label="x"), node("a:2", symbol_path="app.a", label="y")])
        current = export([node("a:3", symbol_path="app.a", label="x"), node("a:4", symbol_path="app.a", label="y")])
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.match_strategy_counts, {"id": 0, "symbol_path": 0, "kind_label_path": 2})
        self.assertEqual(diff.node_counts, {"added": 0, "removed": 0, "matched": 2})

    def test_symbol_path_ambiguous_on_one_side_only_does_not_match(self):
        baseline = export([
            node("a:1", symbol_path="app.a", label="x", path="app/x.py"),
            node("a:2", symbol_path="app.a", label="y", path="app/y.py"),
        ])
        current = export([node("a:3", symbol_path="app.a", label="z", path="app/z.py")])
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.match_strategy_counts, {"id": 0, "symbol_path": 0, "kind_label_path": 0})
        self.assertEqual(diff.node_counts, {"added": 1, "removed": 2, "matched": 0})

    def test_shape_ambiguous_on_one_side_only_does_not_match(self):
        baseline = export([
            node("a:1", label="run", path="app/x.py"),
            node("a:2", label="run", path="app/x.py"),
        ])
        current = export([node("a:3", label="run", path="app/x.py")])
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.node_counts, {"added": 1, "removed": 2, "matched": 0})

    def test_unmatchable_nodes_become_added_and_removed(self):
        baseline = export([node("a:1", symbol_path="app.a", label="x", path="app/x.py")])
        current = export([node("a:3", symbol_path="app.b", label="y", path="app/y.py")])
        diff = diff_repository_cost(baseline, current)
        self.assertEqual(diff.node_counts, {"added": 1, "removed": 1, "matched": 0})


class DiagnosticsDeltaTests(unittest.TestCase):
    def test_findings_are_classified(self):
        baseline = export(
            [node("a"), node("b")],
            {"a": metrics(), "b": metrics()},
            diagnostics={"findings": [
                finding("central_large_symbol", ["a"]),
                finding("missing_test_link", ["b"]),
            ]},
        )
        current = export(
            [node("a"), node("b")],
            {"a": metrics(), "b": metrics()},
            diagnostics={"findings": [
                finding("central_large_symbol", ["a"]),
                finding("cyclic_dependency", ["a", "b"]),
            ]},
        )
        delta = diff_repository_cost(baseline, current).diagnostics
        self.assertEqual([item["kind"] for item in delta.introduced], ["cyclic_dependency"])
        self.assertEqual([item["kind"] for item in delta.resolved], ["missing_test_link"])
        self.assertEqual([item["kind"] for item in delta.persisted], ["central_large_symbol"])

    def test_finding_survives_a_node_id_change(self):
        baseline = export(
            [node("a:1", symbol_path="app.a")],
            {"a:1": metrics()},
            diagnostics={"findings": [finding("central_large_symbol", ["a:1"])]},
        )
        current = export(
            [node("a:9", symbol_path="app.a")],
            {"a:9": metrics()},
            diagnostics={"findings": [finding("central_large_symbol", ["a:9"])]},
        )
        delta = diff_repository_cost(baseline, current).diagnostics
        self.assertEqual((delta.introduced, delta.resolved), ((), ()))
        self.assertEqual(len(delta.persisted), 1)

    def test_diagnostics_on_one_side_only_is_still_compared(self):
        baseline = export([node("a")], {"a": metrics()})
        current = export([node("a")], {"a": metrics()},
                         diagnostics={"findings": [finding("central_large_symbol", ["a"])]})
        delta = diff_repository_cost(baseline, current).diagnostics
        self.assertEqual(len(delta.introduced), 1)
        self.assertEqual(delta.resolved, ())


class TaskDiffTests(unittest.TestCase):
    def test_matching_reports_produce_metric_deltas(self):
        baseline = {"reports": [task_report()]}
        current = {"reports": [task_report(target_discovery_cost=4.0, impact_discovery_cost=25.0)]}
        diffs = diff_task_reports(baseline, current)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].task_id, "t1")
        self.assertEqual(diffs[0].policy, "bfs")
        self.assertEqual(diffs[0].deltas["target_discovery_cost"], -6.0)
        self.assertEqual(diffs[0].deltas["impact_discovery_cost"], 5.0)
        self.assertEqual(diffs[0].deltas["branching_burden.irrelevant_ratio"], 0.0)
        self.assertEqual(diffs[0].deltas["context_fragmentation.total_graph_distance"], 0.0)
        self.assertEqual(diffs[0].deltas["evidence_gap.ratio"], 0.0)
        self.assertIsNone(diffs[0].termination_change)

    def test_unreached_goal_yields_a_none_delta_and_termination_change(self):
        baseline = {"reports": [task_report(target_discovery_cost=None, termination_reason="frontier_exhausted")]}
        current = {"reports": [task_report()]}
        diff = diff_task_reports(baseline, current)[0]
        self.assertIsNone(diff.deltas["target_discovery_cost"])
        self.assertEqual(diff.deltas["impact_discovery_cost"], 0.0)
        self.assertEqual(diff.termination_change, ("frontier_exhausted", "goals_satisfied"))

    def test_unpaired_reports_are_excluded_but_reported(self):
        baseline = {"reports": [task_report(policy="bfs"), task_report(policy="weighted_shortest")]}
        current = {"reports": [task_report(policy="bfs"), task_report(task_id="t2", policy="bfs")]}
        self.assertEqual([(item.task_id, item.policy) for item in diff_task_reports(baseline, current)], [("t1", "bfs")])
        self.assertEqual(
            unmatched_task_pairs(baseline, current),
            {"baseline_only": ["t1:weighted_shortest"], "current_only": ["t2:bfs"]},
        )

    def test_results_are_sorted_by_task_then_policy(self):
        baseline = {"reports": [task_report(task_id="b"), task_report(task_id="a", policy="weighted_shortest"),
                                task_report(task_id="a")]}
        current = baseline
        self.assertEqual(
            [(item.task_id, item.policy) for item in diff_task_reports(baseline, current)],
            [("a", "bfs"), ("a", "weighted_shortest"), ("b", "bfs")],
        )


class SerializationTests(unittest.TestCase):
    def test_payload_is_json_serializable_and_shaped(self):
        payload = export([node("a")], {"a": metrics()})
        repository = diff_repository_cost(payload, payload)
        tasks = diff_task_reports({"reports": [task_report()]}, {"reports": [task_report()]})
        document = cost_diff_to_dict(repository, tasks, {"baseline_only": [], "current_only": []})
        restored = json.loads(json.dumps(document, ensure_ascii=False))
        self.assertEqual(sorted(restored), ["repository", "tasks", "unmatched_task_pairs"])
        self.assertEqual(
            sorted(restored["repository"]),
            ["diagnostics", "match_strategy_counts", "node_counts", "top_movers", "totals"],
        )
        self.assertEqual(sorted(restored["tasks"][0]), ["deltas", "policy", "task_id", "termination_change"])

    def test_default_unmatched_section_is_empty(self):
        payload = export([node("a")], {"a": metrics()})
        document = cost_diff_to_dict(diff_repository_cost(payload, payload))
        self.assertEqual(document["unmatched_task_pairs"], {"baseline_only": [], "current_only": []})
        self.assertEqual(document["tasks"], [])


if __name__ == "__main__":
    unittest.main()
