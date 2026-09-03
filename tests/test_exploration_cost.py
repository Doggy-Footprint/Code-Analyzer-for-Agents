import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import (
    ExplorationCostAnalyzer,
    GraphAnalyzer,
    SeedKind,
    SeedQuery,
    TargetDiscoveryCost,
    TaskDefinition,
    TaskExplorationCostReport,
    TaskType,
    exploration_cost_collection,
    exploration_cost_to_dict,
)
from analysis.exploration_cost import _build_adjacency
from analysis.friction_diagnostics import _STRUCTURAL_RELATIONS
from code_analyzer.cli import main
from language_analyzers.core.graph_models import GraphEdge, GraphNode, NodeCost, RelationKind


def _node(node_id, cost, flags=None, label=None):
    return GraphNode(
        id=node_id,
        label=label or node_id,
        group="symbol",
        category="symbol",
        cost=NodeCost(cost, cost * 4, 1),
        flags=flags or [],
    )


def _edge(source, target, relation=RelationKind.CALLS):
    return GraphEdge(source, target, relation)


def _metrics(nodes, edges):
    return GraphAnalyzer().analyze(nodes, edges)["node_metrics"]


def _task(task_id, seed_value, target_ids, seed_kind=SeedKind.SYMBOL, task_type=TaskType.BUG_FIX):
    return TaskDefinition(
        id=task_id,
        type=task_type,
        seeds=(SeedQuery(seed_kind, seed_value),),
        target_node_ids=frozenset(target_ids),
    )


def _compute_one(task, nodes, edges, metrics):
    return ExplorationCostAnalyzer().compute([task], nodes, edges, metrics).results[0]


class DiamondFixtureTests(unittest.TestCase):
    """Mandatory brute-force-verified fixture from the contract (row #2)."""

    def test_diamond_matches_hand_computed_and_brute_forced_expected_cost(self):
        nodes = [_node("seed", 1), _node("a", 2), _node("b", 3), _node("target", 1)]
        edges = [_edge("seed", "a"), _edge("a", "target"), _edge("seed", "b")]
        metrics = _metrics(nodes, edges)

        cost = {node_id: metrics[node_id]["effective_token_cost"] for node_id in ("seed", "a", "b", "target")}
        self.assertEqual(cost, {"seed": 1.0, "a": 2.0, "b": 3.0, "target": 1.0})

        task = _task("diamond", "seed", {"target"})
        result = _compute_one(task, nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 4)
        self.assertEqual(result.max_cost, 7)
        self.assertEqual(result.expected_cost, 5.5)
        self.assertEqual(result.min_path_node_ids, ("seed", "a", "target"))
        self.assertEqual(result.ball_node_ids, ("a", "b", "seed", "target"))

        # Brute force, written independently of exploration_cost.py: enumerate the two valid
        # shell-consistent (weighted-distance non-decreasing) orderings and average their
        # cumulative cost at the moment `target` is first discovered.
        def cumulative_cost_at_target(order):
            total = 0.0
            for node_id in order:
                total += cost[node_id]
                if node_id == "target":
                    return total
            raise AssertionError("target never appears in this order")

        order_a = ["seed", "a", "target", "b"]
        order_b = ["seed", "a", "b", "target"]
        self.assertEqual(cumulative_cost_at_target(order_a), 4)
        self.assertEqual(cumulative_cost_at_target(order_b), 7)
        brute_force_expected = (cumulative_cost_at_target(order_a) + cumulative_cost_at_target(order_b)) / 2
        self.assertEqual(brute_force_expected, 5.5)
        self.assertEqual(result.expected_cost, brute_force_expected)


