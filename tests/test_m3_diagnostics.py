import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import (
    DiagnosticKind,
    DiagnosticsConfig,
    FrictionDiagnoser,
    GraphAnalyzer,
    TaskType,
    diagnostics_collection,
)
from code_analyzer.cli import main
from language_analyzers.core.graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    NodeCost,
    NodeKind,
    RelationKind,
    Resolution,
    SourceSpan,
)


def node(node_id, tokens, path, kind=NodeKind.FUNCTION, **values):
    return GraphNode(
        node_id,
        values.pop("label", node_id),
        "symbol",
        kind,
        kind=kind,
        span=SourceSpan(path, 1, 1),
        cost=NodeCost(tokens, tokens * 4, 1),
        **values,
    )


def edge(source, target, relation=RelationKind.CALLS, **values):
    return GraphEdge(source, target, relation, **values)


def diagnose(nodes, edges, config=None):
    metrics = GraphAnalyzer().analyze(nodes, edges)["node_metrics"]
    return FrictionDiagnoser(config).diagnose(nodes, edges, metrics)


def kinds(report, kind):
    return [finding for finding in report.findings if finding.kind == kind]


class DiagnosticsConfigTests(unittest.TestCase):
    def test_percentile_out_of_range_raises(self):
        for value in (1.0, 1.5, -0.1, float("nan")):
            with self.assertRaises(ValueError):
                DiagnosticsConfig(percentile=value)

    def test_non_numeric_percentile_raises(self):
        with self.assertRaises(ValueError):
            DiagnosticsConfig(percentile="0.9")

    def test_cycle_length_below_two_raises(self):
        for value in (1, 0, -3):
            with self.assertRaises(ValueError):
                DiagnosticsConfig(max_cycle_length=value)

    def test_negative_bounds_raise(self):
        with self.assertRaises(ValueError):
            DiagnosticsConfig(min_effective_token_cost=-1.0)
        with self.assertRaises(ValueError):
            DiagnosticsConfig(min_fan_in=-1)
        with self.assertRaises(ValueError):
            DiagnosticsConfig(min_ambiguous_candidates=0)

    def test_defaults_round_trip(self):
        self.assertEqual(
            DiagnosticsConfig().to_dict(),
            {
                "percentile": 0.95,
                "min_effective_token_cost": 400.0,
                "min_fan_in": 4,
                "min_betweenness": 0.0,
                "min_ambiguous_candidates": 2,
                "max_cycle_length": 8,
                "max_evidence_paths": 3,
                "max_findings_per_kind": 20,
            },
        )


