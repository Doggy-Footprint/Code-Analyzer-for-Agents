import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from framework_analyzers.android.graph import AndroidArchitectureGraphBuilder
from framework_analyzers.android.models import AndroidProjectArchitecture, DiBindingInfo
from language_analyzers.core.graph_models import GraphNode, NodeKind, RelationKind


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


if __name__ == "__main__":
    unittest.main()