class LinearChainTests(unittest.TestCase):
    """Row #1: no branching means min == expected == max."""

    def test_unbranched_chain_has_equal_min_expected_max(self):
        nodes = [_node("seed", 2), _node("mid", 3), _node("target", 4)]
        edges = [_edge("seed", "mid"), _edge("mid", "target")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("chain", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 9)
        self.assertEqual(result.min_cost, result.expected_cost)
        self.assertEqual(result.expected_cost, result.max_cost)
        self.assertEqual(result.min_path_node_ids, ("seed", "mid", "target"))
        self.assertEqual(result.ball_node_ids, ("mid", "seed", "target"))


class MultiSourceSeedTests(unittest.TestCase):
    """Row #3: two disjoint seeds, the cheaper path wins."""

    def test_multi_source_dijkstra_prefers_the_cheaper_source(self):
        nodes = [_node("seedA", 1), _node("seedB", 100), _node("mid", 1), _node("target", 1)]
        edges = [_edge("seedA", "mid"), _edge("mid", "target"), _edge("seedB", "target")]
        metrics = _metrics(nodes, edges)
        task = TaskDefinition(
            id="multi-seed", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "seedA"), SeedQuery(SeedKind.SYMBOL, "seedB")),
            target_node_ids=frozenset({"target"}),
        )
        result = _compute_one(task, nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.start_frontier_node_ids, ("seedA", "seedB"))
        self.assertEqual(result.min_cost, 3)
        self.assertEqual(result.min_path_node_ids, ("seedA", "mid", "target"))

    def test_the_cheaper_overall_path_can_originate_from_the_costlier_seed(self):
        # seedA's own node cost (10) is higher than seedB's (1), but seedA connects
        # directly to target while seedB only reaches it through an expensive detour,
        # so the cheaper *overall* path must win even though picking "the seed with
        # the lowest own cost" (a single-source shortcut) would pick seedB and lose.
        nodes = [_node("seedA", 10), _node("seedB", 1), _node("detour", 50), _node("target", 1)]
        edges = [_edge("seedA", "target"), _edge("seedB", "detour"), _edge("detour", "target")]
        metrics = _metrics(nodes, edges)
        task = TaskDefinition(
            id="costlier-seed-wins", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "seedA"), SeedQuery(SeedKind.SYMBOL, "seedB")),
            target_node_ids=frozenset({"target"}),
        )
        result = _compute_one(task, nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 11)
        self.assertEqual(result.min_path_node_ids, ("seedA", "target"))

    def test_unresolved_seed_count_reflects_a_genuine_mix_on_an_ok_result(self):
        nodes = [_node("seedA", 1), _node("target", 1)]
        edges = [_edge("seedA", "target")]
        metrics = _metrics(nodes, edges)
        task = TaskDefinition(
            id="mixed-seeds", type=TaskType.BUG_FIX,
            seeds=(
                SeedQuery(SeedKind.SYMBOL, "seedA"),
                SeedQuery(SeedKind.SYMBOL, "nonexistent-1"),
                SeedQuery(SeedKind.SYMBOL, "nonexistent-2"),
            ),
            target_node_ids=frozenset({"target"}),
        )
        result = _compute_one(task, nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.start_frontier_node_ids, ("seedA",))
        self.assertEqual(result.unresolved_seed_count, 2)


class TiedSeedMatchTests(unittest.TestCase):
    """Row #4: one seed with multiple best-tier ties in retrieve_scored."""

    def test_tied_best_tier_matches_are_all_included_in_the_start_frontier(self):
        nodes = [
            _node("seed1", 1, label="seed"),
            _node("seed2", 5, label="seed"),
            _node("target", 1),
        ]
        edges = [_edge("seed2", "target")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("tied", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.start_frontier_node_ids, ("seed1", "seed2"))
        # only seed2 can reach target, so this value proves seed1's tie was really placed in S
        self.assertEqual(result.min_cost, 6)
        self.assertEqual(result.min_path_node_ids, ("seed2", "target"))


class EmptyStartFrontierTests(unittest.TestCase):
    """Row #5: every seed resolves to nothing."""

    def test_all_unresolved_seeds_yield_empty_start_frontier(self):
        nodes = [_node("target", 1)]
        metrics = _metrics(nodes, [])
        task = TaskDefinition(
            id="empty", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "nonexistent1"), SeedQuery(SeedKind.SYMBOL, "nonexistent2")),
            target_node_ids=frozenset({"target"}),
        )
        result = _compute_one(task, nodes, [], metrics)

        self.assertEqual(result.status, "empty_start_frontier")
        self.assertEqual(result.start_frontier_node_ids, ())
        self.assertEqual(result.unresolved_seed_count, 2)
        self.assertIsNone(result.min_cost)
        self.assertIsNone(result.expected_cost)
        self.assertIsNone(result.max_cost)
        self.assertEqual(result.min_path_node_ids, ())
        self.assertEqual(result.ball_node_ids, ())