class EmptyAndExcludedGraphTests(unittest.TestCase):
    def test_empty_graph_yields_no_findings(self):
        report = diagnose([], [])
        self.assertEqual(report.findings, ())
        self.assertEqual(
            report.thresholds,
            {
                "effective_token_cost": 400.0,
                "pagerank": 0.0,
                "betweenness_centrality": 0.0,
                "weighted_centrality_cost": 0.0,
            },
        )
        self.assertEqual(set(report.counts().values()), {0})

    def test_single_small_node_yields_no_findings(self):
        report = diagnose([node("a", 10, "app/a.py")], [])
        self.assertEqual(report.findings, ())

    def test_vendored_and_generated_nodes_are_excluded(self):
        nodes = [
            node("v", 5000, "vendor/big.py", flags=["vendored"]),
            node("g", 5000, "app/schema_pb2.py", flags=["generated"]),
        ]
        self.assertEqual(diagnose(nodes, [edge("v", "g"), edge("g", "v")]).findings, ())

    def test_test_nodes_are_excluded_from_the_population(self):
        nodes = [node("t", 5000, "tests/test_big.py")] + [
            node(f"c{index}", 10, "app/c.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "t") for index in range(5)]
        report = diagnose(nodes, edges)
        self.assertEqual([finding.node_ids for finding in report.findings], [])


class CentralLargeSymbolTests(unittest.TestCase):
    def _hub(self, hub_tokens):
        nodes = [node("hub", hub_tokens, "app/hub.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "hub") for index in range(5)]
        return nodes, edges

    def test_large_symbol_with_high_fan_in_is_reported(self):
        nodes, edges = self._hub(1000)
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.node_ids, ("hub",))
        self.assertEqual(finding.metrics["effective_token_cost"], 1000.0)
        self.assertEqual(finding.metrics["fan_in"], 5.0)
        self.assertEqual(finding.applicable_task_types, tuple(TaskType))
        self.assertEqual(finding.confidence, Confidence.STATIC_CERTAIN.value)
        self.assertEqual([item.action for item in finding.improvements], ["split_symbol"])
        self.assertEqual(
            finding.improvements[0].linked_metrics,
            ("effective_token_cost", "hop_2_token_cost", "target_discovery_cost"),
        )

    def test_evidence_paths_are_capped_and_point_at_dependents(self):
        nodes, edges = self._hub(1000)
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)[0]
        self.assertEqual(len(finding.evidence_paths), 3)
        for path in finding.evidence_paths:
            self.assertEqual(path.node_ids[1], "hub")
            self.assertEqual(len(path.edges), 1)
            self.assertEqual(path.edges[0].relation, RelationKind.CALLS)

    def test_absolute_floor_blocks_a_small_repository(self):
        nodes, edges = self._hub(100)
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL), [])

    def test_percentile_blocks_a_node_above_the_floor_only(self):
        nodes = [
            node("huge", 5000, "app/huge.py", kind=NodeKind.CLASS),
            node("big", 500, "app/big.py", kind=NodeKind.CLASS),
        ] + [node(f"c{index}", 10, "app/caller.py") for index in range(5)]
        edges = [edge(f"c{index}", "huge") for index in range(5)]
        edges += [edge(f"c{index}", "big") for index in range(5)]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)
        self.assertEqual([finding.node_ids for finding in findings], [("huge",)])

    def test_isolated_large_symbol_without_fan_in_is_not_reported(self):
        nodes = [node("lonely", 1000, "app/lonely.py", kind=NodeKind.CLASS)]
        nodes += [node(f"c{index}", 10, "app/caller.py") for index in range(4)]
        nodes.append(node("popular", 10, "app/popular.py"))
        edges = [edge(f"c{index}", "popular") for index in range(4)]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)
        self.assertEqual(findings, [])

    def test_non_subject_kinds_are_ignored(self):
        nodes = [node("cfg", 1000, "app/cfg.py", kind=NodeKind.CONFIGURATION)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "cfg") for index in range(5)]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL), [])

    def test_findings_are_capped_and_ordered_by_cost(self):
        nodes = []
        edges = []
        for index in range(4):
            nodes.append(node(f"hub{index}", 1000 + index, f"app/hub{index}.py", kind=NodeKind.CLASS))
            for caller in range(5):
                nodes.append(node(f"c{index}_{caller}", 10, "app/caller.py"))
                edges.append(edge(f"c{index}_{caller}", f"hub{index}"))
        config = DiagnosticsConfig(percentile=0.5, max_findings_per_kind=2)
        findings = kinds(diagnose(nodes, edges, config), DiagnosticKind.CENTRAL_LARGE_SYMBOL)
        self.assertEqual([finding.node_ids[0] for finding in findings], ["hub3", "hub2"])


