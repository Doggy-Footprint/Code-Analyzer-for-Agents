import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import framework_analyzers.android.graph as android_graph
from framework_analyzers.android.graph import AndroidArchitectureGraphBuilder
from framework_analyzers.android.models import (
    AndroidProjectArchitecture,
    ComposableInfo,
    DiBindingInfo,
)
from language_analyzers.core.graph_models import GraphNode, NodeKind, RelationKind, Resolution


class AndroidGraphContractTests(unittest.TestCase):
    def test_removed_cost_constructor_argument_is_rejected(self):
        with self.assertRaises(TypeError):
            AndroidArchitectureGraphBuilder(unresolved_inject_field_cost=4.0)

    def test_only_resolved_inject_field_gets_an_implementation_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "MainActivity.kt"
            source.write_text("class MainActivity\n", encoding="utf-8")
            bindings = [
                self._binding("resolved", source, "Owner", "existing"),
                self._binding("missing-field", source, "Owner", "absent"),
                self._binding("missing-owner", source, "MissingOwner", "absent"),
            ]
            architecture = AndroidProjectArchitecture(
                project_name="sample",
                project_path=str(root),
                di_bindings=bindings,
            )
            language_nodes = [
                GraphNode(
                    id="kotlin-owner",
                    label="Owner",
                    group=NodeKind.CLASS,
                    category=NodeKind.CLASS,
                    provenance="kotlin-core",
                    metadata={"file_path": str(source), "qualname": "Owner"},
                ),
                GraphNode(
                    id="kotlin-field",
                    label="existing",
                    group=NodeKind.FIELD,
                    category=NodeKind.FIELD,
                    provenance="kotlin-core",
                    metadata={"file_path": str(source), "qualname": "Owner.existing"},
                ),
            ]

            with patch("framework_analyzers.android.graph.KotlinAnalyzer") as analyzer:
                analyzer.return_value.build.return_value = (language_nodes, [])
                result = AndroidArchitectureGraphBuilder().build_graph(architecture)

        implementation_edges = [edge for edge in result.edges if edge.relation == RelationKind.IMPLEMENTED_BY]
        self.assertEqual(len(implementation_edges), 1)
        self.assertEqual(
            (implementation_edges[0].from_id, implementation_edges[0].to_id),
            ("resolved", "kotlin-field"),
        )
        unresolved_ids = {"missing-field", "missing-owner"}
        self.assertFalse(any(
            edge.relation == RelationKind.IMPLEMENTED_BY
            and ({edge.from_id, edge.to_id} & unresolved_ids)
            for edge in result.edges
        ))
        self.assertNotIn("exploration_warnings", {item.key for item in result.report_collections})
        self.assertFalse(hasattr(result, "evaluation_relations"))
        side_channel_keys = {
            "evaluation_relations",
            "exploration_warnings",
            "unresolved_inject_field_cost",
        }
        for key in side_channel_keys:
            self.assertFalse(hasattr(result, key))
        self.assertTrue(side_channel_keys.isdisjoint(result.stats))
        for node in result.nodes:
            self.assertTrue(side_channel_keys.isdisjoint(node.metadata))
        for edge in result.edges:
            self.assertTrue(side_channel_keys.isdisjoint(edge.metadata))
            self.assertEqual(edge.weight, 1.0)

    @staticmethod
    def _binding(binding_id, source, owner, field):
        return DiBindingInfo(
            id=binding_id,
            name=field,
            kind="inject_field",
            module="",
            file_path=str(source),
            line_number=1,
            end_line_number=1,
            injected_type="InjectedType",
            owner_class_name=owner,
            field_name=field,
        )


class AndroidFrameworkRuleDeclarationTests(unittest.TestCase):
    def test_built_framework_edges_carry_their_declared_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "MainActivity.kt"
            source.write_text("class MainActivity\n", encoding="utf-8")
            architecture = AndroidProjectArchitecture(
                project_name="sample",
                project_path=str(root),
                di_bindings=[AndroidGraphContractTests._binding("resolved", source, "Owner", "existing")],
            )
            language_nodes = [
                GraphNode(
                    id="kotlin-owner", label="Owner", group=NodeKind.CLASS, category=NodeKind.CLASS,
                    provenance="kotlin-core",
                    metadata={"file_path": str(source), "qualname": "Owner"},
                ),
                GraphNode(
                    id="kotlin-field", label="existing", group=NodeKind.FIELD, category=NodeKind.FIELD,
                    provenance="kotlin-core",
                    metadata={"file_path": str(source), "qualname": "Owner.existing"},
                ),
            ]

            with patch("framework_analyzers.android.graph.KotlinAnalyzer") as analyzer:
                analyzer.return_value.build.return_value = (language_nodes, [])
                result = AndroidArchitectureGraphBuilder().build_graph(architecture)

        implementation = next(
            edge for edge in result.edges if edge.relation == RelationKind.IMPLEMENTED_BY
        )
        self.assertEqual(
            implementation.metadata["framework_rule"],
            {"id": "android.implemented_by", "specificity": "unique"},
        )


    def test_every_emitted_framework_relation_declares_a_rule(self):
        source = Path(android_graph.__file__).read_text(encoding="utf-8")
        emitted = {
            keyword.value.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "relation"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        }

        undeclared = emitted - set(AndroidArchitectureGraphBuilder.FRAMEWORK_RULE_SPECIFICITY)

        self.assertEqual(undeclared, set())

    def test_declared_specificities_are_within_the_contract(self):
        self.assertEqual(
            set(AndroidArchitectureGraphBuilder.FRAMEWORK_RULE_SPECIFICITY.values()) - {"unique", "narrowing"},
            set(),
        )


class AndroidNameCollisionTests(unittest.TestCase):
    def build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "TopicScreen.kt"
            source.write_text("fun a() {}\n", encoding="utf-8")

            def composable(suffix, line, calls=()):
                return ComposableInfo(
                    id=f"composable_{suffix}", name="TopicScreen" if suffix.startswith("overload") else suffix,
                    module="feature", file_path=str(source), line_number=line, end_line_number=line,
                    calls=list(calls),
                )

            architecture = AndroidProjectArchitecture(
                project_name="sample", project_path=str(root),
                composables=[
                    composable("overload_a", 74, ["TopicScreen"]),
                    composable("overload_b", 99),
                    composable("Caller", 300, ["TopicScreen"]),
                ],
            )
            with patch("framework_analyzers.android.graph.KotlinAnalyzer") as analyzer:
                analyzer.return_value.build.return_value = ([], [])
                result = AndroidArchitectureGraphBuilder(include_language_graph=False).build_graph(architecture)
        return [edge for edge in result.edges if edge.relation == "CALLS"]

    def test_collision_records_the_other_declaration_as_a_candidate(self):
        caller = next(edge for edge in self.build() if edge.from_id == "composable_Caller")

        self.assertEqual(caller.to_id, "composable_overload_a")
        self.assertEqual(caller.candidates, ["composable_overload_b"])
        self.assertEqual(str(caller.resolution), str(Resolution.AMBIGUOUS))

    def test_an_overload_calling_its_sibling_is_not_dropped_as_a_self_call(self):
        edges = self.build()
        from_overload = [edge for edge in edges if edge.from_id == "composable_overload_a"]

        self.assertEqual([edge.to_id for edge in from_overload], ["composable_overload_b"])
        self.assertEqual(from_overload[0].candidates, [])
        self.assertEqual(str(from_overload[0].resolution), str(Resolution.UNIQUE_NAME))


if __name__ == "__main__":
    unittest.main()