class UnreachableTargetTests(unittest.TestCase):
    """Row #6 (disconnected component) and row #7 (target id absent from nodes)."""

    def test_target_in_a_disconnected_component_is_unreachable(self):
        nodes = [_node("seed", 1), _node("island", 2), _node("target", 1)]
        edges = [_edge("island", "target")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("unreachable", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "target_unreachable")
        self.assertEqual(result.start_frontier_node_ids, ("seed",))
        self.assertIsNone(result.min_cost)
        self.assertIsNone(result.expected_cost)
        self.assertIsNone(result.max_cost)
        self.assertEqual(result.min_path_node_ids, ())
        self.assertEqual(result.ball_node_ids, ())

    def test_target_id_absent_from_nodes_folds_into_the_same_status(self):
        nodes = [_node("seed", 1)]
        metrics = _metrics(nodes, [])
        result = _compute_one(_task("missing-target", "seed", {"ghost"}), nodes, [], metrics)

        self.assertEqual(result.status, "target_unreachable")
        self.assertEqual(result.start_frontier_node_ids, ("seed",))
        self.assertIsNone(result.min_cost)
        self.assertIsNone(result.expected_cost)
        self.assertIsNone(result.max_cost)
        self.assertEqual(result.min_path_node_ids, ())
        self.assertEqual(result.ball_node_ids, ())


class TargetInSeedFrontierTests(unittest.TestCase):
    """Row #8: target itself is already in S."""

    def test_target_as_its_own_seed_has_a_trivial_path(self):
        nodes = [_node("target", 3), _node("other", 1)]
        edges = [_edge("target", "other")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("target-is-seed", "target", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 3)
        self.assertEqual(result.min_path_node_ids, ("target",))
        self.assertEqual(result.ball_node_ids, ("target",))


class MultiTargetTests(unittest.TestCase):

    def test_zero_targets_has_an_explicit_status(self):
        nodes = [_node("seed", 1)]
        metrics = _metrics(nodes, [])
        task = TaskDefinition(
            id="zero", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "seed"),), target_node_ids=frozenset(),
        )
        result = _compute_one(task, nodes, [], metrics)

        self.assertEqual(result.status, "empty_target_set")
        self.assertIsNone(result.target_node_id)
        self.assertIsNone(result.unresolved_seed_count)
        self.assertIsNone(result.min_cost)
        self.assertIsNone(result.expected_cost)
        self.assertIsNone(result.max_cost)
        self.assertEqual(result.start_frontier_node_ids, ())
        self.assertEqual(result.min_path_node_ids, ())
        self.assertEqual(result.ball_node_ids, ())

    def test_multiple_targets_charge_shared_nodes_once_and_sibling_tasks_still_run(self):
        nodes = [_node("seed", 1), _node("a", 2), _node("b", 3), _node("target", 1)]
        edges = [_edge("seed", "a"), _edge("a", "target"), _edge("seed", "b")]
        metrics = _metrics(nodes, edges)
        multi_task = TaskDefinition(
            id="multi", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "seed"),), target_node_ids=frozenset({"a", "target"}),
        )
        ok_task = _task("single", "seed", {"target"})

        report = ExplorationCostAnalyzer().compute([multi_task, ok_task], nodes, edges, metrics)

        self.assertEqual(report.results[0].status, "ok")
        self.assertEqual(report.results[0].min_cost, 4)
        self.assertEqual(report.results[0].expected_cost, 5.5)
        self.assertEqual(report.results[0].max_cost, 7)
        self.assertEqual(report.results[0].target_node_ids, ("a", "target"))
        self.assertEqual(dict(report.results[0].target_min_path_node_ids), {
            "a": ("seed", "a"), "target": ("seed", "a", "target"),
        })
        for _name, minimum, expected, maximum in report.results[0].confidence_costs:
            self.assertLessEqual(minimum, expected)
            self.assertLessEqual(expected, maximum)
        self.assertEqual(report.results[1].status, "ok")
        self.assertEqual(report.results[1].min_cost, 4)

    def test_two_targets_in_the_final_shell_use_full_recall_and_its_exact_coefficient(self):
        nodes = [_node("seed", 1), _node("left", 2), _node("right", 2), _node("decoy", 2)]
        edges = [_edge("seed", "left"), _edge("seed", "right"), _edge("seed", "decoy")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("two-final-targets", "seed", {"left", "right"}), nodes, edges, metrics)

        self.assertEqual((result.min_cost, result.max_cost), (5, 7))
        self.assertEqual(result.expected_cost, 1 + 2 + 2 + (2 * 2 / 3))
        self.assertLess(result.min_cost, 3 + 3)

    def test_any_unreachable_target_makes_full_recall_unreachable(self):
        nodes = [_node("seed", 1), _node("reachable", 1), _node("island", 1)]
        metrics = _metrics(nodes, [_edge("seed", "reachable")])
        result = _compute_one(_task("partial", "seed", {"reachable", "island"}), nodes, [_edge("seed", "reachable")], metrics)

        self.assertEqual(result.status, "target_unreachable")
        self.assertEqual(result.unreachable_target_node_ids, ("island",))
        self.assertEqual(dict(result.target_min_path_node_ids), {"reachable": ("seed", "reachable")})

    def test_exact_minimum_can_prefer_a_shared_route_over_each_target_shortest_path(self):
        nodes = [
            _node("seed", 1), _node("a", 2), _node("b", 2), _node("hub", 3),
            _node("left", 1), _node("right", 1),
        ]
        edges = [
            _edge("seed", "a"), _edge("a", "left"), _edge("seed", "b"), _edge("b", "right"),
            _edge("seed", "hub"), _edge("hub", "left"), _edge("hub", "right"),
        ]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("shared-steiner", "seed", {"left", "right"}), nodes, edges, metrics)

        self.assertEqual(result.min_cost, 6)
        self.assertEqual(dict(result.target_min_path_node_ids), {
            "left": ("seed", "a", "left"), "right": ("seed", "b", "right"),
        })

    def test_multi_source_minimum_uses_one_start_node_for_the_complete_tree(self):
        nodes = [_node("seed-a", 1), _node("seed-b", 1), _node("hub", 4), _node("left", 1), _node("right", 1)]
        edges = [
            _edge("seed-a", "left"), _edge("seed-a", "hub"), _edge("hub", "right"),
            _edge("seed-b", "right"), _edge("seed-b", "hub"), _edge("hub", "left"),
        ]
        metrics = _metrics(nodes, edges)
        task = TaskDefinition(
            id="one-source", type=TaskType.BUG_FIX,
            seeds=(SeedQuery(SeedKind.SYMBOL, "seed-a"), SeedQuery(SeedKind.SYMBOL, "seed-b")),
            target_node_ids=frozenset({"left", "right"}),
        )
        result = _compute_one(task, nodes, edges, metrics)

        self.assertEqual(result.min_cost, 7)