class BridgeBottleneckTests(unittest.TestCase):
    def test_node_joining_two_directories_is_reported(self):
        nodes = [
            node("a", 10, "alpha/a.py"),
            node("m", 10, "middle/m.py"),
            node("b", 10, "beta/b.py"),
        ]
        edges = [edge("a", "m"), edge("m", "b")]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.BRIDGE_BOTTLENECK)
        self.assertEqual([finding.node_ids for finding in findings], [("m",)])
        finding = findings[0]
        self.assertEqual(finding.metrics["crossing_pair_count"], 1.0)
        self.assertEqual(finding.metrics["neighbor_directory_count"], 2.0)
        self.assertEqual(finding.evidence_paths[0].node_ids, ("a", "m", "b"))
        self.assertEqual(len(finding.evidence_paths[0].edges), 2)
        self.assertEqual(
            finding.applicable_task_types,
            (TaskType.BUG_FIX, TaskType.FEATURE_ADD, TaskType.API_CHANGE),
        )

    def test_single_directory_chain_is_not_a_bridge(self):
        nodes = [node(name, 10, "alpha/module.py") for name in ("a", "m", "b")]
        edges = [edge("a", "m"), edge("m", "b")]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.BRIDGE_BOTTLENECK), [])

    def test_zero_betweenness_graph_is_not_reported(self):
        nodes = [node("a", 10, "alpha/a.py"), node("b", 10, "beta/b.py")]
        self.assertEqual(kinds(diagnose(nodes, [edge("a", "b")]), DiagnosticKind.BRIDGE_BOTTLENECK), [])

    def test_test_neighbours_do_not_create_a_crossing(self):
        nodes = [
            node("t", 10, "tests/test_m.py"),
            node("m", 10, "middle/m.py"),
            node("b", 10, "middle/b.py"),
        ]
        edges = [edge("t", "m"), edge("m", "b")]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.BRIDGE_BOTTLENECK), [])


class ReexportAmbiguityTests(unittest.TestCase):
    def test_ambiguous_edge_with_two_candidates_is_reported(self):
        nodes = [node("barrel", 10, "app/index.py"), node("target", 10, "app/impl.py")]
        edges = [edge(
            "barrel", "target", RelationKind.IMPORTS_SYMBOL,
            confidence=Confidence.STATIC_INFERRED,
            resolution=Resolution.AMBIGUOUS,
            candidates=["other", "another"],
        )]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.node_ids, ("barrel",))
        self.assertEqual(finding.metrics["ambiguous_edge_count"], 1.0)
        self.assertEqual(finding.metrics["candidate_count"], 2.0)
        self.assertEqual(finding.confidence, Confidence.STATIC_INFERRED.value)
        self.assertEqual([item.action for item in finding.improvements], ["narrow_reexport"])

    def test_single_candidate_is_below_the_threshold(self):
        nodes = [node("barrel", 10, "app/index.py"), node("target", 10, "app/impl.py")]
        edges = [edge(
            "barrel", "target", RelationKind.IMPORTS_SYMBOL,
            resolution=Resolution.AMBIGUOUS, candidates=["other"],
        )]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY), [])

    def test_reexport_relation_and_flag_are_reported(self):
        nodes = [
            node("barrel", 10, "app/index.py", flags=["reexport"]),
            node("target", 10, "app/impl.py"),
        ]
        edges = [edge("barrel", "target", RelationKind.RE_EXPORTS)]
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)[0]
        self.assertEqual(finding.node_ids, ("barrel",))
        self.assertEqual(finding.metrics["reexport_edge_count"], 1.0)


