import unittest

from language_analyzers.core import flags as flag_names
from language_analyzers.core.annotate import mark_edges
from language_analyzers.core.cost import cost_for_span, cost_for_text, estimate_tokens
from language_analyzers.core.graph_models import (
    Confidence,
    GraphEdge,
    GraphNode,
    Resolution,
    SourceSpan,
)

SOURCE = "def first():\n    return 1\n\ndef second():\n    return first()\n"


class TestGraphModels(unittest.TestCase):
    def test_positional_construction_matches_previous_field_order(self):
        node = GraphNode("id", "label", "group", "category", "title", "ellipse", 30, None, {"a": 1})

        self.assertEqual(node.id, "id")
        self.assertEqual(node.shape, "ellipse")
        self.assertEqual(node.size, 30)
        self.assertEqual(node.metadata, {"a": 1})
        self.assertIsNone(node.span)
        self.assertEqual(node.flags, [])

    def test_span_mirrors_into_conventional_metadata_keys(self):
        node = GraphNode("id", "label", "g", "c", span=SourceSpan("app/main.py", 4, 9))

        self.assertEqual(node.metadata["file_path"], "app/main.py")
        self.assertEqual(node.metadata["line_number"], 4)
        self.assertEqual(node.metadata["end_line_number"], 9)

    def test_explicit_metadata_wins_over_span_mirror(self):
        node = GraphNode(
            "id", "label", "g", "c",
            metadata={"file_path": "explicit.py"},
            span=SourceSpan("app/main.py", 4, 9),
        )

        self.assertEqual(node.metadata["file_path"], "explicit.py")
        self.assertEqual(node.metadata["line_number"], 4)

    def test_node_without_span_leaves_metadata_untouched(self):
        node = GraphNode("id", "label", "g", "c")

        self.assertEqual(node.metadata, {})

    def test_flags_are_not_shared_between_instances(self):
        first = GraphNode("a", "a", "g", "c")
        second = GraphNode("b", "b", "g", "c")
        first.flags.append(flag_names.TEST)

        self.assertEqual(second.flags, [])

    def test_edge_defaults_are_the_most_certain_values(self):
        edge = GraphEdge("a", "b", "CALLS")

        self.assertEqual(edge.confidence, Confidence.STATIC_CERTAIN)
        self.assertEqual(edge.resolution, Resolution.EXACT)
        self.assertEqual(edge.weight, 1.0)
        self.assertEqual(edge.candidates, [])
        self.assertIsNone(edge.evidence)

    def test_confidence_and_resolution_stringify_to_their_wire_values(self):
        self.assertEqual(str(Confidence.DYNAMIC_REQUIRED), "dynamic_required")
        self.assertEqual(str(Resolution.AMBIGUOUS), "ambiguous")
        self.assertEqual(Confidence.STATIC_INFERRED, "static_inferred")


class TestCost(unittest.TestCase):
    def test_estimate_tokens_rounds_up_and_never_returns_zero(self):
        # "abcde" is 5 chars -> ceil(5/4) = 2.
        self.assertEqual(estimate_tokens("abcde"), 2)
        self.assertEqual(estimate_tokens(""), 1)

    def test_cost_for_span_uses_the_exact_line_range(self):
        # Lines 1-2 are "def first():\n    return 1" -> 25 chars, ceil(25/4) = 7.
        cost = cost_for_span(SOURCE, SourceSpan("sample.py", 1, 2))

        self.assertEqual(cost.char_count, 25)
        self.assertEqual(cost.token_estimate, 7)
        self.assertEqual(cost.line_count, 2)

    def test_cost_for_span_of_a_single_line(self):
        # Line 5 alone is "    return first()" -> 18 chars, ceil(18/4) = 5.
        cost = cost_for_span(SOURCE, SourceSpan("sample.py", 5, 5))

        self.assertEqual(cost.char_count, 18)
        self.assertEqual(cost.token_estimate, 5)
        self.assertEqual(cost.line_count, 1)

    def test_cost_for_empty_text_has_no_lines(self):
        cost = cost_for_text("")

        self.assertEqual(cost.line_count, 0)
        self.assertEqual(cost.char_count, 0)
        self.assertEqual(cost.token_estimate, 1)


class TestPathFlags(unittest.TestCase):
    def test_generated_paths(self):
        for path in (
            "app/db/migrations/versions/abc_main_tables.py",
            "alembic/versions/9c0a_add_max_length.py",
            "proto/service_pb2.py",
            "lib/model.g.dart",
        ):
            self.assertIn(flag_names.GENERATED, flag_names.path_flags(path), path)

    def test_versions_directory_alone_is_not_generated(self):
        self.assertEqual(flag_names.path_flags("app/api/versions/v1.py"), [])

    def test_vendored_paths(self):
        self.assertIn(flag_names.VENDORED, flag_names.path_flags("third_party/lib/a.py"))
        self.assertIn(flag_names.VENDORED, flag_names.path_flags("web/node_modules/pkg/index.js"))

    def test_test_paths(self):
        for path in ("tests/test_users.py", "app/user_test.py", "src/button.spec.ts", "src/button.test.tsx"):
            self.assertIn(flag_names.TEST, flag_names.path_flags(path), path)

    def test_production_module_carries_no_flags(self):
        self.assertEqual(flag_names.path_flags("app/models/user.py"), [])

    def test_latest_test_word_inside_a_filename_is_not_a_test(self):
        self.assertEqual(flag_names.path_flags("app/contest.py"), [])


class TestMarkEdgesFrameworkRules(unittest.TestCase):
    def test_declared_relation_gets_namespaced_rule_and_specificity(self):
        edge = GraphEdge("a", "b", "USES_VIEWMODEL")

        mark_edges([edge], rule_namespace="android",
                   rule_specificity={"USES_VIEWMODEL": "unique"})

        self.assertEqual(
            edge.metadata["framework_rule"],
            {"id": "android.uses_viewmodel", "specificity": "unique"},
        )

    def test_undeclared_relation_gets_no_rule(self):
        edge = GraphEdge("a", "b", "HOSTS")

        mark_edges([edge], rule_namespace="android",
                   rule_specificity={"USES_VIEWMODEL": "unique"})

        self.assertNotIn("framework_rule", edge.metadata)

    def test_namespace_without_specificity_map_declares_nothing(self):
        edge = GraphEdge("a", "b", "ROUTES")

        mark_edges([edge], rule_namespace="android")

        self.assertNotIn("framework_rule", edge.metadata)

    def test_existing_rule_is_not_overwritten(self):
        existing = {"id": "android.implemented_by", "specificity": "narrowing"}
        edge = GraphEdge("a", "b", "ROUTES", metadata={"framework_rule": existing})

        mark_edges([edge], rule_namespace="android",
                   rule_specificity={"ROUTES": "unique"})

        self.assertEqual(edge.metadata["framework_rule"], existing)


if __name__ == "__main__":
    unittest.main()