class AdjacencyConstructionTests(unittest.TestCase):
    """Rows #11 (self-loop skipped) and #12 (duplicate edges dedup naturally)."""

    def test_self_loop_edges_are_skipped(self):
        adjacency = _build_adjacency([_edge("a", "a")], {"a"})
        self.assertEqual(adjacency, {"a": set()})

    def test_duplicate_edges_between_the_same_pair_dedupe(self):
        edges = [_edge("a", "b"), _edge("a", "b"), _edge("b", "a")]
        adjacency = _build_adjacency(edges, {"a", "b"})
        self.assertEqual(adjacency, {"a": {"b"}, "b": {"a"}})

    def test_self_loop_and_duplicate_edges_do_not_change_compute_end_to_end(self):
        nodes = [_node("seed", 1), _node("target", 2)]
        edges = [
            _edge("seed", "seed"),  # self-loop: must not let "seed" relax itself for free
            _edge("seed", "target"), _edge("seed", "target"), _edge("target", "seed"),
        ]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("self-loop-and-dupes", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 3)

    def test_edges_are_traversable_in_reverse_for_every_relation_kind(self):
        relation_kinds = [value for name, value in vars(RelationKind).items() if name.isupper()]
        for relation in relation_kinds:
            nodes = [_node("seed", 1), _node("target", 2)]
            edges = [_edge("target", "seed", relation)]
            metrics = _metrics(nodes, edges)
            result = _compute_one(_task(f"reverse-{relation}", "seed", {"target"}), nodes, edges, metrics)

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.min_cost, 3)
        self.assertEqual(result.min_path_node_ids, ("seed", "target"))
        self.assertEqual(result.ball_node_ids, ("seed", "target"))