class CyclicDependencyTests(unittest.TestCase):
    def test_two_node_cycle_is_reported_with_a_closed_path(self):
        nodes = [node("a", 10, "app/a.py"), node("b", 10, "app/b.py")]
        edges = [edge("a", "b", RelationKind.IMPORTS), edge("b", "a", RelationKind.IMPORTS)]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.CYCLIC_DEPENDENCY)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.node_ids, ("a", "b"))
        self.assertEqual(finding.metrics, {"size": 2.0, "same_file": 0.0})
        self.assertEqual(finding.evidence_paths[0].node_ids, ("a", "b", "a"))
        self.assertEqual([item.action for item in finding.improvements], ["break_cycle"])

    def test_same_file_cycle_is_flagged(self):
        nodes = [node("a", 10, "app/pair.py"), node("b", 10, "app/pair.py")]
        edges = [edge("a", "b", RelationKind.CALLS), edge("b", "a", RelationKind.CALLS)]
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.CYCLIC_DEPENDENCY)[0]
        self.assertEqual(finding.metrics["same_file"], 1.0)

    def test_cycle_longer_than_the_limit_is_ignored(self):
        nodes = [node(name, 10, f"app/{name}.py") for name in ("a", "b", "c")]
        edges = [
            edge("a", "b", RelationKind.IMPORTS),
            edge("b", "c", RelationKind.IMPORTS),
            edge("c", "a", RelationKind.IMPORTS),
        ]
        config = DiagnosticsConfig(max_cycle_length=2)
        self.assertEqual(kinds(diagnose(nodes, edges, config), DiagnosticKind.CYCLIC_DEPENDENCY), [])
        default = kinds(diagnose(nodes, edges), DiagnosticKind.CYCLIC_DEPENDENCY)
        self.assertEqual(default[0].node_ids, ("a", "b", "c"))

    def test_non_structural_relations_do_not_form_a_cycle(self):
        nodes = [node("a", 10, "app/a.py"), node("b", 10, "app/b.py")]
        edges = [edge("a", "b", RelationKind.CONTAINS), edge("b", "a", RelationKind.CONTAINS)]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.CYCLIC_DEPENDENCY), [])