class DeterministicTieBreakTests(unittest.TestCase):
    """Row #13: two full equal-cost paths through different intermediates stay deterministic."""

    def test_equal_cost_paths_repeatedly_pick_the_lexicographically_smaller_predecessor(self):
        nodes = [_node("seed", 1), _node("zebra", 3), _node("apple", 3), _node("target", 1)]
        edges = [
            _edge("seed", "zebra"), _edge("seed", "apple"),
            _edge("zebra", "target"), _edge("apple", "target"),
        ]
        metrics = _metrics(nodes, edges)
        task = _task("tie-break", "seed", {"target"})

        for _ in range(5):
            result = _compute_one(task, nodes, edges, metrics)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.min_path_node_ids, ("seed", "apple", "target"))
            self.assertEqual(result.ball_node_ids, ("apple", "seed", "target", "zebra"))

    def test_lexicographically_smallest_predecessor_wins_even_with_asymmetric_discovery_depth(self):
        # "mango" and "zebra" reach target's exact tied distance in a single hop from seed,
        # so they are both discovered (pushed) immediately. "apple" reaches the same tied
        # distance only after two extra relaxation steps through "relay1"/"relay2", so it is
        # discovered later than "mango"/"zebra". This exercises three predecessors of target
        # arriving at genuinely different times while still tying on distance, not just two
        # predecessors pushed in the same round -- any implementation that picks "whichever
        # predecessor happens to relax target first" instead of the smallest id would report
        # "mango" or "zebra" here instead of "apple".
        nodes = [
            _node("seed", 1),
            _node("mango", 5), _node("zebra", 5),
            _node("relay1", 2), _node("relay2", 2), _node("apple", 1),
            _node("target", 1),
        ]
        edges = [
            _edge("seed", "mango"), _edge("seed", "zebra"),
            _edge("seed", "relay1"), _edge("relay1", "relay2"), _edge("relay2", "apple"),
            _edge("mango", "target"), _edge("zebra", "target"), _edge("apple", "target"),
        ]
        metrics = _metrics(nodes, edges)
        task = _task("three-way-tie-break", "seed", {"target"})

        for _ in range(5):
            result = _compute_one(task, nodes, edges, metrics)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.min_path_node_ids, ("seed", "relay1", "relay2", "apple", "target"))


class NonStructuralRelationRegressionTests(unittest.TestCase):
    """Row #14: adjacency must include every relation kind, not just the structural ones."""

    def test_target_reachable_only_via_a_non_structural_relation_is_still_found(self):
        self.assertNotIn(RelationKind.CONTAINS, _STRUCTURAL_RELATIONS)
        nodes = [_node("seed", 1), _node("target", 2)]
        edges = [_edge("seed", "target", RelationKind.CONTAINS)]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("non-structural", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 3)


class VendoredNodeOnPathTests(unittest.TestCase):
    """Row #15: a vendored (cost-multiplier-0) node on the path contributes 0 cost but stays in the path."""

    def test_vendored_node_contributes_zero_cost_but_remains_in_the_path(self):
        nodes = [_node("seed", 1), _node("vendor", 50, flags=["vendored"]), _node("target", 2)]
        edges = [_edge("seed", "vendor"), _edge("vendor", "target")]
        metrics = _metrics(nodes, edges)
        self.assertEqual(metrics["vendor"]["effective_token_cost"], 0.0)

        result = _compute_one(_task("vendored-path", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.min_cost, 3)
        self.assertEqual(result.min_path_node_ids, ("seed", "vendor", "target"))


class EmptyInputTests(unittest.TestCase):
    """Row #16 (empty task list) and row #17 (empty graph)."""

    def test_empty_task_list_returns_an_empty_report(self):
        nodes = [_node("a", 1)]
        metrics = _metrics(nodes, [])
        report = ExplorationCostAnalyzer().compute([], nodes, [], metrics)
        self.assertEqual(report, TaskExplorationCostReport(results=()))

    def test_empty_graph_yields_empty_start_frontier_per_task(self):
        task = _task("no-graph", "seed", {"target"})
        report = ExplorationCostAnalyzer().compute([task], [], [], {})
        result = report.results[0]

        self.assertEqual(result.status, "empty_start_frontier")
        self.assertEqual(result.start_frontier_node_ids, ())
        self.assertEqual(result.unresolved_seed_count, 1)
        self.assertIsNone(result.min_cost)
        self.assertIsNone(result.expected_cost)
        self.assertIsNone(result.max_cost)
        self.assertEqual(result.min_path_node_ids, ())
        self.assertEqual(result.ball_node_ids, ())


class ReportShapeTests(unittest.TestCase):
    def test_to_dict_serializes_to_json_with_the_contract_fields(self):
        nodes = [_node("seed", 1), _node("target", 1)]
        edges = [_edge("seed", "target")]
        metrics = _metrics(nodes, edges)
        report = ExplorationCostAnalyzer().compute([_task("shape", "seed", {"target"})], nodes, edges, metrics)

        payload = exploration_cost_to_dict(report)
        restored = json.loads(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            sorted(restored["results"][0]),
            sorted([
                "ball_node_ids", "expected_cost", "max_cost", "min_cost", "min_path_node_ids",
                "start_frontier_node_ids", "status", "target_node_id", "task_id", "task_type",
                "unresolved_seed_count", "target_node_ids", "unreachable_target_node_ids",
                "target_min_path_node_ids", "confidence_costs",
            ]),
        )
        self.assertEqual(restored["results"][0]["target_node_ids"], ["target"])
        self.assertEqual(restored["results"][0]["target_min_path_node_ids"], {"target": ["seed", "target"]})
        self.assertEqual(restored["results"][0]["unreachable_target_node_ids"], [])
        self.assertEqual(restored["results"][0]["confidence_costs"]["baseline"], {
            "min_cost": 2.0, "expected_cost": 2.0, "max_cost": 2.0,
        })

    def test_to_dict_preserves_multi_target_and_unreachable_evidence(self):
        nodes = [_node("seed", 1), _node("reachable", 1), _node("island", 1)]
        edges = [_edge("seed", "reachable")]
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("serialized-partial", "seed", {"reachable", "island"}), nodes, edges, metrics)

        payload = result.to_dict()
        self.assertEqual(payload["target_node_ids"], ["island", "reachable"])
        self.assertEqual(payload["unreachable_target_node_ids"], ["island"])
        self.assertEqual(payload["target_min_path_node_ids"], {"reachable": ["seed", "reachable"]})
        self.assertEqual(payload["confidence_costs"]["optimistic"], {
            "min_cost": None, "expected_cost": None, "max_cost": None,
        })
        self.assertEqual(payload["confidence_costs"]["pessimistic"], {
            "min_cost": None, "expected_cost": None, "max_cost": None,
        })


class ConfidenceScenarioTests(unittest.TestCase):
    def test_confidence_scenarios_bound_costs_and_keep_baseline_as_default(self):
        nodes = [_node("seed", 1), _node("mid", 1), _node("target", 1)]
        edges = [
            _edge("seed", "target", RelationKind.CALLS),
            _edge("seed", "mid", RelationKind.CALLS),
            _edge("mid", "target", RelationKind.CALLS),
        ]
        edges[0].confidence = "dynamic_required"
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("confidence", "seed", {"target"}), nodes, edges, metrics)

        self.assertEqual((result.min_cost, result.expected_cost, result.max_cost), (3, 3, 3))
        scenarios = dict((name, (minimum, expected, maximum)) for name, minimum, expected, maximum in result.confidence_costs)
        self.assertEqual(scenarios["optimistic"], (2, 2.5, 3))
        self.assertEqual(scenarios["baseline"], (3, 3, 3))
        self.assertEqual(scenarios["pessimistic"], (3, 3, 3))
        for minimum, expected, maximum in scenarios.values():
            self.assertLessEqual(minimum, expected)
            self.assertLessEqual(expected, maximum)

    def test_static_inferred_edges_are_available_to_baseline_but_not_pessimistic(self):
        nodes = [_node("seed", 1), _node("target", 1)]
        edges = [_edge("seed", "target")]
        edges[0].confidence = "static_inferred"
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("inferred", "seed", {"target"}), nodes, edges, metrics)

        scenarios = dict((name, (minimum, expected, maximum)) for name, minimum, expected, maximum in result.confidence_costs)
        self.assertEqual(scenarios["optimistic"], (2, 2, 2))
        self.assertEqual(scenarios["baseline"], (2, 2, 2))
        self.assertEqual(scenarios["pessimistic"], (None, None, None))

    def test_top_level_result_uses_unreachable_baseline_not_reachable_optimistic_costs(self):
        nodes = [_node("seed", 1), _node("target", 1)]
        edges = [_edge("seed", "target")]
        edges[0].confidence = "dynamic_required"
        metrics = _metrics(nodes, edges)
        result = _compute_one(_task("dynamic-only", "seed", {"target"}), nodes, edges, metrics)

        scenarios = dict((name, (minimum, expected, maximum)) for name, minimum, expected, maximum in result.confidence_costs)
        self.assertEqual(result.status, "target_unreachable")
        self.assertEqual((result.min_cost, result.expected_cost, result.max_cost), (None, None, None))
        self.assertEqual(scenarios["optimistic"], (2, 2, 2))
        self.assertEqual(scenarios["baseline"], (None, None, None))

    def test_collection_rows_expose_all_columns_with_status_specific_blanks(self):
        nodes = [_node("seed", 1, label="seed"), _node("target", 1)]
        edges = [_edge("seed", "target")]
        metrics = _metrics(nodes, edges)
        ok_task = _task("ok-task", "seed", {"target"})
        unsupported_task = TaskDefinition(id="unsupported", type=TaskType.BUG_FIX, seeds=(), target_node_ids=frozenset())

        report = ExplorationCostAnalyzer().compute([ok_task, unsupported_task], nodes, edges, metrics)
        collection = exploration_cost_collection(report, nodes)

        self.assertEqual(collection.key, "exploration_cost")
        self.assertEqual(collection.view, "table")
        for row in collection.rows:
            for column in collection.columns:
                self.assertIn(column.key, row)

        ok_row, unsupported_row = collection.rows
        self.assertEqual(ok_row["min_cost"], "2")
        self.assertEqual(ok_row["min_path_length"], 2)
        self.assertEqual(ok_row["cost_spread"], "0")
        self.assertEqual(unsupported_row["target"], "")
        self.assertEqual(unsupported_row["min_cost"], "")
        self.assertEqual(unsupported_row["min_path_length"], "")
        self.assertEqual(unsupported_row["cost_spread"], "")