class MissingTestLinkTests(unittest.TestCase):
    def _graph(self, tested):
        nodes = [node("core", 1000, "app/core.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "core") for index in range(5)]
        if tested:
            nodes.append(node("spec", 10, "tests/test_core.py"))
            edges.append(edge("spec", "core", RelationKind.TESTS,
                              confidence=Confidence.STATIC_INFERRED,
                              resolution=Resolution.UNIQUE_NAME))
        return nodes, edges

    def test_untested_costly_node_is_reported(self):
        findings = kinds(diagnose(*self._graph(False)), DiagnosticKind.MISSING_TEST_LINK)
        self.assertEqual([finding.node_ids for finding in findings], [("core",)])
        finding = findings[0]
        self.assertEqual(finding.metrics["effective_token_cost"], 1000.0)
        self.assertGreater(finding.metrics["weighted_centrality_cost"], 0.0)
        self.assertEqual([item.action for item in finding.improvements], ["add_focused_test"])
        self.assertEqual(finding.improvements[0].linked_metrics, ("impact_discovery_cost",))

    def test_tested_node_is_not_reported(self):
        self.assertEqual(kinds(diagnose(*self._graph(True)), DiagnosticKind.MISSING_TEST_LINK), [])

    def test_cheap_untested_node_is_below_the_floor(self):
        nodes = [node("core", 100, "app/core.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "core") for index in range(5)]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.MISSING_TEST_LINK), [])


class ReportShapeTests(unittest.TestCase):
    def _graph(self):
        nodes = [
            node("hub", 1000, "alpha/hub.py", kind=NodeKind.CLASS),
            node("side", 10, "beta/side.py"),
        ] + [node(f"c{index}", 10, "alpha/caller.py") for index in range(5)]
        edges = [edge(f"c{index}", "hub") for index in range(5)] + [edge("hub", "side")]
        return nodes, edges

    def test_report_is_deterministic(self):
        nodes, edges = self._graph()
        self.assertEqual(diagnose(nodes, edges).to_dict(), diagnose(nodes, edges).to_dict())

    def test_report_serializes_to_json(self):
        nodes, edges = self._graph()
        payload = diagnose(nodes, edges).to_dict()
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(restored["counts"]["central_large_symbol"], 1)
        self.assertEqual(sorted(restored), ["config", "counts", "findings", "thresholds"])
        finding = restored["findings"][0]
        self.assertEqual(
            sorted(finding),
            ["applicable_task_types", "confidence", "evidence_paths", "false_positive_risks",
             "improvements", "kind", "metrics", "node_ids"],
        )
        self.assertTrue(finding["false_positive_risks"])

    def test_collection_rows_carry_the_subject_node_id(self):
        nodes, edges = self._graph()
        collection = diagnostics_collection(diagnose(nodes, edges), nodes)
        self.assertEqual(collection.key, "diagnostics")
        self.assertEqual(collection.view, "table")
        row = collection.rows[0]
        self.assertEqual(row["id"], "hub")
        self.assertEqual(row["kind"], "central_large_symbol")
        self.assertEqual(row["improvement"], "split_symbol")
        self.assertIn("effective_token_cost=1000", row["metrics"])
        for column in collection.columns:
            self.assertIn(column.key, row)


class ThresholdResolutionTests(unittest.TestCase):
    def test_nearest_rank_quantile_is_used(self):
        costs = (100, 200, 300, 400, 5000)
        nodes = [node(f"n{index}", cost, "app/n.py") for index, cost in enumerate(costs)]
        config = DiagnosticsConfig(percentile=0.6, min_effective_token_cost=0.0)
        metrics = GraphAnalyzer().analyze(nodes, [])["node_metrics"]
        report = FrictionDiagnoser(config).diagnose(nodes, [], metrics)
        # nearest rank at 0.6 over five values is index ceil(0.6 * 4) == 3, i.e. 400 —
        # linear interpolation would give 340 instead.
        self.assertEqual(report.thresholds["effective_token_cost"], 400.0)

    def test_absolute_floor_wins_over_a_lower_cut(self):
        nodes = [node(f"n{index}", 10, "app/n.py") for index in range(5)]
        report = diagnose(nodes, [])
        self.assertEqual(report.thresholds["effective_token_cost"], 400.0)

    def test_nodes_missing_from_metrics_are_skipped(self):
        nodes = [node("hub", 5000, "app/hub.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "hub") for index in range(5)]
        metrics = GraphAnalyzer().analyze(nodes, edges)["node_metrics"]
        del metrics["hub"]
        report = FrictionDiagnoser().diagnose(nodes, edges, metrics)
        self.assertEqual(kinds(report, DiagnosticKind.CENTRAL_LARGE_SYMBOL), [])


class OrderingTieBreakTests(unittest.TestCase):
    def test_equal_primary_metric_falls_back_to_node_id(self):
        nodes = []
        edges = []
        for name in ("hub_b", "hub_a"):
            nodes.append(node(name, 1000, f"app/{name}.py", kind=NodeKind.CLASS))
            for caller in range(5):
                nodes.append(node(f"{name}_c{caller}", 10, "app/caller.py"))
                edges.append(edge(f"{name}_c{caller}", name))
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)
        self.assertEqual([finding.node_ids[0] for finding in findings], ["hub_a", "hub_b"])
        self.assertEqual(
            {finding.metrics["effective_token_cost"] for finding in findings}, {1000.0}
        )


class ConfidenceAggregationTests(unittest.TestCase):
    def test_weakest_evidence_confidence_wins(self):
        nodes = [node("barrel", 10, "app/index.py")] + [
            node(f"t{index}", 10, "app/impl.py") for index in range(2)
        ]
        edges = [
            edge("barrel", "t0", RelationKind.IMPORTS_SYMBOL,
                 confidence=Confidence.STATIC_INFERRED, resolution=Resolution.AMBIGUOUS,
                 candidates=["x", "y"]),
            edge("barrel", "t1", RelationKind.IMPORTS_SYMBOL,
                 confidence=Confidence.DYNAMIC_REQUIRED, resolution=Resolution.AMBIGUOUS,
                 candidates=["x", "y"]),
        ]
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)[0]
        self.assertEqual(finding.metrics["ambiguous_edge_count"], 2.0)
        self.assertEqual(finding.confidence, Confidence.DYNAMIC_REQUIRED.value)

    def test_stronger_edge_alone_keeps_its_confidence(self):
        nodes = [node("barrel", 10, "app/index.py"), node("t0", 10, "app/impl.py")]
        edges = [edge("barrel", "t0", RelationKind.IMPORTS_SYMBOL,
                      confidence=Confidence.STATIC_CERTAIN, resolution=Resolution.UNRESOLVED,
                      candidates=["x", "y"])]
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)[0]
        self.assertEqual(finding.confidence, Confidence.STATIC_CERTAIN.value)


class ReexportTriggerIsolationTests(unittest.TestCase):
    def test_reexport_flag_alone_is_reported(self):
        nodes = [
            node("barrel", 10, "app/index.py", flags=["reexport"]),
            node("target", 10, "app/impl.py"),
        ]
        edges = [edge("barrel", "target", RelationKind.IMPORTS_SYMBOL)]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)
        self.assertEqual([finding.node_ids for finding in findings], [("barrel",)])
        self.assertEqual(findings[0].metrics["reexport_edge_count"], 0.0)
        self.assertEqual(findings[0].evidence_paths[0].node_ids, ("barrel", "target"))

    def test_reexport_relation_alone_is_reported(self):
        nodes = [node("barrel", 10, "app/index.py"), node("target", 10, "app/impl.py")]
        edges = [edge("barrel", "target", RelationKind.RE_EXPORTS)]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)
        self.assertEqual([finding.node_ids for finding in findings], [("barrel",)])
        self.assertEqual(findings[0].metrics["reexport_edge_count"], 1.0)

    def test_plain_import_without_flag_or_ambiguity_is_not_reported(self):
        nodes = [node("module", 10, "app/index.py"), node("target", 10, "app/impl.py")]
        edges = [edge("module", "target", RelationKind.IMPORTS_SYMBOL)]
        self.assertEqual(kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY), [])