PROJECT_SOURCE = {
    "app/__init__.py": "",
    "app/service.py": "def helper():\n    return 1\n\n\ndef run():\n    return helper()\n",
}


class CliContractTests(unittest.TestCase):
    """CLI integration: --task-set / --exploration-cost wiring (contract §5)."""

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
        self.task_set_path.write_text(json.dumps([{
            "id": "reach-run",
            "type": "bug_fix",
            "seeds": [{"kind": "symbol", "value": "helper"}],
            "target_node_ids": ["py:app.service#run"],
        }]), encoding="utf-8")

    def _run(self, *extra):
        argv = [
            "code-analyzer", str(self.project),
            "--language", "python",
            "-o", str(self.root / "report.html"),
            *extra,
        ]
        with patch.object(sys, "argv", argv):
            main()

    def test_exploration_cost_flag_writes_report_stats_and_collection(self):
        output = self.root / "exploration-cost.json"
        self._run(
            "--json", "--task-set", str(self.task_set_path),
            "--exploration-cost", "--exploration-cost-output", str(output),
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["task_id"], "reach-run")
        self.assertEqual(payload["results"][0]["status"], "ok")

        exported = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertIn("exploration_cost", exported["stats"])
        self.assertIn("exploration_cost", exported["collections"])
        self.assertEqual(exported["collections"]["exploration_cost"]["view"], "table")

    def test_task_set_alone_is_a_no_op_that_still_succeeds(self):
        # Contract §5: --task-set without --exploration-cost is a forward-compatible no-op
        # for a future consumer (M2), not a rejected combination -- it must still validate
        # and load the file, but must not compute or export exploration-cost stats.
        self._run("--json", "--task-set", str(self.task_set_path))

        self.assertTrue((self.root / "report.html").exists())
        exported = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertNotIn("exploration_cost", exported["stats"])
        self.assertNotIn("exploration_cost", exported["collections"])

    def test_exploration_cost_without_task_set_exits_via_parser_error(self):
        argv = ["code-analyzer", str(self.project), "--language", "python", "--exploration-cost"]
        stderr = io.StringIO()
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as raised:
                with contextlib.redirect_stderr(stderr):
                    main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--exploration-cost requires --task-set", stderr.getvalue())

    def test_malformed_task_set_fails_fast_before_analysis_runs(self):
        bad_path = self.root / "bad-tasks.json"
        bad_path.write_text("not json", encoding="utf-8")
        argv = [
            "code-analyzer", str(self.project), "--language", "python",
            "--task-set", str(bad_path),
        ]
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit):
                main()
        self.assertFalse((self.root / "report.html").exists())

    def test_nonexistent_task_set_fails_fast_before_analysis_runs(self):
        argv = [
            "code-analyzer", str(self.project), "--language", "python",
            "--task-set", str(self.root / "missing.json"),
        ]
        with patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit):
                main()
        self.assertFalse((self.root / "report.html").exists())


if __name__ == "__main__":
    unittest.main()