class NameCollisionTests(unittest.TestCase):
    def test_colliding_names_are_grouped_into_one_finding(self):
        nodes = [
            node("py:b#router", 10, "app/b.py", label="router", flags=["ambiguous_name"]),
            node("py:a#router", 10, "app/a.py", label="router", flags=["ambiguous_name"]),
            node("caller", 10, "app/caller.py"),
        ]
        edges = [edge("caller", "py:a#router")]
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.REEXPORT_AMBIGUITY)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].node_ids, ("py:a#router", "py:b#router"))
        self.assertEqual(findings[0].metrics["collision_count"], 2.0)
        self.assertEqual(findings[0].evidence_paths[0].node_ids, ("caller", "py:a#router"))

    def test_a_unique_ambiguous_name_is_not_a_collision(self):
        nodes = [
            node("py:a#router", 10, "app/a.py", label="router", flags=["ambiguous_name"]),
            node("py:b#other", 10, "app/b.py", label="other", flags=["ambiguous_name"]),
        ]
        self.assertEqual(kinds(diagnose(nodes, []), DiagnosticKind.REEXPORT_AMBIGUITY), [])


class DetectorBoundaryTests(unittest.TestCase):
    def test_cycle_of_exactly_the_limit_is_reported(self):
        nodes = [node(name, 10, f"app/{name}.py") for name in ("a", "b", "c")]
        edges = [
            edge("a", "b", RelationKind.IMPORTS),
            edge("b", "c", RelationKind.IMPORTS),
            edge("c", "a", RelationKind.IMPORTS),
        ]
        findings = kinds(diagnose(nodes, edges, DiagnosticsConfig(max_cycle_length=3)),
                         DiagnosticKind.CYCLIC_DEPENDENCY)
        self.assertEqual([finding.node_ids for finding in findings], [("a", "b", "c")])
        self.assertEqual(findings[0].evidence_paths[0].node_ids, ("a", "b", "c", "a"))

    def test_tests_edge_direction_is_respected(self):
        nodes = [node("core", 1000, "app/core.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        nodes.append(node("spec", 10, "tests/test_core.py"))
        edges = [edge(f"c{index}", "core") for index in range(5)]
        edges.append(edge("core", "spec", RelationKind.TESTS))
        findings = kinds(diagnose(nodes, edges), DiagnosticKind.MISSING_TEST_LINK)
        self.assertEqual([finding.node_ids for finding in findings], [("core",)])

    def test_missing_test_metrics_mirror_the_node_metrics(self):
        nodes = [node("core", 1000, "app/core.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "core") for index in range(5)]
        metrics = GraphAnalyzer().analyze(nodes, edges)["node_metrics"]
        finding = kinds(FrictionDiagnoser().diagnose(nodes, edges, metrics),
                        DiagnosticKind.MISSING_TEST_LINK)[0]
        self.assertEqual(
            finding.metrics["weighted_centrality_cost"],
            metrics["core"]["weighted_centrality_cost"],
        )
        self.assertEqual(
            finding.metrics["effective_token_cost"],
            metrics["core"]["effective_token_cost"],
        )

    def test_false_positive_risks_are_the_documented_sentences(self):
        nodes = [node("hub", 1000, "app/hub.py", kind=NodeKind.CLASS)] + [
            node(f"c{index}", 10, "app/caller.py") for index in range(5)
        ]
        edges = [edge(f"c{index}", "hub") for index in range(5)]
        finding = kinds(diagnose(nodes, edges), DiagnosticKind.CENTRAL_LARGE_SYMBOL)[0]
        self.assertEqual(
            finding.false_positive_risks,
            (
                "framework entrypoints are expected to be large and central",
                "aggregation-only modules concentrate references without concentrating logic",
            ),
        )


PROJECT_SOURCE = {
    "app/__init__.py": "",
    "app/service.py": "\n".join(
        [f"def helper_{index}():\n    return {index}\n" for index in range(60)]
        + ["def run():\n    return " + " + ".join(f"helper_{index}()" for index in range(60)) + "\n"]
    ),
    "app/api.py": "from app.service import run\n\n\ndef endpoint():\n    return run()\n",
}
PROJECT_SOURCE.update({
    f"app/consumer_{index}.py": "from app.service import run\n\n\ndef use():\n    return run()\n"
    for index in range(5)
})


class CliContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = self.root / "project"
        for relative, source in PROJECT_SOURCE.items():
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")

    def _run(self, *extra):
        argv = [
            "code-analyzer", str(self.project),
            "--language", "python",
            "-o", str(self.root / "report.html"),
            *extra,
        ]
        with patch.object(sys, "argv", argv):
            main()

    def test_diagnostics_file_is_not_written_by_default(self):
        self._run()
        self.assertFalse((self.root / "diagnostics.json").exists())

    def test_diagnostics_flag_writes_report_and_dashboard_collection(self):
        output = self.root / "diagnostics.json"
        self._run("--json", "--diagnostics", "--diagnostics-output", str(output))
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(sorted(payload), ["config", "counts", "findings", "thresholds"])
        self.assertEqual(payload["counts"]["central_large_symbol"], 1)
        self.assertEqual(payload["findings"][0]["node_ids"], ["py:app.service"])
        exported = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertIn("diagnostics", exported["stats"])
        self.assertIn("diagnostics", exported["collections"])
        self.assertEqual(exported["collections"]["diagnostics"]["view"], "table")

    def test_framework_mode_populates_metrics_for_diagnostics(self):
        output = self.root / "framework-diagnostics.json"
        argv = [
            "code-analyzer", str(self.project),
            "-o", str(self.root / "framework.html"),
            "--json",
            "--diagnostics", "--diagnostics-output", str(output),
        ]
        with patch.object(sys, "argv", argv):
            main()
        exported = json.loads((self.root / "framework.json").read_text(encoding="utf-8"))
        self.assertIn("node_metrics", exported["stats"]["analysis"])
        self.assertTrue(output.exists())

if __name__ == "__main__":
    unittest.main()
